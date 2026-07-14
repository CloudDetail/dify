# Alert Root Cause Workflow V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a new `告警简单根因分析V2.yml` workflow that fixes RTT sparse anomaly detection, preserves and enriches downstream evidence with spans, samples representative traces, and emits environment-correct VM/container guidance.

**Architecture:** Keep the original workflow immutable and add a deterministic Python generator that loads it with PyYAML, replaces or adds nodes by stable node IDs/titles, rewires the affected branches, and writes the V2 YAML. Tests load the generated YAML, execute its embedded Python code nodes with synthetic inputs, inspect graph reachability, and verify prompt environment constraints.

**Tech Stack:** Python 3, PyYAML, pytest, Dify workflow YAML, embedded Python code nodes.

---

## File Map

- Create: `api/scripts/build_alert_simple_root_cause_workflow_v2.py` — deterministic V2 workflow generator.
- Create: `api/init_data/workflows/zh/告警简单根因分析V2.yml` — generated importable workflow.
- Create: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py` — structure and embedded-node behavior tests.
- Modify: `api/tests/unit_tests/init_data/test_alert_report_workflows.py` — register the V2 report workflow.
- Reference: `docs/superpowers/specs/2026-07-14-alert-root-cause-workflow-v2-design.md` — approved behavior.

### Task 1: Generator scaffold and structural validation

**Files:**
- Create: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Create: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Create: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Write failing workflow existence and identity tests**

```python
from pathlib import Path
import yaml

WORKFLOW_DIR = Path(__file__).parents[3] / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
V2 = WORKFLOW_DIR / "告警简单根因分析V2.yml"


def load_workflow(path=V2):
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -v
```

Expected: FAIL because `告警简单根因分析V2.yml` does not exist.

- [ ] **Step 3: Add deterministic generator scaffold**

The generator must define these helpers and write UTF-8 YAML without aliases:

```python
from pathlib import Path
from typing import Any
import copy
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
TARGET = WORKFLOW_DIR / "告警简单根因分析V2.yml"


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def node_by_id(document: dict, node_id: str) -> dict:
    for node in document["workflow"]["graph"]["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


def build() -> dict:
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["app"]["name"] = "告警简单根因分析V2"
    return document


def main() -> None:
    document = build()
    TARGET.write_text(
        yaml.dump(
            document,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate V2 and rerun structural tests**

Run:

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -v
```

Expected: PASS for existence, name, node uniqueness, and valid edges.

- [ ] **Step 5: Commit generator scaffold**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "feat: scaffold alert root cause workflow v2"
```

### Task 2: Add runtime environment context and prompt constraints

**Files:**
- Modify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Add failing environment-node tests**

Tests must locate a code node titled `运行环境上下文`, execute its embedded code, and assert:

```python
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
```

Also inspect these LLM nodes and assert they reference the new node output:

```python
ENV_AWARE_TITLES = {
    "llm analysis root cause",
    "网络方向分析",
    "总结下游影响",
    "可行动方向建议",
    "可行动建议JSON",
    "根因方向JSON",
    "生成报告展示结构",
}
```

- [ ] **Step 2: Run the targeted tests and verify failure**

Run:

```bash
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k environment -v
```

Expected: FAIL because no environment context node exists.

- [ ] **Step 3: Add the environment context node through the generator**

Add a new code node with a stable V2-only ID such as `v2_runtime_environment_context`. Its embedded `main` must return:

```python
def main(pod: str, container_id: str, node: str, pid: str) -> dict:
    pod = str(pod or "").strip()
    container_id = str(container_id or "").strip()
    node = str(node or "").strip()
    pid = str(pid or "").strip()

    if not pod and not container_id and node and pid:
        return {
            "scene": "vm",
            "instance_term": "进程实例",
            "location_text": f"主机 {node} 上的进程 PID {pid}",
            "allowed_command_context": "top, pidstat, ss, nstat, iotop, strace, perf, systemctl, journalctl",
            "forbidden_terms": "Pod, 容器, Namespace, Deployment, K8s, Kubernetes, OOMKill, kubectl, docker",
            "prompt_context": "当前为纯虚拟机环境。使用主机、进程、PID、系统服务等术语；禁止输出任何容器或 Kubernetes 专属术语与命令。",
        }
    if pod or container_id:
        return {
            "scene": "container",
            "instance_term": "应用实例",
            "location_text": pod or container_id,
            "allowed_command_context": "仅使用与现有证据匹配的容器或 Kubernetes 命令",
            "forbidden_terms": "",
            "prompt_context": "当前为容器环境，可使用 Pod、容器和 Kubernetes 术语，但命令必须与证据匹配。",
        }
    return {
        "scene": "unknown",
        "instance_term": "实例",
        "location_text": node,
        "allowed_command_context": "使用跨环境通用诊断命令",
        "forbidden_terms": "不得猜测 Pod、容器或虚拟机",
        "prompt_context": "当前运行环境不明确，必须使用实例、运行节点、进程或服务等中性术语。",
    }
```

Connect the alert label extraction node to this node. Inject `{{#v2_runtime_environment_context.prompt_context#}}` into every environment-aware prompt, with an explicit rule that environment context overrides conflicting knowledge-base commands.

- [ ] **Step 4: Regenerate and run environment tests**

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k environment -v
```

Expected: PASS.

- [ ] **Step 5: Commit environment support**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "feat: add environment-aware alert guidance"
```

### Task 3: Replace RTT detection and attribution

**Files:**
- Modify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Add failing RTT behavior tests**

Execute the embedded nodes titled `RTT分析` and `分析RTT问题`. Cover:

```python
def test_sparse_40ms_rtt_spike_is_detected():
    values = [0.0] * 99 + [0.04]
    detected = run_rtt_detection([series(values, complete_labels())])
    assert len(detected) == 1
    assert "sparse_spike" in detected[0]["detectionReasons"]


def test_rtt_detection_processes_series_after_first_ten():
    normal = [series([0.0, 0.0], complete_labels(dst_pod=f"normal-{i}")) for i in range(10)]
    detected = run_rtt_detection(normal + [series([0.0, 0.08], complete_labels(dst_pod="late"))])
    assert detected[0]["labels"]["dst_pod"] == "late"


def test_missing_dst_node_or_ip_does_not_drop_instance():
    detected = [{"labels": {"dst_pod": "db-1"}, "legend": "db-1", "avg": 0.04, "spike": 0.04, "unit": "s"}]
    result = run_rtt_attribution(detected)
    assert result["direction_summary"] == "下游实例问题"
    assert json.loads(result["abnormal_downstream_instances"])[0]["instance_name"] == "db-1"


def test_attribution_never_returns_empty_downstream_problem():
    result = run_rtt_attribution([{"labels": {}, "legend": "", "avg": 0.04, "spike": 0.04, "unit": "s"}])
    assert result["direction_summary"] == "未明确归因"
    assert result["requires_span_fallback"] is True
```

- [ ] **Step 2: Run RTT tests and verify failure**

```bash
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k rtt -v
```

Expected: FAIL on sparse spike, 11th series, missing labels, or missing output fields.

- [ ] **Step 3: Replace embedded RTT code through the generator**

The new detector must implement constants and outputs from the design:

```python
ABSOLUTE_THRESHOLD = 0.05
SPARSE_MIN_SPIKE = 0.02
SPARSE_ZERO_RATIO = 0.5
SPARSE_POSITIVE_RATIO = 0.2
ROBUST_SIGMA_FACTOR = 3.0
MIN_RELATIVE_INCREASE = 1.5
```

Use finite non-negative numeric values, compute positive median/MAD, detect `absolute`, `robust_baseline`, and `sparse_spike`, and return all required metadata.

The attribution node must preserve partial labels, use `dst_pod -> dst_ip -> legend`, add `evidence_quality` and `requires_span_fallback`, and enforce the classification invariants in the approved spec.

- [ ] **Step 4: Regenerate and run RTT tests**

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k rtt -v
```

Expected: PASS.

- [ ] **Step 5: Commit RTT fixes**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "fix: improve sparse RTT attribution"
```

### Task 4: Make Span enrichment non-exclusive and merge evidence

**Files:**
- Modify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Add failing P90, graph, and merge tests**

Tests must assert:

```python
def test_p90_uses_all_response_time_series_and_ignores_zeroes():
    result = p90_main(json.dumps({"data": [
        {"title": "吞吐量", "unit": "count", "timeseries": [{"chart": {"chartData": {"1": 999}}}]},
        {"title": "Response Time", "unit": "ms", "timeseries": [
            {"chart": {"chartData": {"1": 0, "2": 100}}},
            {"chart": {"chartData": {"1": 200, "2": 300}}},
        ]},
    ]}))
    assert result["threshold_source"] == "response_time_p90"
    assert result["p90_value_us"] == 280000


def test_downstream_instance_branch_reaches_span_query():
    assert graph_path_exists(
        condition_node_id,
        span_tool_node_id,
        source_handle=downstream_instance_case_id,
    )


def test_merge_keeps_rtt_and_database_span_evidence():
    merged = merge_main(
        rtt_instances=json.dumps([{"instance_name": "mysql-1", "rtt_avg": "40ms"}]),
        span_data=json.dumps({"data": [{"serviceName": "mysql", "dbSystem": "mysql", "duration": 900000}]}),
    )
    assert "mysql-1" in merged["result"]
    assert "mysql" in merged["result"]
```

- [ ] **Step 2: Run targeted tests and verify failure**

```bash
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k "p90 or span or merge" -v
```

Expected: FAIL because the current branch skips spans and the aggregator does not merge evidence.

- [ ] **Step 3: Replace P90 code and add the evidence merge node**

The P90 node must return both `p90_value_us` and `threshold_source`. Add a code node titled `合并RTT与Span下游证据` that parses both inputs safely and produces one JSON string with:

```json
{
  "rtt_instances": [],
  "span_dependencies": [],
  "evidence_status": "complete|partial|empty"
}
```

Normalize spans to service, instance, operation, database system, statement summary, duration, error, traceId, and spanId. Replace downstream aggregator consumers with the merge node output.

- [ ] **Step 4: Rewire network branches**

Make the `未明确归因`, `下游实例问题`, and `下游节点问题` handles reach the RED -> P90 -> spans chain. Preserve the existing non-network classifier path. Add graph tests for each network attribution handle.

- [ ] **Step 5: Regenerate and run P90/span tests**

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k "p90 or span or merge or graph" -v
```

Expected: PASS.

- [ ] **Step 6: Commit Span enrichment**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "fix: enrich downstream evidence with spans"
```

### Task 5: Add representative slow/error Trace sampling

**Files:**
- Modify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Add failing Trace merge tests**

Tests must execute a code node titled `合并慢Trace与错误Trace` and verify:

```python
def test_trace_merge_deduplicates_and_preserves_slow_trace():
    slow = trace_payload([
        trace("slow-db", duration=2_000_000, child=database_span(duration=1_800_000)),
    ])
    errors = trace_payload([
        trace(f"short-{i}", duration=5_000, error=True) for i in range(20)
    ] + [trace("slow-db", duration=2_000_000, error=True)])
    result = trace_merge_main(slow, errors)
    ids = [item["traceId"] for item in json.loads(result["result"])["traces"]]
    assert ids.count("slow-db") == 1
    assert "slow-db" in ids


def test_trace_merge_extracts_root_slowest_and_error_spans():
    result = trace_merge_main(trace_payload([database_trace()]), trace_payload([]))
    item = json.loads(result["result"])["traces"][0]
    assert item["entry"]["service"]
    assert item["slowestSpan"]["dbSystem"] == "mysql"
    assert item["errorSpan"] is not None
```

Also inspect the two trace tool nodes:

```python
assert slow_trace["data"]["tool_parameters"]["limit"]["value"] == 30
assert slow_trace["data"]["tool_parameters"]["minDuration"]["value"] == 200000
assert error_trace["data"]["tool_parameters"]["limit"]["value"] == 20
assert error_trace["data"]["tool_parameters"]["isError"]["value"] is True
```

- [ ] **Step 2: Run Trace tests and verify failure**

```bash
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k trace -v
```

Expected: FAIL because only one unfiltered trace query exists.

- [ ] **Step 3: Add slow/error Trace nodes and merge code**

Clone the existing trace tool node into two V2-only nodes. Rewire the predecessor to both nodes, connect both to the merge node, and connect the merge output to the entry-service extraction node. The merge code must safely parse empty/error payloads, deduplicate by trace ID, preserve at least 10 slow traces when available, and cap the merged result at 30.

- [ ] **Step 4: Replace root-only extraction**

Update `获取入口服务` to consume merged trace evidence. Return unique root entries plus a `trace_evidence` array containing the slowest and error spans so the later affected-service summary can use them.

- [ ] **Step 5: Regenerate and run Trace tests**

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
cd api && uv run pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k trace -v
```

Expected: PASS.

- [ ] **Step 6: Commit Trace sampling**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "fix: sample representative slow and error traces"
```

### Task 6: Register V2 and run the complete verification matrix

**Files:**
- Modify: `api/tests/unit_tests/init_data/test_alert_report_workflows.py`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`

- [ ] **Step 1: Register the V2 report workflow**

Add:

```python
REPORT_VIEW_WORKFLOWS = {
    "告警简单根因分析.yml": "1764048001002",
    "告警简单根因分析V2.yml": "1764048001002",
    "可用性告警分析.yml": "1764048001001",
    "资源告警分析.yml": "1764048001003",
}
```

- [ ] **Step 2: Add deterministic generation test**

Run the generator in a temporary output comparison or call `build()` twice and assert serialized documents are equal. Also assert the source workflow hash remains unchanged during generation.

- [ ] **Step 3: Regenerate V2 and run formatting checks**

```bash
python api/scripts/build_alert_simple_root_cause_workflow_v2.py
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Run V2 and report workflow tests**

```bash
cd api && uv run pytest \
  tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py \
  tests/unit_tests/init_data/test_alert_report_workflows.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run related report and tool regression tests**

```bash
cd api && uv run pytest \
  tests/unit_tests/core/tools/builtin_tool/providers/apo_analysis/test_alert_report_cleanup.py \
  tests/unit_tests/init_data/test_alert_report_workflows.py \
  tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Validate YAML and graph from a clean Python process**

```bash
python - <<'PY'
from pathlib import Path
import yaml

path = Path("api/init_data/workflows/zh/告警简单根因分析V2.yml")
doc = yaml.safe_load(path.read_text(encoding="utf-8"))
graph = doc["workflow"]["graph"]
ids = {node["id"] for node in graph["nodes"]}
assert doc["app"]["name"] == "告警简单根因分析V2"
assert all(edge["source"] in ids and edge["target"] in ids for edge in graph["edges"])
print(len(graph["nodes"]), len(graph["edges"]))
PY
```

Expected: prints node and edge counts without exceptions.

- [ ] **Step 7: Inspect final diff and commit**

```bash
git status --short
git diff --stat
git diff --check
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py \
  api/tests/unit_tests/init_data/test_alert_report_workflows.py
git -c commit.gpgsign=false commit -m "feat: add validated alert root cause workflow v2"
```

