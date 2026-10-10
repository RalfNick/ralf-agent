# 持续能力开发与验收队列

用户授权：2026-10-10 持续执行直到能力完成；只本地提交，不推送远端。
当前 dev63 Temporal DecisionPolicy 子集已验收（基线cb370f9/dev62）；实际提交 SHA 以 Git 为准。此队列落实既有架构，不新增执行权威。
权威范围：[剩余清单](remaining-work.md) R01–R26、[Harness 架构](../architecture/viewpoints/harness-runtime.md) H1–H5。
历史设计中明确后置的高级 Realtime/TTS、公共插件市场和运行中热迁移保持单独路线图；按需适配器不以数量定义完成。

## 执行与记录

按依赖逐批开发、复现、审查、验证、同步能力文档和本地提交。批次完成后继续下一批。
不把本页的勾选代替验收；每个能力的接口、默认、另一实现、配置、身份／生命周期／恢复和实际证据分别记录。
真实服务、真实模型、外部采用缺证据时保持未验收，继续能独立推进的实现。涉及确实不可逆的外部发布或缺授权才暂停对应动作。
当前批次详见实施记录；上下文压缩后从实际 Git 提交和能力文档恢复位置，避免重复已完成工作。

## 依赖队列

- [ ] H3 计量与数据：R14/R16 可替换 tokenizer、token 分块及输出预留；R18 文件 Artifact；R15 全库语义索引与记忆生命周期；R16 来源／索引生命周期。
- [ ] H1/H2 闭环：R01/R02/R04 Temporal 其余绑定与共享 Session；输入续接、deadline／审批期限及明确移交；公共能力／错误／生命周期组合矩阵。
- [ ] H4 执行环境：R12/R13 Workspace／文件访问、固定 CLI Runner、MCP HTTP／权限、受控 Sandbox、Skills／Coding／首个外部 Runner；R11/R20 受控团队交接。
- [ ] H5 服务治理：R19/R21 单权威多 Process Worker、全局容量与背压；R18/R20/R24 保留／迁移／恢复；R22/R23 Agent Service 与流式观察／基础控制台；R24 企业身份与源 ACL。
- [ ] 横向能力：R05 多协议模型一致性／Gemini工具／路由；R06 媒体；R08 高级节点与合并；R09 数据流工作流；R10 受管理验证；R17 检索／适配／索引；R25 可复用 AdapterContractSuite。
- [ ] R26 质量与 M1：固定最终组合反复实测、分组故障与升级报告、真实服务验证、外部首用，以及同配置 AgentScope/LangGraph 比较。外部采用不由内部测试替代。

## 已验收批次

- dev54：可替换Tokenizer、字节基线／可选tiktoken、输出预留与token分块；[验收](../architecture/reviews/2026-10-10-tokenization.md)。
- dev55：POSIX FileArtifactStore、SDK／JSON/TOML与受管理卸载恢复；3343/98、安装117、模块193、core及旧回执兼容。随后官方CLI1.9.1/Server1.32.0的实际Temporal file6＋SQLite6通过；[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。功能cde3966，真实服务补记ce32d6a，仅本地。
- dev56：有界FactScanner、固定snapshot、独立CAS元数据端口、全库构建／accepted embedding／幂等vector／完整active、权威召回和JSON/TOML独立工厂。memory/SQLite/Redis来源，显式HTTP/Qdrant；[验收](../architecture/reviews/2026-10-11-fact-indexing.md)。最终3397/98、安装74、模块197、core与dev55↔56原回执兼容通过。

## dev56 设计与证据

四个实际进程窗口覆盖response保存／vector ACK丢失／page commit／active commit，2次已接受batch与最终4个vector保持。
真实Redis270条、Unicode／大整数／过期、snapshot变化及client+SQLite向量重开；完整ready复用不重复Embedding。
独立review两项P2（DataPort忽略Qdrant物理身份、SQLite大key未截断）已针对RED→GREEN修复。Qdrant新组合HTTP fixture不是实际服务质量。
Scanner是显式宿主枚举，含expired不自动扩张Agent权限；recall是全库排序top256候选分页，不是全库枚举。
默认Hash是离线词项基线，写后显式rebuild；自动增量／修复／GC和真实语义质量均未完成。不关闭整个R15/R17/H3/M1。

## 下一批依赖与主链路

1. R15/R17：PostgreSQL native snapshot／有界scan、真实远端索引组合和全库索引质量；再推进自动增量、信念修订／遗忘与索引生命周期。
2. H1/H2：Temporal其余绑定角色、共享Session与输入续接；业务deadline／审批期限和移交。
3. H4：Workspace／文件权限与固定CLI Runner，MCP HTTP／受控Sandbox／Skills与首个外部Coding Runner。
4. H5与横向：容量／保留／迁移／服务观察、模型一致性、可复用AdapterContractSuite及真实质量／首用／同场景比较。

缺少服务只阻断相应真实验收，不停止其他能力实现；版本适配不能靠原型或接口声明标完成。
PostgreSQL官方16.15源码已验证并在任务目录临时编译；本轮真实PG门槛已通过并停止实例，下一批可复用已构建binary。Temporal／Qdrant等缺失服务仍分别验收。

## 运行资源交接

当前dev56测试目录由 /private/tmp/ralf-agent-dev56-current 指向 /private/tmp/ralf-agent-dev56-zujg6n38。
full-suite.log确认3397/98，执行会话22663已exit0；所有fixture Redis已正常关闭，无托管中的新服务。
旧dev55目录 /private/tmp/ralf-agent-dev55-5hg43c2i 保留已SHA256校验的官方temporal-cli和验收日志。
旧服务43396与下载6304均已确认结束；SDK默认下载失败后改用官方CLI成功，下一次复用该可执行文件启动新任务状态目录，避免重复下载。
任何清理都先确认任务自有进程结束，不修改其他任务／用户服务。dist保留55／56产物；新功能仅本地提交，禁止push。

## dev57 最终验收

PostgresMemory增加native snapshot/scan；显式initialize新增epoch表，既有writer/advisory锁和CAS保持。named server cursor itersize1，原始key/value SQL截断再解码。
官方PG16.15源码25181309字节／SHA256 c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed已验证并临时编译；无系统安装，仅0700 Unix socket。
服务runner55632在 /private/tmp/ralf-agent-dev57-xjhrw5oj，DSN postgres.dsn，官方源码与binary在同目录；服务已正常关闭，runner55632 exit0且stopped=0确认；无运行中PG实例。
初始4个实际服务RED缺端口已GREEN，四个进程窗口+配置Agent/owned关闭形成9个新PG案例。相关60／PG组合52与Qdrantskip1／安装69通过；独立review实际验证取消释放游标／事务／锁，未发现P1/P2。
实际wheel56→57→56新数据库显式schema升级保持原事实，旧写者使新cursor/index失效；原默认Run／Manifest／SQLite引用和21 starter亦保持。198模块一致，独立core venv通过。
首轮完整34197结束：2failed/3434passed/68skip，两处旧PG夹具解包错误修复并使用匹配Scope；远程绑定4项通过且补入CI。旧第二轮99904在运行早期被中断，已exit130且log无持有进程，不算成功。最终完整24107已exit0，full-suite-verified.log记录3436passed/68skip（653.58s），.pid记录实际子进程5885。最终安装4个远程绑定修复亦通过，总计73项；198模块字节保持。CI远程job已显式纳入新Redis/PG索引tests。
自有Service已通过stop关闭并确认正常退出；验收已保存，随后仅本地提交。随后继续Temporal Facts绑定／索引生命周期及其他主能力；不因PG子集完成缩小整体目标。

下一阶段定位：temporal_bindings.ROLES当前只有provider/context/knowledge/tool_set/stage_policy，selector被明确拒绝；TemporalActivityRuntime.manifest没有Facts召回注册/证据。后续优先扩展Facts注册／scoped view／原model accepted context receipt，再覆盖原生顺序与高级Agent-node实际History，不添加第三套状态机。agent-bindings旧导读已同步为实际Facade/Temporal子集，避免仍把已交付能力写为尚未实现。

## dev58 当前批次与下一定位

Temporal Facts 绑定、host namespace、纯planner与有界pages沿原 Context History 采纳；源码及安装真实12恢复组合、原服务16、安装94、core与57↔58默认回执通过。
审查3项P2已RED→GREEN并复核，纯Scope/JSON与新证据模块预加载/passthrough覆盖真实sandbox；未知model不重试。
真实Redis/PG16.15 Activity/state scoped read、TTL、stale与物理connection替换探针通过。两项自有Service runner39428/13352已exit0，服务停止标记确认。
初次全量唯一版本一致性失败因pytest收集时载入旧dev57；代码及版本固定后full-suite-final.log记录3417 passed/119 skipped（577.74s），58529 exit0；Ruff/格式/空白通过。
当前目录 /private/tmp/ralf-agent-dev58-7f724wa1；最终提交及全量结果见[dev58验收](../architecture/reviews/2026-10-11-temporal-facts.md)。
下一定位：temporal_bindings已支持facts与其namespace，但knowledge selector仍拒绝；KnowledgeBindingResource.resolve已有Local scoped view。先补Temporal Knowledge原始resource/method/backend固定和独立来源验证、实际History/绑定矩阵，再推进共享Session/续接与其余R01–R26门槛。不把本批次当完整goal完成。


## dev59 当前批次与下一定位

Temporal KnowledgeBindingResource namespace、实际 effective namespace、纯 source evidence 和原生检索资源固定已实现，原 Context History 仍唯一采纳。
两项review P2已复现RED→GREEN并复核；Facts/Knowledge共存、取消最终来源await、来源变化、跨Scope和非法selector/protocol均有测试。
真实源码与安装各12 Worker kill/restart/replay组合通过；真实PG16.15普通/managed Activity/state来源/TTL/版本/连接替换探针通过。
最终：原Temporal28、全量3436/131（467.01s，66357 exit0）、安装63/202模块、core-only/58↔59原回执兼容通过；两项自有Service runner68836/97489 exit0，停止标记确认。验收/文档/构建同步，仅本地提交。当前任务目录 /private/tmp/ralf-agent-dev59-v76202ba。
下一定位：Temporal现在支持Facts/Knowledge的namespace；Session仍明确拒绝shared session_id。需按原Session/Turn契约设计跨Run持久身份/占用/续接，保留原History权威；随后其余role和R15/H4/H5继续。未关闭整个目标。

## dev60 当前批次与下一定位

按原 H2 Session／Turn 契约补齐 Temporal History Conversation、实际 Namespace UUID、耐久串行占用／busy／CAS 与启动恢复；原 Run/Parent 保持业务执行权威。普通／managed 六种编排的真实 Worker kill／replay 及审批／重连分别验收；review 四项 P2 已复现修复，含冷入口预检、冻结声明与普通来源复验取消。
下一定位：Temporal Session 数据目前仅 History，外置 SessionStore 路由／准确保存回执与其他绑定角色继续推进；R15 生命周期／H4 环境／H5 治理和真实语义质量仍未闭环。

最终dev60：全量3466/146（536.83s、47316 exit0），原Temporal27＋最终入口3、安装Session15／契约103、207模块、core-only与59↔60默认Run／Manifest／Artifact／21 starter兼容。四项P2已修复；实际CLI1.9.1/Server1.32.0，最后Service35988 exit0且stopped。任务目录 /private/tmp/ralf-agent-dev60-_vif9k8h；日志与已验证CLI保留。
下一批先完善 Temporal 其余角色的固定选择／受管理采纳，外置 Session 数据需先补资源身份／准确保存与同权威责任；继续 R15/H4/H5 和质量门槛。不以本批提交关闭全能力目标。

## dev61 当前批次与下一定位

Temporal H1f 复用可替换纯 LimitsPolicy，原 Run History 逐节点采纳宿主／AgentSpec 交集；同定义不同节点、普通／managed、图／Team／动态／嵌套保持固定绑定和 caps。实际 Worker 恢复与新旧审批兼容已验证；最终全量及本地提交在[验收记录](../architecture/reviews/2026-10-11-temporal-agent-limits.md)更新。自有 Temporal Service83761正常退出且stopped标记确认，源码和安装恢复都不调用真实模型。

下一定位：Temporal 仍缺每 Agent CompletionVerifier 与纯 DecisionPolicy 替换。优先把现有 CompletionRequest/CompletionVerdict 接到原模型完成、原工具回执和原 History 受管理采纳，区分 retry/reject/accept，先验证再记忆／终态，不添加第三套状态机；随后其余角色、外置 Session 数据和 R15/H4/H5/真实质量。整个 R01–R26 目标继续 active。

最终dev61：全量3492/164（523.45s、56122 exit0），源码实际12恢复+6超限、最终安装18真实Temporal/85契约、209模块、core-only与60→61→60原审批/回执/一次测试工具兼容。宿主入口P2、沙箱异常身份P2与错误码Minor已闭环，自有Service83761 exit0且stopped；只做本地提交。完整能力目标继续active。

## dev62 Temporal 纯完成验证

沿 R01/H1e 复用 CompletionVerifier 与 ToolReceiptVerifier，Worker 提出纯 verdict，原 Run History 固定当前节点原输入与已提交回执并一次采纳。accept 才进入原记忆和完成链路；retry 保留原额度、审批和受保护反馈，reject 明确失败。宿主／每 Agent inherit/ref/disabled 支持原生、顺序、图、Team、动态及嵌套。实际十八项恢复／取消／重放通过；最终交付证据见[验收记录](../architecture/reviews/2026-10-11-temporal-completion-verification.md)。模型验证、DecisionPolicy／外置 Session 和其他环境角色、H3 质量及完整 M1 继续开放。

最终dev62：全量3519 passed/182 skipped（537.24s，8978 exit0），源码实际Temporal18/133.86s、最终安装18/133.40s及163契约；212模块、core-only与61→62→61原审批／回执／一次工具兼容。只读review140通过且无待办P1/P2/Minor；两处控制／反馈P2已RED→GREEN。自有Service25330正常exit0且stopped。未调用真实模型、未重验远端数据库；只本地提交，完整R01–R26目标继续active。

## dev63 Temporal DecisionPolicy

沿 R01/H1 公共纯 Harness 的 prepare/propose，提供宿主默认／每 Agent inherit/ref；固定实际方法、编译器 super 闭包及原 Scope。实际模型请求与原响应/提案证据由原 Run History 一次采纳；不改变审批、Schema、limits、完成规则和记忆责任。Temporal 九类绑定已接通，外置 Session/环境角色、完整 Profile/服务治理和真实质量仍待交付。见[指南](temporal-decision-policy.md)和[验收](../architecture/reviews/2026-10-11-temporal-decision-policy.md)。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。
