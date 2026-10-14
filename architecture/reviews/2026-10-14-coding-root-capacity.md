# Dev111：原 Coding 资源容量与 create 恢复验收

日期：2026-10-14。范围为第二阶段 R12／R13 的同物理根容量、原 CID 正向冷控制恢复与所有权安全。第一阶段 dev99 冻结不变；完整 R13、第二阶段和 R01–R26 不因本子集关闭。

## 交付

- 同实际 Runner 根容量一：根级 flock＋持久原义务，Scope、工具别名、参数、模型连接和 journal 配置不拆槽。原 invocation 在 prepare grant 前等待；同对象和不同对象均覆盖。取消等待者不清理持有者；不重授 attempt／prepare／Thread／Turn。
- OS owner 退出只释放锁，不释放原义务。原 recovery claim 只控制；release 严格匹配原 token、dispatch、Runner、generation 和实际停止证据。明确未准入控制的 foreign root obligation 仅观察，不修改。
- 选定 create operation 先 fsync submitted，再可能 CREATE。回复丢失／CID 持久化失败只能找回唯一原 CID、完整验证、持久化再退休；空查询保留未知义务，不再次 CREATE／START。普通环境默认 identity／metadata shape 保持。
- 冷 stop 在 await 后重新核对实际 owner；同原请求关闭真实 owner，其他请求 Busy。所有旧 finally／cleanup 仅清自己仍持有的引用。
- Local base 与 Connected、选定 Temporal 固定容量、环境、实例方法、库存 entry 和 typed policy。拒绝 JSON 同值却改变格式化行为的 builtin subclass；拒绝缓存旧指纹伪装新 helper。
- 新选定 native v4／binding18、composition v5／binding19；旧选定16／17使用 immutable dev110 Worker。未选定默认发布字节保持。

契约见[物理容量与 create 恢复](../specs/coding-root-capacity-contract.md)，接入与升级边界见[指南](../../docs/coding-resource-recovery.md)。

## 验证与证据范围

| 门槛 | 最终结果 | 说明 |
| --- | --- | --- |
| 完整源码回归 | **9924 passed／694 skipped** | 五个风险分组覆盖618个测试模块、10618个用例，五组exit0，完整期间产品／测试快照未变。wheel-building fixtures单组串行；完整脚本先执行native组，独立安装服务验收并行运行，不宣称整个机器静默 |
| 安装包 focused | **256 passed** | checkout外安装、无src Python，容量／环境／owner race／selected pins等正式契约 |
| 原 Local 业务容量 | 源码3／安装3通过 | 两Engine／Scope／别名／任务、同对象／独立journals、等待取消；第二CREATE必须观察首容器已退休且真实attached peer已退出，原Action/attempt保持 |
| 真实 Docker create 恢复 | 源码2／安装2通过 | 实际CREATE完成后控制丢回复或CID fsync失败；原Worker已实际退出，冷恢复每例CREATE1／START0／RM1，只退休原CID并验证缺席 |
| 真实 Temporal＋PG | 源码8／安装8通过 | Agent、Team、动态DAG：审批冷重启／运行取消各2，加Team／DAG owned关闭2；原SDK epoch、grant、PG／History与停止回执及重放通过。native stdio peer为结构化替身，未调用真实模型 |
| 旧版本边界 | immutable dev110原17恢复1通过 | 新代码拒绝实际原17及伪装18／19；原历史不由新Worker重新解释 |
| 包一致性 | **387产品模块＋3资产**一致 | 源码／最终wheel／安装逐字节核对；wheel SHA `76d59218e735516932a503f3c2f111d97ebd28c2b04655be7cab7d0aea8bb3ba` |
| 未选定默认 | 源码／安装保持 | 五份固定发布fixture SHA `35004369d4aa8b8b85cc45f59f00fa3f6ee83be8061c20fbf053b99446d03349` |
| 工程与清理 | Ruff／格式／Git空白通过 | 自有PG容器、匿名卷、Temporal／PG／metrics三个端口和17个socket均确认退出；实际Docker恢复容器及原Worker单独清理，用户Docker daemon保留 |

完整回归未注入模型密钥或服务环境；694项配置依赖跳过不等于已交付。实际服务由独立有限场景验收。源服务与安装服务各14条原History的选定implementation字段已逐一核对最终源码，均一致；额外模型调用、真实质量或独立采用没有在本批重验。

私有本地证据位于 `/private/tmp/ralf-agent-dev111-root`、`ralf-agent-dev111-review` 与独立 `ralf-agent-dev111-environment-{source,installed}-*`：保留分组日志／快照、wheel provenance、各原History／PG结果、actual CID／进程退出／清理证据和mutation复现。基础设施密码仅在私有临时测试配置，用户模型密钥未进入源码或这些测试。

旧版本driver实际测试为1 passed，后续提取artifact因误取`runtime_manifest`而exit1；保留原错误，再从同一成功原History的`manifest`字段提取并验证17／18／19拒绝，未重跑服务来覆盖原记录。首轮接口集成、版本fixture和测试fixture失败也保留，最终冻结后完整与安装验收均通过。

## 审查

正式与独立复现关闭 owner覆盖／旧cleanup清后来owner、Local transitive helper绕过、slot实例替换、缓存旧库存以及同JSON值的typed常量漂移。最终独立只读审查在冻结选定范围内未发现剩余具体 P1／P2；独立16＋143＋8项focused检查通过，包括物理root alias、slot实例替换、完整库存、默认字节和既有RED复验。审查者未把根作者服务／安装／全量计为自身执行；不以测试数量代替恢复契约检查。

## 剩余门槛

- 未获得可靠负向 create 完成证明。空 inventory、CLI reap 或Worker死亡不能释放可能晚到的create；CLI gated supervisor／daemon结束屏障未交付。
- 初始根锁已存在却durable记录缺失保守失败关闭；尚无自动修复或管理员恢复协议。
- 当前是有限原 invocation 等待，不提供持久队列、公平性或跨宿主容量。未参与新锁协议的旧Worker不受锁约束，升级必须排空并隔离根。
- Temporal嵌套／sequence成员Coding、跨宿主恢复、企业凭证代理、其他Runner、复杂真实Coding质量与多模型／语言质量仍开放。
- 物理槽释放不清除未知效果、费用或原预算义务；不保证任意外部业务恰好执行一次。本批没有新增AgentScope对等质量或企业正式生产可用结论。
