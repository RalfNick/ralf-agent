# 持续能力开发与验收队列

用户授权：2026-10-10 持续执行直到能力完成；当前接续先补齐完整默认单 Agent、语义 RAG、Plan／Team 主链路，再分阶段验收全部能力。只本地提交，不推送远端。
当前基线为 dev85 推荐链路／评测已验收子集（上一批 dev84，本轮接续起点 `0ca8eb5`）；实际版本及本地提交 SHA 以 Git 为准。dev67 会话树是历史已验收增量，不能代表当前开发位置。
权威范围保持[剩余清单](remaining-work.md) R01–R26、[Harness 架构](../architecture/viewpoints/harness-runtime.md) H1–H5；下文排序不删除或缩小任何目标，也不新增执行权威。
历史设计中明确后置的高级 Realtime/TTS、公共插件市场和运行中热迁移保持单独路线图；按需适配器不以数量定义完成。完整 M1、对等框架比较和企业正式可用仍未完成。

## 执行与记录

按依赖开发、复现、审查、验证、同步能力文档和本地提交。独立任务可以并行推进；共享 DTO、Profile／Release、绑定身份、错误、取消、真实结束和恢复协议必须统一集成，不能以各分支单测替代组合验收。
不把本页勾选、接口存在或测试数量代替验收；分别记录公共契约、最小默认、另一实现替换、配置／注入、身份／生命周期／错误／恢复、安装包与实际证据。
Local 原 Run 与 Temporal 原 History 分别保留唯一执行权威；原 Session／Turn、审批、预算、写意图和精确回执继续复用。独立任务不得另造协调状态机。
真实服务、真实模型或外部采用缺证据时，保留相应未验收状态并继续其他独立实现；缺少服务只阻断对应真实门槛。涉及确实不可逆的外部发布或缺授权才暂停对应动作。
上下文压缩后从实际 Git、[剩余矩阵](remaining-work.md#2-分层剩余清单)及最新验收恢复位置；以下历史接续判断不再作为当前优先级。

## 当前已交付基础与开放边界

| 已交付子集 | 当前仍开放的范围 |
| --- | --- |
| dev54 可替换 tokenizer、token 分块和输出预留；dev55 POSIX 文件 JSON Artifact；dev84 第十四类独立 artifacts 绑定及六类组合 SQLite／file 子集 | R14/R16 实际模型词表、完整协议计量、语义分块与长上下文质量；R18 远端／binary、引用保留／孤儿 GC、磁盘治理与缓存；其余 selector／组合契约 |
| dev56–59 全库事实扫描／显式索引、Temporal Facts／Knowledge 来源绑定；dev60／66／67 History／外置 Session 与根／成员树；dev68 实际 Context 读取生命周期；dev69–71 Profile／多版本 Host／启动预检 | 自动索引生命周期与语义质量、跨权威租约、输入续接／业务期限、剩余角色／受管理阶段及完整推荐配置，不能关闭 R01–R04/R15/R17/R19/H1–H3/H5 |
| dev72–74 固定 CLI／业务 HTTP／MCP HTTP；dev75–81 Workspace 读写、成员绑定与原生写真实结束；dev78–82 Skills 解析／加载／绑定／被动目录；dev83 本地 Docker Sandbox 子集 | 完整工具包／MCP 会话与认证、Workspace 其余操作／权限／远端租约、语义 Skills 选择／自动正文／插件激活、远端 Sandbox／持久文件与 Coding Runner；R12/R13/H4 仍开放 |
| dev43–50 推荐 Local、显式语义 Knowledge／记忆召回及 Plan／Team 起步组合 | 完整默认业务链路、真实生成／Embedding／重排质量、业务 verifier、替换与诊断、最终配置重复验收；Echo／Hash／Schema 验证不能证明业务质量 |

后续子集状态以[剩余清单](remaining-work.md)及[dev84 验收](../architecture/reviews/2026-10-12-artifact-bindings.md)为准。dev83 的实际 Temporal Sandbox CI 覆盖缺口与缺失 ServerVersion 的错误类型（验收记录 M1/M2）仍延期；它们与完整 M1 验收是不同条目。

## 当前权威优先队列

1. **完整默认主链路优先：R01–R05/R07/R10/R11/R14–R18。** 在既有[推荐组合](recommended-harness.md)与[语义／Plan／Team 起步](h3-intelligent-combinations.md)上补齐单 Agent 的模型→工具→上下文／摘要／产物→来源化记忆→完成验证／Session 恢复，语义 RAG 的摄取→分块→显式 Embedding／索引→检索／重排→来源回读→答案／引用验证，以及 Plan／Team 的业务成员、工具、依赖输入、停止条件和结果验证。现有 Profile 与 starter 是接续基础，未证明完整默认业务链路；需要真实模型的组合明确配置 Provider／Embedding，不能把 offline-echo 或 Hash 标为语义默认已验收。
2. **入口与共同协议随主链路集成：R01–R04/R08/R10/R11/R19/R21/R22。** 接续输入／needs_input／send_input、业务 deadline／Local 审批期限、受管理验证及其余阶段、类型化交接和受控共享状态；补完整绑定／推荐配置、CLI async 工厂、共同错误／能力／生命周期／故障／升级矩阵。保留既有 Session／Turn 与各自执行权威；跨权威租约／耐久 FIFO 仍需独立交付。
3. **可独立推进的环境与数据任务：R12/R13/R15–R18/R20/R25。** 先补当前默认链路实际需要的工具、Workspace／Skills／Sandbox 使用缺口、首个 Codex／外部 Coding Runner，验收停止／租约／效果未知与交接；并行接续自动索引／删除传播／修复、记忆修订／遗忘、数据和产物生命周期、角色 AdapterContractSuite。共享协议完成统一集成后再计组合通过；不重复把已交付 tokenizer／文件 Artifact／固定 CLI／MCP HTTP／Workspace／Skills 子集列为未实现。
4. **完整能力与正式部署继续：R05/R06/R08/R09/R19–R25。** 多协议能力／用量／错误／路由及真实模型矩阵、基础多模态、高级 Workflow 节点／合并、逐记录流式 Workflow、单权威多 Process Worker、全局容量／背压、MQ／A2A 续接、服务流式／控制台、保留／迁移／备份／恢复／部署治理仍需完成。R24 OIDC／企业 actor、源 ACL、凭据代理、工作区配额、健康／HA／故障演练与控制面全部保留；Scope 不是认证，事件展示不是流式 Workflow，Docker 子集不是完整隔离治理。
5. **R26 与 M1 贯穿各阶段并独立收口。** 固定最终配置重复执行业务、规划、记忆与 RAG 引用任务；形成完整 fixture／评分器、成组故障／升级／Temporal 契约报告、独立首用及同模型／工具／服务的 AgentScope／LangGraph 对等比较。已有模型小试验和运行恢复证据分别保留，不能拼接为最终配置成功率、外部采用或框架优越性。

这是 R01–R26 的执行排序。尚缺企业／全能力范围不会因默认链路先完成而取消；缺少远端或模型验收不阻止其他独立任务继续。

## 分阶段验收与证据

| 阶段 | 本阶段通过条件 | 未由本阶段证明的范围 |
| --- | --- | --- |
| 契约与最小默认 | 每项接口、可运行默认、另一实现替换、配置／注入、身份／错误／生命周期与安装示例一致；必需能力缺失在准入前拒绝 | SPI、离线 mock 或 Echo 不能证明完整业务链路与真实质量 |
| 默认组合闭环 | 单 Agent、语义 RAG、Plan／Team 分别用固定 Profile／Release 完成端到端运行、取消／关闭、原保存与恢复；共同协议集成通过 | 一条链路通过不能关闭其他链路或 R01–R26 |
| 运行与后端 | 选定 Local／Temporal、数据／环境替换组合完成真实服务、Worker 故障、精确回执／真实结束、旧新版本和最终安装包验收 | Runtime／History 恢复、内容核验、PID wait 不替代真实模型质量或原处理器 end 证据 |
| 最终配置质量 | 同一最终配置重复真实模型／Embedding／重排的业务、规划、事实保留与答案／引用任务，记录评分、失败、用量与限额 | 离线 Hash／词项召回、Schema 合法及不同阶段小试验不能合成最终成功率 |
| 全能力与采用 | 补齐仍开放 R01–R26 的必要默认／替换／治理门槛，完成 M1 报告、独立首次采用及对等比较；企业能力逐项验收 | 内部测试与本地提交不能代替外部采用、正式企业可用或发布状态 |

每阶段按能力记录通过、未交付或缺证据，保留尚未通过门槛；不要求先实现全部数据库与角色的笛卡尔积。dev85已验收版本2规则DAG串接、有效资源声明替换、重复评测摘要及质量标签／评分／恢复观察修复；源码5520／447配置跳过、独立核心安装171通过。真实RAG／Plan／Team质量及外部采用门槛仍开放，详见[本批验收](../architecture/reviews/2026-10-12-default-chains-evaluation.md)。当前任务只沿既有架构接续，任何阶段完成均不自动关闭整个目标。

## dev54–dev67 历史批次与证据

以下保留原批次记录、回归数字、资源交接及当时判断。文中的“当前”“下一批”“下一定位”和未交付结论均指该批次检查点，不能覆盖上面的当前队列；dev68–dev85 的后续交付以[剩余清单](remaining-work.md)及对应验收为准。dev67 开发中检查点的 Task2–4／dev66 包状态已由本页末尾 dev67 最终验收更新。历史路径不代表当前运行资源，也不授权清理或重启服务。

- dev54：可替换Tokenizer、字节基线／可选tiktoken、输出预留与token分块；[验收](../architecture/reviews/2026-10-10-tokenization.md)。
- dev55：POSIX FileArtifactStore、SDK／JSON/TOML与受管理卸载恢复；3343/98、安装117、模块193、core及旧回执兼容。随后官方CLI1.9.1/Server1.32.0的实际Temporal file6＋SQLite6通过；[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。功能cde3966，真实服务补记ce32d6a，仅本地。
- dev56：有界FactScanner、固定snapshot、独立CAS元数据端口、全库构建／accepted embedding／幂等vector／完整active、权威召回和JSON/TOML独立工厂。memory/SQLite/Redis来源，显式HTTP/Qdrant；[验收](../architecture/reviews/2026-10-11-fact-indexing.md)。最终3397/98、安装74、模块197、core与dev55↔56原回执兼容通过。

## dev56 设计与证据（历史）

四个实际进程窗口覆盖response保存／vector ACK丢失／page commit／active commit，2次已接受batch与最终4个vector保持。
真实Redis270条、Unicode／大整数／过期、snapshot变化及client+SQLite向量重开；完整ready复用不重复Embedding。
独立review两项P2（DataPort忽略Qdrant物理身份、SQLite大key未截断）已针对RED→GREEN修复。Qdrant新组合HTTP fixture不是实际服务质量。
Scanner是显式宿主枚举，含expired不自动扩张Agent权限；recall是全库排序top256候选分页，不是全库枚举。
默认Hash是离线词项基线，写后显式rebuild；自动增量／修复／GC和真实语义质量均未完成。不关闭整个R15/R17/H3/M1。

## dev56 当时的下一批依赖（历史）

1. R15/R17：PostgreSQL native snapshot／有界scan、真实远端索引组合和全库索引质量；再推进自动增量、信念修订／遗忘与索引生命周期。
2. H1/H2：Temporal其余绑定角色、共享Session与输入续接；业务deadline／审批期限和移交。
3. H4：Workspace／文件权限与固定CLI Runner，MCP HTTP／受控Sandbox／Skills与首个外部Coding Runner。
4. H5与横向：容量／保留／迁移／服务观察、模型一致性、可复用AdapterContractSuite及真实质量／首用／同场景比较。

缺少服务只阻断相应真实验收，不停止其他能力实现；版本适配不能靠原型或接口声明标完成。
PostgreSQL官方16.15源码已验证并在任务目录临时编译；本轮真实PG门槛已通过并停止实例，下一批可复用已构建binary。Temporal／Qdrant等缺失服务仍分别验收。

## dev67 开发中检查点（历史，已由最终验收更新）

实施计划：[Temporal 会话树](superpowers/plans/2026-10-11-temporal-session-trees.md)。
显式 `session_topology` 注册现已接通 Runtime、原 Parent 根读取／聚合保存 Activity、
原成员私有读写与 SDK 调度；默认不注册时保留 save-v1，显式注册发布 tree-v1／save-v2。
拓扑只提案地址，Scope、实际 namespace UUID、原绑定／声明路径、直接父 Workflow、
选中数据源和根占用仍由原执行权威校验。自定义提案可扩展路由后缀，不能移除原成员代际或改写根。
根快照单次采纳后仅投影给后代，不改变原请求，也不重复引用外置 Conversation 的 History。
原 Parent 预留根写额度，并在独立聚合证据、精确回执采纳及实际处理器结束后提交成功。

当前相关回归 **237 passed**（11.10s）。实际本机 Temporal／SQLite 的 Graph、Team、规则 DAG、
嵌套编排 × 普通／managed 上下文，两轮根／私有保存及全部后代 History replay **8 项通过**。
独立 Worker 根读取后强制退出的恢复测试 **1 项通过**：模型1次、两个不同地址各写1次、读取2次；
其余根聚合／成员提交／回执采纳窗口正在运行，未完成的测试不计入验收。
实际恢复发现并修复了 sandbox 内外 SessionRef 类型身份不一致；按 Agent 选源的兼容回归也已修复。
基础增量的旧全量3745／226跳过发生在这些集成之前，不能作为当前完整回归结果。

Task2–4 尚未验收：仍需完整绑定／混合源／规划默认组合、远端数据库和真实处理器关闭证据，
以及安装、默认旧新 History 兼容、最终审查和全量回归。包仍为已提交 dev66；未发布或提交 dev67，
也未进行真实模型质量或外部采用验收。完整 R01–R26 与 H1/H2/H3/M1 保持开放。

## dev55／dev56 运行资源交接（历史）

当前dev56测试目录由 /private/tmp/ralf-agent-dev56-current 指向 /private/tmp/ralf-agent-dev56-zujg6n38。
full-suite.log确认3397/98，执行会话22663已exit0；所有fixture Redis已正常关闭，无托管中的新服务。
旧dev55目录 /private/tmp/ralf-agent-dev55-5hg43c2i 保留已SHA256校验的官方temporal-cli和验收日志。
旧服务43396与下载6304均已确认结束；SDK默认下载失败后改用官方CLI成功，下一次复用该可执行文件启动新任务状态目录，避免重复下载。
任何清理都先确认任务自有进程结束，不修改其他任务／用户服务。dist保留55／56产物；新功能仅本地提交，禁止push。

## dev57 最终验收（历史）

PostgresMemory增加native snapshot/scan；显式initialize新增epoch表，既有writer/advisory锁和CAS保持。named server cursor itersize1，原始key/value SQL截断再解码。
官方PG16.15源码25181309字节／SHA256 c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed已验证并临时编译；无系统安装，仅0700 Unix socket。
服务runner55632在 /private/tmp/ralf-agent-dev57-xjhrw5oj，DSN postgres.dsn，官方源码与binary在同目录；服务已正常关闭，runner55632 exit0且stopped=0确认；无运行中PG实例。
初始4个实际服务RED缺端口已GREEN，四个进程窗口+配置Agent/owned关闭形成9个新PG案例。相关60／PG组合52与Qdrantskip1／安装69通过；独立review实际验证取消释放游标／事务／锁，未发现P1/P2。
实际wheel56→57→56新数据库显式schema升级保持原事实，旧写者使新cursor/index失效；原默认Run／Manifest／SQLite引用和21 starter亦保持。198模块一致，独立core venv通过。
首轮完整34197结束：2failed/3434passed/68skip，两处旧PG夹具解包错误修复并使用匹配Scope；远程绑定4项通过且补入CI。旧第二轮99904在运行早期被中断，已exit130且log无持有进程，不算成功。最终完整24107已exit0，full-suite-verified.log记录3436passed/68skip（653.58s），.pid记录实际子进程5885。最终安装4个远程绑定修复亦通过，总计73项；198模块字节保持。CI远程job已显式纳入新Redis/PG索引tests。
自有Service已通过stop关闭并确认正常退出；验收已保存，随后仅本地提交。随后继续Temporal Facts绑定／索引生命周期及其他主能力；不因PG子集完成缩小整体目标。

当时的接续判断（历史）：下一阶段定位：temporal_bindings.ROLES当前只有provider/context/knowledge/tool_set/stage_policy，selector被明确拒绝；TemporalActivityRuntime.manifest没有Facts召回注册/证据。后续优先扩展Facts注册／scoped view／原model accepted context receipt，再覆盖原生顺序与高级Agent-node实际History，不添加第三套状态机。agent-bindings旧导读已同步为实际Facade/Temporal子集，避免仍把已交付能力写为尚未实现。

## dev58 批次与当时下一定位（历史）

Temporal Facts 绑定、host namespace、纯planner与有界pages沿原 Context History 采纳；源码及安装真实12恢复组合、原服务16、安装94、core与57↔58默认回执通过。
审查3项P2已RED→GREEN并复核，纯Scope/JSON与新证据模块预加载/passthrough覆盖真实sandbox；未知model不重试。
真实Redis/PG16.15 Activity/state scoped read、TTL、stale与物理connection替换探针通过。两项自有Service runner39428/13352已exit0，服务停止标记确认。
初次全量唯一版本一致性失败因pytest收集时载入旧dev57；代码及版本固定后full-suite-final.log记录3417 passed/119 skipped（577.74s），58529 exit0；Ruff/格式/空白通过。
当前目录 /private/tmp/ralf-agent-dev58-7f724wa1；最终提交及全量结果见[dev58验收](../architecture/reviews/2026-10-11-temporal-facts.md)。
当时的接续判断（历史）：下一定位：temporal_bindings已支持facts与其namespace，但knowledge selector仍拒绝；KnowledgeBindingResource.resolve已有Local scoped view。先补Temporal Knowledge原始resource/method/backend固定和独立来源验证、实际History/绑定矩阵，再推进共享Session/续接与其余R01–R26门槛。不把本批次当完整goal完成。


## dev59 批次与当时下一定位（历史）

Temporal KnowledgeBindingResource namespace、实际 effective namespace、纯 source evidence 和原生检索资源固定已实现，原 Context History 仍唯一采纳。
两项review P2已复现RED→GREEN并复核；Facts/Knowledge共存、取消最终来源await、来源变化、跨Scope和非法selector/protocol均有测试。
真实源码与安装各12 Worker kill/restart/replay组合通过；真实PG16.15普通/managed Activity/state来源/TTL/版本/连接替换探针通过。
最终：原Temporal28、全量3436/131（467.01s，66357 exit0）、安装63/202模块、core-only/58↔59原回执兼容通过；两项自有Service runner68836/97489 exit0，停止标记确认。验收/文档/构建同步，仅本地提交。当前任务目录 /private/tmp/ralf-agent-dev59-v76202ba。
当时的接续判断（历史）：下一定位：Temporal现在支持Facts/Knowledge的namespace；Session仍明确拒绝shared session_id。需按原Session/Turn契约设计跨Run持久身份/占用/续接，保留原History权威；随后其余role和R15/H4/H5继续。未关闭整个目标。

## dev60 批次与当时下一定位（历史）

按原 H2 Session／Turn 契约补齐 Temporal History Conversation、实际 Namespace UUID、耐久串行占用／busy／CAS 与启动恢复；原 Run/Parent 保持业务执行权威。普通／managed 六种编排的真实 Worker kill／replay 及审批／重连分别验收；review 四项 P2 已复现修复，含冷入口预检、冻结声明与普通来源复验取消。
当时的接续判断（历史）：下一定位：Temporal Session 数据目前仅 History，外置 SessionStore 路由／准确保存回执与其他绑定角色继续推进；R15 生命周期／H4 环境／H5 治理和真实语义质量仍未闭环。

最终dev60：全量3466/146（536.83s、47316 exit0），原Temporal27＋最终入口3、安装Session15／契约103、207模块、core-only与59↔60默认Run／Manifest／Artifact／21 starter兼容。四项P2已修复；实际CLI1.9.1/Server1.32.0，最后Service35988 exit0且stopped。任务目录 /private/tmp/ralf-agent-dev60-_vif9k8h；日志与已验证CLI保留。
当时的接续判断（历史）：下一批先完善 Temporal 其余角色的固定选择／受管理采纳，外置 Session 数据需先补资源身份／准确保存与同权威责任；继续 R15/H4/H5 和质量门槛。不以本批提交关闭全能力目标。

## dev61 批次与当时下一定位（历史）

Temporal H1f 复用可替换纯 LimitsPolicy，原 Run History 逐节点采纳宿主／AgentSpec 交集；同定义不同节点、普通／managed、图／Team／动态／嵌套保持固定绑定和 caps。实际 Worker 恢复与新旧审批兼容已验证；最终全量及本地提交在[验收记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)更新。自有 Temporal Service83761正常退出且stopped标记确认，源码和安装恢复都不调用真实模型。

当时的接续判断（历史）：下一定位：Temporal 仍缺每 Agent CompletionVerifier 与纯 DecisionPolicy 替换。优先把现有 CompletionRequest/CompletionVerdict 接到原模型完成、原工具回执和原 History 受管理采纳，区分 retry/reject/accept，先验证再记忆／终态，不添加第三套状态机；随后其余角色、外置 Session 数据和 R15/H4/H5/真实质量。整个 R01–R26 目标继续 active。

最终dev61：全量3492/164（523.45s、56122 exit0），源码实际12恢复+6超限、最终安装18真实Temporal/85契约、209模块、core-only与60→61→60原审批/回执/一次测试工具兼容。宿主入口P2、沙箱异常身份P2与错误码Minor已闭环，自有Service83761 exit0且stopped；只做本地提交。完整能力目标继续active。

## dev62 Temporal 纯完成验证（历史）

沿 R01/H1e 复用 CompletionVerifier 与 ToolReceiptVerifier，Worker 提出纯 verdict，原 Run History 固定当前节点原输入与已提交回执并一次采纳。accept 才进入原记忆和完成链路；retry 保留原额度、审批和受保护反馈，reject 明确失败。宿主／每 Agent inherit/ref/disabled 支持原生、顺序、图、Team、动态及嵌套。实际十八项恢复／取消／重放通过；最终交付证据见[验收记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。模型验证、DecisionPolicy／外置 Session 和其他环境角色、H3 质量及完整 M1 继续开放。

最终dev62：全量3519 passed/182 skipped（537.24s，8978 exit0），源码实际Temporal18/133.86s、最终安装18/133.40s及163契约；212模块、core-only与61→62→61原审批／回执／一次工具兼容。只读review140通过且无待办P1/P2/Minor；两处控制／反馈P2已RED→GREEN。自有Service25330正常exit0且stopped。未调用真实模型、未重验远端数据库；只本地提交，完整R01–R26目标继续active。

## dev63 Temporal DecisionPolicy（历史）

沿 R01/H1 公共纯 Harness 的 prepare/propose，提供宿主默认／每 Agent inherit/ref；固定实际方法、编译器 super 闭包及原 Scope。实际模型请求与原响应/提案证据由原 Run History 一次采纳；不改变审批、Schema、limits、完成规则和记忆责任。Temporal 九类绑定已接通，外置 Session/环境角色、完整 Profile/服务治理和真实质量仍待交付。见[指南](temporal-decision-policy.md)和[验收](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。

## dev64 默认数据前置与当时下一批（历史）

默认 memory/SQLite 现在提供与 Redis/PG 相同形状的精确 Session 回执；Local 原绑定/保存恢复复用原执行权威。Temporal 外置 Session 尚未交付；按[完整数据契约](../architecture/specs/temporal-session-data-contract.md)接通受管理读、原写意图/回执、成功门禁与根/成员绑定，不能把这一前置能力作为目标完成。随后继续输入续接/deadline、H4/H5 与 R01–R26 其余能力；真实质量与外部采用保持独立验收。

### dev64 最终证据与资源

最终完整3613/198（563.98s）、安装146、默认/原会话122、源/wheel/sdist/install214模块、core-only与实际63↔64兼容通过；新外置默认后端旧版拒绝派发。独立审查1P2类型ID已3RED→GREEN。见[验收](../architecture/reviews/2026-10-11-default-session-receipts.md)。root由 `/private/tmp/ralf-agent-dev64-current` 指向 `/private/tmp/ralf-agent-dev64-hk711mpa`，full22252 exit0；本批无托管Temporal/PG服务，完整回归及fixture已结束。下一批从实际本地提交SHA接续完整外置Session契约，不关闭R01–R26。


## dev65 固定有界 Session 数据读与当时下一批（历史）

原生／顺序 stateless 支持 session 选择与 namespace，原 Context/managed History 固定 scoped 私有 Run/node 原快照；资源／方法／客户端／PG 初始化实际 schema 固定。三个 review P2 已 RED→GREEN：桥接原方法、嵌套模型 Planner 准入、真实 PostgreSQL schema 切换。见[验收](../architecture/reviews/2026-10-11-temporal-session-data-reads.md)。
这只是完整外置 Session 的依赖，不关闭持久数据契约。下一阶段按原规格实现原生／顺序的保存意图／派发／CAS／精确消息回执与终态门禁，之后根／成员稳定跨 Turn 路径、Parent 根保存与租约。还需补齐 Profile 工厂／资源拥有与借用、故障窗口和旧 Worker 门槛，继而输入续接／deadline、H4/H5 与其余 R01–R26。禁止用私有读地址替代最终持久 SessionKey，禁止把 SPI 或回归数量当作全部能力完成。
本轮未调用真实模型，不修改用户提供的密钥配置，不推送远端。最终全量、制品和本地提交状态见本批验收；整个目标继续 active。

### dev65 阶段门槛与资源记录

安装140契约、真实安装服务7项及加强源码/安装各4项Context采纳后模型调度前窗口、freshcore默认/Session/文档例子、实际64↔65默认/审批/TemporalHistory兼容均已通过。初次加强夹具错误地停在已启动模型Activity，失败保持正确unknown语义；已改为SDK outbound命令调度前fault injection，不修改业务重试规则。三项自有服务48054/96105/74178全部exit0且stopped，无遗留Worker。产品Python在全量前冻结；后续仅服务测试夹具加强，真实最终源码/安装重验，未以skip作为此窗口通过。最终全量和制品数字填入本批验收后才本地提交。


### dev65 最终结果

最终全量3642 passed/204 skipped（620.69s，44944 exit0）；安装140契约及独立相关39项（有重叠）、真实安装服务7及最终源码/安装各4个Temporal窗口、217模块一致、freshcore/文档例子及实际64↔65默认/审批/History兼容通过。Ruff/格式/空白通过；三项自有服务全部关闭。只本地提交，无真实模型或完整H1/H2/H3/M1质量宣称。后续按完整外置Session写/持久路由继续，不关闭R01–R26目标。


## dev66 原生／顺序外置会话与当时下一批（历史）

原计划任务1／2已分别验收25和65项；原History保存协议、真实Handler独立拥有、数据集／Namespace身份、根地址和source-once完成。唯一独立review4项P2及自己的派发前超时fence由RED→GREEN闭环，最终全量3686 passed/226 configured skips（519.28s），安装150契约／25真实服务，源码真实65、freshcore及实际65↔66兼容通过。最终制品／服务关闭／本地提交证据见[验收](../architecture/reviews/2026-10-11-temporal-session-data-writes.md)。未调用真实模型，不推送远端，完整R01–R26继续active。

当时的接续判断（历史）：下一批沿同一完整外置Session规格实现Graph／Team／动态DAG／嵌套的原成员稳定地址与原Parent根保存，先明确来源分类／单次保存和父子静默门禁，复用既有写意图／CAS／回执／采纳。随后补Profile推荐装配、其他绑定与治理／质量门槛；不把本批局部验收替代完整H1/H2/H3/M1。


## dev67 Temporal 根／成员会话树与当时下一批（历史）

本批基线 ae9854e/dev66。显式纯拓扑、原 Parent 聚合保存、稳定私有成员源、
source-once Context／RAG／记忆、真实处理器结束通知接通。唯一独立审查的根读超时 P1
已 RED→GREEN 修复；代码注释一项 Minor 留作后续修订。最终源码3801/267（508.59s）、安装198契约／实际41（455.60s）、core-only与226模块一致，
不可用此前 foundation3745/226 代替本批最终产品证据，见[验收记录](../architecture/reviews/2026-10-11-temporal-session-trees.md)。
当时的接续判断（历史）：下一批先完善原生／私有 Context 读者治理，再补 Temporal 推荐配置／starter与其余绑定，随后输入续接／期限、
环境／Runner、长期容量／迁移及真实质量。完整 R01–R26 继续 active；只本地提交，不推送。

最终冻结产品全量7679 exit0；安装全服务57843 exit0。旧新默认、21 starters、typed Session、Local审批与Temporal默认/native-v1 History兼容通过；旧66 Worker新协议无业务Activity即拒绝。实际源码41/469.59s在主P1修复后、最后重复拒绝分支前，最终安装41重新覆盖全部服务形状。唯一审查的读者P1以2状态+1真实线程+1重复读者RED→GREEN闭环；一项候选注释Minor待修。PostgreSQL65460、Temporal92718均exit0，PGstopped=0，测试Worker全部结束。仅本地提交；完整R01–R26目标active。
