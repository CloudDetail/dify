# 告警简单根因分析 V2 设计

## 背景

现有 `告警简单根因分析.yml` 在 RTT 稀疏采样、下游依赖归因、Trace 采样和纯虚拟机环境适配方面存在四组相互关联的问题：

1. RTT 只按固定 50ms 阈值判断、只处理前 10 条序列，并在下游标签不完整时静默丢弃异常记录。
2. 有效下游实例为零时仍可能分类为“下游实例问题”，从而绕过高耗时 Span 查询并把空依赖交给总结节点。
3. Trace 固定查询 10 条且无耗时、错误或排序策略，短错误入口可能占满样本；后续只提取 root span，丢失慢调用和数据库证据。
4. 纯虚拟机环境仍使用 Pod、容器、K8s 和 `kubectl` 等术语或建议，导致输出不可执行。

本次不修改现有工作流，新增 V2 文件和专项测试，便于并行验证和安全回退。

## 目标

- 新增 `api/init_data/workflows/zh/告警简单根因分析V2.yml`。
- 保持现有 `告警简单根因分析.yml` 内容不变。
- 修复上述四项问题，并确保 RTT、Span、Trace 和运行环境上下文可以共同参与归因。
- 使用自动化测试覆盖关键代码节点、工作流结构和 VM/容器回归场景。

## 非目标

- 不修改数据平面后端接口或其默认排序实现。
- 不重写整个告警分析工作流。
- 不改变其他内置工作流的业务逻辑。
- 不在本次引入新的外部依赖。

## 文件与命名

- 原文件：`api/init_data/workflows/zh/告警简单根因分析.yml`
- 新文件：`api/init_data/workflows/zh/告警简单根因分析V2.yml`
- 新工作流展示名称：`告警简单根因分析V2`
- 专项测试：`api/tests/unit_tests/init_data/test_alert_simple_root_cause_workflow_v2.py`
- 现有报告工作流登记测试需要加入 V2 文件，确保新版报告展示节点仍连接到告警报告生成工具。

## 总体数据流

```text
告警实例字段
  -> 运行环境上下文（vm/container/unknown）
  -> 指标和线程分析
  -> RTT 全量序列检测
  -> RTT 初步归因与证据质量判断
  -> 网络方向统一查询 RED/P90/高耗时 Span
  -> 合并 RTT 下游证据与 Span 下游证据
  -> 初步根因总结
  -> 慢 Trace + 错误 Trace 双路采样
  -> Trace 证据合并和入口/慢调用提取
  -> 环境感知的建议与报告展示
```

## 1. RTT 异常检测

### 输入

沿用容器/进程 RTT 工具返回结构：

```json
{
  "unit": "s",
  "data": {
    "timeseries": [
      {
        "legend": "...",
        "labels": {},
        "chart": {"chartData": {"timestamp": 0.0}}
      }
    ]
  }
}
```

### 序列处理

- 处理全部 `timeseries`，删除 `[:10]` 限制。
- 只接受有限数值；忽略 `null`、字符串、NaN、无穷大和负值。
- 保留总采样数、零值数、正值数和零值比例。
- 全零或没有合法数据的序列不判为异常。

### 异常规则

每条序列可以由以下任一规则命中：

1. 绝对异常：存在 RTT `> 0.05s` 的点。
2. 稳健基线异常：正值样本不少于 3 个，点值高于 `median + 3 * robust_sigma`，且相对中位数至少升高 50%。`robust_sigma` 优先使用 MAD，MAD 为零时退化为标准差。
3. 稀疏突增：零值比例不低于 50%，正值样本占比不高于 20%，且峰值不低于 `0.02s`。该规则用于识别大量零采样中出现的明显 20–50ms 峰值。

异常输出必须包含：

- `chart`
- `labels`
- `legend`
- `avg`：正值平均值
- `spike`
- `unit`
- `abnormalCount`
- `zeroRatio`
- `positiveCount`
- `detectionReasons`
- `baseline`

所有阈值以常量集中放在代码节点开头，便于后续校准。

### 下游实例标识降级

目标实例名称按以下优先级产生：

1. `dst_pod`
2. `dst_ip`
3. `legend`
4. `unknown_dst_instance_N`

`dst_node` 和 `dst_ip` 不再是保留异常记录的必要条件。缺失字段只降低证据质量，不得删除记录。

## 2. RTT 初步归因和 Span 回退

### 归因状态

RTT 分析节点输出：

- `direction_summary`
- `abnormal_downstream_instances`
- `evidence_quality`: `complete|partial|insufficient`
- `requires_span_fallback`: boolean
- `result`

### 分类规则

- 没有 RTT 异常数据：`未明确归因`，`requires_span_fallback=true`。
- 检测到异常但无法取得任何目标标识：`未明确归因`，`evidence_quality=insufficient`。
- 有 1–4 个有效下游实例且未形成多节点广泛分布：`下游实例问题`。
- 同一已知下游节点包含多个异常实例，且占全部异常实例至少 70%：`下游节点问题`。
- 至少涉及 3 个不同下游节点，或至少 5 个分散下游实例：`自身问题`。
- 任何情况下都禁止输出“下游实例问题”且 `abnormal_downstream_instances=[]`。

### Span 查询策略

网络方向不再把 RTT 分类作为是否查询 Span 的互斥开关。

- `未明确归因`、`下游实例问题`、`下游节点问题` 均进入 RED/P90/高耗时 Span 补充链路。
- `自身问题` 可以保留原网络自身归因，但仍允许 Span 作为排除或影响证据；不得用 Span 覆盖明确的自身网络证据。
- 新增合并代码节点，显式合并 RTT 实例证据与 Span 证据，替换当前变量聚合器的“选择一个可用输入”行为。

### P90 修正

- 只匹配标题 `Response Time`，不再把“吞吐量”作为候选。
- 合并所有 Response Time timeseries 的合法正值。
- 忽略空值、非数值、负值和零值。
- 正常计算 P90 并转换为微秒。
- 数据不足或单位未知时使用 200000 微秒兜底，并输出 `threshold_source=fallback`；正常计算时输出 `threshold_source=response_time_p90`。

### Span 提取

- 数据平面 Span 查询保持 `limit=50`，最小耗时使用修正后的 P90。
- 优先保留 `client`、数据库和远程依赖 Span。
- 按耗时倒序保留前 10 条。
- 标准化输出下游服务、实例、操作名、数据库系统、数据库语句摘要、耗时、错误状态、Trace ID 和 Span ID。
- SQL 内容只保留必要摘要，避免在报告中输出超长语句。

## 3. Trace 双路采样

### 查询

新增两个 Trace 查询节点：

1. 慢 Trace：`limit=30`，`minDuration=200000us`。
2. 错误 Trace：`limit=20`，`isError=true`。

由于数据平面接口未暴露排序参数，V2 通过扩大样本并分离慢/错两类查询降低后端默认排序的偏差。

### 合并与排序

新增 Trace 合并代码节点：

- 按 `traceId` 去重。
- 计算 Trace 总耗时、错误状态和最慢子 Span。
- 排序优先级：错误状态、Trace 总耗时、最慢子 Span 耗时、时间新旧。
- 合并后最多保留 30 条代表性 Trace。

### 证据提取

不再只提取 root span。每条 Trace 输出：

- root 入口服务和接口。
- 最慢 Client/数据库/远程调用 Span。
- 首个或最关键错误 Span。
- 下游服务或数据库实例。
- Trace 总耗时和关键 Span 耗时。
- 错误信息摘要。

入口服务仍用于受影响服务检索，但慢调用和错误子 Span 同时进入证据链。

## 4. VM、容器和未知环境适配

### 环境判定

新增“运行环境上下文”代码节点：

```text
pod 为空 AND containerId 为空 AND node/nodeName 非空 AND pid 非空 -> vm
pod 非空 OR containerId 非空 -> container
其他 -> unknown
```

输出：

- `scene`
- `instance_term`
- `location_text`
- `allowed_command_context`
- `forbidden_terms`
- `prompt_context`

### VM 场景

使用术语：

- 主机
- 进程
- PID
- 系统服务
- 主机节点

允许命令：

- `top`
- `pidstat`
- `ss`
- `nstat`
- `iotop`
- `strace`
- `perf`
- `systemctl`
- `journalctl`

禁止输出：

- Pod
- 容器
- Namespace
- Deployment
- K8s/Kubernetes Event
- OOMKill
- `kubectl`
- `docker`
- 容器重启、容器 CPU 节流等容器专属建议

### 容器场景

保留现有 Pod、容器和 Kubernetes 能力，但建议仍必须与已有证据匹配，不得无条件输出 `kubectl`。

### 未知场景

统一使用“实例”“运行节点”“进程或服务”等中性术语，不猜测 Pod、容器或虚拟机。

### 注入节点

环境上下文注入以下关键 LLM 节点：

- 初步根因分析
- 网络方向分析
- 下游影响总结
- 可行动方向建议
- 可行动建议 JSON
- 根因方向 JSON
- 报告展示结构

所有节点遵循：运行环境上下文优先于知识库中的通用容器命令。如果知识库建议与当前环境冲突，忽略冲突建议。

## 错误处理

- JSON 解析失败时返回结构化空结果和 `error` 字段，不让代码节点直接终止工作流。
- RTT、Span 或 Trace 任一数据源为空时，其他证据仍可继续执行。
- 下游证据为空时使用“证据不足，需要进一步查询调用链”，不得生成具体下游实例。
- LLM 输出不得把缺失数据描述成正常数据。

## 测试策略

### 工作流结构测试

1. V2 YAML 可由 `yaml.safe_load` 完整解析。
2. 节点 ID 唯一。
3. 边的 source/target 均引用存在节点。
4. 关键变量选择器引用存在节点和已声明输出。
5. V2 报告展示节点仍传给告警报告生成工具。
6. 原工作流文件内容不在本次提交中变化。

### RTT 代码节点测试

1. 全零序列不报异常。
2. 大量零值加 40ms 峰值命中稀疏突增。
3. 60ms 点命中绝对异常。
4. 稳定低基线上的相对抬升命中稳健基线异常。
5. 第 11 条及之后的异常序列不会丢失。
6. 缺少 `dst_node` 时仍保留实例。
7. 缺少 `dst_ip` 时仍保留实例。
8. 仅有 legend 时使用 legend 标识实例。
9. 完全没有目标标识时输出“未明确归因”。
10. 永远不产生空列表的“下游实例问题”。

### Span 和分支测试

1. 下游实例问题也能到达高耗时 Span 节点。
2. 未明确归因能到达高耗时 Span 节点。
3. RTT 与 Span 证据同时存在时被合并。
4. RTT 为空但 Span 有数据库证据时保留数据库证据。
5. P90 不读取吞吐量。
6. P90 合并全部响应时间序列。
7. 大量零值不会把 P90 压成零。
8. 数据不足时明确使用 200ms 兜底。
9. 数据库 Client Span 能提取数据库实例、操作和耗时。

### Trace 测试

1. 慢 Trace 和错误 Trace 能合并。
2. 相同 traceId 被去重。
3. 短错误 Trace 不会挤掉全部慢 Trace。
4. 能提取 root 入口、最慢子 Span 和错误 Span。
5. 数据库慢 Span 能进入结果。
6. 空数据源返回结构化空结果。

### 环境适配测试

1. `pod/containerId` 为空且 `node+pid` 存在时判定 VM。
2. `pod` 或 `containerId` 存在时判定容器。
3. 字段不足时判定 unknown。
4. VM prompt_context 明确禁止所有容器/K8s 术语和命令。
5. 容器 prompt_context 保留容器诊断能力。
6. unknown prompt_context 要求使用中性术语。
7. 关键 LLM 节点均引用运行环境上下文。

### 回归测试

- 运行 `api/tests/unit_tests/init_data/test_alert_report_workflows.py`。
- 运行新增的 V2 专项测试文件。
- 执行仓库中与告警报告、报告清理和内置工具相关的现有单元测试。
- 对 YAML 中的关键 Python 代码节点使用合成输入直接 `exec`，验证真实嵌入代码而非测试副本。

## 验收标准

- 新工作流能够独立导入，旧工作流未被替换。
- 40ms 稀疏 RTT 峰值可以被识别并说明检测原因。
- 缺少下游节点或 IP 标签不会导致异常实例静默消失。
- 不再出现“下游实例问题”但依赖实例为空。
- 网络下游方向可以同时使用 RTT 和 Span 证据。
- 数据库故障可以通过高耗时 Span 或慢 Trace 提供具体数据库/调用证据。
- Trace 样本同时覆盖慢调用和错误调用。
- VM 场景不输出容器/Kubernetes 专属术语或指令。
- 容器场景保持原有能力。
- 所有新增和相关回归测试通过。

## 风险与控制

- 稀疏突增阈值可能需要根据真实数据校准：阈值集中定义并通过测试固定当前行为。
- 扩大 Trace 查询会增加返回数据量：分别限制为 30 和 20，合并后最多保留 30 条。
- 新增 V2 文件会被报告工作流登记测试发现：同步登记 V2，避免误判为未知工作流。
- 工作流 YAML 体积较大：只修改明确节点，并用结构测试检测断边和错误引用。

