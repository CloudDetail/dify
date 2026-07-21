from pathlib import Path

WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
REPORT_VIEW_WORKFLOWS = {
    "告警简单根因分析.yml": "1764048001002",
    "告警简单根因分析V2.yml": "1764048001002",
    "可用性告警分析.yml": "1764048001001",
    "资源告警分析.yml": "1764048001003",
}


def test_all_report_view_workflows_are_known():
    workflow_files = sorted(
        path.name
        for path in WORKFLOW_DIR.glob("*.yml")
        if "title: 生成报告展示结构" in path.read_text(encoding="utf-8")
    )

    assert workflow_files == sorted(REPORT_VIEW_WORKFLOWS)


def test_report_view_workflows_pass_report_view_to_alert_report_tool():
    for workflow_name, report_view_node_id in REPORT_VIEW_WORKFLOWS.items():
        workflow_text = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")

        assert "tool_name: Generate alert analysis report" in workflow_text
        assert f"value: '{{{{#{report_view_node_id}.text#}}}}'" in workflow_text


def test_alert_simple_root_cause_instance_history_uses_history_window():
    workflow_text = (WORKFLOW_DIR / "告警简单根因分析.yml").read_text(encoding="utf-8")
    history_node = workflow_text.split("title: 实例过去延时", maxsplit=1)[1].split("type: tool", maxsplit=1)[0]

    assert "- '1742807803325'\n            - historyStartTime" in history_node
    assert "- '1742807803325'\n            - historyEndTime" in history_node
