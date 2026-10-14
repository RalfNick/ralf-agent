# dev115：剩余能力与架构验收清单

Dev115 补齐[Local 持久期限](local-execution-policy.md)与原编排的审批到期、宿主计时诊断、实际线程保留及冷恢复；[验收登记](../architecture/reviews/2026-10-14-local-deadlines.md)区分实现、源码、安装与历史兼容。批次 2 的部署原子准入／容量尚待交付，服务观察、身份 ACL、保留及框架恢复仍按第三阶段矩阵继续开发。

当前执行依据为[第三阶段支持矩阵](phase3-support-matrix.md)。Dev114 首批补齐[Temporal 策略配置](temporal-execution-policy.md)：原期限／审批策略通过 SDK／JSON／TOML 与同步／异步工厂装配，内置非法配置提前拒绝，错误自定义返回值不得静默省略。本批[验收登记](../architecture/reviews/2026-10-14-temporal-policy-profiles.md)单独管理源码／安装、实际恢复与兼容；部署准入、服务控制／持久观察、身份／权限、保留与框架恢复仍待后续批次。

第二阶段已按[冻结支持矩阵](phase2-support-matrix.md)收口；R01–R26是长期路线图，安全拒绝的未选择组合不自动阻塞阶段。Dev113顺序／递归Temporal Coding的所选真实服务、安装、兼容与完整回归已通过，第二阶段随本地提交冻结；当前工作转入第三阶段服务化与企业治理。远程Facts联合索引／自动维护、其他Runner、跨宿主及完整daemon负向自动恢复继续保留，不能以历史批次未支持段落扩大当前必需项。

Dev112 补原 CREATE broker／两层单次 gate、真实处理器生命周期、固定源码与别名身份、持久回执和 `create_not_dispatched` 专用证明；原 Local／Temporal 采纳和实际排空后才释放容量。新选定20／21，旧18／19使用 immutable dev111 Worker，未选定默认保持。验收见[本批记录](../architecture/reviews/2026-10-14-coding-create-supervision.md)。CLI 监督与严格未发送窗口不再笼统列为未实现；可能已发送但 daemon 终态丢失、持久排队、公平性、跨宿主、嵌套／sequence Coding 及复杂真实质量仍开放，完整 R13／第二阶段未关闭。下述历史段落按各批次保留。

Dev111 补同物理 Runner 根容量、一原 invocation 等待、持久原义务、原 CID 冷控制恢复与所有权 CAS；新选定 Temporal18／19，旧16／17需要 immutable dev110 Worker。能力按[本批验收](../architecture/reviews/2026-10-14-coding-root-capacity.md)分层登记。create 空查询的负窗口、CLI监督、持久排队、公平性、跨宿主、嵌套／sequence Coding 与复杂真实质量仍开放，完整 R13／第二阶段未关闭。

Dev110 已验收直接 Agent 成员子集：实现原 Temporal 父 History 的一层 Agent Team／Dynamic Coding，固定有效成员绑定、物理停止与结算双重背压、replan 历史义务和 pending-only DAG patch。未选定默认字节保持；嵌套／sequence 成员、跨父容量、不确定 create／CID、跨宿主及复杂真实质量继续开放。验收按[本批记录](../architecture/reviews/2026-10-14-temporal-coding-orchestration.md)登记，不以实现或测试数量关闭完整 R13／第二阶段。

Dev109 接通固定 Responses 模型连接、延迟解析的可替换凭证源和 Local／Temporal 显式装配，继续复用原 Action／History 执行权威。dev109 当时选定 Temporal 发布为 native protocol 2／binding 14、静态组合 version 3／binding 15；旧选定发布需要匹配的 immutable Worker。安装包真实 DeepSeek 的三类有限 POSIX Coding 任务各重复三次，通过 9/9 次、78 项独立禁网容器检查；不代表通用 Coding 质量或 AgentScope 对齐。Temporal Team／Dynamic／嵌套 Coding、跨父全局容量、跨宿主和不可确定 create／CID 窗口仍开放，完整 R13／第二阶段未关闭。 见[连接指南](codex-model-connection.md)和[本批验收](../architecture/reviews/2026-10-14-codex-model-connection.md)。

Dev108 已验收有限 Temporal 有界静态 Agent 图 Coding：协议 13／组合版本 2，在原父 History 按有效 Runner 授权调度不同资源并行和共享资源背压；财务已结算但未证明物理结束的原子仍占槽。关闭尝试全部独立原叶、准确核对 PG／History 完整请求并重扫，失败保留资源；停止失败恢复不会重开取消中的业务。Team／Dynamic 的持久选择阶段、跨父全局 Runner 容量、嵌套／直接 Tool、专用认证和真实 Coding 质量仍开放，完整 R13／第二阶段未关闭。 见[并行指南](temporal-parallel-coding.md)和[本批验收](../architecture/reviews/2026-10-14-temporal-parallel-coding.md)。

Dev107 已验收有限 Temporal 串行 Agent 图 Coding：显式 `coding_composition=True` 依赖原 Coding 开关，协议 12 固定原父子请求、namespace UUID 和 SDK epoch；原 History 继续管理调度、审批、结果和预算，PG 只存证据。owned 关闭排空真实 SDK 提交、关闭已有提交准入，并采纳原后代的物理停止；未知效果与整个子 cap 保留。直接 Tool／并行／Team／Dynamic／嵌套 Temporal Coding、跨宿主、专用原生认证和真实 Coding 任务质量仍开放，完整 R01–R26／R13／第二阶段未关闭；dev99 四链路保持冻结。 见[组合指南](temporal-coding-composition.md)和[本批验收](../architecture/reviews/2026-10-14-temporal-coding-composition.md)。

Dev106 完成有限 Temporal Agent／顺序 Coding 的有限实现与阶段验收：原 History 管理阶段准入、原 Tool claim／进程 owner、结果和预算；同一个 PG EffectJournal 持久化资源意图及回执。SDK／JSON／TOML 的原 Runner 绑定与 owned 关闭重试已接通，真实原生控制使用精确 readonly 配置保护。最终交付检查以[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)为准。复杂 Temporal Coding、跨宿主接管、不可确定 create／CID 窗口、专用原生认证和真实 Coding 任务质量继续开放；固定进程 peer 的业务协议验证不代替真实模型质量。dev99 参考链路仍保持冻结。

Dev105 将有限 Coding 委托扩展到 Local 图 Agent／直接 Tool 节点、串行／有界并行图、Team／Dynamic 和嵌套成员。复杂发布使用 `local-11`／`local-bindings-19`、`delegated_composition_protocol=1`；根级 Agent／顺序的旧路径和默认未选择工具的字节保持。原子 Run／节点 Action 继续拥有审批、额度和阶段准入；父级取消等待原后代实际停止，unknown 效果与 escrow 不因此清空。并行节点视图核对原 Run／Action／索引／资源，已排除的工具不影响调度，拥有资源关闭仍保留原权威供停止与退出回执。Temporal Coding、专用认证、真实 Coding 任务质量及完整 R01–R26／第二阶段继续开放。见[复杂组合指南](coding-composition.md)和[本批记录](../architecture/reviews/2026-10-14-coding-local-composition.md)，dev99 冻结链路保持。

Dev104 将可选 `runner` 绑定和异步 `tools/codex-coding` 声明接入原 Local 根级 Agent／顺序 Workflow，支持一个 Profile 中多个独立 Runner、精确 `registered-tool` 借用和 owned 关闭重试。显式绑定使用 Descriptor 3／`local-bindings-18`，省略角色保留原 Descriptor 1／2 与默认发布；工具授权交集和原 Run／Action／预算／审批权威保持。具体资源在模型 I/O 前复核物理身份，owned 清理开始前隔离原 Engine，停止或关闭失败保留 Coordinator 和资源账本。图／Team／动态／嵌套与 Temporal Coding 继续拒绝，原生认证和真实 Coding 质量未验收。见[配置指南](coding-profiles.md)和[本批记录](../architecture/reviews/2026-10-14-coding-bindings-and-profiles.md)；dev99 冻结链路不重复评测，完整 R01–R26／G1–G8／第二阶段继续开放。

Dev103 将[有限 Coding 委托](local-coding-delegation.md)接入原 Local 审批、预算、Action、阶段准入、未知效果和停止采纳；公共待停止存储查询与 opt-in 原容器移除补齐冷关闭保护。首期仅 SDK 根级未绑定 Agent／顺序 Workflow，真实 Docker 停止／旧 argv 失效与结构化假服务的业务恢复分别登记。下一门槛是 per-Agent／声明接入、复杂父级编排及 Temporal 原 History 准入／控制／共享 PG 证据；专用原生认证、真实业务 Turn、完整 G1–G8／R13／第二阶段未完成。dev99 继续冻结，验收详见[本批记录](../architecture/reviews/2026-10-14-local-coding-delegation.md)。

Dev102 增加[保留环境与共享 PG 启动证据](codex-coding-environment.md)：同容器冷检查、实际整容器停止、原 EffectJournal 原意图事务与共享纯规则已实现，最终受影响源码 301 项零跳过、PG 初始化路由 P1／全循环取消 P2 已实际复验闭环。下一批接原 Action 审批／阶段 grant、旧 worker 启动失效、原 Local／Temporal 停止采纳与 History；原始 argv 仍可重启，不宣称 fence。专用认证、业务 Turn 与完整 G3／G5／G7／G8／R13 保持开放。[本批记录](../architecture/reviews/2026-10-14-codex-environment-journal.md)保留无效中断全量，独立安装同 301 项零跳过、实际无模型控制／停止／冷重开通过，dev99 冻结范围保持。

Dev101 已补固定候选的[配置／原生控制检查](codex-coding-preflight.md)及有限 namespace 命令／后继停止证据。dev102 补共享启动日志基础，下一步以[原 Action 委托契约](../architecture/specs/delegated-coding-action-contract.md)实现原准入、History 绑定、停止采纳和冷恢复；专用原生认证与真实模型 Turn 待验收。控制检查不授予执行权，完整 R13／第二阶段继续开放。

第二阶段首批新增 [Codex 协议／启动日志基础](codex-runner-foundation.md)。回执丢失禁止重发，通信／证据组件不增加执行权威。完整 Runner、真实业务工具隔离、Local／Temporal 停止门禁及真实模型 Codex 验收未完成；第一阶段 dev99 冻结证据和 R01–R26 保留。

当前按用户修订的[分阶段交付门槛](delivery-gates.md)推进：四条有限 Local 参考链路的安装／必要恢复／质量／文档验证已通过，随本地提交冻结后转入环境执行阶段；服务与企业治理随后推进。R01–R26 保留，非阻塞扩展不自动进入当前批次。默认模型配置、失败历史和真实质量范围分别登记，不以案例分数宣称完整框架或 M1 验收。

Dev98 自动 Facts 索引维护首期子集已验收：来源快照分代、原 Graph ToolAction、准确效果日志和 ready-only Agent 门禁；SDK／JSON／TOML、owned／borrowed 与可编辑 memory-index 模板接通原 Session／Profile 恢复。最终冻结源码 8298 passed／617 配置依赖跳过，两套安装各 163 项零跳过，12 种配置／32 个实际 Turn、六类进程窗口和旧 dev97 的 16 组 Run／Turn 双向兼容通过。349 产品模块一致，四项审查问题由同一审查者闭环。首期仅原生 SQLite／Hash；真实语义／模型质量、远程及 Temporal 维护、后台／增量物理清理／GC、两项 P3 严格输入观察、完整 R01–R26／H3／M1 和外部采用继续开放。 见[使用指南](fact-index-maintenance.md)与[验收记录](../architecture/reviews/2026-10-13-fact-index-maintenance.md)。

Dev97 模型替换与业务组合子集已验收：固定 model-provider core P01–P10／tools P01–P16、可编辑 SQLite 供应方、SDK／JSON／TOML、同步／异步与 owned／borrowed 装配接通 Agent／当前来源 RAG／规则 DAG Plan／Supervisor Team。最终源码 8183 passed／617 配置依赖跳过；独立核心／SDK 各 205 项零跳过，修复后的安装应用共 192 种配置组合通过。六项 P2 经同一审查者闭环；实际原响应、审批效果与遗失响应窗口、旧 dev96 的 16 组 Run／Turn 双向恢复、8 类原生模型方法与默认及 K/S/Facts 字节兼容通过。345 产品模块与安装包保持一致。新返回模型证据以 128 层容器为界，超限保留完成与结算，历史已接收记录保持。未重新验收真实模型、远程服务、Temporal 或独立采用；完整 R01–R26／H3／M1、路由、索引生命周期和质量目标继续开放。 见[验收记录](../architecture/reviews/2026-10-13-model-adapter-contracts.md)。

Dev96 Facts 存储契约子集已验收：core F01–F10／managed F01–F16，独立 SQLite 替换、SDK／JSON／TOML、同步／异步装配及原提炼／受管理恢复通过。最终源码 7989 passed／617 配置依赖跳过；独立核心／SDK 各 262 项零跳过，每套安装示例完成同一应用 24 种配置组合及实际原工厂恢复。旧 dev95 的 16 组 Run／Turn 双向兼容、80 个已回收子进程、原默认／方法／K/S 字节及 342 模块一致通过。一次独立审查的三项 P2 已由同一审查者闭环，含慢速／最长及空白 namespace、历史计数与审计快照修复。本批没有重新验收真实远程服务、Temporal、模型／语义质量或独立采用；其他角色、索引生命周期、完整 R25／R01–R26／H3／M1 继续开放。 见[验收记录](../architecture/reviews/2026-10-13-facts-adapter-contracts.md)。

Dev95 Session 存储契约子集已验收：core 固定 S01–S10，receipts 固定 S01–S14；独立可编辑 SQLite 替换、同步／异步 SDK／JSON／TOML 装配及原保存恢复通过。最终源码 7727 passed／617 配置依赖跳过；独立核心安装 272 零跳过，SDK 166／1 服务配置跳过，安装示例 13 个实际命令通过。旧 dev94 默认和原 Run／Turn 的 68 个进程兼容验证、338 产品模块一致、隔离／取消及示例地址审查修复通过。本批没有重新验收真实 Temporal 服务、外部远程适配器或模型质量。严格原始非法输入、其他角色 Suite、独立采用与完整 R25／R01–R26／H3／M1 继续开放。
见[本批验收](../architecture/reviews/2026-10-13-session-adapter-contracts.md)。

Dev94 已验收 R25 首个知识检索适配套件：零配置不运行、固定 K01–K12、独立可编辑外部实现、SDK／声明替换／安装及真实本地恢复。原生 Temporal 兼容另验，不认证任意外部适配器。未验证能力不折算完成，完整清单和质量目标保持。见[本批验收](../architecture/reviews/2026-10-13-knowledge-adapter-contracts.md)。

Dev93 的持久用户输入子集已验收：问题和答案沿原 Run／Turn 保存，回复具有
独立命令回执，动态规划消耗原修订额度而不重置预算。最终源码 7339 passed／
617 配置依赖跳过；独立核心 259／SDK 277 零跳过，源码和安装 Temporal 各 12 项、
24 Worker 实际等待、48 条 History 重放；旧 dev92 兼容与六项审查修复通过。
R01–R26／H3／M1 整体目标、真实模型质量与独立采用继续开放。
见[使用指南](user-input.md)与[本批验收](../architecture/reviews/2026-10-13-durable-user-input.md)。

Dev92 R10／H3 父级完成验证子集已验收：显式可替换policy、真实子Run／工具回执、Receipt／Inventory纯gate、受管理模型stage、Plan反馈和Team拒绝沿原Local／Temporal权威实现，提供SDK／Profile和安装后默认参考。最终源码7126 passed／605配置依赖跳过；独立核心522／SDK413零跳过，实际源码及安装Temporal各7项／各23条History重放；旧91默认及六类原Run双向兼容、旧Local／Worker业务I/O前拒绝、321产品模块一致和自有服务退出通过。一次fresh review及同一reviewer修复复验闭环五项Important，包括根Session写响应丢失后的原回执／真实结束证明恢复。原通用推荐版本1／2默认保持；真实模型质量、完整R10／H3／M1／R01–R26及外部采用继续开放。见[使用指南](parent-completion.md)及[本批验收](../architecture/reviews/2026-10-13-parent-completion.md)。

Dev91 显式 Responses 推理续接子集已验收：保留原有序 output／密文／phase 和工具原参数，复用原 ModelContinuation／ModelHistory 与 Local／Temporal 执行权威，接通 SDK／Profile／四类评测 CLI。最终源码6792 passed／598配置依赖跳过（856.08s），独立核心安装494 passed／零跳过，实际源码Temporal5／安装Temporal17通过；311产品模块一致，旧90四类原Run及默认字节兼容。一次审查3个P2与1个CI Minor已修复，另5项公共边界回归通过；自有服务正常退出0并等待。原默认和历史发布不迁移；真实模型质量、完整R05／H3／M1／R01–R26及独立采用继续开放。见[使用指南](responses-reasoning.md)及[本批验收](../architecture/reviews/2026-10-13-responses-reasoning.md)。

Dev90 思考模型适配子集已验收：新增显式 DeepSeekThinkingProvider／deepseek-thinking，复用原 ModelContinuation／完整历史及 Local／Temporal 执行权威，接通 SDK／Profile／四类评测 CLI。保留非思考默认和原 Run；最终源码6519 passed／593配置依赖跳过（993.63s），独立核心安装266 passed／零跳过，实际源码Temporal4／安装Temporal12通过；308产品模块一致，旧89四类原Run和默认字节兼容。唯一审查2个P2已修复；自有服务退出0并等待。真实模型质量、完整 R05／H3／M1／R01–R26及独立采用继续开放。见[接入指南](deepseek-thinking.md)及[本批记录](../architecture/reviews/2026-10-13-deepseek-thinking.md)。

dev89跨Session原生模型历史子集已验收：最终源码6317 passed／589配置跳过（746.39s），独立核心安装243 passed／零跳过，独立安装真实Temporal76及Local/Redis/PostgreSQL50项通过。显式session/frame、每Agent继承/ref/禁用、同步/异步Profile和通用无SQL publication端口已接通；原根成功、准确CAS回执、失败候选排除及真实处理器责任保持。唯一审查4个P2及1个Minor已修复并复核；旧88四类原Run/默认字节兼容、Schema13及实际旧Worker零Activity拒绝通过。外置128轮使用明确128MiB私有服务，原50MiB服务104个已接受Turn后终止的证据保留，Continue-As-New/长期治理不据此完成。完整H3/M1/R01–R26、真实模型质量、独立采用和对等比较继续开放。见[使用指南](model-history.md)与[本批验收](../architecture/reviews/2026-10-13-session-model-history.md)。

Dev88 完整已采纳模型历史子集已验收：最终源码6021 passed／463配置跳过（897.57s），独立核心安装368 passed／8可选SDK跳过，实际Temporal源码和安装各35项通过。新增可替换ModelHistoryPolicy/CompleteModelHistory、Local local6/Temporal joint7显式门槛、原final/签名保存、验证retry单次反馈和完整交互保护。原参数与实际默认值分离；预算不足明确失败，Artifact投影需显式许可，原参考opaque在投影前拒绝。五项Important及真实Worker未获许可读取窗口经RED统一修复；301产品模块字节一致、旧87原Run/默认兼容和三个真实Local进程恢复通过，自有服务已关闭并等待。跨Session Turn原生transcript、DeepSeek thinking/Responses reasoning、真实质量、完整H3/M1/R01–R26及外部采用继续开放。见 [使用指南](model-history.md)与[本批验收](../architecture/reviews/2026-10-13-complete-model-history.md)。

Dev87 模型续接与 Gemini 原生函数子集已验收：最终源码5882 passed／455配置跳过（818.09s），独立核心安装295；实际Temporal源码8新恢复＋17既有场景、安装25均通过，300产品模块一致；旧86默认与同一Run双向回执／完整快照兼容通过。Local原接收／采纳与Temporal joint6两阶段保持各自唯一执行权威，签名原参数与真实默认参数分离；SDK／Profile／中间件和RAG／Plan／Team显式接通。一次独立review的2Important及重新评级的名称范围问题经RED统一修复，自有服务已正常关闭并等待退出。真实Gemini质量、其他推理续接、完整H3／M1／R01–R26及外部采用保持开放。见[模型续接](model-continuation.md)与[本批验收](../architecture/reviews/2026-10-13-model-continuation.md)。

Dev86 端到端任务评测子集已验收：源码5681 passed／447配置跳过（830.34s）、独立核心安装161；源码三次重复RAG24/24、Plan15/15、Team15/15及安装CLI／SDK例子、旧85默认／原Plan回执兼容与298模块一致通过。复用原执行权威，新增最终模型请求可见引用、实际成员／工具回执、独立Embedding计量和观察式恢复；2项Important／1项Minor经有效RED统一修复。离线／MockTransport不构成真实模型质量；完整H3／M1／R01–R26及外部采用保持开放。见[任务评测指南](task-evaluation.md)与[本批验收](../architecture/reviews/2026-10-13-task-evaluation-chains.md)。

dev85 已验收：源码5520 passed／447配置跳过、核心安装171、旧84默认／Plan回执兼容和292模块一致通过。本批补齐版本 2 推荐 Plan 证据链与组件替换、重复评测摘要和评测边界修复；整批验收记录见[本批记录](../architecture/reviews/2026-10-12-default-chains-evaluation.md)。长期 R01–R26 目标及 H1–H5 门槛保持；旧版默认声明不迁移。下述 dev84 数字仅属于已验收历史基线。

最终源码5431 passed／447配置跳过（678.60s），核心104／SDK242安装、真实源码51／安装51（均零跳过）、旧83双向兼容／22原模板／旧Worker零Activity拒绝及291模块一致通过。九类Important经一轮34项有效失败复现统一修复；本任务Temporal PID12900／session19994实际退出0并已等待，用户Docker平台保留。完整R01–R26、远端／binary／GC／cache／治理与真实质量继续开放。

独立artifacts默认／替换／配置及恢复子集已验收，但R01/R18/H1/H3完整范围仍开放；原写者真实end证明不可由内容核验或PID wait替代。dev83 M1/M2继续延期。见[本批验收](../architecture/reviews/2026-10-12-artifact-bindings.md)。

## 1. 结论与判定方式

RALF 已有可运行的通用 SDK 预览：模型／工具循环、顺序与图编排、动态 DAG、
受管理多 Agent、远程数据适配及有限 Temporal 分布式执行。dev99四条参考业务链路与dev113第二阶段所选环境／执行组合已经验收。
当前剩余主链路为期限与容量治理、托管观察／服务控制、企业身份权限及运维恢复；
每Agent／Session及智能数据的高级可选组合继续按长期清单登记，不覆盖当前阶段边界。
H1a–H1f、Local stateless H2a、同库原生／顺序 H2b1／复合会话 H2b2 和 Temporal 原生／顺序入口 H2c1／已注册高级编排入口 H2c2 已交付；完整 H1/H2 尚未完成，H3–H5 有可复用基础但未达到各自交付门槛。
完整 M1、AgentScope 目标业务链路对齐及企业正式可用均不能标为完成。

H1c 的[验收记录](../architecture/reviews/2026-10-08-session-capability-bindings.md)：
修复后 1998 passed／43 配置依赖跳过，安装包绑定契约 155 passed，
实际 Redis 1 passed／PostgreSQL 1 skipped。共享远程 Session 存储不提供跨独立执行权威租约。

H1d 的[验收记录](../architecture/reviews/2026-10-08-scoped-data-bindings.md)：
2055 passed／44 配置依赖跳过，安装包211 passed；Facts／Knowledge 宿主允许范围已交付。
[固定 DeepSeek 试验](live-model-quality-dev28.md)业务10/16、范围提取4/4。
六个修复任务未写入却回答 resolved。dev29 增加显式纯 CompletionVerifier、回执对应规则及耐久有界反馈；动态计划 PlanVerifier、受管理模型验证与完整质量门槛仍待验收。

dev29 H1e 增加[可替换完成验证](completion-verification.md)，[验收与审查记录](../architecture/reviews/2026-10-08-completion-verification.md)：最终2113 passed／44配置依赖跳过，实际安装包250 passed，dev28十类原审批兼容恢复。[固定 DeepSeek 试验](live-model-quality-dev29.md)八个业务任务单次全部通过，三个修复各发生一次审批写入。完整 AgentScope 对齐、重复质量基线和企业验收仍未完成。

dev30 H1f 增加[每 Agent 执行限制](agent-limits.md)：静态决策／上下文／工具动作 caps、不可移除的宿主约束、固定发布与有界批次采纳；并行投影、模型 Planner 和嵌套子 Run 保持父级已接受的成员上限。[验收记录](../architecture/reviews/2026-10-08-agent-limits.md)：2183 passed／44配置依赖跳过，实际安装包320 passed，dev29十三类原审批兼容恢复。分布式容量、真实费用和长期治理仍待交付。

dev31 H2a 增加 [Local Agent API](agent-api.md)：固定声明、独立执行托管、纯观察等待、嵌套原根控制与可重试 owned/borrowed 关闭。十类实际旧 wheel 审批兼容恢复已验证；完整 H2b 会话／Turn、Temporal Facade 和 H3 自动阶段继续待交付，见[实施审查](../architecture/reviews/2026-10-09-local-agent-facade.md)。

dev32 H2b1 增加[同库原生／顺序 Sessions](session-api.md)：持久身份、Turn 顺序与占用、原绑定固定、稳定 busy/mismatch 回执和 idle CAS rebind。最终2280 passed／44配置依赖跳过、实际安装包159 passed；九类 schema1 审批双向旧新 wheel 恢复及 schema2 旧代码拒绝／新代码单次效果恢复通过，见[验收与取舍](../architecture/reviews/2026-10-09-local-session-turns.md)。远程／复合会话和完整 H2b 仍未完成。

dev33 H2c1 增加[Temporal 原生／顺序 Agent 入口](temporal-agent-api.md)：共同 DTO／异步重连、RPC 固定组件派发、真实时间的已有快照超时和 detach 关闭。实际持久 Service／Worker 的三项审批／重连／观察取消／History 重放探针通过；该 dev33 边界在 dev34 扩展，Temporal 绑定／共享会话和完整 H2 继续待交付。

dev34 H2c2 接通已注册 Graph／Team／Dynamic／嵌套 Agent 入口；通过原父子命令／发布身份验证读取实际子 Run 控制，有界固定派发观察保留客户端取消和 detach。Temporal 绑定、远程／复合会话与完整 H2 继续待交付。

dev35 H2b2 接通同库 Graph／并行／Team／动态 Plan/DAG／嵌套 Session Turns：固定成员绑定、原子最终保存、真实子处理器／未知效果／缺失结果占用、idle CAS 跨种类 rebind。成功接受启用 schema3，dev34 在派发前拒绝；详见[验收与取舍](../architecture/reviews/2026-10-09-local-composite-session-turns.md)。远程共享会话、复合根 namespace、Temporal 绑定和完整 H2 待交付。

dev36 H2b3 增加宿主授权的同库复合根 namespace、独立根资源、原绑定派发校验和 schema4 兼容门槛。Profile 专用声明、远程共享会话、Temporal 绑定及完整 H2 尚待交付。见[验收记录](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md)。

dev37 补齐授权根会话的 JSON/TOML Profile 声明及 sync/async Runtime 装配，提供可安装 sessions starter 与原 Profile/Turn 重连；远程会话及 Temporal 绑定仍待交付。

本清单对照[总架构](../architecture/design.md)、[通用能力清单](../architecture/viewpoints/framework-capabilities.md)、
[AgentHarness H1–H5](../architecture/viewpoints/harness-runtime.md)、
[建设顺序](agentscope-alignment.md)和[当前实现](implementation-status.md)，并核对 SDK 源码。
它汇总剩余工作，不新增执行架构，也不替代各项能力的版本化规格。

**子集已交付**表示有运行实现但目标范围未覆盖；**未交付**表示目标公共能力／
默认链路尚不存在；**验收未完成**表示有实现或试验，仍缺最终配置、故障、升级、
质量或独立采用证据。同一层可以同时具有这三种状态。
不按端口、模块、适配器或测试数量换算完成百分比。

以下能力已经实现，不能再次列为从零建设项：Redis／PG Session/Facts、
PG Knowledge/Inbox/Outbox、Qdrant、HTTP Embedding、Hybrid/RRF／基础重排、
文本摄取、动态 DAG／嵌套／团队、Redis Streams、A2A 轮询、Temporal 声明子集、
显式记忆提炼／受管理模型摘要／Temporal 纯自定义上下文、持久 Run 事件订阅。
已有实现只覆盖各自声明的范围。

## 2. 分层剩余清单

### 组合、入口、模型与编排

| ID／层 | 当前已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R01 每 Agent 绑定 | dev83 Local／Temporal原生、顺序、Graph、Team、Dynamic及嵌套支持十三类版本化角色provider/context/knowledge/tool_set/stage_policy/facts/limits/verifier/decision_policy/session/workspace/skills/sandbox；固定成员路径、父子发布和Profile；Session树与Facts／Knowledge宿主namespace；Workspace／Skills／Sandbox选择只收紧原授权。dev84实现第十四类artifacts及纯Context派生、ref/disabled/inherit、host namespace选择，六组合SQLite/file已有子集证据；dev104可选runner schema3、根级Local Agent／顺序显式选择与原工具资源借用；dev105扩展图／Team／Dynamic／嵌套和原节点投影 | 其余Artifact角色selector和组合契约；其余资源身份／selector／作用域视图与完整配置；Workspace append/delete/mkdir／subroot／权限／远端租约；其他受管理阶段、Runner Temporal及完整隔离治理 | H1：已有子集交付；dev84 Artifact子集已验收 |
| R02 Agent／Session 入口 | H2a Local stateless Agent/Runtime/AgentRun、RunRef/WaitResult；独立任务托管、纯观察等待、原根流程控制路由、owned/borrowed 关闭与 CloseIncomplete 重试、显式重连；保留旧 RunHandle DTO；H2b1 同库原生／顺序及 H2b2 图／团队／动态／嵌套及 H2b3 授权根 namespace、H2b4a 远程原生／顺序及 H2b4b 复合根保存意图／准确回执／终态只查询恢复、异步 Profile 配置，SessionKey／路由／Turn／busy／CAS rebind；H2c1 Temporal 原生／顺序共同入口、异步重连、固定 RPC 组件与客户端 detach；H2c2 已注册 Graph／Team／Dynamic／嵌套入口与实际子 Run 控制；H2c3 Temporal History Session／原 Namespace UUID／耐久 Turn／busy／启动意图／空闲 CAS，普通与 managed Conversation 及原后代静默证据；dev66 原生／顺序外置Root保存及 dev67 图／Team／Plan／DAG／嵌套根保存、稳定成员地址、原根／私有数据只读取一次、数据集身份与跨Turn召回；dev93原owner问题／答案、同Run/Turn续接、纯观察等待与SDK/Profile/CLI/A2A | 跨权威会话租约、业务 deadline、Temporal 推荐配置／其他绑定角色、移交与耐久 FIFO | H2a／H2b1／H2b2／H2b3／H2b4a／H2b4b／H2c1／H2c2／H2c3：子集已交付；完整 H2 未交付 |
| R03 Harness 与公共规则 | 纯 Harness/NativeHarness、ToolExecutor、共享决策／证据规则、dev88纯历史策略／dev89跨Turn原生历史、Workflow Compiler/Interpreter、固定声明的 AgentHarness 组合入口；Local 原生／顺序及高级实际 Agent、Temporal 的规则／模型选择记忆、历史摘要和数据上下文，独立来源／提案／意图／回执与 Run 额度 | 其余广义 Harness 受管理阶段及默认组合；逐步提取 RuntimeKernel 纯规则；Prepare/Verify/Memory 等阶段的身份、证据、取消和恢复协议。保持 Local/Temporal 各自唯一执行权威 | H1–H3：部分抽象已实现 |
| R04 配置与装配 | Local 版本 Profile/Catalog、JSON/TOML、工厂、sync/async 装配与历史路由；dev69 显式 Temporal Profile／十类绑定工厂、实际 Worker 排空与离线起步模块；dev70 多版本 Host、原队列 Run/Session 路由、共享资源全局排空与声明 PostgreSQL EffectJournal；dev71 普通启动参数纯预检与纠正重试；dev85版本2完整资源声明替换与互斥召回默认切换 | 复杂 SDK 对象语义的构造校验；配置迁移、剩余环境角色、完整绑定／推荐组合配置；CLI/ProfiledEngine 异步工厂路由；插件显式安装／激活／兼容检查；配置／组件迁移、旧代码归档、部署版本管理；配置来源／监听按需分期 | H1／H5：子集已交付 |
| R05 模型适配 | Chat Completions、DeepSeek 非思考／dev90显式思考原生续接、Anthropic 文本／工具、Gemini 文本／显式原生函数、stateless Responses/JSON/完整 SSE；dev91显式 Responses reasoning/phase 原生续接与配置／恢复子集；dev87原History两阶段，dev88完整已采纳历史，dev89跨Session原生Turn，dev90原推理与工具参数、配置和恢复子集 | 其余 Responses 范围及线上型号／任务兼容、DeepSeek思考线上兼容／质量及其余受限字段；能力／用量／错误／超时／重试一致性；路由/fallback/负载策略及效果不重复契约；国内外及本地模型真实兼容矩阵。兼容 URL 不证明每个模型支持同一能力 | A1／H5：协议子集已交付，线上验收未完成 |
| R06 多模态／实时 | 当前 Provider 链路为文本 | 图片／音频／视频媒体类型、来源／访问／限额及逐适配器验收；Realtime/TTS/高级压缩后置，不作为当前 v1 目标业务链路先决条件 | 能力未交付；高级实时后置 |
| R07 Agent 能力包 | 原生循环、可定制 AgentSpec、规划／团队／RAG starter、dev47 显式 semantic-knowledge／memory-recall／Plan／Team 默认组合；dev85显式版本2规则DAG结果串接；dev86安装后RAG与Plan／Team完整有限任务执行器；dev99四条固定参考链路的安装、替换、恢复和真实模型重复任务已验收 | 更完整 Search／业务 Plan／Team 与 Coding 能力包；默认 verifier／上下文／工具、替换示例、诊断及业务验收。Coding 依赖环境／Runner | H3／H4：有限参考默认组合已验收；完整能力包未交付 |
| R08 静态 Workflow | 顺序、串行／有界并行 Graph、条件／映射、Agent/Transform/Tool 节点及嵌套 | 通用受管理异步自定义节点；HumanInput/Retrieve/Planner/Verifier 节点族；受限循环；first-success/quorum/reducer 合并和类型化工作流状态。复用审批、预算与恢复 | G1/G2／H5：子集已交付 |
| R09 流式 Workflow | 模型完整 SSE 收集、耐久 Run 事件游标 | 逐记录 StreamChannel/Source/Operator/Sink、背压、关闭／失败传播、检查点／重放和 Sink 效果身份。事件订阅和模型 delta 展示均不等于节点数据流 | G5：未交付 |
| R10 动态规划／验证 | Rule/Model Planner、Plan/Revision、动态 DAG/CAS 修订、受限 execute/verify/replan；Local Agent纯CompletionVerifier；dev92父级原回执gate／库存默认、可替换受管理模型stage、真实Plan反馈／Team拒绝及Local／Temporal恢复；dev93显式needs_input／ModelPlanner input_requests、固定回复Schema、自身澄清和原修订续接；dev99固定三次Plan参考任务15/15 | 更多领域oracle和受管理非模型验证阶段、非literal来源证明；复杂重规划、依赖、参数、拒绝与停止的真实模型实测。Schema合法不等于业务正确 | H2／H3／A4：子集已验收，有限参考质量已验收；完整规划质量未验收 |
| R11 多 Agent | Sequential/Router/Supervisor、子Run、隔离Session、递归预算／取消和恢复；dev83 Local／Temporal六类实际Agent的十三角色成员绑定和节点回执完成验证；dev84新增独立artifacts成员存储／namespace；dev99固定三次Team参考任务15/15 | 其他角色／selector／受管理阶段；类型化交接／受控共享状态／reducer；按需Debate/Critic；跨权威关联、停止和未知远端效果；全局容量及团队质量验收。普通消息不能作为成功回执 | H1／H4／H5：基础团队已交付，完整范围未完成 |

### 工具、上下文、记忆与知识

| ID／层 | 当前已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R12 工具接入／工具包 | typed Python/Schema/默认参数、ToolRegistry、async ToolSource、MCP stdio／HTTP JSON／POST SSE、A2A ToolSource、固定命令 JSON CLI ToolSource/async 声明/实际进程停止；固定POST HTTP ToolSource与CLI完整示例、授权／审批／核验；dev103显式SDK Coding工具与根级未绑定Local Agent／顺序原Action委托；dev104原Runner绑定、多资源声明工厂和owned停止／关闭重试；dev109固定模型连接与有限真实认证基线；dev110直接Agent Team／Dynamic组合；dev111同物理根容量与仅控制原CID的create恢复；dev112原CREATE两层gate监督、真实处理器排空与严格未发送证明（按本批证据验收） | MCP持续 Session/GET恢复/OAuth；其他外部CLI／Runner、Temporal嵌套／sequence Coding、跨宿主容量与企业凭证治理；HTTP GET/参数映射／凭据引用与工具组合；搜索／文件／浏览器工具包与发现；有状态工具租约和停止证据 | H4：子集已交付 |
| R13 Workspace/Skills/Sandbox/Runner | 可信 Python、MCP 受管理进程生命周期；Runner 目标契约；Workspace Port／文件／内存默认和受管理读工具；dev77 WritePort／CAS／稳定回执／单根租约和原受管理写工具子集已验收；dev78 Skills Catalog／Memory／固定File和原读工具；dev79每Agent Skills固定ref/disabled原授权交集子集已验收；dev80标准文档解析／固定File声明子集已验收；dev82被动目录选择／原Knowledge自动Context子集已验收；dev81真实Temporal原生阻塞写取消／关闭／租约与显式结束子集、dev83本地Docker受限临时命令／成员Sandbox绑定子集；dev100–108固定Codex协议／控制、保留环境／共享PG启动证据和有限Local原Action Coding委托、opt-in原容器移除与冷停止门禁；dev104原Runner绑定、JSON／TOML多资源声明和owned关闭隔离；dev105复杂Local编排、原后代停止与节点权限／资源投影；dev106有限Temporal Agent／顺序原History准入、共享PG资源意图与回执、固定Runner绑定和owned关闭重试；dev107显式串行Agent图、原父子SDK身份、实际提交排空、未知cap与独立物理停止；dev108单层静态Agent图有界并行／共享Runner背压、完整PG对应和全部原后代关闭恢复；dev109固定模型连接／延迟凭证源／非敏感SDK/JSON/TOML、原审批恢复和有限真实POSIX Coding基线；dev110原History直接Agent Team／动态计划、物理停止与结算双门、固定修订及pending-only DAG patch；dev111同物理根容量／一原invocation等待、持久原义务、create正向原CID恢复及所有权CAS；dev112原CREATE监督、固定源／别名、原处理器结束与专用未发送证明（按本批证据验收） | Workspace append/delete/mkdir／subroot selector／文件权限／跨主机租约；语义selector／自动正文阶段／插件激活；远端Sandbox／持久文件／Artifact传输与完整隔离治理；Temporal嵌套／sequence Coding编排、持久容量排队与跨宿主恢复、可能已发送create的daemon负向完成屏障、复杂真实Coding质量、多模型与多语言质量、企业凭证代理，其他外部Runner验收。普通子进程不是安全沙箱 | H4：读写子集已交付，其余目标未交付 |
| R14 上下文 | ContextBuilder/Counter/Budgeter/Summarizer、完整工具组／近期召回／摘录、实际快照；显式独立模型摘要；Temporal 纯自定义 Context；Local 原生／顺序及高级编排受管理规则／模型摘要与引用摘录／产物投影；Temporal History 受管理摘要／Knowledge 摘录／产物阶段；最新完成反馈及其后工具证据原子保留；dev54可替换TextTokenizer、字节默认／可选tiktoken及canonical输出预留 | 模型协议完整计量、实际模型词表与长上下文验收；Session／RAG 语义压缩和质量；覆盖／来源失效策略和辅助失败恢复；不同模型长上下文事实保留实测。UTF-8 token 估算不是精确用量 | H3：确定性与显式路径已交付 |
| R15 短期／长期记忆 | memory/SQLite/Redis/PG 的 sync/async、CAS/去重/TTL/分页/来源；opt-in MemoryPipeline 规则／模型字段选择；原生／顺序及高级实际 Agent 的受管理规则／模型字段选择阶段、原节点／子 Run 证据恢复与 JSON／TOML 默认工厂；Temporal History 自动规则／模型选择、准确CAS核验与根子证据恢复；dev47 有界候选词项相关排序；dev49 有界原生候选语义排序／任务查询与有序上下文组合；dev56 memory/SQLite/Redis、dev57 PostgreSQL 全库扫描、可替换 CAS Catalog、分阶段索引／激活与权威召回；dev58 Temporal有界Facts绑定／namespace／纯planner／原Context采纳；dev98原Graph／Session有界自动刷新、来源分代／准确历史效果与SQLite／Hash配置及恢复子集 | PostgreSQL/Qdrant等远端联合索引组合验收；自动增量／修复／删除传播；自由合成；语义冲突／修订／撤回／遗忘／可信度策略和多事实原子采纳；最终 Session append 大历史效率；导出／迁移／保留；真实记忆利用。追加来源观察不是自主信念修订 | H3／H5：存储和显式提炼已交付 |
| R16 摄取／知识生命周期 | text/Markdown Parser；dev51 HTML／dev52 DOCX 正文／dev53 可选文本 PDF Parser 与摄取模板；字符／段落与 dev54 可替换 token Chunker；memory/SQLite/PG 原子文档／块／词项／回执 | PDF OCR／布局与兼容语料、其他 Office、网页／业务连接器及游标／增量；语义分块及模型词表兼容；来源目录／ACL；后台索引、修复、删除传播和版本重建。knowledge_committed 不代表向量就绪 | H3／H5：基础已交付 |
| R17 检索／Embedding／向量／重排 | HTTP Embedding、Hash 基线、本地 cosine/Qdrant、词法／向量／Hybrid、RRF/保序/词项重排、来源回读、dev47 显式 HTTP 语义组合、dev48 HTTP 语义重排适配；dev49 替换式查询改写及默认字面 aliases；dev50 显式模型改写适配；dev99固定可选本地语义模型／资产与安装后参考RAG，固定三次真实模型任务24/24 | 本地模型更广适配；自动查询策略；pgvector 参考适配及其他库逐项验收；索引发布／修复／迁移；端到端召回、答案和引用质量。Hash/TokenOverlap 不证明语义质量 | H3／G4：有限参考链路质量已验收；完整检索范围未闭环 |
| R18 Artifact／缓存 | Scope隔离memory/SQLite／POSIX文件JSON产物、摘要／TTL／读取限额／事务容量；Local六组合与Temporal managed Context自动卸载、预览、独立意图／回执。dev84独立target／namespace及disabled选择，Context策略独立、custom sync/async与声明owned／注入borrowed | S3等远端Artifact、binary传输、引用保留／孤儿GC／全局磁盘限额及恢复依赖；CacheStore/Policy的键、版本和失效。默认关闭缓存合法；语义答案缓存后置 | H3／H5：JSON产物子集已交付，dev84绑定子集已验收，缓存未交付 |

### 执行、通信、服务与验收

| ID／层 | 当前已交付基础 | 尚未完成的具体能力 | 阶段／状态 |
| --- | --- | --- | --- |
| R19 执行模式／后端一致性 | Local 单 Coordinator/SQLite；Temporal 独立 History，原生 Agent/sequence 与显式发布的 Agent-node Graph/Team/Dynamic/嵌套、RAG；scoped Facts/Knowledge 与 opt-in History Sessions／原生顺序及显式高级根／成员外置数据保存 | 单 Coordinator 多 Process Worker；Temporal 其余环境绑定角色／selector、完整配置／数据迁移、其他受管理 Harness 阶段及直接 Tool/Transform 图节点等组合；共同能力／故障／升级门禁；Continue-As-New、部署版本及长期容量。PG Facts/Knowledge 不等于 PG ExecutionStore/分布式调度 | H5／C1：分布式子集已交付 |
| R20 MQ／A2A | memory/SQLite/Redis Streams、Inbox/Outbox、PG 共享回执；A2A JSON-RPC0.3 文本/数据 polling、async controls；dev93显式输入扩展展示公共根Task原问题／ownerTaskId，回复并恢复原任务 | 保留／压缩／积压／重投递与 failover 认证；额外 Broker 按需；A2A SSE/push/files/通用Task continuation 及真实停止约定。ack 不等于效果确认，不承诺跨系统全局恰好一次 | H4／H5：子集已交付 |
| R21 控制／审批／预算／容量 | 幂等命令与 DAG patch、local policy、固定动作、unknown holds／父子额度；每 Agent 固定决策／上下文／工具Action caps；Temporal timer/审批期限、dev114 Profile/SDK/JSON/TOML 与可替换执行策略工厂；dev93幂等send_input、无预算重置的原输入续接 | Local deadline／审批过期、鉴权续接；not-executed/in-progress 核验证据；业务资源别名规范化；真实费用／共享账户；独立并发／工作区额度／背压，真实调用未退出仍占容量 | H2／H5：基础已交付 |
| R22 事件／展示／观察 | 耐久 Run 事件／游标／分页、pull 订阅、SSE 编码、只读 CLI、opt-in middleware | 托管 HTTP/SSE/WebSocket；类型化 Agent/model delta、结束／取消／重连；OTel trace/metrics、跨 Run/远端关联、审计／脱敏／保留。展示 hook 不得丢失业务证据 | H2／H5／B2：观察基础已交付 |
| R23 Service／交互／作业 | packaged 本地 HTTP/A2A service、owned shutdown、remote CLI、二十八种已验收 wheel starter（含user-input、adapter-contracts、session-contracts、facts-contracts、model-contracts、memory-index） | 统一 Agent Service/sessions/资源库、默认托管／共享池、TUI/Web 基础控制台；渠道／定时／后台／唤醒／索引；审批／核验／恢复管理。现有模板不是完整应用平台 | H5／B1/B2：有限服务已交付 |
| R24 企业身份／运维 | 宿主 Scope、本地授权、版本固定和部分容量保护 | OIDC/企业 actor、资源 ACL/SourceCatalog、凭据代理、工作区配额；保留／迁移／备份／恢复、升级回滚、健康／HA/故障演练、自部署文档和控制面。Scope 字段不是认证体系 | H5／C2：企业目标未交付 |
| R25 扩展验收／首用 | SDK/API/教程/恢复/发布/贡献文档、wheel starter 和旧新兼容；dev94知识角色v1固定黑盒Suite、独立可编辑外部Source、配置／生命周期／原真实进程恢复子集；dev95 Session core／receipts、独立替换与原保存恢复子集已验收；dev96 Facts core／managed、独立替换及原提炼／受管理恢复子集已验收；dev97 ModelProvider core／tools 和原 Agent／RAG／Plan／Team 配置与恢复子集已验收；dev98原生Facts索引维护默认配置／实际恢复子集已验收 | 远程／Temporal Facts 索引及完整生命周期／严格非法输入与其余完整组合；其余模型协议组合与工具等其余角色Suite；Session 严格非法输入和其余完整替换／恢复组合；独立开发者换模型/库/工具/节点；性能／升级矩阵、稳定 API 弃用策略。公开 PyPI/Release／社区采用本轮未核验 | 横向验收：知识／Session／Facts／模型角色子集已交付，完整R25未完成 |
| R26 真实质量／M1／比较 | 冻结 20 案例规划、八案例业务执行器；dev21 真实小试验；独立 response/receipt 窗口和 Worker 故障证据；dev85重复任务摘要与评测边界修复；dev86八类RAG来源oracle及五类库存Plan／Team回执、实际可见引用评分与私有报告 | 完整最终配置重复业务／规划／记忆／RAG 引用任务；M1 20 类原型完整 fixture/评分器；成组窗口／Temporal 契约报告；独立首次采用；同模型/工具/服务的 AgentScope/LangGraph 实现与成绩 | A4／M1／D：验收未完成 |

每层的完成条件都是：公共契约、最小默认、另一实现替换、配置／注入、身份／错误／
生命周期、安装包场景和必要的真实证据。缺少必需能力应在准入前拒绝。
维护经过验收的组合矩阵，无需先实现所有数据库与全部角色的笛卡尔积。

## 3. 沿既有架构继续的顺序

~~~mermaid
flowchart LR
    H1a[H1a 已交付] --> H1b[Local H1b 已交付]
    H1b --> H1c[Local Session H1c 已交付]
    H1c --> H1d[Local 数据范围 H1d 已交付]
    H1d --> H1e[Local 纯完成验证 H1e 及执行限制 H1f 已交付]
    H1e --> H1f[Local 执行限制 H1f 已交付]
    H1f --> H2a[H2a Local stateless 入口已交付]
    H1f --> H1[H1 剩余绑定与资源身份]
    H2a --> H2b1[H2b1 同库会话已交付]
    H2b1 --> H2c1[H2c1 Temporal 原生入口已交付]
    H2c1 --> H2c2[H2c2 已注册高级 Temporal 入口]
    H2c2 --> H2b2[H2b2 同库复合会话已交付]
    H2b2 --> H2b3[H2b3 授权根 namespace 已交付]
    H2b3 --> H2[H2 剩余会话与绑定]
    H1 --> H2
    H2 --> H3[H3 推荐智能数据链路]
    H3 --> H4[H4 环境与协作]
    H4 --> H5[H5 后端与服务治理]
    Q[真实质量与共同案例] -.贯穿.-> H1
    Q -.贯穿.-> H3
    Q -.贯穿.-> H5
~~~

1. **H1/H2 闭环组合与入口。** R01–R04，以及 R10/R21/R22 的续接与等待。
   H2a 已有 Local stateless 入口与独立托管，H2b1 已有同库原生／顺序 Session／Turn 占用及稳定绑定，H2c1 已有 Temporal 原生／顺序共同入口，H2c2 已接通已注册高级编排、H2b2 已接通同库复合会话；继续完成跨权威会话与 Temporal 其余绑定角色。
   旧审批、原发布恢复及 caller/HTTP 断连共同验收；H2b 首期忙碌拒绝，耐久 FIFO 后续 opt-in。
2. **H3 做三个可安装、可替换的参考组合。** Local Basic、Local Knowledge、Managed Memory；
   补 R07/R14–R18 的受管理阶段、自动卸载、语义可选组件和明确失败降级。
   复用已有摘要／提炼，不能在纯 Context/Harness 方法隐藏模型 I/O。
3. **H4 补环境与工具。** R11–R13/R20 的 Workspace、Skills、Sandbox、CLI/MCP HTTP、
   Coding/Runner 和协作，验收隔离、真实停止、租约、交接及未知效果。
4. **H5 做长运行和正式部署。** R19–R25 的多进程、Temporal 扩展、容量、保留、
   服务流式、身份、迁移／备份与恢复管理。R09 流式 Workflow 独立交付，UI 流式不替代它。
5. **真实质量贯穿；比较另行形成结论。** R26 固定最终配置与完整任务，报告业务、规划、
   引用、记忆及外部采用；对等实验不由功能数量推导优越性。

这些是分期依赖，不是一次重写计划。保留原 AgentSpec/Profile/Release/command 身份，
由各自执行权威采纳受管理阶段；新增 Facade 不创建第三套 Run 状态机。

## 4. 实现与证据的区别

既有真实 Redis/PG/Qdrant、Temporal Worker/History 故障证据已经记录，
远端版本矩阵、长期负载、failover、完整组合和运行治理仍需分别验收。
受支持版本以[远程数据](remote-data.md)及历史记录为准，不将既有测试重复列为从未执行。

[dev21 真实模型试验](live-model-quality.md)保留 38 次调用：原业务配置 0/8、
选定规划 3/6、摘要与来源字段选择各 3/3、修订指令子集 3/4、JSON 缺失输入子集 3/3。
它们使用不同阶段配置，不能拼成最终配置 8/8，也不证明通用摘要、事实真值或跨框架优越性。

[M1 协议](m1-acceptance.md)仍缺完整真实任务、独立接收窗口成组报告、Temporal
契约映射及外部采用。单项故障回归已有通过证据；缺成组重复／升级／采用报告时，
标为验收未完成。当前没有对等 AgentScope/LangGraph 的成绩。

dev25 审计时，127 个 SDK 模块与已测试快照一致；历史回归为 **1902 passed、42 skipped**，安装包契约测试为 **60 passed**，见[H1a 记录](../architecture/reviews/2026-10-08-agent-capability-bindings.md)。
dev26 已实现 Local 高级编排绑定；修复后完整回归 **1959 passed、42 skipped**，安装包契约 **117 passed**，原生／H1a 实际旧 wheel 升级及新复合发布降级拒绝已验证。验证与独立审查见[H1b 记录](../architecture/reviews/2026-10-08-composite-agent-bindings.md)。未调用真实模型或发布远端。
skipped 不计为通过，测试数不替代剩余功能和验收。

## 5. 范围与维护

v1 目标业务链路包含 SDK/CLI/API/基础控制台、General/RAG/Plan/Coding、
三种执行模式及企业私有部署。持续公网群聊、拖拽编排、公共插件市场、
运行中热迁移、语义答案缓存和高级 Realtime/TTS 等按原设计后置。
配置监听、额外 Broker/向量库及团队策略按需扩展，不用适配器数量定义成熟度。

后续更新对应 ID 的实际范围和证据，并同步实现状态；保留 dev9/dev20 历史基线，
明确其日期。完成子集不表示整层完成，只有目标范围和验收均满足才关闭该项。

### dev34 H2c2 verification

Registered advanced Temporal entry is delivered; full H2 remains open. Final
2352passed56skipped,231 installed contracts and12+12 actual Service/Worker probes
pass. Actual dev33 old/current7 histories and Local schema1/schema2 wheel recovery
retain original evidence. [Review/rulings](../architecture/reviews/2026-10-09-temporal-composite-agent-facade.md) records the pruning/import/bookkeeping fixes; old marker-less histories retain their original evidence rules.


### dev35 H2b2 verification

Final2393 passed/56 explicit service/optional skips; outside-checkout wheel259 passed.
Actual dev34↔dev35 native/sequence schema1/schema2 approval recovery passes4 cases
each direction; six composite schema3 cases preserve Turns/receipts/manifests and
one effect per Action. Old read-only/writable SDKs refuse3 before dispatch. A real
COMMIT failure and failed rollback were independently reproduced and fixed in one
RED→GREEN pass. [Review/evidence and all rulings](../architecture/reviews/2026-10-09-local-composite-session-turns.md)
records installed/package gates and remaining full H2/H3 scope.

### dev36 H2b3 verification

Authorized colocated composite root namespaces are delivered through SDK/factory
assembly; dedicated Profile declaration, remote Sessions and full H2 remain open.
Independent Run admission evidence also protects configured None selection while
genuine legacy Turns retain their original behavior in mixed schema4 databases.
[Review/evidence and all rulings](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md)
records original approval/recovery, actual old/new wheels and final gates.


dev38 H2b4a 接通 Redis／PostgreSQL 原生 Agent／顺序 Workflow 持久 Turn；
Scope 内保守地址准入、schema5 原子激活、独立原绑定证据、保存意图和准确
回执支持丢失响应及终态只查询恢复。远程数据与 Local 执行权威保持分离，
没有跨库原子性、跨权威共享会话或真实模型质量的新验收结论。


dev39 H2b4b 已接通 Local 远程复合根会话及 JSON／TOML 异步装配；保存
未知时直接恢复已采纳结果，保持原唯一执行权威与成员绑定。schema6 前向
激活、元数据缺失拒绝、审批重启单次效果及终态只查询纳入验收。完整 H2
仍缺跨权威共享租约、Temporal 绑定／Session、FIFO／续接／deadline，
H3 自动阶段、默认智能组合及企业治理继续沿原清单推进。


dev40 H3a 首期接通 Local 原生／顺序自动规则记忆；每 Agent 可继承、选择、关闭
宿主写目标。来源是已验证结果观察，提案／预算／意图／回执由原 Run 权威保存；
丢失确认和终态只查询恢复不重复模型、业务工具或已确认事实。新阶段使用 schema7；
默认关闭且旧发布身份保留。Graph／Team／动态／嵌套／Temporal 阶段、模型自动
选择、ContextPipeline 和默认智能组合仍按原清单推进。见[接入与边界](managed-memory-stages.md)。


dev41 H3b1 接通原生／顺序同 Run 完整遗漏历史组的受管理规则／模型摘要；
每 Agent 复用 context 绑定与 JSON／TOML managed-summary 工厂。原 Engine 保存
来源／意图／响应／快照与独立预算证据，未知调用保留额度且不重试，
终态恢复不发起模型调用。新能力原子启用 schema8，默认身份与旧 schema 保持。
Session／RAG 自动摘要、产物卸载、Graph／Team／动态／嵌套／Temporal 阶段、
模型提炼、默认智能组合和真实质量门槛仍未完成。见[使用与边界](managed-context-stages.md)。


dev42 H3a2 接通 Local 原生／顺序的自动模型字段选择，复用已有 stage_policy
与 sourced-memory(-async) JSON／TOML 工厂。原 Run 保存选择请求／响应／字段和
独立预算，未确认调用不重试、非法输出不写事实；已完成结果值由宿主取回。
新语义9原子准入，默认与schema1–8保持。自由合成、语义修订、Session／RAG
压缩、产物卸载、推荐默认组合、高级／Temporal阶段与完整H3仍待交付。
见[接入与边界](managed-model-memory-stages.md)。

### dev43 H3 recommended combinations

[推荐组合与恢复](recommended-harness.md)交付版本化 Local Basic／Local Knowledge／Managed Memory、确定性引用压缩与原 Run 大结果产物投影。Schema10 opt-in；仅原生／顺序 Local。执行日志保留完整效果证据，不声称减少总存储、语义质量或完成 H3。高级／Temporal 自动阶段、远程产物／GC 继续待交付。

[dev43 架构审查与实际恢复证据](../architecture/reviews/2026-10-10-h3-default-data-context.md)记录三项独立审查修复、四个进程退出窗口和 dev42↔dev43 的 Schema1/8/9 实际审批恢复。

最终 dev43：2773 passed／66 skipped；Ruff、格式和 Git 空白检查通过。最终 wheel 安装后150契约测试；实际四个进程退出恢复窗口、Schema1/8/9 双向旧新 wheel 审批及三个推荐组合的双 Turn／重启通过。未调用真实模型，完整 H3／M1 质量验收仍待完成。

### dev44 H3 高级与 Temporal 数据上下文

[高级编排与 Temporal 指南](composite-temporal-context.md)：Local 图／并行／Team／动态／嵌套 Agent 复用原协议，Schema11 opt-in；并行节点证据与摘要预算隔离。Temporal 显式 temporal-2 注册，以原 History 分阶段持久计划、产物读／写派发／核验、摘要回执与快照采纳；默认 temporal-1 身份与分支保持。写／摘要单次派发，未知保留额度和远程不确定性。

准备完成后的外部模型／摘要／产物写由原 History 原子准入；取消先接受时拒绝新派发。产物写超时的不确定性不会被后续成功工具清除；并行根 Action 存在而 execution 投影丢失时明确拒绝恢复／查询。

Basic／Knowledge 数据上下文已扩展；高级／Temporal 自动记忆写入、每 Agent Temporal 绑定、语义引用压缩、远程产物默认适配／GC、真实质量与完整 H3 仍未完成。卸载不减少原库／History 体积。

最终 dev44：2809 passed／72 skipped；真实 Temporal 7 passed（五类 Worker 恢复、读取期间取消、原纯上下文与父子 History replay）；安装后 93 契约、六项推荐组合高级入口、dev43↔44 六项审批恢复及旧版 Schema11 拒绝通过。Ruff／格式／空白检查通过。此轮未调用真实模型。[验收记录](../architecture/reviews/2026-10-10-h3-composite-temporal-context.md)

### dev45 H3 Local 高级自动记忆

[高级记忆与恢复](composite-memory-stages.md)：原规则／模型字段选择支持 Local 图／并行／Team／动态 flat/DAG／嵌套实际 Agent；Schema12 原子准入，原生／顺序 Schema7/9 与策略类保持。并行事实固定 workflow_node、额度与记录留在原 Run；每成员可选择宿主授权写目标。推荐 managed-memory 已验证同步／异步装配和统一入口重连。

纯观察不做恢复；显式终态根 resume 通过原有子 Run 锁恢复已结束 Agent／嵌套子 Run 证据，再结算父额度，不新增模型或 CAS。未知且不可证明的事实继续保留。Temporal 自动记忆写入、自由合成／语义修订、真实质量与完整 H3 未完成。

最终 dev45：2877 passed／72 skipped；安装后 186 契约通过，24 个进程退出窗口、dev44↔45 十项实际审批恢复、旧版 Schema12 拒绝与原 Policy 类不变通过。独立审查无阻塞问题；Ruff／格式／空白检查和 wheel／sdist 构建通过。[验收记录](../architecture/reviews/2026-10-10-composite-memory-stages.md)

### dev46 Temporal 自动记忆与每 Agent 绑定

[Temporal 指南](temporal-memory-bindings.md)：temporal-3 发布复用 AgentDefinition／BoundDefinition 与 scoped catalog；provider／context／knowledge／tool_set／stage_policy 五类选择沿原声明子树进入各实际 Agent。History 分阶段保存来源、选择响应、字段采纳、CAS 与核验，选择／写只有一次尝试。显式根 drive 通过原有子 Run 控制恢复未知事实；无法证明的效果／远程停止继续持有父额度。

旧 temporal-1／2 发布保持；未支持角色／selector、共享 Session、语义修订／遗忘、真实模型质量和完整 H3 仍待完成。

最终 dev46：2919 passed／92 skipped；真实 localhost Temporal 26 passed，安装后 151 契约通过；旧协议六项双向审批 JSON 快照恢复、原 manifest 相等与旧 wheel 拒绝 temporal-3 通过。独立 review 三项 Important 由七项 RED→GREEN 测试修复，无待办 Minor。Ruff／格式／空白检查与 wheel／sdist 构建通过。未调用真实模型，完整 H3／M1 继续待验收。[证据与决策](../architecture/reviews/2026-10-10-temporal-memory-bindings.md)

### dev47 H3 智能数据与编排起步组合

新增显式 HTTP 语义知识组合、相关事实／完整近期 Session 选择，以及使用原 Spec／AgentHarness 的 Plan／Team 默认和可替换成员；保留旧三个 Profile 及 ManagedDataContext 的版本身份。混合来源从正相关 Facts 开始交替 Knowledge，保存源选择用于摘要恢复，不改变原执行权威。

最终 2972 passed／92 skipped，安装后 75 契约、八个进程退出窗口、六项 dev46↔47 原审批与准确 Manifest 恢复、旧 wheel 拒绝新工厂及两示例通过；wheel／sdist、Ruff／格式／空白检查通过。独立审查的三项召回问题由七项 RED→GREEN 用例修复，文档矛盾同步校正，无延后 Minor。本轮未调用真实生成／Embedding 模型，未重新运行远程数据库／Temporal 服务；完整 H3／M1 与真实质量仍待验收。[指南](h3-intelligent-combinations.md)、[验收及决策](../architecture/reviews/2026-10-10-h3-intelligent-combinations.md)。

### dev48 H3 显式 HTTP 重排

R17 增加原 AsyncReranker 的 indexed-results HTTP 适配、原候选ID／分数／明确计量报告，
复用 Hybrid 来源前后校验；语义组合可显式启用，Hash+HTTP 需独立异步工厂。
原排序、七类推荐声明和运行权威保持。真实传输／响应流失败或取消清理可重试，不以 HTTPX 标志判定已释放。

最终3019 passed／92 skipped，安装103契约、12次双向审批与2次语义身份恢复通过；
旧 wheel 在建库前拒绝新适配器；构建／静态检查通过。准备中断仍可能重复付费检索，
dev48验收时，真实语义质量、本地语义模型、query transform、索引治理和完整 H3／M1 仍待验收；query transform 在下述dev49交付。
[使用指南](http-reranking.md)、[验收及完整决策](../architecture/reviews/2026-10-10-h3-http-reranking.md)。

### dev49 H3 Query transform 与语义 Facts

R17 提供 sync/async QueryTransform、确定性默认和原 Retriever 组合；R15 提供有界候选语义 Facts 召回、TaskRecallPlanner、有序引用选择与显式语义记忆 Profile。保留原来源、CAS、引用快照和执行权威；原七类默认声明及旧 Embedding 类保持。Query Knowledge 可显式注册 Temporal，语义 Facts 目前只在 Local；候选窗口外的全库索引、生成改写默认适配、语义修订／遗忘、真实质量和完整 H3/M1仍待验收。

[指南](query-and-semantic-recall.md)、[验收与完整决策](../architecture/reviews/2026-10-10-query-semantic-recall.md)。

最终3105 passed／92条件依赖跳过，安装86新增契约；dev48↔49的12组审批恢复及2组语义Knowledge身份恢复、旧wheel的3类声明建库前拒绝通过。审查的3项Important以TTL／同标识原生资源替换／校验输入变异回归修复，无延后Minor。构建、静态与文档链接检查通过；只做本地提交。


### dev50 H3 显式模型查询改写

R17 增加 ModelQueryTransform，复用已装配的 async ModelProvider，严格限制无工具的 JSON 查询提案。R15 的 Local 语义 Facts 与原 Knowledge 组合均可显式选择命名 Provider；作用域、原始正文与来源仍由原数据权威管理。旧八类 Profile 不自动启用模型改写。检索准备在接受前可能重复付费；Temporal 只覆盖 Knowledge，不宣称 Facts 召回。全库索引、自动查询策略、本地语义模型、质量与完整 H3/M1 仍待验收。

[指南](model-query-transform.md)、[验收记录](../architecture/reviews/2026-10-10-model-query-transform.md)。

最终冻结回归3168 passed／92 skipped，529.76s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。
安装后64项新增契约，dev49↔50八类默认16组身份恢复（12组实际审批／单次效果、4组语义身份-only）、旧 wheel 三项 model 声明建库前拒绝及187模块打包一致性通过。一次独立审查发现的 Facts 提案后读顺序问题由12项 RED→GREEN 修复；无延后 Minor。


### dev51 H3 HTML 摄取

R16 增加可替换纯 HTML Parser 和 ingest 模板 .html/.htm 支持，复用原分块／来源／原子回执。原文本默认保持兼容；新回执保存解析后位置。SDK 重启和两个 SQLite 实际进程退出窗口验证原子性；真实 PostgreSQL、本轮线上模型质量未重新认证。PDF/Office、网页连接器、CSS/语义解析、来源生命周期与完整 H3/M1 仍待交付。

[指南](html-ingestion.md)、[验收](../architecture/reviews/2026-10-10-html-ingestion.md)。

最终冻结回归3197 passed／92 skipped，533.12s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。
安装包82项解析／摄取契约、188模块打包一致性、三组旧新回执／默认 pipeline 兼容及旧版未提交 HTML 拒绝通过。独立审查4个 Important／1个 Minor 经11项复现用例在一轮修复闭环，无延后 Minor。

### dev52 H3 DOCX 正文摄取

R16 增加纯 DocxDocumentParser 与 ingest 模板 .docx 支持，复用原知识／分块／词项／回执。正文段落和表格文本保持来源、空白和解析文本位置；ZIP/XML 预算及无效包在提交前拒绝。完整 Word 排版／样式、图片、页眉脚注、PDF／其他 Office、连接器和知识生命周期仍待交付。验收见[记录](../architecture/reviews/2026-10-10-docx-ingestion.md)。

dev52 最终验收：3230 passed／92 skipped，实际安装包115 passed；189个 Python 模块工件一致。旧新文本／HTML回执双向恢复与旧版重读已提交 DOCX 已验证；未提交 DOCX 在旧版拒绝且无写入。审查1个 P2与常见文本结构共五项复现经一轮 RED→GREEN修复。

### dev53 H3 可选文本 PDF 摄取

R16 增加可替换 PdfDocumentParser 和 ingest 模板 .pdf 支持；核心安装不依赖 pypdf，需显式 pdf extra。原知识权威／来源／分块／回执保持。原子恢复与身份边界见[验收](../architecture/reviews/2026-10-10-pdf-ingestion.md)；OCR／布局、复杂字体与实际语料兼容、来源／索引生命周期仍待完善。

dev53 最终验收：3256 passed／92 skipped，实际安装包141 passed；190模块工件一致。实际无 pypdf 环境的核心／文本首用／既有 PDF 回执重读通过；三种旧 Parser 与默认 pipeline 双向旧新恢复兼容。审查 P1 Form 静默缺失和 P2 RTL 身份经八项复现在一轮修复闭环，详见验收记录。

持续执行状态：2026-10-10 用户要求不中断推进；当前执行目标 active。批次与依赖接续见[持续队列](continuous-development.md)，不以本地提交或测试数量宣布全能力完成。

## dev54 token 计量与分块增量

沿既有 Counter／Chunker 接入 TextTokenizer、UTF8ByteTokenizer、可选 TiktokenTokenizer、TokenizerMessageCounter、TokenChunker；budgeted／managed 声明显式 byte counter 和输出预留。默认字符身份与摄取模板不变。中文／emoji／特殊标记、惰性结果、原子失败／进程中断、Local 审批重启与 Temporal 状态采纳见[使用边界](tokenization.md)。实际模型词表、真实 Temporal 新组合、语义分块、协议完整计量和长期上下文质量仍待独立验收。

[dev54 最终验收](../architecture/reviews/2026-10-10-tokenization.md)：3296 passed／92 配置依赖跳过，安装包127项通过，192源码模块一致；独立核心无 tokenizer/pdf extra 和实际 cl100k_base 均通过。持续目标 active，下一批文件 Artifact。


## dev55 文件 Artifact 增量

R18 增加 FileArtifactStore、SDK／JSON/TOML 配置和 owned 关闭，默认 SQLite 保持。
沿用原 Scope／引用／digest／TTL／读取限额／namespace 容量与 Local／Temporal 受管理阶段。
正文与索引分离；先 fsync 正文／目录再提交索引；孤儿重提也重新同步，不把缺失或损坏确认为成功。
真实进程发布窗口／多进程容量、Local 图／Team／动态 DAG／嵌套卸载恢复有测试；
Temporal runtime/state 与真实 Worker/History 的证据分开，详见[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。
文件后端不是云对象存储；GC／引用保留／全局磁盘限额继续开放。

最终3343 passed／98配置依赖跳过、实际安装包117项及193模块一致、独立 core venv 和 dev54↔55 原回执兼容通过。后续另行验证实际本机 Service：安装 dev55 wheel 的 file6及原SQLite6实际 Worker/History 全部通过；98配置跳过仍是原全量结果，不作为真实服务验收。

## dev56 全库事实索引增量

R15/R17 的显式 full-corpus 构建基础扩展 FactScanner、EmbeddingProvider、VectorIndex 与 CAS 元数据端口。
默认 SQLite/Hash、SDK sync/async 注入、JSON/TOML 独立 role 工厂及 Qdrant 配置；旧 bounded semantic-recall 和默认声明不自动升级。
四个实际进程窗口验证已接受 embedding 复用、向量 ACK 丢失幂等 upsert 和完整 active publication。
Redis 实际本地服务验证超过256条事实、原始大整数／Unicode／过期、snapshot 拒绝与客户端及 SQLite 向量重开。
Qdrant 新组合先验证 HTTP fixture 协议与生命周期，不替代真实服务验收。
每次事实写入后显式 rebuild；查询为全库向量排序的前256候选分页，不承诺枚举所有匹配项。
总记录／单页／输入／回执额度限制的是索引工作，不是模型账单上限。
PostgreSQL 新扫描、Temporal Facts绑定、自动增量／信念修订／遗忘、全局容量／GC／修复及真实语义质量仍未验收。
最终3397 passed／98配置依赖跳过、74安装包契约、197模块一致、独立core venv和dev55↔56原回执兼容通过。证据见[dev56 验收](../architecture/reviews/2026-10-11-fact-indexing.md)，不关闭整个 R15/H3/M1。

## dev57 PostgreSQL 原生索引增量

R15 补齐 PostgresMemory 的 native snapshot/scan_facts，复用原事务／advisory writer 锁，新增 epoch 表；有界 named server cursor 不将整页大正文装入 libpq。
真实 PostgreSQL16.15 覆盖Unicode／大整数／expired、key/value截断、无遗漏byte分页、270条索引／连接重开、四个真实进程窗口和配置Agent/owned关闭。
CI远程契约明确纳入Redis／PG新索引测试。PG/Qdrant联合组合、Temporal Facts绑定、自动维护／修复／质量仍开放。
最终3436 passed／68服务依赖跳过、安装73／模块198一致／core-only、原回执及真实PG56↔57升级通过。证据见[dev57验收](../architecture/reviews/2026-10-11-postgres-fact-indexing.md)；不关闭整个R15/H3/M1。

## dev58 Temporal Facts 绑定增量

在原 temporal-3/Context Activity/History 中加入 Facts 读链路、scoped namespace、MemoryRecallPolicy/纯 planner 和固定原生资源。
Knowledge/Facts 的校验与来源分类分开，普通/managed采纳固定证据；多页维持游标query身份与总预算。
默认关闭，不新增第三权威。原生/顺序/高级实际Agent兼容原子树投影；实际服务、安装、升级及质量证据见[dev58验收](../architecture/reviews/2026-10-11-temporal-facts.md)。
Temporal其他角色、Knowledge selector、共享Session、索引自动生命周期及完整H1/H3/M1继续未验收。

最终dev58：3417 passed/119未配置服务跳过；真实Temporal新增12＋原组合16、安装新增12、安装94契约／200模块一致、core-only／57↔58默认Run与Temporal manifest兼容、真实Redis/PG Activity探针通过。全量已固定版本并完成。仅本地提交；完整能力与质量门槛继续开放。


## dev59 Temporal Knowledge 绑定增量

新增 KnowledgeBindingResource 宿主 namespace selector，原 Context History 采纳具体 Scope／namespace／版本／文本摘要，保留原路径与实际 Agent 子树。
原生 SQLite/PG 资源、Lexical/Vector/Hybrid/Query 组合、方法和 HTTP client 固定；最后来源 await 在 History admission 前。
原 raw/global Knowledge 发布保持；新 scoped 发布启用 knowledge_protocol=1。SDK borrowed 工厂装配，未新增独立执行状态机。
恢复／安装／兼容证据见[dev59验收](../architecture/reviews/2026-10-11-temporal-knowledge.md)。共享 Session、其余绑定角色、自动 Temporal Profile、索引生命周期和真实语义质量继续开放。

最终dev59：3436 passed/131未配置服务跳过；真实源码Temporal12+原组合28、安装Temporal12+独立63、202模块一致、core-only与58↔59原默认/raw发布兼容、真实PG Activity探针通过。两项review P2已闭环，服务正常退出。仅本地提交，不将子集验收当全能力完成。

## dev60 Temporal History Session 增量

H2c3 复用共同 DTO／异步入口；实际 Namespace UUID、原绑定修订、串行 Turn、稳定 busy／mismatch、先接受后启动与空闲 CAS。Conversation 保存在协调 History，业务 Run／Parent 独占 Action／审批／预算；独立原根与后代静默证据才释放，普通／managed 上下文保持本轮 Knowledge/Facts 查询。
[指南](temporal-sessions.md)及[验收](../architecture/reviews/2026-10-11-temporal-sessions.md)分别记录实际恢复、安装及兼容证据。
此为 History Conversation 默认子集；Temporal 外置 SessionStore、其余角色、输入续接／FIFO、迁移／保留／Continue-As-New 和完整 H2/H3/M1 继续开放。

最终dev60：3466 passed/146未配置服务跳过（536.83s）；真实源码Temporal27＋最终入口3，最终安装Temporal15＋103契约，207模块一致。独立core安装和59↔60默认发布／原回执／21 starter、旧Worker新发布拒绝通过；四项P2闭环，自有Service停止。全能力目标继续active。

## dev61 Temporal Agent limits 增量

R01/H1f 接通可替换纯 LimitsPolicy、强制 host/Spec 交集、原 History 逐 Agent 节点采纳、决定／上下文／工具 Action caps 与整批拒绝。详情和恢复证据见[限制指南](temporal-agent-limits.md)及[验收记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)。其他 Temporal 角色／外置 Session 数据、全局容量、H3 质量及完整 M1 继续开放。

最终dev61：全量3492/164（523.45s、56122 exit0），源码实际12恢复+6超限、最终安装18真实Temporal/85契约、209模块、core-only与60→61→60原审批/回执/一次测试工具兼容。宿主入口P2、沙箱异常身份P2与错误码Minor已闭环，自有Service83761 exit0且stopped；只做本地提交。完整能力目标继续active。

## dev62 Temporal 纯完成验证

沿 R01/H1e 复用 CompletionVerifier 与 ToolReceiptVerifier，Worker 提出纯 verdict，原 Run History 固定当前节点原输入与已提交回执并一次采纳。accept 才进入原记忆和完成链路；retry 保留原额度、审批和受保护反馈，reject 明确失败。宿主／每 Agent inherit/ref/disabled 支持原生、顺序、图、Team、动态及嵌套。实际十八项恢复／取消／重放通过；最终交付证据见[验收记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。模型验证、DecisionPolicy／外置 Session 和其他环境角色、H3 质量及完整 M1 继续开放。

最终dev62：全量3519 passed/182 skipped（537.24s，8978 exit0），源码实际Temporal18/133.86s、最终安装18/133.40s及163契约；212模块、core-only与61→62→61原审批／回执／一次工具兼容。只读review140通过且无待办P1/P2/Minor；两处控制／反馈P2已RED→GREEN。自有Service25330正常exit0且stopped。未调用真实模型、未重验远端数据库；只本地提交，完整R01–R26目标继续active。

## dev63 Temporal DecisionPolicy

沿 R01/H1 公共纯 Harness 的 prepare/propose，提供宿主默认／每 Agent inherit/ref；固定实际方法、编译器 super 闭包及原 Scope。实际模型请求与原响应/提案证据由原 Run History 一次采纳；不改变审批、Schema、limits、完成规则和记忆责任。Temporal 九类绑定已接通，外置 Session/环境角色、完整 Profile/服务治理和真实质量仍待交付。见[指南](temporal-decision-policy.md)和[验收](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。

### dev64 默认精确 Session 回执

R01/R02/R14 增加默认 memory/SQLite 的准确消息核验和 threaded sync 桥接；Local 独立资源使用既有远程保存权威，同库仍原子保存。原生/Team 的真实进程写前/写后恢复、七类复合根与 borrowed 生命周期有测试。完整 Temporal 外置 Session 读/写/完成门禁仍待实施，见[目标契约](../architecture/specs/temporal-session-data-contract.md)和[指南](session-receipts.md)。不把默认 SPI 当作第十类 Temporal 绑定、跨权威租约或完整 H1/H2/H3。


## dev65 Temporal Session 有界读依赖

R01/R02/R14：host／每 Agent session 选择接入原 Context/managed History，支持 native/sequence stateless 私有地址。源码、安装包和真实服务证据见[验收](../architecture/reviews/2026-10-11-temporal-session-data-reads.md)。外置持久会话尚无自动保存／稳定跨 Turn 路由，不能作为完整第十类绑定或 H1/H2 完成；高级组合与 History Sessions 选中外置源时接受前拒绝。下一步继续原写意图／精确回执／完成门禁、根和成员持久地址，再推进其他 R01–R26 能力。

PostgreSQL 的新 Session 读取固定 initialize 解析的表 schema；旧 Facts／Knowledge 发布的跨 schema 恢复身份及迁移仍须独立验收，不能以本批读取固定推断已有发布格式已升级。


### dev65 最终结果

最终全量3642 passed/204 skipped（620.69s，44944 exit0）；安装140契约及独立相关39项（有重叠）、真实安装服务7及最终源码/安装各4个Temporal窗口、217模块一致、freshcore/文档例子及实际64↔65默认/审批/History兼容通过。Ruff/格式/空白通过；三项自有服务全部关闭。只本地提交，无真实模型或完整H1/H2/H3/M1质量宣称。后续按完整外置Session写/持久路由继续，不关闭R01–R26目标。


## dev66 Temporal 原生／顺序外置保存与持久 Turn

R01/R02/R14 接通原 History 保存门禁和实际 Namespace／数据集 UUID；原 CAS/message_id、收到回执与独立采纳、真实处理器和消息通知拥有关系保持。普通／managed Context 只注入外置会话一次；顺序源必须一致，idle rebind 不迁移。高级根／成员仍接受前拒绝，完整目标保持开放。

最终源码3686 passed/226 skips（519.28s），安装150契约／25真实服务，源码真实65、fresh core-only、实际65↔66默认／审批／History兼容通过。4项独立P2和派发前超时fence修复已RED→GREEN，模块／制品／关闭证据见[验收](../architecture/reviews/2026-10-11-temporal-session-data-writes.md)。尚未证明真实模型质量、完整配置或完整H1/H2/H3/M1；下一批继续高级持久地址与原 Parent 最终保存，不关闭R01–R26。


## dev67 Temporal 根／成员会话树（本批验收通过）

R01/R02/R14/R19 的显式 `CompositeSessionTopology` 接通原 Parent 根读／聚合保存与
原 Agent 私有保存。根 SessionKey 不迁移；成员以根身份、绑定修订、结构化声明路径和
Agent 声明固定独立地址。可替换纯拓扑必须保留原 Scope／namespace／generation。
原 History 接收源快照、消息回执和真实处理器结束证据；Coordinator 仍只持有 Turn。
SQLite／Redis／PostgreSQL、History-only 根加远程私有源、混合 namespace 已有实际证据。
自动上下文压缩、大结果卸载、RAG 和规则／模型记忆复用原阶段，并保留每 Agent 绑定。

唯一独立审查发现根读超时处理器未结束仍可释放 Turn；已以状态和真实线程 RED→GREEN 修复，
单次读尝试、真实 Future 和原结束 Update 共同保留占用。最终源码3801/267，安装198契约与实际41项；core-only、226模块与真实旧新兼容通过，
详见[本批验收](../architecture/reviews/2026-10-11-temporal-session-trees.md)。
完整 Temporal Profile／starter、跨权威租约、FIFO／输入续接、其余环境绑定、
全量原生读者生命周期治理、容量／保留／迁移、真实模型与外部首用仍开放。

## dev68 Temporal Context 实际读取生命周期（本批验收通过）

R01/R02/R14/R19：显式 context_reads=True 固定可替换处理器 Owner，并由原 Native
History 分别采纳许可、响应和准确结束证明。普通 Context 与 plan/read/verify/finalize
只读阶段实际线程、async 与通知尚未结束时保持原后代非静默／Turn busy。
默认 False 不改变旧发布；新 binding2 由 dev67 接受前拒绝。Redis/PG、七类组合、
摘要／产物／自动记忆及真实 Worker kill+wait/restart 已有测试，最终源码3940/306、安装241契约与39真实服务、231模块和 core-only、
旧67↔新68默认／save-v1兼容已通过。根读取、Session 保存、模型／工具／写效果保持独立责任。

完整 H1/H2/H3/M1、R01–R26、Temporal Profile 装配、其他环境角色、自动监督恢复、
跨权威会话租约、治理与真实质量继续开放。见[指南](temporal-context-read-lifetime.md)与[验收](../architecture/reviews/2026-10-11-temporal-context-read-lifetime.md)。

## dev69 Temporal Profile 装配子集

新增不可变声明与单客户端／单队列 Assembly，原 Scope、Release、数据集与实际 Activity 身份固定。模型／工具／摘要／写入和 Context／Session 原通知排空后才关闭 Worker 与工厂资源；启动、取消、失败和重试保留责任。高级裸 Runtime 只能在执行前明确移交。

真实服务验证含七类编排的独立 Worker／两Turn／重启与原 History replay、Redis／PostgreSQL 根及选择私有 Session、四类处理器关闭窗口和审批重复命令；最终冻结版本、安装包、旧新兼容及独立 review 结果以[dev69 验收](../architecture/reviews/2026-10-11-temporal-profile-assembly.md)为准。文档与接口实现不代替最后门槛。

完整 R04/H1/H3/H5/M1 仍开放：多版本路由、SDK／环境绑定角色、EffectJournal 声明工厂、跨权威租约、容量／保留／迁移、真实语义质量与独立采用。见[配置指南](temporal-profiles.md)。

## dev70 Temporal 多版本 Host

R04/H1/H5 沿原 Assembly、SDK History/Registry/Coordinator 增加显式 Catalog 全预检、最多32个固定版本、原发布确定队列与 Scope/namespace UUID 路由。默认切换只影响新 Facade；原 Run、Session、Turn 与回执必须保留原版本，空闲 CAS rebind 仍显式。共享 owned 对象全局排空后只关闭一次，SDK Client 借用。配置可声明既有 PostgreSQL EffectJournal，业务写审批与恢复不需要自造 journal 装配。

实际独立进程、完整 Worker 间隔、默认切换、原审批／重复回执、native/graph Session idle rebind、History replay、缺失 Registry 队列和真实异步／线程关闭已验收。最终冻结全回归／安装／旧69兼容／审查证据以[dev70 记录](../architecture/reviews/2026-10-11-temporal-profile-host.md)为准。没有新的执行索引或状态机。

完整 R01–R26/H1–H5/M1 继续 ACTIVE。配置监听／代码归档／部署迁移、环境角色、跨权威租约、自动监督、容量／保留、企业身份和真实质量／外部采用均未由本子集完成。

最终dev70：4060 passed/328 configured skips（650.66s）；冻结源码原服务53/453.23s与Host9/47.04s，安装同组62/504.83s（1项离线）；安装104契约/1未配置服务跳过、core90/31可选SDK跳过和恢复50项通过，组间有重叠。241模块完全一致，旧69双向默认/native save-v1/Local兼容、自有服务停止通过。独立4Important由9RED→72GREEN统一修复；SDK启动选项预检Minor保留，见[完整判断与代价](../architecture/reviews/2026-10-11-temporal-profile-host.md)。完整目标继续active。

## dev71 启动选项纯预检（本批验收通过）

R04/H5 在原 Host 入口补齐字段／普通数值／基础 Worker 参数与全部 build_id 的无 I/O 校验，纠正后允许重试。共享 timeout 规则保持直接 Engine 默认与旧发布，真实 SDK 验证cache=0/slot=1与重启回执。复杂插件对象仍借用并交给 SDK，未由纯预检保证其语义。最终审查／冻结全量／安装／兼容门槛见[验收](../architecture/reviews/2026-10-11-temporal-startup-preflight.md)，最终源码4114 pass／329配置跳过、安装136契约／7必需服务、旧70双向兼容与242模块一致已通过；3项Important修复、极端数值Minor延后。完整 R01–R26继续active。

## dev72 CLI 工具子集

沿 R12/H4 复用原工具与执行协议，新增固定命令 JSON stdin/stdout、实际进程／线程停止、async 声明工厂和 cli starter。最终4159项源码回归、安装契约、真实Temporal＋PG及旧71兼容通过，服务已停止；异常cwd预检、空argv参数和完整read/plan示例继续开放；[记录](../architecture/reviews/2026-10-11-cli-tools.md)。普通进程不是 Sandbox；MCP HTTP、其余环境绑定、外部 Runner 和主 CLI async 工厂继续开放。

## dev73 固定业务工具（本批验收通过）

CLI三项使用缺口、读取／规划／审批示例与HTTP固定POST沿原Action／效果协议接入。最终源码4225／333配置跳过、核心及扩展安装、真实源码／安装各4项、实际72兼容、250模块一致与服务退出门槛通过；[验收](../architecture/reviews/2026-10-11-fixed-business-tools.md)。MCP HTTP、映射／凭据代理、Workspace／Skills／Sandbox／Runner与完整R12/R13仍开放。

## dev74 MCP HTTP（子集验收通过）

原工具协议已接入固定目标JSON／POST SSE、async声明、真实线程／Client关闭和原未知效果核验。最终源码4304／337配置跳过、核心79／扩展320安装、真实源码和安装各8项、旧73双向兼容、22原模板与254模块一致通过；3项Important修复，自有服务停止并等待实际退出。[验收](../architecture/reviews/2026-10-11-mcp-http.md)保留完整边界。完整R12/R13及全框架能力继续开放。

## dev75 只读Workspace（子集验收通过）

可替换Port和POSIX／Memory默认、三项原工具与async装配、声明Scope准入及实际读取拥有已实现。最终源码4431／339配置跳过，核心127／扩展191安装、真实源码和安装各2项、旧74双向恢复／22模板与258模块一致通过。8项Important闭环，1项C1路径Minor延后，自有服务停止并等待退出。[验收](../architecture/reviews/2026-10-11-workspace-read.md)保留完整边界。Agent.workspace绑定、写入、Skills／Sandbox／Runner和完整R13／H4保持开放。

## dev76：每Agent只读Workspace绑定（子集验收通过）

R01/R13共享纯工具授权交集、固定原Source身份、借用Registry及Profile registered-tools复用；原Engine／History负责实际读取、审批和恢复。最终源码4501／345配置跳过，核心59／扩展160安装、真实源码及安装各6项、旧75恢复／22模板／259模块一致及真实旧Worker Activity前拒绝通过；1项Important闭环，1项错误分类Minor延后，自有服务已停止。[本批记录](../architecture/reviews/2026-10-11-workspace-bindings.md)。完整R01–R26目标保持进行中；文件写入、Skills／Sandbox／Runner和企业治理并未由本子集交付。

## dev77：受管理Workspace写入

R01/R13沿原ToolSource／Action／History接入可替换WritePort、Memory／POSIX默认、CAS／稳定效果键、单根租约、下游意图／回执与保守inode核验。最终源码4615／351配置跳过、核心100／SDK214安装、真实源码及安装各6项、旧76兼容及独立审查修复通过；原服务停止并等待。实际原生取消窗口延期。[使用指南](workspace-writes.md)／[本批证据](../architecture/reviews/2026-10-12-workspace-writes.md)区分目标剩余能力，完整清单继续开放。

## dev78：Skills目录与受管理加载

R13接入同步可替换目录和Memory／JSON+Markdown File默认，原SkillToolSource读Action和声明工厂。最终源码4757／357配置跳过、核心142／SDK204安装、实际7项与旧77兼容通过；四项Important已修复，原服务停止并等待。[指南](skills.md)／[证据](../architecture/reviews/2026-10-12-skills-catalog.md)。专用R01角色、完整YAML、异步加载／自动目录阶段、Sandbox／Runner和R01–R26仍开放。

## dev79：每Agent Skills绑定

R01/R13沿原借用工具目录、授权交集和Local/History接入显式ref/disabled；正式116、实际六类6及旧78Worker Activity前拒绝通过。最终源码4823／364配置跳过、核心55／SDK127安装、真实源码与安装各6、旧78兼容和实际执行前拒绝通过；两项Important闭环，自有服务停止并等待。[指南](skills-bindings.md)和[证据](../architecture/reviews/2026-10-12-skills-bindings.md)。selector／自动目录阶段、asyncLoader／Sandbox／Runner和完整目标仍开放。
