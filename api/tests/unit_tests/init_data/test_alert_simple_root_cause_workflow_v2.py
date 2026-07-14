from pathlib import Path
from typing import Callable

import yaml


WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
V2 = WORKFLOW_DIR / "告警简单根因分析V2.yml"


def load_workflow(path: Path = V2) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def nodes_by_title(title: str) -> list[dict]:
    nodes = load_workflow()["workflow"]["graph"]["nodes"]
    return [node for node in nodes if node.get("data", {}).get("title") == title]


def code_node_main(title: str) -> Callable:
    matches = nodes_by_title(title)
    assert len(matches) == 1
    namespace: dict = {}
    exec(matches[0]["data"]["code"], namespace)
    return namespace["main"]


def prompt_text(node: dict) -> str:
    return "\n".join(item.get("text", "") for item in node["data"].get("prompt_template", []))


def test_v2_workflow_exists_and_has_distinct_name():
    workflow = load_workflow()

    assert workflow["app"]["name"] == "告警简单根因分析V2"
    assert SOURCE.read_bytes() != V2.read_bytes()


def test_v2_graph_has_unique_nodes_and_valid_edges():
    graph = load_workflow()["workflow"]["graph"]
    node_ids = [node["id"] for node in graph["nodes"]]

    assert len(node_ids) == len(set(node_ids))
    known = set(node_ids)
    for edge in graph["edges"]:
        assert edge["source"] in known
        assert edge["target"] in known


def test_environment_context_detects_vm_container_and_unknown():
    main = code_node_main("运行环境上下文")

    vm = main(pod="", container_id="", node="vm-01", pid="123")
    container = main(pod="pod-1", container_id="", node="node-1", pid="123")
    unknown = main(pod="", container_id="", node="", pid="")

    assert vm["scene"] == "vm"
    assert "kubectl" in vm["forbidden_terms"]
    assert "主机" in vm["prompt_context"]
    assert container["scene"] == "container"
    assert unknown["scene"] == "unknown"
    assert "中性术语" in unknown["prompt_context"]


def test_key_llm_prompts_reference_environment_context():
    titles = {
        "llm analysis root cause",
        "网络方向分析",
        "总结下游影响",
        "可行动方向建议",
        "可行动建议JSON",
        "根因方向JSON",
        "生成报告展示结构",
    }

    for title in titles:
        matches = nodes_by_title(title)
        assert matches, title
        for node in matches:
            text = prompt_text(node)
            assert "{{#v2_runtime_environment_context.prompt_context#}}" in text, title
            assert "运行环境上下文优先" in text, title
