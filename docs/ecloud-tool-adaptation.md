# Dify 查询工具电子云适配

2026-09-24，代码与本地验证完成；未修改初始化工作流图、未导入发布或部署，未访问现场 COS。

## 调用约定

- `DATA_SOURCE=dataplane`，`DATAPLANE_URL` 指向 dataplane。
- 工具新增 `tenantId`，必须由工作流绑定告警事件里的租户，Agent 使用会话上下文。不能使用 Dify 自己的 workspace tenant_id，也不能由模型猜测。声明保留可选以兼容 APO 模式，dataplane 请求实际要求非空。
- 保留 `providerId=0`，不新增 groupId。Trace/Span、全量拓扑已有 providerId 参数时，将字符串数字转换为整数再发送。
- 时间入参是 Unix 微秒，保留对象/namespace/服务完整名称等原查询条件。

## 已适配内容

1. 71 处旧指标直连代码统一经过 `query_legacy_metric`；DATA_SOURCE=apo 时保留原 POST `/api/metric/query` 请求与返回，dataplane 时使用 `/datasource/queryMetrics`。已有公共指标调用和进程基类也传递 tenantId，共更新 102 份工具声明。
2. `query_full_logs` 保留原过滤和日志返回结构，补租户及数字时间参数；不放宽 source/container 等过滤条件。
3. `dataplane_traces` / `dataplane_spans` 补租户、整数 Provider/时间/时长，支持精确 traceId；保留原 Provider 包装和空结果处理。
4. `dataplane_topology` 补租户；`dataplane_service_topology` 改用 POST `/datasource/queryTopology`，按 parentService/childService 构造上下游，不伪造 endpoint/isTraced。
5. `dataplane_service_redcharts` 使用 POST `/datasource/queryServiceRedCharts`，对外仍为 `type=metric, data=[...]`，三项 title 为 `cpm/errorRate/avgDurationMs`，单位分别为 `requests/min/percentunit/ms`，timeseries 保留实际 step。精确端点通过 queryMetrics 的 RED 映射查询；旧 `endpoint=.*`/`*` 表示服务汇总，不作为 COS 精确端点发送。
6. RED 成功率工具使用 dataplane 已有成功率映射，保持 0..1，不再次除100或舍入到两位小数。平均耗时工具改走公共查询入口。
7. 公共模型保留 chart.value，包括零/null；不从窗口单值造趋势。COS 普通资源曲线的毫秒键仅在乘1000后落入本次查询窗口且原值不在窗口时转换为微秒；RED/eBPF 微秒键及其他 Provider 不重复转换。

保留现有指标异常转空结果、日志 Provider 错误跳过及工作流有效性处理；没有引入新状态协议。

## 尚未完成的调用方与数据能力

- 五个中文初始化工作流图尚未修改。后续在参数提取节点输出事件 tenantId，并绑定每个查询工具；分类、时间窗口、工作流代码里的直接 HTTP 请求和报告分支另行适配。工具声明更新不会自动替已发布的工作流增加变量绑定。
- RED 专用工具 title 已变更，读取旧 Response Time/Error Rate/Tpm 的工作流代码需同步；本轮不自动改分析算法。
- `dataplane_instance_service`、`dataplane_service_instances`、`dataplane_service_endpoints` 的旧对象发现能力没有 COS 等价接口，本轮未改这些工具，不用服务目录冒充实例/端点。旧 APO 专用 Trace 报告、on/off CPU、故障日志等工具也未迁移。
- 统一指标入口只使用 dataplane 已有映射，不增加指标能力。进程 last_seen/count、PSI/FD 等旧指标可能不支持；原进程快照工具的单点时间合同也未重做。查询入口已切换不代表这些分析分支可用。
- eBPF 的实际数据和底层租户过滤、COS logLabels 配置、真实查询结果及完整诊断质量仍待现场验证。

## 验证

- `cd api && .venv/bin/pytest tests/unit_tests/core/tools/builtin_tool/providers/apo_select -q --disable-warnings`：119 项通过。
- 覆盖所有适配指标工具的实际 _invoke、请求租户/Provider/对象，RED 小数与真实 step、成功率、单值零、毫秒/微秒、拓扑方向、日志与 Trace、缺租户不发送请求、错误保持空结果、旧 APO 请求。
- 真实本地 HTTP Server 下并发执行两个租户同名主机查询，捕获 tenantId/labels，分别返回不同数值，无串租户；上游为受控 fixture，不是实际 dataplane/COS。
- 102 份 YAML 按真实 Provider 加载流程注入 identity.provider 后，经 ToolEntity 校验通过。
- 原 Span 测试错误地期望内部 data，但源码原来就保留 Provider 包装；本轮校正测试断言，业务输出不变。
