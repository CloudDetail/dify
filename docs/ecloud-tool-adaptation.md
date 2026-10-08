# Dify 查询工具电子云适配

2026-09-24，工具适配及五个中文初始化工作流的租户解析/绑定已完成本地验证；未导入发布或部署，未访问现场 COS。

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

## 中文工作流租户传参

- 仅修改告警事件分类、告警有效性确认、资源告警分析、可用性告警分析、告警简单根因分析五个中文 YAML，英文不变。
- 四个分析/检查流程从原事件 params 提取 tenantId，兼容 tenant_id 及 raw_tags/tags/labels；顶层身份优先，缺失时保持空字符串，不用 Provider、数据组或 Dify workspace 替代。
- 109个已适配查询工具节点绑定提取结果：有效性37、资源41、可用性10、简单根因21，包含24个迭代内节点及既有历史查询。其余查询参数、路由、分析判断不变。
- 分类流程增加可选 params 和出口 tenantId；旧 backend 分类请求仅含 alertName/alertGroup，仍兼容。分析流程从原事件独立取租户，不依赖分类结果补身份。
- 50组租户解析/原字段不变用例、171个代码节点模型校验和编译通过；验证提取节点先于查询执行。两租户沿工作流变量选择器→实际工具→受控HTTP执行218次查询，租户传参正确。不等同完整 Dify 引擎或现场验收。

## 尚未完成的调用方与数据能力

- 工作流分类及其他分支仍需另行适配。本轮已迁移有效性平均耗时、可用性拓扑、简单根因拓扑和RED共4个代码直连节点；剩余有效性依赖/自身判断的eBPF查询按用户要求保留自采backend/VM链路，不增加电子云租户适配、不激活分支。修改仓库YAML不会自动更新已发布图。
- RED消费全链路复核已补齐资源/可用性/简单根因的提取、拓扑、提示词和证据适配，详见下方记录；本轮不重做分析算法。
- `dataplane_instance_service`、`dataplane_service_instances`、`dataplane_service_endpoints` 的旧对象发现能力没有 COS 等价接口，本轮未改这些工具，不用服务目录冒充实例/端点。旧 APO 专用 Trace 报告、on/off CPU、故障日志等工具也未迁移。
- 统一指标入口只使用 dataplane 已有映射，不增加指标能力。进程 last_seen/count、PSI/FD 等旧指标可能不支持；原进程快照工具的单点时间合同也未重做。查询入口已切换不代表这些分析分支可用。
- eBPF按自采链路保留，不将电子云租户过滤列为本轮要求。eBPF实际数据、COS logLabels配置、真实查询结果及完整诊断质量仍待现场验证。

## 2026-09-24 直连节点迁移

用户确认：修复历史粒度、统一RED；eBPF保持自采链路与现有判断，能用的部分不改、不增加租户对接。

- 有效性：检测节点改为纯计算，复用已绑定tenantId的当前/历史平均耗时工具。只将该分支历史工具的endTime改绑告警startTime，窗口精确为[start-24h,start]，避免24小时加告警窗口导致COS返回天点。公共历史时间节点不变。峰值时长按实际相邻时间戳累计，保持20%比较及abnormal字符串约定。
- 简单根因RED：新增服务RED工具节点，保留原代码节点ID和result出口用于格式转换。按名称和完整服务身份解析，统一avgDurationMs/ms、errorRate/percentunit、cpm/requests/min。兼容旧APO的Response Time/us、Error Rate/%、Tpm/requests/minute；保留零、null、实际step及已有窗口单值，不从曲线造单值。
- 两个拓扑：已有拓扑工具→服务去重→串行迭代已有RED工具→原节点组装。所有COS查询使用事件tenantId和providerId=0，不加入groupId；保留上下游方向、报告分支和原result引用。
- eBPF节点1744339618961、前置条件1744599891369及其边与改前完全相同。未验证现场eBPF数据，不宣称已迁移该链路。
- 配套APO前端只在报告侧识别新RED字段与单位，显示120ms、0.02→2%、120CPM→120次/分钟；旧latency/errorRate/tps报告仍走旧渲染。拓扑无窗口单值时显示最新采样并明确标注，不称为窗口平均。

验证：Dify工具目录129项通过（含10项本轮YAML变量→真实工具→受控HTTP用例）；173个代码节点编译及模型校验、164个工具节点和13个迭代节点模型校验通过；新增边及输出合同校验通过。200组相同曲线输入的有效性判定与原算法一致。报告侧41项测试、前端生产构建通过。没有运行完整Dify引擎、真实COS或现场浏览器验收；未导入发布、部署或提交。

## 验证

### 2026-09-28 资源缺失点和其他 Pod CPU 使用量修复

- 修复资源工作流 CPU、内存、网络收发带宽异常/Top统计共7个代码节点，以及公共 `abnormal_chart` 工具：均值、标准差与阈值比较跳过 `None`。保持原有非零样本统计、Top3、前75条和异常比例阈值；原始曲线、零值、缺失点、标签及单位保持，不补零或制造样本。全缺失/空曲线沿用空结果。
- 修复 `1752818508497`“其他pods CPU使用量”：读取上游异常样本的直接 `chart` 时间戳映射，同时兼容 `chart.chartData`；unit 从每条样本读取，消除未定义变量。保持原 `result`、`chartData` 输出及 Top3，继续传递 namespace 到实例提取。
- 新增34项回归，覆盖混合零/null、全缺失、原统计结果不变、原曲线保留、两种chart结构、不同单位和Top3排序，并执行真实异常样本工具→CPU使用量→实例提取链路。五个中文YAML的173代码、164工具、13迭代节点模型校验通过；代码编译通过、图边不变。
- 相关回归234项通过（含新增34项），diff检查通过。本轮只修改资源YAML的8个代码节点和公共异常样本工具；报告保存、分类、指标口径、eBPF查询及其他工作流不改。此前未提交改动保留；未提交、推送、导入发布或现场验收。

### 2026-09-24 资源历史窗口及返回标签兼容

用户确认本轮仅修复历史窗口和资源结果标签；指标口径、未就绪分类不调整。

- 有效性确认的容器 CPU/内存历史节点 `17429835599060`、`17429835940550` 改为 `[startTime-24h,startTime]`，不再查询当前窗口。实际工具请求采用小时步长；公共历史时间节点及其他分支不改。
- Dify 公共指标响应转换仅对 `dataSource=cos` 补 `k8s_pod_name→pod`、`k8s_namespace_name→namespace`、`k8s_node_name→node`、`k8s_container_name→containerName`。保留原标签及已有非空旧字段，空旧字段可补齐；不将容器名写成 container/containerId，不生成 pid。query_metric 和 query_legacy_metric 共用此入口；APO/其他 Provider 响应不变。
- 扫描五个中文工作流全部代码标签读取：资源分析的六处旧字段消费（`1743652552181`、`1752655200938`、`17526596567180`、`1752741434678`、`1752742381956`、`1752804688058`）统一由响应入口兼容。前两处对象发现相关链路及获取节点等仍有自采数据依赖，兼容字段不代表 COS 新增了实例发现能力。其余服务 RED 标签已兼容；事件标签继续使用已有后端兼容；线程/RTT 消费保持原自采链路。
- 三个实例列表提取节点 `1752655200938`、`17526596567180`、`1752804688058` 补 namespace 输出及去重键，避免同名 Pod 在列表中被合并。这里只保证查询结果身份保留，不宣称旧实例目录已支持 namespace 精确关联。
- 新增 11 项回归：真实工具及受控 HTTP 验证两个历史请求、两种查询入口的 COS/其他 Provider 隔离、旧字段冲突/缺失、零/null/原标签保留，以及六个实际消费节点、跨 namespace 同名 Pod 去重。相关测试总计 200 项通过。五个中文 YAML 共173个代码节点编译通过，图边不变，eBPF节点与分类未改。
- 本轮新增改动仅2个中文YAML内的5个节点、公共响应转换及测试/说明；此前未提交改动保留。未提交、推送、导入发布或现场验收。

### 2026-09-24 中文RED消费全链路补齐

检查18个RED查询节点及下游：13个服务/端点RED和5个平均耗时/成功率查询。旧中文指标查询名已有dataplane映射，保持兼容；query_red_metrics新增cpm/errorRate/avgDurationMs/successRate入口，端点RED内部调用使用原生字段。

- 3个请求速率提取节点修复cpm匹配；3个当前/历史延时、错误率提取节点统一单位；与4个报告组装节点使用同一明确字段映射，避免数组位置、旧title及service标签依赖。
- 资源拓扑补serviceName/service_name关联、服务去重；3个资源证据节点对同服务同序列去重，明确每分钟请求速率和服务粒度。原tps输出变量保留作为兼容出口。
- RED模型提示统一CPM、0..1错误比例、毫秒；修正固定微秒和“不要做转化”的冲突、移除格式化结论中虚构20%阈值样例。可用性错误序列保留unit；平均耗时样本P90补充实际用途说明，算法不变。
- 成功率历史查询也固定为[start-24h,start]，避免超过24小时。图边、eBPF节点和告警判断保持。报告图保留null，统计输入副本跳过null以适配原统计器；不补零、不新增结果状态。
- 本轮31个已有节点调整（资源14、可用性9、简单根因7、有效性1），分类和英文不变。Dify相关回归189项、报告41项、前端构建通过；173个代码、164个工具、13个迭代模型校验通过。未提交、导入发布或现场验收。

以下为此前公共工具阶段验证记录：

- `cd api && .venv/bin/pytest tests/unit_tests/core/tools/builtin_tool/providers/apo_select -q --disable-warnings`：119 项通过。
- 覆盖所有适配指标工具的实际 _invoke、请求租户/Provider/对象，RED 小数与真实 step、成功率、单值零、毫秒/微秒、拓扑方向、日志与 Trace、缺租户不发送请求、错误保持空结果、旧 APO 请求。
- 真实本地 HTTP Server 下并发执行两个租户同名主机查询，捕获 tenantId/labels，分别返回不同数值，无串租户；上游为受控 fixture，不是实际 dataplane/COS。
- 102 份 YAML 按真实 Provider 加载流程注入 identity.provider 后，经 ToolEntity 校验通过。
- 原 Span 测试错误地期望内部 data，但源码原来就保留 Provider 包装；本轮校正测试断言，业务输出不变。
