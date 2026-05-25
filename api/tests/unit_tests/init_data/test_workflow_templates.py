from pathlib import Path


def _node_block(workflow_text: str, node_id: str) -> str:
    marker = f"      id: '{node_id}'"
    marker_index = workflow_text.index(marker)
    start = workflow_text.rfind("\n    - data:", 0, marker_index)
    end = workflow_text.find("\n    - data:", marker_index + len(marker))
    if end == -1:
        end = len(workflow_text)
    return workflow_text[start:end]


def test_availability_alert_query_condition_node_passes_source_from():
    api_root = Path(__file__).resolve().parents[3]
    workflow_path = (
        api_root
        / "init_data"
        / "workflows"
        / "zh"
        / "\u53ef\u7528\u6027\u544a\u8b66\u5206\u6790.yml"
    )

    node = _node_block(workflow_path.read_text(encoding="utf-8"), "1779266302359")

    assert (
        "        - value_selector:\n"
        "          - '1742807803325'\n"
        "          - sourceFrom\n"
        "          variable: sourceFrom"
    ) in node
