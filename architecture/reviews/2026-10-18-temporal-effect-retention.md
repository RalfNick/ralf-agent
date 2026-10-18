# P3-4：原封存树下的 PostgreSQL 冗余效果副本清理

本批落实原冻结P3-4的完成数据安全保留入口，复用Local／Temporal执行权威，
没有新后端、拓扑、Runner或治理平台。只本地提交，不推送。

## 产品边界

新增`TemporalEngine.compact_effect_evidence`，先沿原Scope授权status、Describe epoch、
`_proof`、只读`_ancestry`和`_tree(seal=False)`核验既有完整根seal，再调用原PG事务。
终态、ready和Registry退休不能代替效果采纳、实际handler停止与整树封存。
原`PostgresEffectJournal.initialize`固定两个既有表的实际schema，不新增表或必需端口。
未初始化、split schema、替换连接／Runtime／发布、旧selected或自定义Journal均安全拒绝。

每个Action沿原target advisory lock重读主行，只删除adopted主回执的精确重复evidence，
主行零修改。坏摘要、非规范原字节、其他来源／结果、外Scope／Run与未采纳效果保留。
原begin／observation／晚到重复ACK仍回读主回执，已完成业务不重新派发。
分页最多1000主行；返回payload字节不等于物理缩库或业务回执。

独立review发现一个P2：SQL等待期间的最终检查只核对namespace名称，没有重查UUID。
原完整seal fixture中实际复现`DID NOT RAISE`，随后补框架内异步复核：每次实际DELETE后、
当前Action事务提交前向原服务重查UUID，10秒上限，失败回滚；返回前再查一次。
有效RED日志`/private/tmp/p3-retention-namespace-red-20261018.log`；修复后边界15项通过。
真实PG异步故障、真实Temporal SDK namespace读取与实际DELETE组合的回滚也已验证。
未进行第二轮冗余review或新增协议／业务权威。

每Action独立原子，整页可能部分提交；后续错误不意味着零修改，已提交前缀不能回滚。
此处没有跨Temporal／PG原子事务，维护期必须固定部署配置；原主效果始终保留，可安全重试。
完整限制和SDK用法见[使用指南](../../docs/temporal-retention.md)。

## 最终制品与验证

最终wheel：`dist/p3-temporal-retention-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `1f8efacb14afffb187e6fe71a64ab73e4b1f688267637e124d90e1210f026e06`。
版本号保持dev120，必须按此哈希区分原冻结制品；原制品没有改写。
442产品（439 Python＋3 JSON）在源码／wheel／隔离安装逐字一致，925 Python测试输入固定。

| 检查 | 实际结果与出处 |
| --- | --- |
| 源码受影响12模块 | **234 passed／22配置skipped，零失败／错误**；`/private/tmp/p3-retention-final-source-20261018.xml`，JUnit 3.464秒 |
| 隔离wheel相同12模块 | **234 passed／22配置skipped，零失败／错误**；`/private/tmp/ralf-p34-retention-final-install-20261018/installed.xml`，JUnit 4.027秒；包含既有52项资源授权交集 |
| 同一最终wheel真实服务 | **24 passed／零失败、错误、跳过**；`/private/tmp/ralf-p34-retention-final-service-20261018/current-service.xml`，JUnit 38.162秒：真实PG20、Temporal清理2、远程HTTP身份／审计2 |
| 默认约定兼容 | 普通默认Card／完整发布材料SHA256仍为`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`；原／continued默认History均离线重放，无新模型或服务调用 |
| 产品与证据固定 | 安装目录`all-products.json`／`all-products-verification.json`／`verification.json`、服务目录`products.json`／`inputs.json`、结果及关闭记录；没有将凭据纳入提交或校验输出 |

22项skip是所列普通适配器／Runner Journal的其他服务配置输入，按原范围保留未运行，
不与已显式配置并运行的PG20项混为通过。没有重跑全suite或真实模型质量评测。

原始RED和首轮证据另存：旧440产品wheel在真实PG的缺维护方法失败；修复前源码真实
PG／Temporal／HTTP **23 passed**，目录`/private/tmp/ralf-p34-retention-source-service-20261018/`。
它们属于此前产品，不充当最终wheel同次全绿；原失败与修改前已知4项输入夹具失败保留。

## 实际场景与生命周期

真实PG20项涵盖精确副本／UTF-8计量、所有保护记录、分页、两个独立连接的原target锁、
search_path漂移、实际DELETE后的同步／异步复核回滚与晚到ACK重建／安全重试。
无SQL状态模拟器。合成Journal schema不包含实际Workflow或业务义务，仅作事务测试。

实际普通Agent和两步顺序Workflow沿原审批运行；顺序两次均实际写业务库后丢响应，
人工核验后原History采纳。审批／unknown期间清理被拒绝且PG逐字不变。
完成后等待原整树实际结束、原seal和根额度0，分页清理1／2份冗余副本。
实际DELETE后注入namespace UUID不一致，原服务真实读取仍执行，事务回滚且证据逐字保留。
正常清理后主效果与原History逐字不变；全新SDK facade重取原submit／approve／reconcile回执，
重复清理为零，每effect业务calls保持1，原History再次重放、原Owner关闭通过。

同包远程双身份两场景重跑，保留原七类跨Scope拒绝、宿主重启、消息／控制回执、
审计脱敏与一次写入断言；没有以清理接口新增HTTP业务端点。
测试使用哈希固定真实Temporal CLI、普通持久dev server（无time-skipping）、新自有PG16容器。
成功场景先有原证明再关闭／删自有schema，剩余schema为空；Temporal关闭、PG停止并只移除
本次成功容器。旧失败容器、卷和数据库不动，Docker Desktop继续运行；无真实模型调用。

## P3-4门槛核对与后续

| 原门槛 | 有效证据／结论 |
| --- | --- |
| 可信宿主调用者→Scope、资源交集 | 复用原认证callback／Scope路由和能力绑定；本批安装包含52项原资源交集，无新权限系统 |
| 越权控制与事件读取拒绝 | 原Local源码／安装真实HTTP与所选Temporal双有效身份七类拒绝；Temporal本批同包实际2项复验 |
| 可替换脱敏审计 | 固定DTO／域隔离HMAC／有界默认sink及宿主替换已交付；本批重启关联复验，依旧是best-effort，非耐久合规审计 |
| 完成数据清理与活动／效果／幂等／恢复保护 | Local原SQLite事务工作消息压缩按原440产品证据；本批PG原完整seal与严格副本删除、故障回滚、冷SDK原回执、一次写入均通过 |

**P3-4冻结最小范围据此收口。** 这里只验收上述有限入口和所选路径，不要求完整Run删除、
任意旧selected迁移或全拓扑清理；未选Local复杂组合继续拒绝，PG其他编排仅复用原树守卫，
不伪称新增实际全矩阵。企业完整身份、强制耐久审计、跨宿主和通用数据治理仍属长期清单。

P3-2/S2原360秒失败与其他原门槛继续后置／开放，不能用600秒诊断替代。
P3-5框架备份恢复与P3-A整体交付尚未完成，按原依赖等待推进，不自动解锁；
基础SDK／dev99／dev113保持冻结，不将本批结论外推第三阶段／M1／R01–R26全部完成。
