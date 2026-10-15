"""原核心图执行验证：只替换外部模型、查询边界。"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from flask import Flask

from core.app.entities.app_invoke_entities import InvokeFrom
from core.helper.code_executor.code_executor import CodeExecutor
from core.workflow.entities.node_entities import NodeRunResult
from core.workflow.entities.variable_pool import VariablePool
from core.workflow.enums import SystemVariableKey
from core.workflow.graph_engine.entities.event import GraphRunFailedEvent, GraphRunSucceededEvent, NodeRunSucceededEvent
from core.workflow.graph_engine.entities.graph import Graph
from core.workflow.graph_engine.graph_engine import GraphEngine
from core.workflow.nodes.event import RunCompletedEvent
from core.workflow.nodes.llm.node import LLMNode
from core.workflow.nodes.question_classifier.question_classifier_node import QuestionClassifierNode
from core.workflow.nodes.tool.tool_node import ToolNode
from models.enums import UserFrom
from models.workflow import WorkflowNodeExecutionStatus, WorkflowType

ROOT = Path(__file__).parents[3]
START = 1791600000000000
END = START + 900000000
SERVICE = "test:v1::orders|ns|"


def load(name):
    return yaml.safe_load((ROOT / "init_data/workflows/zh" / f"{name}.yml").read_text())


def metric(value, kind):
    return {
        "type": "metric",
        "unit": "ns",
        "data": {
            "timeseries": [
                {
                    "legend": "p",
                    "labels": {"pod": "pod-a", "namespace": "ns", "node": "node-a", "pid": "42", "type": kind},
                    "chart": {"chartData": {str(START): value, str(END): value}},
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("name", "kind"),
    [("告警简单根因分析", k) for k in ("cpu", "net", "file", "runq", "epoll", "unknown")]
    + [("可用性告警分析", "unknown"), ("告警有效性确认", "unknown")]
    + [
        ("资源告警分析", name)
        for name in (
            "CPU高负载",
            "CPU高IO Wait",
            "异常网络入吞吐量",
            "主机内存使用率持续10分钟超过90%",
            "磁盘不足20%",
            "容器内存使用率超过80%",
            "容器CPU使用率超过80%",
        )
    ],
)
def test_original_graph_to_report(name, kind, live_inputs=None, tool_runner=None, record=None, instance_records=None):  # noqa: PT028 - 现场回放复用
    g = load(name)["workflow"]["graph"]
    assert not any(n["id"].startswith("cos_") for n in g["nodes"])
    params = {
        "tenantId": "tenant-a",
        "service": SERVICE,
        "alertEventId": "event-a",
        "ruleId": "rule-a",
        "alertName": "请求错误率超过0%" if name == "可用性告警分析" else "平均请求延时超过1s",
        "status": "firing",
    }
    if name == "资源告警分析":
        params.update(
            alertName=kind,
            node="node-a",
            nodeName="node-a",
            instanceName="node-a",
            pod="pod-a",
            namespace="ns",
            pid="42",
        )
    if live_inputs:
        params = json.loads(live_inputs["params"])
    instances = [
        {
            "service": SERVICE,
            "instanceId": "cos-instance",
            "podName": "pod-a" if kind != "unknown" else "",
            "namespace": "ns",
            "pid": "42" if kind != "unknown" else "",
            "nodeName": "node-a" if kind != "unknown" else "",
            "containerId": "",
            "sampleMaxDurationUs": 200000,
            "identityStatus": "resolved" if kind != "unknown" else "unresolved",
            "currentRED": {},
            "historyRED": {},
        }
    ]
    if instance_records is not None:
        instances = instance_records
    saved = []
    queried = []
    tool_calls = []

    def code(language, code, inputs):
        ns = {}
        exec(
            compile(code, next((n["id"] for n in g["nodes"] if n["data"].get("code") == code), "workflow"), "exec"), ns
        )
        return ns["main"](**inputs)

    def resolve(pool, value):
        def repl(m):
            selector = m.group(1).split(".")
            if len(selector) == 1:
                return ""
            v = pool.get(selector)
            assert v is not None, "unresolved template " + m.group(1)
            x = v.to_object()
            return x if isinstance(x, str) else json.dumps(x)

        return re.sub(r"\{\{#([^#]+)#\}\}", repl, value)

    def llm(self):
        for p in self.node_data.prompt_template:
            resolve(self.graph_runtime_state.variable_pool, p.text)
        value = json.dumps(
            {
                "cause": "未明确归因" if self.node_id == "17430596469370" else "受控测试",
                "other": [],
                "suggest": [],
                "timestamp": (live_inputs or {}).get("endTime", END),
                "reason": "待核验",
                "detail": "受控测试",
                "tags": {},
                "rootCause": "受控测试",
            },
            ensure_ascii=False,
        )
        yield RunCompletedEvent(
            run_result=NodeRunResult(status=WorkflowNodeExecutionStatus.SUCCEEDED, outputs={"text": value})
        )

    def classifier(self):
        category = self.node_data.classes[0]
        return NodeRunResult(
            status=WorkflowNodeExecutionStatus.SUCCEEDED,
            outputs={"class_id": category.id, "class_name": category.name},
            edge_source_handle=category.id,
        )

    def tool(self):
        pool = self.graph_runtime_state.variable_pool
        values = {}
        for k, p in self.node_data.tool_parameters.items():
            if p.type == "variable":
                v = pool.get(p.value)
                assert v is not None, (self.node_id, k, p.value)
                values[k] = v.to_object()
            elif p.type == "mixed":
                values[k] = resolve(pool, p.value or "")
            else:
                values[k] = p.value
        n = self.node_data.tool_name
        tool_calls.append({"node": self.node_id, "tool": n, "params": values})
        queried.append(n)
        if tool_runner is not None and n not in {"Generate alert analysis report", "get alert report url"}:
            result = tool_runner(n, values)
        elif n in {"dataplane_instance_evidence", "dataplane_service_instances"}:
            result = {"data": instances}
        elif n == "dataplane_instance_service":
            result = {"data": SERVICE}
        elif n == "polar_process_all_resp_three_scenes":
            result = (
                metric(10 if self.node_id == "1779332543996" else 1, kind)
                if kind != "unknown"
                else {"data": {"timeseries": [], "status": "unresolved_instance"}}
            )
        elif n == "Originx 北极星指标 (服务层级) - RED指标 - 平均响应时间":
            result = metric(100 if self.node_id == "1741328045214" else 1, "latency")
        elif n == "knowledge_retrieval":
            result = {"records": []}
        elif n == "dataplane_service_redcharts":
            result = {
                "data": [
                    {
                        "title": k,
                        "unit": u,
                        "timeseries": [
                            {"labels": {"serviceName": SERVICE}, "chart": {"chartData": {str(START): v, str(END): v}}}
                        ],
                    }
                    for k, u, v in [
                        ("cpm", "requests/min", 100),
                        ("errorRate", "percentunit", 0.1),
                        ("avgDurationMs", "ms", 200),
                    ]
                ]
            }
        elif n == "dataplane_service_topology":
            result = {"data": {"current": {"service": SERVICE}, "parents": [], "children": []}}
        elif n == "dataplane_traces":
            result = {
                "data": {
                    "data": [
                        {
                            "traceId": "t",
                            "spans": [
                                {
                                    "traceId": "t",
                                    "spanId": "s",
                                    "parentSpanId": "",
                                    "serviceName": SERVICE,
                                    "name": "GET /",
                                    "duration": 200000,
                                    "isError": False,
                                    "attributes": {},
                                }
                            ],
                        }
                    ]
                }
            }
        elif n == "dataplane_spans":
            result = {"data": {"data": []}}
        elif n == "查询全量日志":
            result = {"data": {"logContents": {"contents": []}}}
        elif n == "Generate alert analysis report":
            saved.append(values)
            result = {"type": "report"}
        elif n == "get alert report url":
            result = {"url": "test://report"}
        elif n == "abnormal charts":
            result = []
        elif n == "timeSeriesAnalysis":
            result = {}
        else:
            result = {"data": {"timeseries": []}, "unit": "ns", "result": {"timeseries": []}}
        yield RunCompletedEvent(
            run_result=NodeRunResult(
                status=WorkflowNodeExecutionStatus.SUCCEEDED, outputs={"text": json.dumps(result), "json": [result]}
            )
        )

    pool = VariablePool(
        system_variables={
            SystemVariableKey.FILES: [],
            SystemVariableKey.USER_ID: "u",
            SystemVariableKey.WORKFLOW_RUN_ID: "run-a",
        },
        user_inputs={
            "params": json.dumps(params),
            "startTime": START,
            "endTime": END,
            "edition": "ee",
            "nodeName": "",
            "nodeIp": "",
            "alert": params["alertName"],
            **(live_inputs or {}),
        },
    )
    pool.add(["env", "is_vm"], "false")
    engine = GraphEngine(
        tenant_id="t",
        app_id="a",
        workflow_type=WorkflowType.WORKFLOW,
        workflow_id="w",
        graph_config=g,
        user_id="u",
        user_from=UserFrom.ACCOUNT,
        invoke_from=InvokeFrom.WEB_APP,
        call_depth=0,
        graph=Graph.init(graph_config=g),
        variable_pool=pool,
        max_execution_steps=300,
        max_execution_time=60,
    )
    with (
        Flask(__name__).app_context(),
        patch("extensions.ext_database.db.session.remove"),
        patch("extensions.ext_database.db.session.close"),
        patch.object(CodeExecutor, "execute_workflow_code_template", side_effect=code),
        patch.object(LLMNode, "_run", llm),
        patch.object(QuestionClassifierNode, "_run", classifier),
        patch.object(ToolNode, "_run", tool),
    ):
        events = list(engine.run())
    assert not [str(e) for e in events if isinstance(e, GraphRunFailedEvent)]
    assert isinstance(events[-1], GraphRunSucceededEvent)
    if record is not None:
        record.update(
            tool_calls=tool_calls,
            saved=saved,
            queried=queried,
            outputs=events[-1].outputs,
            visited=[e.node_id for e in events if isinstance(e, NodeRunSucceededEvent)],
        )
    if live_inputs:
        return
    if name == "告警有效性确认":
        assert "dataplane_instance_evidence" in queried
        assert events[-1].outputs["text"] in ("false", "unknown")
        return
    assert saved, "原流程未保存报告"
    assert json.loads(saved[0]["tags"])["alertEventId"] == "event-a"
    assert all(isinstance(v, str) for v in json.loads(saved[0]["overview"])["tags"].values())
    visited = [e.node_id for e in events if isinstance(e, NodeRunSucceededEvent)]
    if name == "告警简单根因分析":
        assert "查询容器网络与下游RTT" not in queried
        assert "1754375770920" in visited
        assert "1779332497301" in visited
        assert "polar_process_all_resp_three_scenes" in queried
        assert {
            "cpu": "17430595109950",
            "net": "17430598907140",
            "file": "17430597987060",
            "runq": "17430610719970",
            "epoll": "17430610599980",
            "unknown": "17430598907140",
        }[kind] in visited
