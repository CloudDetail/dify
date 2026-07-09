import json
import re
from typing import Any

_DETAILS_THINKING_RE = re.compile(
    r"<details\b[^>]*>\s*<summary\b[^>]*>[^<]*thinking[^<]*</summary>.*?</details>",
    flags=re.DOTALL | re.IGNORECASE,
)
_CLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", flags=re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"<think\b[^>]*>.*", flags=re.DOTALL | re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.DOTALL | re.IGNORECASE)


def strip_llm_thinking_blocks(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _DETAILS_THINKING_RE.sub("", text)
    text = _CLOSED_THINK_RE.sub("", text)
    text = _UNCLOSED_THINK_RE.sub("", text)
    return text.strip()


def load_first_json_value(value: Any) -> Any:
    text = strip_llm_thinking_blocks(value)
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _ = decoder.raw_decode(text, index)
            return parsed
        except json.JSONDecodeError:
            continue

    raise ValueError("no valid JSON object or array found in input")
