import json
import re
from collections.abc import Generator
from dataclasses import dataclass
from itertools import starmap
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage

DATAPLANE_LOG_ENDPOINT = "/datasource/queryLogs"
REQUEST_TIMEOUT_SECONDS = 15
MAX_FILTER_GROUPS = 100

_FIELD_MAPPING = {
    "container_id": "containerId",
    "containerId": "containerId",
    "container_name": "containerName",
    "containerName": "containerName",
    "host_name": "hostName",
    "hostName": "hostName",
    "k8s_namespace_name": "k8sNamespace",
    "k8sNamespace": "k8sNamespace",
    "k8s_pod_name": "podName",
    "podName": "podName",
    "pid": "pid",
    "serviceName": "serviceName",
    "level": "level",
}
_CLIENT_FILTER_FIELDS = {"source"}
_CLIENT_FALLBACK_FIELDS = {"container_name"}
_TOKEN_RE = re.compile(
    r"\s*(?:(?P<lparen>\()|(?P<rparen>\))|(?P<equals>=)|"
    r"(?P<string>'(?:''|\\.|[^'])*')|(?P<word>[A-Za-z_][A-Za-z0-9_]*))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _FilterGroup:
    dataplane: dict[str, str]
    client: dict[str, str]


def _merge_groups(left: _FilterGroup, right: _FilterGroup) -> _FilterGroup:
    dataplane = dict(left.dataplane)
    client = dict(left.client)
    for destination, values in ((dataplane, right.dataplane), (client, right.client)):
        for key, value in values.items():
            if key in destination and destination[key] != value:
                raise ValueError(f"Conflicting values for log filter {key}")
            destination[key] = value
    return _FilterGroup(dataplane=dataplane, client=client)


class _LegacyQueryParser:
    """Parse the equality-only raw_logs clauses emitted by existing workflows."""

    def __init__(self, query: str):
        self._tokens = self._tokenize(query)
        self._position = 0

    @staticmethod
    def _tokenize(query: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        position = 0
        while position < len(query):
            match = _TOKEN_RE.match(query, position)
            if not match:
                raise ValueError(f"Unsupported log query near: {query[position : position + 30]!r}")
            token_type = match.lastgroup
            if token_type is None:
                raise ValueError("Invalid log query")
            value = match.group(token_type)
            if token_type == "word" and value.lower() in {"and", "or"}:
                token_type = value.lower()
            tokens.append((token_type, value))
            position = match.end()
        return tokens

    def parse(self) -> list[_FilterGroup]:
        if not self._tokens:
            return [_FilterGroup(dataplane={}, client={})]
        groups = self._parse_or()
        if self._position != len(self._tokens):
            raise ValueError(f"Unexpected token in log query: {self._peek()}")
        if len(groups) > MAX_FILTER_GROUPS:
            raise ValueError(f"Log query expands to more than {MAX_FILTER_GROUPS} filter groups")
        return groups

    def _parse_or(self) -> list[_FilterGroup]:
        groups = self._parse_and()
        while self._accept("or"):
            groups.extend(self._parse_and())
            if len(groups) > MAX_FILTER_GROUPS:
                raise ValueError(f"Log query expands to more than {MAX_FILTER_GROUPS} filter groups")
        return groups

    def _parse_and(self) -> list[_FilterGroup]:
        groups = self._parse_atom()
        while self._accept("and"):
            right = self._parse_atom()
            groups = [_merge_groups(left_group, right_group) for left_group in groups for right_group in right]
            if len(groups) > MAX_FILTER_GROUPS:
                raise ValueError(f"Log query expands to more than {MAX_FILTER_GROUPS} filter groups")
        return groups

    def _parse_atom(self) -> list[_FilterGroup]:
        if self._accept("lparen"):
            groups = self._parse_or()
            self._expect("rparen")
            return groups
        return [self._parse_condition()]

    def _parse_condition(self) -> _FilterGroup:
        field = self._expect("word")
        self._expect("equals")
        raw_value = self._expect("string")
        value = raw_value[1:-1].replace("''", "'")
        value = re.sub(r"\\(.)", r"\1", value)

        if field in _CLIENT_FILTER_FIELDS:
            return _FilterGroup(dataplane={}, client={field: value})
        mapped_field = _FIELD_MAPPING.get(field)
        if mapped_field is None:
            raise ValueError(f"Unsupported log query field: {field}")
        client = {field: value} if field in _CLIENT_FALLBACK_FIELDS else {}
        return _FilterGroup(dataplane={mapped_field: value}, client=client)

    def _peek(self) -> Optional[tuple[str, str]]:
        if self._position >= len(self._tokens):
            return None
        return self._tokens[self._position]

    def _accept(self, token_type: str) -> bool:
        token = self._peek()
        if token is None or token[0] != token_type:
            return False
        self._position += 1
        return True

    def _expect(self, token_type: str) -> str:
        token = self._peek()
        if token is None or token[0] != token_type:
            raise ValueError(f"Expected {token_type} in log query, got {token}")
        self._position += 1
        return token[1]


def _parse_query(query: Any) -> list[_FilterGroup]:
    if query is None:
        return [_FilterGroup(dataplane={}, client={})]
    if not isinstance(query, str):
        raise ValueError("Log query must be a string")
    try:
        return _LegacyQueryParser(query.strip()).parse()
    except ValueError as exc:
        raise ValueError(f"Unsupported log query: {exc}") from exc


def _positive_int(value: Any, name: str, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _matches_client_filters(log: dict[str, Any], filters: dict[str, str]) -> bool:
    if not filters:
        return True
    attributes = log.get("attributes")
    if not isinstance(attributes, dict):
        return False
    for key, value in filters.items():
        if key in _CLIENT_FALLBACK_FIELDS and key not in attributes:
            # Some providers may normalize the container-name field away after
            # applying the server-side containerName filter.
            continue
        if str(attributes.get(key, "")) != value:
            return False
    return True


def _log_identity(provider: dict[str, Any], log: dict[str, Any]) -> tuple[str, str, str, str]:
    attributes = log.get("attributes") if isinstance(log.get("attributes"), dict) else {}
    return (
        str(provider.get("providerId", "")),
        str(log.get("timestamp", "")),
        str(log.get("message", "")),
        json.dumps(attributes, ensure_ascii=False, sort_keys=True, default=str),
    )


def _convert_log(provider: dict[str, Any], log: dict[str, Any]) -> dict[str, Any]:
    raw_attributes = log.get("attributes")
    tags = dict(raw_attributes) if isinstance(raw_attributes, dict) else {}
    level = log.get("level")
    if level not in (None, ""):
        tags.setdefault("level", level)
    tags.setdefault("dataSource", provider.get("dataSource", ""))
    tags.setdefault("clusterId", provider.get("clusterId", ""))
    return {
        "body": log.get("message", ""),
        "timestamp": log.get("timestamp"),
        "tags": tags,
    }


class QueryFullLogsTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        start_time = tool_parameters.get("startTime")
        end_time = tool_parameters.get("endTime")
        page_num = _positive_int(tool_parameters.get("pageNum"), "pageNum", 1)
        page_size = _positive_int(tool_parameters.get("pageSize"), "pageSize", 100)
        filter_groups = _parse_query(tool_parameters.get("query"))

        fetch_limit = page_num * page_size
        url = f"{dify_config.DATAPLANE_URL}{DATAPLANE_LOG_ENDPOINT}"
        collected: list[tuple[dict[str, Any], dict[str, Any]]] = []
        seen: set[tuple[str, str, str, str]] = set()

        for filter_group in filter_groups:
            params = {
                "providerId": 0,
                "startTime": start_time,
                "endTime": end_time,
                "filter": filter_group.dataplane,
                "limit": fetch_limit,
            }
            response = requests.post(url=url, json=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError("Dataplane log query returned an unsuccessful response")
            providers = payload.get("data", [])
            if not isinstance(providers, list):
                raise ValueError("Dataplane log query response data must be a list")

            for provider in providers:
                if not isinstance(provider, dict) or provider.get("error"):
                    continue
                logs = provider.get("logs", [])
                if not isinstance(logs, list):
                    continue
                for log in logs:
                    if not isinstance(log, dict) or not _matches_client_filters(log, filter_group.client):
                        continue
                    identity = _log_identity(provider, log)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    collected.append((provider, log))

        collected.sort(key=lambda item: str(item[1].get("timestamp", "")), reverse=True)
        offset = (page_num - 1) * page_size
        page = collected[offset : offset + page_size]
        contents = list(starmap(_convert_log, page))

        result = json.dumps(
            {
                "type": "log",
                "display": True,
                "data": {"logContents": {"contents": contents}},
            },
            ensure_ascii=False,
        )
        yield self.create_text_message(result)
