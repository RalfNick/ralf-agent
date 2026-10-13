# 首个委托 Coding Action 集成契约

| 项目 | 内容 |
| --- | --- |
| 状态 | 待实现的集成契约；不代表完整 Runner 或验收已交付 |
| 范围 | 一个显式选择的受限 Codex Coding 场景，一个逻辑 Action 对应一个原生 Turn |
| 上位契约 | [Runner 能力契约](runner-capability-contract.md)、[Run 命令契约](run-command-contract.md) |
| 现有基础 | [Codex 协议与启动证据基础](../../docs/codex-runner-foundation.md) |

本文固定下一步的责任与验收边界，不分配新的 kernel、数据库 Schema、联合绑定协议或发行版本。实施时须发布可被旧执行器识别并拒绝的版本门禁，且保留既有默认声明与历史视图。

dev102 已增加具体 `DockerCodingEnvironment`、借用原 `PostgresEffectJournal` 的
`PostgresRunnerJournal` 与 Local／PG 共用纯阶段规则，见[环境／日志指南](../../docs/codex-coding-environment.md)和[本批登记](../reviews/2026-10-14-codex-environment-journal.md)。
原 ID／generation 冷检查、实际整容器停止及 PG 原 dispatch／启动意图事务已有有限
证据；原 Action／Local／Temporal 准入、停止采纳与 History 尚未集成。原始 Docker
argv 可重启已停容器，不能声称旧 grant 失效。完整 G3／G5／G7／G8／R13 保持开放；
PG 初始化 P1／全循环取消 P2 已由同一审查者实际复验修复，最终受影响源码 301 项零
跳过；这些修复不关闭下列原权威生命周期要求。

## 1. 实现边界

保留 `Action.kind = "tool"`、`ToolSpec.effect = "queryable_write"` 与 `requires_approval = true`。既有参数 Schema、操作摘要、稳定 effect key、审批、预算预留和结果提交继续由原执行权威管理。该 Action 表示整个委托 Turn；外部内部文件、命令与重试不因此成为 RALF 管理的逐步骤工具调用。

Local Coordinator／SQLite 和 Temporal Workflow／History 分别保持原 Run／Action 权威。原生 RPC、启动证据日志和容器所有者只执行已准入的有限操作并返回证据；不建立另一个调度器，不决定 Run 终态，不在 ModelProvider 或纯 Harness 中运行外部循环。

| 对象 | 现有基础 | 本契约要求的待实现集成 |
| --- | --- | --- |
| 原 Tool Action | 类型化调用、审批、效果身份、结果提交 | 显式委托标记及独立原生生命周期记录 |
| Codex 协议／RPC／环境 | 固定协议验证、有界传输、本地进程清理；dev102 保留环境的同 ID 检查与实际整容器停止 | 原权威准入、原句柄观察、旧启动失效及停止证据采纳 |
| RunnerJournal | Local 独占 SQLite 启动阶段、原生句柄与取消意图 | Local Action 绑定与采纳；不能充当 Temporal 共享日志 |
| PostgresRunnerJournal（dev102） | 借用原 EffectJournal 同事务保存原 dispatch／启动意图，共享有限阶段与固定句柄 | 原 History phase／control grant、取消顺序、停止与结果采纳；日志许可不代替准入 |
| Coding 控制读回／namespace 门禁 | 控制检查和物理限制的基础 | 与业务授权、专用原生认证、完整执行生命周期及实际验收结合 |

控制读回通过不表示原生业务已经获准。当前完整链路仍缺专用原生认证接入：认证身份、受控凭据引用、原生提供方连接及失效处理须独立验证。不能借用桌面会话、环境里的未知凭据或配置中的认证存储选项声称此项已交付。

## 2. 显式声明和有限接口

待实现的 `ToolSpec.config.delegated_runner` 是严格校验的标记，绑定 adapter、原生版本、协议摘要、场景 Profile、有效配置、能力报告与输入契约。注册工具的实现摘要和实际 Runner 资源身份同时固定；普通 callable 添加同名配置不能取得启动权。引擎在进入通用 ToolExecutor 之前识别此路径，直接调用通用 handler 必须拒绝启动。

可选 per-Agent `runner` 绑定沿用 `inherit / ref / disabled`：继承显式 Profile 默认，引用精确组件／版本，或禁用委托能力。无 Runner 声明的旧 Agent 保持原路径；禁用或缺失 Runner 时，显式委托工具不能静默换执行器或降低场景限制。新增绑定字段只进入显式新声明，不改变旧声明序列化字节。

以下数据和端口均为待实现名称。跨进程只传有界、严格校验的 JSON 快照；不传 callable、连接对象或裸凭据。

| 数据 | 必须固定的内容 |
| --- | --- |
| `RunnerStartRequest` | 原 DispatchEnvelope、Run／Action／effect key、Release／操作／请求摘要、能力与环境身份、上下文引用、deadline、预算和启用路径 |
| `RunnerHandle` | 原领域身份、Thread／Turn、原生 process epoch、容器 ID／generation、workspace／session store、worker／daemon affinity 与 execution epoch |
| `RunnerObservation` | 原绑定、原生状态／事件水位、pending interaction、输出／产物／用量、独立原生终止／传输结束／整容器停止证据；未知保留未知 |
| `RunnerControlRequest` | 原身份与 Handle、当前 epoch／generation、控制幂等身份、取消原因和已应用命令顺序 |

具体 Runner 资源提供有界 `start / observe / cancel / reconcile`；资源关闭须等待实际控制、传输清理和原权威确认，未结束时返回 `CloseIncomplete` 并保留租约及证据接收方。引擎安排后续观察和控制，传输 reader 不产生新业务推进。

`reconcile` 只查询原环境、原 Thread／Turn 与已有启动／效果证据。它不能调用 `thread/start`、`turn/start`、批准原生操作，或以 `thread/resume` 后追加 Turn 代替恢复。

## 3. 原审批、启动与取消顺序

1. 静态版本／实现／能力／环境声明检查先于业务 I/O；无业务效果的握手读回在原生 Turn 前完成。工具参数、环境限制与委托声明共同进入原操作审批绑定。
2. 原引擎应用审批、策略与预算决定，再持久化启动意图。每次 `thread/start` 和 `turn/start` 分别取得原权威完整请求的阶段准入；阶段提交许可只产生一次。
3. 顺序固定为 `intent → thread_submitted → thread_confirmed → turn_submitted → turn_confirmed`。每个原生回执先保存，再由原权威采纳。已提交但无回执属于 `start_unknown`，包括提交后实际尚未发送的保守窗口；重启或 Activity 重投不能重置阶段或再次提交。
4. 有 Handle 时观察同一任务；缺少可信关联时不能用相近时间、相似输入或同一 Thread 猜测未知 Turn。非取消 Run 按聚合规则等待核验。
5. 原权威应用取消命令后进入 `cancelling`，持久化取消意图并禁止新的业务推进。原生 interrupt 空回执只记录受理；deadline 使用同一取消路径和停止门禁。
6. 完成与取消竞争按原引擎提交顺序裁定。取消已应用后，迟到输出、终态或错误仅保留证据，不能把 Run 改回 running／succeeded；成功已提交后的取消按命令契约处理。

Local 的冷启动取消、异常、abandoned attempt、一般 cancelling 收尾和 deadline 路径，均不能用“没有活跃 Python task”直接关闭委托 Run。Temporal 的取消 Update、deadline、Activity 超时／失败、结果采纳与核验路径同样受此门禁约束。旧非委托路径保持历史行为。

## 4. 生命周期与停止门禁

待实现的 Action 生命周期记录至少保留：完整原绑定与请求、启动阶段／独占准入、原 Handle、观察水位／证据摘要、已应用取消意图、原生取消 ack、原生终态、传输结束、整容器停止、过期执行防护、独立未知效果案件和停止门禁结果。

各证据独立校验：

- **原生停止**：原 Turn 的可信终态，或原生所有者结束的可核验证据；原生终态缺失时保留未知，不补造 interrupted。
- **整容器停止**：原容器 ID／generation 的实际停止检查，覆盖 Profile 内所有受控后继；关闭 docker attach、RPC reader 或父进程不足以证明它。
- **过期执行防护**：旧启动／控制 grant 已失效，旧 worker 不能再发布新状态或创建效果；epoch 本身不证明此前效果没有发生。
- **效果分类**：已确认或独立 unknown 案件及其证据已经持久化；停止不回滚已提交效果。

已启动场景必须独立证明原生执行停止与整容器停止，再提交终态／最终输出或允许后继 Action。若原生终态不可取得，须以覆盖原生所有者及全部受控执行的实际容器停止证明结束执行，同时明确保留原生终态未知；不得用 ack 或本地进程消失替代停止证明。证明尚缺时保持 `cancelling` 或待采纳完成状态。

原生 completed 但后继进程仍活跃只产生待采纳完成证据。产物及会话定位信息须在受控命名空间校验／保留；停止容器不能删除唯一启动、句柄、停止或输出证据。最终结果通过 Schema、来源、权限、命名空间和内容 digest 校验后，复用原 Tool ResultCommit 一次采纳。

执行停止与效果核验不是同一状态：符合停止门禁的取消可以提交 `cancelled`，同时保留独立 unknown 效果案件。未知案件不能强迫取消 Run 回到 `waiting_reconciliation`，也不能因 cancelled 而被关闭或解除跨 Run 的旧效果防护。普通工具完成／`tool_execution_ended` 只说明 handler 生命周期，不自动关闭委托原生执行。

## 5. 原 owner 丢失与 Temporal 耐久边界

首场景声明 `recovery_modes = [none]`。查询原句柄和采纳已有证据不等于检查点恢复、session_continue 或跨 worker 执行续接。持久 Thread／workspace 定位信息不等于可迁移执行状态。

Local 可以复用 RunnerJournal 的物理身份检查、独占租约和一次阶段许可。Temporal 必须使用与原 History 绑定的权威 PostgreSQL 启动／句柄／取消／停止记录，或具备等价实际验证的共享耐久机制；dev102 的 PostgresRunnerJournal 已借用 PostgreSQL EffectJournal 事务与稳定效果身份增加有限启动阶段记录，原 History 绑定、停止记录与采纳仍待接入。每个 Activity 自建 Local SQLite、内存字典或 heartbeat 中的 Handle 均不能满足此要求。共享日志不代替 History 的审批与控制权威，也不证明原生环境可恢复。

原 History 固定容器／daemon、workspace、session store、依赖摘要、generation 与 affinity。新 worker 只允许取得原环境的兼容租约并查询／停止同一执行；不能创建替代容器、换 workspace、换默认 Profile 或重新提交 Turn。旧 owner 死亡后，兼容 owner 能访问原容器时执行实际检查／停止；原 host／daemon 不可用时保留 `cancelling`、未知记录和 `CloseIncomplete`。

初始 stdio 原生连接的可恢复性保持未证明。仅在实际协议与原 session store 支持时，由受限查询连接读取已知原 Thread／Turn；查询不可用则保留未知。旧 connection/process epoch 的原生请求 ID 不重放。首 Profile 对 approval/input/auth 等未支持等待返回类型化 unavailable 并受控停止，不能把等待文本当成功或自行回复。

## 6. 原权威实施落点与发布门禁

Local 在原 store 命令／Run／事件事务中保存准入、取消与证据采纳；drive 优先处理原委托 Action 的观察／控制，再考虑后继 model／tool。已有 unknown Tool Action 仍可有未完成的停止工作。Terminal 和异常分支统一调用委托停止谓词，不由 facade 补写状态。

Temporal 在原 Workflow 中建立有限启动、观察、取消与核验 Activities，以及原始 phase grant／control grant／evidence Updates。请求固定实际 Workflow ID／run ID／namespace、完整摘要和 epoch，结果经 History 采纳。Activity 重试或超时不能重启业务 Turn；有界 Activity 结束后，由原 Workflow 的 timer／wake 安排下一次观察或已应用取消。通用 Tool Activity 与 handler-end Update 不承载完整停止保证。

新增协议／数据库门禁须经过实施评审后分配并使旧 Local／Worker 在业务 I/O 前拒绝；联合绑定校验须显式验证已有功能与委托功能共存。新 worker 仍读取／重放历史非委托发布，默认 Profile、默认字节、原路由及借用／拥有资源语义保持兼容。组件工厂须先纯校验，再取得受控资源，构造不得自动启动原生业务。严格企业工具治理、任意 MCP／管理／实验路径、硬 token／金额预算或不满足 affinity 的请求必须拒绝，不做隐式降级。

## 7. 有限验收 G1–G8

| 门禁 | 首链路必须提供的证据 |
| --- | --- |
| G1 声明／兼容 | SDK／JSON／TOML 与 runner inherit/ref/disabled；无声明默认字节／历史视图保留；真实旧 Local／Worker 拒绝新协议；能力／实现／环境不匹配在业务 I/O 前失败 |
| G2 原准入 | 一个原 Action／效果身份／预算；原审批绑定参数和环境；完整阶段 grant 在原生效果前；外来 invocation／epoch／控制和通用 handler 绕过被拒绝 |
| G3 启动窗口 | intent 后、Thread／Turn 发送与回执之间、Handle 保存与原权威采纳之间故障；进程重开／Activity 重投／重复 worker 至多一个 Turn；无法关联则 unknown 且零重提交；Temporal 使用实际共享 PG |
| G4 原查询／采纳 | 原运行／完成／中断／错误／未知状态；丢失终态通知、重复／乱序／迟到证据与已保存未采纳结果；查询只针对原定位，最终结果一次提交，未知不成为成功 |
| G5 取消／deadline | Local 与实际 Temporal 冷／热取消、ack 后继续执行、父进程结束后存活后继、owner 丢失／Worker 重启；独立原生和整容器停止；deadline 同一路径；竞争按原提交顺序；unknown 效果案件独立保留 |
| G6 原生等待 | approval/input/auth 与 inbox 溢出／断线均类型化处理；首 Profile 不支持时关闭路径并停止，旧 connection/process 请求不回复，无等待伪成功 |
| G7 环境／认证／产物 | 实际禁止根路径、工具出站、生产凭据、MCP 和管理绕过；专用原生认证与提供方连接验证；workspace／session replacement 拒绝；受限写入／测试及 digest 校验输出；原生与整容器实际停止；未知用量不记零 |
| G8 实际发布 | 显式批准的一个真实固定版本 Codex 小型 Coding Turn：原 Agent 调用→外层审批→原生执行→测试／产物→停止→原结果；真实取消夹具、源码／固定 wheel、实际 Temporal History 恢复／重放；记录能力×版本×环境报告 |

控制读回、namespace 拒绝探针、假服务或类型／接口定义只证明各自有限基础。专用认证、实际业务 Turn、完整停止采纳或实际 Temporal 门禁未通过时，继续标记缺项，不能据此声明完整 Coding DelegatedRunner 或 v0.2 契约已经完成。
