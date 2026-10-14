# Coding Runner 容量与 create 恢复

Dev111 在原 Local／Temporal Coding 执行链路增加根级容量保护。相同实际 `runner_root` 容量为一，工具名、Scope、任务参数、模型连接和数据库配置不能拆出额外槽位；不同根仍可并行。个人应用可沿用现有 [Coding 声明](local-coding-delegation.md)与[模型连接](codex-model-connection.md)，无需新增调度服务。

任务已获批但资源忙时，原 invocation 在 prepare grant 前等待，并检查取消、发布身份及期限。等待者取消不会停止当前持有者。该等待受 Runner 原有限期限约束；不提供跨重启持久队列，也不保证公平调度。根级容量释放要求原资源实际退休、原 transport／worker 排空和原停止收据采纳。未知费用与业务效果继续按原协议处理。

根目录保留 `.coding-capacity.lock`、`.coding-capacity.json` 和 Action 子目录。它们是机械租约与原义务证据；不要删文件、改权限、移动根目录或靠 PID 死亡清空义务。已有锁却缺失义务记录会失败关闭。若升级旧选定 Worker，应先排空其原资源，并使用明确隔离的部署根；未参与新协议的旧 Worker 不受新容量锁约束。

新 Runner 使用明确版本的 create operation metadata。Docker CREATE 回复丢失或 CID 落盘失败后，冷恢复只查询并验证原对象：找回唯一原 CID，保存 locator，停止和移除它，再独立确认缺席。不会再次 CREATE／START，也不会重授 Thread／Turn。SDK 与工厂仍通过原 Run 的控制／恢复入口执行这些操作；不能绕开原审批与原执行权威直接恢复业务。

如果没有候选，原义务继续保持未知。Docker inventory 为空、超时、CLI 被 reap 或原 Worker 退出，都不能证明 Docker daemon 不会稍后完成 create。本批未提供负向 create 完成屏障、CLI 监督器或跨宿主恢复；因此不能把所有 create 故障都视为自动可恢复。

普通独立 `DockerCodingEnvironment` 默认 identity 与 metadata 保持旧形状；其新机制需显式 `retire_on_stop=True, create_recovery=True`。受管理 Coding Runner 默认组合自动选用该契约。选定 Temporal 发布为 native version 4／binding 18，composition version 5／binding 19；旧选定 16／17 History 使用 immutable dev110 Worker；旧 Local Coding Run 也须使用其原固定配置与匹配实现。未选定默认发布保持原字节。

支持边界、测试层次与实际服务证据见[本批验收](../architecture/reviews/2026-10-14-coding-root-capacity.md)，权威与释放规则见[契约](../architecture/specs/coding-root-capacity-contract.md)。本能力不代表通用 Coding 质量、恰好一次外部效果或完整 R13／第二阶段已验收。
