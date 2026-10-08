"""Exercise every Chinese RED consumer using native COS and legacy APO contracts."""

import ast
import itertools
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3] / "init_data/workflows/zh"
RESOURCE = "资源告警分析"
AVAILABILITY = "可用性告警分析"
CAUSE = "告警简单根因分析"
RATE_NODES = [(RESOURCE, "1752655378049"), (RESOURCE, "1752659722106017526597221073"), (AVAILABILITY, "1753437328850")]
EXTRACT_NODES = [(RESOURCE, "1760105843418"), (AVAILABILITY, "1760103472918"), (CAUSE, "1759066552234")]
TOPOLOGY_NODES = [(RESOURCE, "17540319953985"), (AVAILABILITY, "1750941439700"), (CAUSE, "1750750056742")]


@lru_cache
def nodes(name):
    return {
        n["id"]: n["data"] for n in yaml.safe_load((ROOT / f"{name}.yml").read_text())["workflow"]["graph"]["nodes"]
    }


def execute(name, id, **args):
    namespace = {"json": json}  # Dify Python3TemplateTransformer prelude supplies json.
    exec(compile(nodes(name)[id]["code"], id, "exec"), namespace)
    return namespace["main"](**args)


def metric(title, unit, value, service="orders", label="serviceName"):
    return {
        "title": title,
        "unit": unit,
        "timeseries": [
            {
                "legend": service,
                "legendFormat": "",
                "labels": {label: service},
                "chart": {"chartData": {"1000000": value, "2000000": 0, "3000000": None}, "value": value},
                "step": 1000000,
            }
        ],
    }


def red(legacy=False, service="orders", label="serviceName"):
    if legacy:
        return [
            metric("Tpm", "requests/minute", 120, service, label),
            metric("Response Time", "us", 120000, service, label),
            metric("Error Rate", "%", 2, service, label),
        ]
    return [
        metric("cpm", "requests/min", 120, service, label),
        metric("avgDurationMs", "ms", 120, service, label),
        metric("errorRate", "percentunit", 0.02, service, label),
    ]


@pytest.mark.parametrize(("name", "id"), RATE_NODES)
@pytest.mark.parametrize("legacy", [False, True])
def test_rate_extraction_is_order_independent_and_retains_zero_null_step(name, id, legacy):
    for data in itertools.permutations(red(legacy)):
        args = {"red": json.dumps({"data": data})}
        if name == RESOURCE:
            args["pod"] = "orders-1"
        result = json.loads(execute(name, id, **args)["tps"])
        assert (result["title"], result["unit"]) == ("cpm", "requests/min")
        assert result["timeseries"][0]["chart"]["chartData"] == {"1000000": 120, "2000000": 0, "3000000": None}
        assert result["timeseries"][0]["step"] == 1000000
        if name == RESOURCE:
            assert result["pod"] == "orders-1"
            assert result["scope"] == "service"


@pytest.mark.parametrize(("name", "id"), RATE_NODES)
def test_rate_does_not_relabel_request_totals_or_network_throughput(name, id):
    args = {"red": json.dumps({"data": [metric("吞吐量", "bytes/s", 500), metric("Tpm", "count", 300)]})}
    if name == RESOURCE:
        args["pod"] = "orders-1"
    assert execute(name, id, **args)["tps"] == ("{}" if name == RESOURCE else "")


@pytest.mark.parametrize(("name", "id"), EXTRACT_NODES)
@pytest.mark.parametrize("legacy", [False, True])
def test_latency_and_error_analysis_use_normalized_units_and_exclude_only_missing_points(name, id, legacy):
    for data in itertools.permutations(red(legacy)):
        args = {"red_json": json.dumps({"data": data})}
        if name != RESOURCE:
            args["history_red_json"] = args["red_json"]
        outputs = execute(name, id, **args)
        for key, unit, value in [("request_latency", "ms", 120), ("request_error_rate", "percentunit", 0.02)]:
            result = json.loads(outputs[key])
            assert result["unit"] == unit
            assert result["data"]["timeseries"][0]["chart"]["chartData"] == {"1000000": value, "2000000": 0}
            if name != RESOURCE:
                assert outputs["history_" + key] == outputs[key]


@pytest.mark.parametrize(("name", "id"), TOPOLOGY_NODES)
@pytest.mark.parametrize("label", ["serviceName", "service", "service_name"])
def test_topology_matches_service_and_metric_names(name, id, label):
    topology = {
        "data": {
            "current": {"service": "orders"},
            "parents": [{"service": "gateway"}],
            "children": [{"service": "database"}],
        }
    }
    outputs = [json.dumps({"data": red(service=s, label=label)}) for s in ["database", "orders", "gateway"]]
    args = {"services_red": outputs, "topology_str" if name == RESOURCE else "topology_json": json.dumps(topology)}
    result = json.loads(execute(name, id, **args)["result"])
    assert result["current"]["service"] == "orders"
    assert result["parents"][0]["service"] == "gateway"
    assert result["children"][0]["service"] == "database"
    for node in [result["current"], *result["parents"], *result["children"]]:
        assert set(node["metrics"]) == {"avgDurationMs", "errorRate", "cpm"}
        assert node["metrics"]["avgDurationMs"]["value"] == 120
        assert node["metrics"]["errorRate"]["value"] == 0.02
        assert node["metrics"]["cpm"]["value"] == 120


@pytest.mark.parametrize(
    ("id", "usage"), [("1753865125982", "throttle"), ("1753931802138", "cpu"), ("1753932004742", "memory")]
)
def test_resource_evidence_does_not_count_same_service_twice_for_two_pods(id, usage):
    rate = metric("cpm", "requests/min", 120)
    rate2 = deepcopy(rate)
    rate["pod"], rate2["pod"] = "orders-1", "orders-2"
    args = {"all_tps": [json.dumps(rate), json.dumps(rate2)]}
    empty = '{"data":{"timeseries":[]}}'
    args.update({"self_usage": empty, "other_usage": empty} if usage == "throttle" else {usage: empty})
    evidence = json.loads(execute(RESOURCE, id, **args)["evidence"])["evidence"]
    cpm = [item for item in evidence if item["unit"] == "requests/min"]
    assert len(cpm) == 1
    assert "请求速率" in cpm[0]["name"]


def test_error_filter_carries_fractional_unit_without_changing_positive_test():
    data = {"unit": "percentunit", "data": {"timeseries": metric("errorRate", "percentunit", 0.02)["timeseries"]}}
    result = json.loads(execute(AVAILABILITY, "1779350144879", data_json=json.dumps(data))["result"])
    assert result[0]["unit"] == "percentunit"
    assert result[0]["chart"]["chartData"]["1000000"] == 0.02
    data["data"]["timeseries"][0]["chart"]["chartData"] = {"1000000": 0}
    assert execute(AVAILABILITY, "1779350144879", data_json=json.dumps(data))["result"] == "[]"


def test_success_history_is_exactly_24_hours_and_ebpf_branch_remains_empty_check():
    ns = nodes("告警有效性确认")
    assert ns["17424344697090"]["tool_parameters"]["endTime"]["value"] == ["1741157526222", "startTime"]
    assert ns["1744599891369"]["cases"][0]["conditions"][0]["comparison_operator"] == "empty"


def test_red_contract_helper_is_identical_at_every_consumer():
    helpers = []
    for name, id in RATE_NODES + EXTRACT_NODES + TOPOLOGY_NODES + [(CAUSE, "1750819000832")]:
        tree = ast.parse(nodes(name)[id]["code"])
        helpers.append(
            ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "select_red_metric"))
        )
    assert len(set(helpers)) == 1


def test_red_summary_prompts_explain_rates_ratios_and_ms():
    for name, id in [
        (CAUSE, "1750927458985"),
        (CAUSE, "1759065784647"),
        (AVAILABILITY, "1760103644528"),
        (RESOURCE, "1760106066557"),
        (RESOURCE, "1752660000891"),
    ]:
        prompt = "\n".join(p["text"] for p in nodes(name)[id]["prompt_template"])
        for word in ["cpm", "errorRate", "avgDurationMs", "0.02", "2%", "次/分钟"]:
            assert word in prompt
        assert "不要做转化" not in prompt
        assert "300000微秒" not in prompt
