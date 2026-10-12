# dev90：DeepSeek 思考续接验收

状态：本批思考续接适配子集已验收，不构成完整 R05／H3／M1／R01–R26 完成声明。
基线：dev89 `fe4474d`；本批规格与计划见
[设计](../../docs/superpowers/specs/2026-10-13-deepseek-thinking-design.md)和
[实施计划](../../docs/superpowers/plans/2026-10-13-deepseek-thinking.md)。

## 实现与边界

独立 `DeepSeekThinkingProvider` 与 `deepseek-thinking`，不改变旧非思考模式、
默认 Profile／模型／执行指纹或原三字段 ModelResponse。
原 ModelContinuation 保存原 assistant message，包括最终 reasoning 和原参数字符串。
适配器只转换 HTTP/SSE，原 Local 收到／采纳、Temporal History 及工具执行权威保持。
所有 native assistant 经 owner／决策／原 message 关系验证，有限证据超限失败；
reasoning 只作私有协议数据，公共报告不返回该字段。

SDK、严格 Registry、Local 同步／异步 Profile、Temporal Profile 和四类评测 CLI
接通同一适配器；组件替换、每 Agent provider ref 复用原机制。
显式思考模型默认 high effort，未提供或不支持的配置不会自动切换模型／协议。

行为修复：dev89 Temporal Gemini functions 在缺少续接 opt-in 时仍能装配，
本批在创建 owned 资源之前与 DeepSeek thinking 一起拒绝该配置。
该原配置缺少可执行发布契约，不作为默认或已接受 Run 的兼容破坏；旧合法
无续接声明保留身份与装配顺序，最终安装旧版兼容另行验证。

## 证据

- 独立任务先 RED：协议缺失、SDK/配置/CLI 缺失和实际 Temporal 配置关系缺失均保留失败日志；JSON/SSE nullable 协议与边界单独复现。
- Local 实际 Provider＋MockTransport、RAG 检索、图／Team／嵌套／ModelPlanner、审批重启、进程响应采纳崩溃和两 Session Turn 均保留原消息、效果与固定 owner。
- 本批真实 Temporal CLI 1.9.1／Server 1.32.0，默认 History 配置；native／graph × approval／receipt 四项实际 Worker 进程故障恢复，原回执及最终 reasoning 保留，重复审批只有一个工具效果，六次 History 重放。Worker 已回收，服务由本批独立管理。
- 最终源码6519 passed／593配置依赖跳过，993.63s（0:16:33）；唯一有效最终进程PID72149／session93703退出0。配置依赖服务未启用，跳过不算通过。
- 独立核心安装266 passed／零跳过；七类可选SDK均不存在。四类CLI help及缺配置not_run共8命令通过，明确配置缺失返回2；原SDK示例＋TOML配置在独立wheel验证，MockTransport未调用付费模型。
- 独立安装真实Temporal12 passed／零跳过（112.99s），其中新DeepSeek4与既有Gemini8；source真实新4和六History重放已另记。两次Worker运行不同队列与独立数据目录，源码／安装证据分别保留。
- 308产品模块在源码／wheel／sdist／核心安装／SDK安装一致；309产品文件冻结后未变。旧dev89默认Profile／Provider／Local/Temporal Manifest／descriptor/DTO字节一致，plain／continued／run-plain／run-continued四类旧→新→旧完整回执与预算一致，每类模型2次、效果1次。
- 本批owned Temporal服务PID38109／session34413经SIGTERM正常shutdown，工具实际等待退出0，PID已消失。未改变用户Docker或其他服务。
- Ruff、1181文件格式和Git空白检查通过；文档链接与凭据形状扫描另留记录。仅本地提交，实际SHA以Git记录为准，不推送远端。

私有证据目录：`/private/tmp/ralf-agent-dev90-zlpyussz/evidence`。
MockTransport 不调用真实 DeepSeek，不证明思考质量或线上型号兼容。
当前凭据环境未配置，无真实付费模型试验。原 dev28／29 成绩是历史非思考试验，
不挪作本适配器成绩；框架对等比较与独立采用仍缺实际证据。

## 持续开放

Responses reasoning、模型路由／fallback、其余厂商协议与实际多模型兼容矩阵；
完整任务集的重复规划／答案／引用／停止／拒绝质量；Temporal Continue-As-New／
History 容量治理、完整部署／隔离／身份权限、外部采用及 R01–R26 其他门槛。
本批不扩大这些能力的验收范围。

## 一轮独立审查

唯一 fresh reviewer 验证两个P2：旧64字符函数名边界错误拒绝合法65–128名称；
超过原历史1024字符上限的call_id被接受后先执行工具、下一模型请求才失败。
六项有效RED（JSON/SSE各名称65/128与ID1025）及三个控制项保留在私有证据。
已统一将名称边界对齐128，并在JSON/SSE原响应验证时拒绝超长call_id，保持原
256调用及131072 UTF-8续接限额；控制ID1024完整往返；最终202 targeted passed，9个审查回归与193新增协议／装配／执行测试均通过。
一轮审查的两个P2均闭环，无第二轮fresh review。

核对原行为后修正测试预期：非法HTTP响应产生ProviderError，原Run保留
waiting_reconciliation／unknown模型额度，工具Action与效果为零。纯观察不会
派发；再次显式drive可新增模型attempt和未知额度。这是既有执行契约，不为
适配器把Run强行改成failed，也不宣称模型调用／计费恰好一次。

## 无效尝试与验收取舍

最初全量在沙箱内因localhost绑定PermissionError无法有效执行；停止时Python真实路径
校验不符，root误启动了第二进程，导致日志重叠。两个本批进程66655／71161经命令／父进程
核对后分别SIGTERM并实际等待exit241（child -15），均已消失，重叠日志标记无效。
最终仅evidence/source-final独立目录的PID72149完整结果用于验收，不将中止输出当通过。

安装Temporal初次未设置地址而12项跳过，随后显式地址的12项真实运行通过；跳过不计成绩。
CLI起初将显式缺凭据返回码错设0，依据原契约纠正为2，status仍not_run/calls0。
这些是验收操作／测试预期纠正，没有放宽产品或修改执行权威来取得GREEN。
