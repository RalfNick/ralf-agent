# Coding Runner 物理容量与 create 恢复契约

本契约补充第二阶段 R12／R13 环境与执行门槛。LocalEngine 与 Temporal History 继续独占 Run／Action 执行权威；资源日志只保存机械证据，不管理预算、审批或结果。第一阶段 dev99 默认业务链路保持冻结。

## 物理容量

首期同一实际 Runner 根目录容量为一。互斥域由固定目录的 canonical path、device、inode 确定；工具别名、任务参数、Scope、模型连接、数据库后端和 Docker socket 的路径别名不能增加容量。根级 flock 与持久原义务一起使用。进程死亡释放操作系统锁，不代表原容器已停止，也不授权新业务。

新任务在原 invocation 内、prepare grant 前等待容量，继续检查原取消、release 和期限；等待期间不增加 attempt，也不重授 prepare／Thread／Turn。等待者取消不清理当前持有者。等待期限仍受原调用有限期限约束；这不是新的跨进程持久任务队列。

原请求的冷控制只能取得 recovery-only claim，核对原 dispatch、Runner identity、generation 和 token 后停止／核验原资源。不能借恢复 claim 再次 prepare 或启动业务。外来请求或陈旧 token 不能释放原义务。

只有以下证据可释放物理槽：

- 原 invocation 确认尚未进入 native intent，且已结束。
- 原执行权威验证过的 exact CID／generation 容器停止、退休、缺席收据。
- 既有窄 namespace_absent 路径：原 History／PG 对应、原 owner 已结束、metadata 未存在、目录只有原 lease，独立 namespace 查询缺席。

原效果或费用不确定与物理容量独立。槽释放不清除未知效果、预算 escrow 或原 History 义务。取消、Future done、Activity timeout、transport close、Worker／CLI PID 消失、租约时间经过均不能单独释放槽。

根、锁、义务文件须校验 owner、mode、link、inode；写入必须有界、atomic rename、fsync。保留带固定锁 inode 的 cleared tombstone，不能让下一次构造忘记锁身份。不得把 root-slot 变成第三套调度状态机。未参与此协议的旧 Worker 不受新锁约束；升级须先排空旧原资源，并隔离部署根，不把新协议当作对旧进程的自动 fence。

## create 一次性意图与原对象恢复

选定环境显式增加 create operation 版本。可能提交 Docker CREATE 前先持久化 submitted 意图；之后即使回复丢失、CID 保存失败或 inventory 为空，也不能重新 CREATE。

CID 缺失时，冷控制只能查询原 exact name／generation／完整固定标签。唯一候选须完整 inspect 校验原配置、身份和完整 CID 后保存原 locator，再沿原 exact-CID stop／rm／absence-confirmed retirement 清理。不得调用 prepare、create、start、Thread 或 Turn。多个候选、外来标签／配置或变化身份失败关闭。

没有候选仍保持 unknown 和原容量义务。一时为空的 inventory 不能证明原 Docker daemon 请求已经结束；查询后可能出现晚到 create。现有 metadata-absent 窄例外不得扩成 `metadata 存在且 CID=null` 的成功停止。

本契约不把原 CLI 被 reap 当作 daemon 完成屏障。可靠的负向 create 完成证明、gated child／supervisor 的 CLI 身份与结束日志仍是后续门槛；未有这些证据时不得标记完整 create 窗口已关闭。

## 所有权与发布

所有 Runner `_active` 安装与清理都核对实际 owner 身份。冷停止经过 await 后重新检查：同一原请求关闭实际 owner，其他请求返回 Busy。旧 finally／cleanup 不清除后来任务的 owner。

新选定 Temporal native publication 为 version 4／binding 18；composition 为 version 5／binding 19。新 Worker 不解释旧选定 16／17 History；它们需要匹配的 immutable dev110 Worker。未选定默认发布字节保持。新增 root-slot、create helper、常量及实际执行方法须纳入显式固定清单；History 只验证纯规则，不能导入物理资源执行作为重放依据。

验收须覆盖不同父 Run、Scope、参数、别名和 Worker 的同根互斥；不同根可并行；等待取消与陈旧释放；进程退出但原义务保留；create 失回执／CID 落盘失败／查询后晚到；仅停止原 CID、无重复启动；原 History／PG 回执一致；安装包与旧发布兼容。接口和单元测试不能代替真实服务证据。
