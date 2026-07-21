# Alert Workflow V2 Prompt Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine V2 report and recommendation prompts so Epoll guidance is network-oriented, reports use real service/environment identity, and placeholder text cannot leak into output.

**Architecture:** Extend the existing deterministic V2 generator with one focused prompt-refinement pass keyed by stable node IDs. Keep graph topology, embedded analysis code, and provider/tool configuration unchanged; validate the generated YAML with static prompt assertions plus all existing workflow tests.

**Tech Stack:** Python 3, PyYAML, pytest, Dify workflow YAML.

---

### Task 1: Add failing prompt quality tests

**Files:**
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`

- [ ] **Step 1: Add prompt lookup helpers and failing assertions**

Add tests that inspect generated V2 prompt text:

```python
def node_prompt(node_id: str) -> str:
    workflow = load_workflow()
    node = next(node for node in workflow["workflow"]["graph"]["nodes"] if node["id"] == node_id)
    return prompt_text(node)


def test_epoll_guidance_uses_network_diagnostics_instead_of_epoll_tracing():
    prompts = node_prompt("1741512806512") + node_prompt("1750662408086")
    assert "strace -e epoll_wait" not in prompts
    assert "epoll_pwait" not in prompts
    assert "perf trace -e epoll:" not in prompts
    for expected in ("ss -s", "nstat -az", "RTT", "下游 Span"):
        assert expected in prompts


def test_root_cause_prompt_uses_real_service_and_environment_identity():
    prompt = node_prompt("17430596469370")
    assert "服务xx" not in prompt
    assert "{{#1754299310647.service#}}" in prompt
    assert "{{#v2_runtime_environment_context.location_text#}}" in prompt
    assert "服务名为空时省略" in prompt


def test_output_prompts_do_not_treat_pod_as_the_only_instance_type():
    for node_id in OUTPUT_PROMPT_NODE_IDS:
        prompt = node_prompt(node_id)
        assert "{{#v2_runtime_environment_context.prompt_context#}}" in prompt
        assert "不得因为指标名称包含按Pod统计" in prompt
```

- [ ] **Step 2: Run tests and verify expected failure**

```bash
cd api
.venv/bin/python -m pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k "epoll_guidance or real_service or only_instance" -v
```

Expected: FAIL because existing prompts still contain Epoll tracing and `服务xx`.

- [ ] **Step 3: Commit tests only after the implementation cycle is green**

Do not commit during RED. Continue directly to Task 2.

### Task 2: Add a deterministic prompt-refinement pass

**Files:**
- Modify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Regenerate: `api/init_data/workflows/zh/告警简单根因分析V2.yml`
- Modify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`

- [ ] **Step 1: Add prompt mutation helpers**

Implement helpers keyed by node ID:

```python
PROMPT_REFINEMENT_NODE_IDS = {
    "1741512806512",
    "17430596469370",
    "17473569800940",
    "1750662084996",
    "1750662408086",
    "1764048001002",
    "1754382620041",
}


def user_prompt(node: dict) -> dict:
    for prompt in node["data"].get("prompt_template", []):
        if prompt.get("role") == "user":
            return prompt
    raise ValueError(f"user prompt missing: {node['id']}")
```

- [ ] **Step 2: Replace Epoll command guidance**

In nodes `1741512806512` and `1750662408086`, replace the Epoll example with:

```text
根因为 EPOLL：保留 EPOLL 作为异常方向，但建议从网络连接和等待原因排查。优先结合 RTT、下游 Span、超时和重传证据；可按证据选择 ss -s、ss -antp、nstat -az、sar -n TCP,ETCP 1、ip -s link。不要默认建议 strace epoll_wait、epoll_pwait 或 perf trace epoll:*，也不要机械输出全部命令。
```

- [ ] **Step 3: Replace report identity/output templates**

For `17430596469370`, replace the fixed `服务xx/应用实例:<pod>` output with:

```text
**服务**：{{#1754299310647.service#}}
**运行对象**：{{#v2_runtime_environment_context.location_text#}}
**对象类型**：{{#v2_runtime_environment_context.instance_term#}}
```

Append strict rules:

```text
服务名为空时省略服务字段，禁止输出“服务xx”“未知服务”等占位文本。
运行对象必须服从运行环境上下文；不得因为指标或工具名称包含“按Pod统计”就推断当前一定是 Pod/容器。
示例占位词只用于理解格式，禁止原样出现在最终输出。
```

- [ ] **Step 4: Make the remaining output prompts environment-neutral**

For nodes `1741512806512`, `17473569800940`, `1750662084996`, `1750662408086`, `1764048001002`, and `1754382620041`:

- replace fixed “Pod 汇总/Pod 明细” wording with “服务汇总/运行对象明细”；
- reference `instance_term`, `location_text`, and `prompt_context`；
- state that empty service fields are omitted；
- state that examples such as `xx/xxx/XXXX` must never be copied；
- preserve their existing business inputs and output formats.

For report-view evidence mapping, add environment-specific evidence selection without changing JSON schema:

```text
VM 使用主机/进程证据；容器使用 Pod/容器/K8s 证据；unknown 使用中性系统证据。
```

- [ ] **Step 5: Regenerate and run targeted tests**

```bash
cd api
.venv/bin/python scripts/build_alert_simple_root_cause_workflow_v2.py
.venv/bin/python -m pytest tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -k "epoll_guidance or real_service or only_instance" -v
```

Expected: PASS.

- [ ] **Step 6: Commit prompt refinement**

```bash
git add api/scripts/build_alert_simple_root_cause_workflow_v2.py \
  api/init_data/workflows/zh/告警简单根因分析V2.yml \
  api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py
git -c commit.gpgsign=false commit -m "fix: refine workflow v2 report prompts"
```

### Task 3: Run full workflow regression verification

**Files:**
- Verify: `api/init_data/workflows/zh/告警简单根因分析V2.yml`
- Verify: `api/scripts/build_alert_simple_root_cause_workflow_v2.py`
- Verify: `api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`

- [ ] **Step 1: Regenerate and compile**

```bash
cd api
.venv/bin/python scripts/build_alert_simple_root_cause_workflow_v2.py
.venv/bin/python -m py_compile scripts/build_alert_simple_root_cause_workflow_v2.py
```

- [ ] **Step 2: Run all related tests**

```bash
.venv/bin/python -m pytest \
  tests/unit_tests/core/tools/builtin_tool/providers/apo_analysis/test_alert_report_cleanup.py \
  tests/unit_tests/init_data/test_alert_report_workflows.py \
  tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py -v
```

Expected: all tests PASS, including graph depth and CodeNodeData Schema validation.

- [ ] **Step 3: Verify no graph or source regression**

```bash
git diff --check
git status --short
```

Expected: only generator, V2 YAML, tests, and this plan/spec history are changed or committed; original workflow remains unchanged.

