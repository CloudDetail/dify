from pathlib import Path

import yaml


WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
V2 = WORKFLOW_DIR / "告警简单根因分析V2.yml"


def load_workflow(path: Path = V2) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
