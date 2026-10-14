# 第二阶段支持矩阵与收口门槛

本矩阵按修订后的阶段目标固定环境与执行范围。阶段收口版本为 dev113；所选递归组合、安装、完整回归与兼容门槛已通过，随本地提交冻结。R01–R26 仍是长期路线图。dev99 四条参考业务链路已冻结；不为新增后端组合重复打开第一阶段。

## 所选组合

| 维度 | 第二阶段所选范围 | 明确不支持／后续范围 |
| --- | --- | --- |
| 宿主与部署 | Python 3.12、macOS ARM POSIX 宿主、本机 Docker Desktop、单受管理 Runner 根；Temporal 与 PostgreSQL 在可信本地服务环境验证。SDK 其他Python版本的CI范围单独记录 | 本批不承诺跨宿主接管、Windows进程生命周期、Kubernetes部署或实际Linux宿主停止验收 |
| Local | Agent、顺序 Workflow、Agent／Tool静态图、有限并行、Team、Dynamic及既有嵌套成员；原 LocalEngine 权威 | 通用数据流 Workflow、无限递归、自主无限任务及其他执行权威 |
| Temporal | Agent、顺序 Workflow、静态Agent图、有限并行、Team／Dynamic；dev113所选Team／Dynamic成员为Agent、sequence、静态Agent图、Team、Dynamic，受原execution policy限深／限量 | 静态图直接Tool／transform节点、复合GraphNode、通用流式图。声明不支持的组合必须在业务I/O前拒绝；不作为本阶段阻塞 |
| Runner | 显式Codex Coding Runner／固定Responses连接，SDK／JSON／TOML、每Agent精确引用与禁用。保留工作区、容器隔离、原Action审批与停止门槛 | 其他Coding Runner、任意shell工具发现、跨宿主共享工作根、企业凭证代理 |
| 数据 | 默认memory／SQLite；已验收Redis／PostgreSQL Session与Facts、PostgreSQL Knowledge、Qdrant＋PostgreSQL Hybrid RAG。沿原绑定和namespace替换 | PostgreSQL Facts catalog＋Qdrant全库联合索引、远程自动维护／Temporal索引维护、pgvector／其他向量库、远端Artifact与GC |
| 消息 | Redis Streams＋PG Inbox／Outbox；A2A polling＋原Temporal／PG交接，原command去重和未知交接效果保留 | 其他Broker、A2A SSE／push、跨企业身份联合及通用Agent消息平台 |
| 模型与质量 | 复用dev99四参考链路冻结证据；Coding采用dev109固定DeepSeek／Codex连接的三个有限POSIX任务、三次重复。机械恢复和Responses直连兼容另外计量 | 新模型／语言、复杂Coding任务、框架对等比较和独立采用；原质量证据不扩大到未知场景 |

嵌套和顺序成员纳入本轮范围，是补齐已在dev112门槛中列明的Local／Temporal公共组合差异，不增加新的图DTO或执行后端。远程Facts联合索引等安全拒绝／未选择能力继续留在R15–R20，不自动加入本阶段。

## 必需门槛与当前证据

| 门槛 | 当前状态与权威证据 |
| --- | --- |
| 公共入口／配置／绑定／默认应用 | 有限Local SDK与声明、Temporal SDK／JSON／TOML、registered-tool／disabled、owned／borrowed已验收；见[coding-profiles](coding-profiles.md)、[模型连接](codex-model-connection.md)与对应dev104–110记录。dev113所选递归声明、有效绑定及源码／安装六场景通过 |
| 精确效果、预算与原处理器结束 | 原Action／History独占grant和采纳；PG存证据。原效果回执、结算、物理停止分别检查；dev111同根容量、dev112CREATE监督与严格未发送证明已验收，见[资源恢复](coding-resource-recovery.md) |
| 所选故障恢复 | Local及Temporal原审批重启、重复控制请求、运行取消、owned关闭／失败重试、原CID正向恢复及未派发证明已有分层证据。dev113源码／安装各六场景通过，共36份原History replay、24条原边证明，真实进程与原资源关闭分别核对 |
| 数据／消息组合 | Redis／PG Session/Facts见dev89；PG Knowledge＋Qdrant RAG见dev19；Redis Streams／PG与A2A polling／Temporal交接见dev16。它们不证明未选择的Facts全库远程索引已通过；当前源码保留相应实际测试 |
| 兼容／安装 | 默认未选择发布字节及原接口保持；显式实验协议通过版本门槛演进。旧selected20／21使用immutable dev112 Worker；dev113独立安装214项、395产品字节一致；原dev112实际冷恢复、当前拒绝旧发布及三份新默认／原执行协议兼容通过。不修改原History或把旧协议改标为新协议 |
| 模型质量 | dev109三个有限任务9/9及78个独立oracle检查，仅原固定配置；dev112直接Responses文本／SSE／auto工具通过，强制函数选择失败保留。不把structural peer或恢复测试计为模型质量 |
| 文档／异常处置 | 必须让使用者从原Run诊断、原资源证据识别pending／unknown，并按原配置恢复或保守人工处置；不能清ledger、TTL偷占或危险重试。dev113恢复指南、固定旧Worker及失败运行原数据保留已复核；阶段验收见[dev113登记](../architecture/reviews/2026-10-14-temporal-coding-nested.md) |

阶段关闭记录须核对上述门槛的完整源码回归、安装、约定兼容与必要实际服务证据；已冻结且无受影响变化的有效证据可引用复用，不按dev数量或测试数量计算完成率。当前全部所选必需门槛已关闭：最终10234 passed／704配置依赖跳过，634模块覆盖且源码／测试全程未变；源码／安装各六个实际Temporal／PG场景通过，自建服务实际退出。第二阶段随本地提交冻结并转入第三阶段；完整R01–R26、框架级备份恢复和独立采用仍未完成。

## 未知效果与停止不是“失败后重试”

可能已exec但没有可靠daemon终态回复的CREATE仍保留unknown及原容量义务。没有完整原CID时，空inventory、CLI退出、PID死亡不作为未创建证明。阶段支持该保守结果和诊断／原控制恢复，不承诺所有故障自动恢复；完整daemon负向完成屏障作为后续能力，不通过删除义务或再CREATE提升完成率。

先用原Engine的`diagnostics(run_id)`／`status(run_id)`读取原Action与pending状态；保留原manifest、dispatch、generation、操作声明、回执及`CloseIncomplete.report`。恢复使用匹配的原Worker／配置，控制原broker与原容器，成功采纳停止证明后才释放。若缺少正向CID或严格未派发证明，停止继续提交同工作根的新任务，保留证据交由宿主运维核验Docker daemon；没有受支持的完成证明时继续保留义务，可改用明确隔离的新部署根进行新业务。移动／删除原根、手工清租约或将旧业务当作新任务重发都不属于受支持处置。

企业级恢复管理、管理员授权清理、远程运维与统一身份是第三阶段／后续清单；当前SDK的可信Scope和本地恢复指南不替代企业治理。
