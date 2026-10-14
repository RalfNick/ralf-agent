# Coding Runner 容量与 create 恢复

Dev111 在原 Local／Temporal Coding 执行链路增加根级容量保护。相同实际 `runner_root` 容量为一，工具名、Scope、任务参数、模型连接和数据库配置不能拆出额外槽位；不同根仍可并行。个人应用可沿用现有 [Coding 声明](local-coding-delegation.md)与[模型连接](codex-model-connection.md)，无需新增调度服务。

任务已获批但资源忙时，原 invocation 在 prepare grant 前等待，并检查取消、发布身份及期限。等待者取消不会停止当前持有者。该等待受 Runner 原有限期限约束；不提供跨重启持久队列，也不保证公平调度。根级容量释放要求原资源实际退休、原 transport／worker 排空和原停止收据采纳。未知费用与业务效果继续按原协议处理。

根目录保留 `.coding-capacity.lock`、`.coding-capacity.json` 和 Action 子目录。它们是机械租约与原义务证据；不要删文件、改权限、移动根目录或靠 PID 死亡清空义务。已有锁却缺失义务记录会失败关闭。若升级旧选定 Worker，应先排空其原资源，并使用明确隔离的部署根；未参与新协议的旧 Worker 不受新容量锁约束。

新 Runner 使用明确版本的 create operation metadata。Docker CREATE 回复丢失或 CID 落盘失败后，冷恢复只查询并验证原对象：找回唯一原 CID，保存 locator，停止和移除它，再独立确认缺席。不会再次 CREATE／START，也不会重授 Thread／Turn。SDK 与工厂仍通过原 Run 的控制／恢复入口执行这些操作；不能绕开原审批与原执行权威直接恢复业务。

Dev112 增加原 CREATE 的机械监督器：持久化固定操作声明后，broker 和 CLI gate 分别登记原进程，再各接收一次执行许可。原 Worker 退出时，broker 继续持有原处理器及 namespace／operation 租约；冷恢复只能 query／abort／drain 原操作。进程结束观察发生在 reap 之前，输出 EOF 不代替实际退出。监督器不负责 Run、审批或业务调度。

若原 CLI gate 从未接收许可、未 exec，且不可重开，原 helper 已实际结束、控制处理器排空，并且原 namespace 查询成功确认没有容器，可以采纳专用 `create_not_dispatched` 证明。它保留原 prepare grant、attempt、未知效果和费用；不能用来重新执行。原 Local／Temporal 采纳及实际关闭成功后才释放容量。

如果可能已经 exec 而没有原 CID，义务继续保持未知。Docker inventory 为空、超时、CLI 被 reap 或原 Worker 退出，都不能证明 Docker daemon 不会稍后完成 create。已发送请求的负向完成屏障与跨宿主恢复仍未提供，不能把所有 create 故障都视为自动可恢复。

普通独立 `DockerCodingEnvironment` 默认 identity 与 metadata 保持旧形状；其监督机制需显式 `retire_on_stop=True, create_recovery=True, create_supervision=True` 及固定 generation。受管理 Coding Runner 默认组合自动选用该契约。声明固定完整 helper 源码及执行文件身份，实际导入别名被替换时拒绝执行，不能在旧 grant 下移动实现。选定 Temporal 发布为 native version 5／binding 20，composition version 6／binding 21；旧选定 18／19 History 使用 immutable dev111 Worker，16／17 使用 immutable dev110 Worker；旧 Local Coding Run 也须使用其原固定配置与匹配实现。未选定默认发布保持原字节。

支持边界、测试层次与实际服务证据见[监督验收](../architecture/reviews/2026-10-14-coding-create-supervision.md)及[容量验收](../architecture/reviews/2026-10-14-coding-root-capacity.md)，权威与释放规则见[监督契约](../architecture/specs/coding-create-supervision-contract.md)与[容量契约](../architecture/specs/coding-root-capacity-contract.md)。本能力不代表通用 Coding 质量、恰好一次外部效果或完整 R13／第二阶段已验收。
