# Temporal 原生／顺序外置保存与持久 Turn 验收

状态：dev66 原生／顺序子集最终验收通过；仅本地提交，不推送。
基线：fd506b2 / dev65。完整 R01–R26 目标继续 active。

本批落实[原计划](../../docs/superpowers/plans/2026-10-11-temporal-session-writes.md)
的原生／顺序范围，保持[完整规格](../specs/temporal-session-data-contract.md)全部后续门槛。
原 Run History 采纳保存意图、派发许可、收到的精确回执、独立采纳及成功；
Session Coordinator 只持有原 Turn／占用／成功 Conversation 投影。
CAS 数据存储和真实处理器跟踪不调度业务，不形成第三套执行权威。

## 已观察的行为

- 明确 `session_writes=True`；默认关闭不改变既有只读／History-only 请求。
- 真实数据集 UUID 与实际 Temporal Namespace UUID 构成会话资源身份；Root 跨 Turn 地址保持。
- 每步骤原子预留写额度，原 message_id／CAS／完整消息保持；模型、工具不因保存恢复重新调用。
- 收到精确回执与采纳为独立阶段。回执存在和真实 handler 结束分别核验。
- 取消／观察取消／整个事件循环取消后，实际线程或未送达结束通知仍由 ExecutionOwner 持有。
- 普通／managed Context 保护外置来源及独立 History 投影，外置会话只注入一次。
- 原生／顺序两 Turn、同资源／namespace 限制、idle no-migration、连接与方法固定及 metadata 替换拒绝。

## 独立审查及修复

唯一 fresh-context 只读 reviewer：`/root/dev66_session_save_review`。无实现委派、无第二轮审查。
四项 P2 均有独立复现及 RED→GREEN：

1. 取消后实际停止且明确未写入的保存，结算原额度并关闭原阶段，不重派写。
2. 首次 inspection 暂时失败，恢复原 inspect；发生过写尝试后才使用 verify。
3. 旧已结算尝试的原结束通知按原身份一次确认，不修改新的尝试或未知状态。
4. Worker 在回执返回前限制完整 inspection／message；原 History 采纳再次限制。

补充自查的两项 RED：写 Activity 超时且从未获得原 History 派发许可。
原 Action 被 held 后永久拒绝迟到许可；核验原基点未写后，取消只结算，活跃 Run 才重试原意图。
未派发尝试不收费，不借此重跑模型。修复后相关84项通过（5.79s）；最终大范围验收另列。

## 验收快照及证据边界

实现任务1：25 passed / 1.62s。实现任务2：65 passed / 188.18s，包含真实服务。
此前真实 SQLite/Temporal Worker 矩阵12项覆盖 native/sequence × 普通/managed × 写前、
真实提交后 ACK 丢失、回执接收未采纳；独立进程 kill/wait 后重启，检查实际模型／append次数、
原 ID／地址及 History 重放。实际取消中的线程测试1项检查 busy／关闭拒绝／迟到结算。
真实 Redis/PostgreSQL 连续 Turn、丢 ACK 与精确核验8项，数据集身份4项。

审查前全量3680 passed/226 configured skips（507.15s）；审查前安装144相关契约、25真实服务
（187.92s）；221源码／wheel／sdist／wheel-env／core模块与 METADATA 一致。
fresh core-only 能完成离线索引、原只读协议和 SQLite 持久原生 Turn；optional SDK 不存在。
实际 dev65→66→65→66 默认发布／Run／Artifact／21 starter／typed receipt／Local Session
审批单次工具，以及实际 Temporal 审批／原 History／新协议旧 Worker 接受前拒绝通过。
这些是审查前证据，不能代替修复后最终快照；最终结果待以下门槛真正完成再填写。

## 保持开放的原目标

Graph／并行／Team／Plan／DAG／嵌套的外置根和稳定成员私有保存尚未交付，选中来源继续拒绝。
完整 Profile／starter／默认推荐装配、跨权威租约、迁移／FIFO／保留／企业身份、长期容量治理未完成。
自有服务按最终结果关闭。未调用真实模型；真实模型质量、外部首用和完整 H1/H2/H3/M1 保持开放。

Reviewer 未独立运行最终 full/install；作者负责检查实际最终命令及输出。其余 set-aside
均保留在完整目标中，不因本增量标为完成。没有独立 actionable Minor。


## 最终快照

修复后最终全量 **3686 passed / 226 configured skips**（519.28s，51084 exit0），相关84（5.79s）。
源码最终任务组合 **65 passed**（189.57s，12582 exit0），安装契约 **150 passed**（8.41s，74128 exit0），
安装真实服务 **25 passed**（192.92s，3535 exit0）；均非以跳过代替实际数据库／Worker运行。
安装指南直接使用真实Client，结果succeeded并保存外置记录（44412 exit0）。
fresh core-only索引／原只读／持久原生保存三个场景通过（51499 exit0）。
实际65↔66默认发布／typed数据／Local审批／Temporal History兼容已通过；上述修复只改变新保存协议。

最终产品Python221模块一致性／文档sdist打包以及Ruff／格式／Git空白在本地提交前复核。
自有PostgreSQL32779和Temporal89036均已正常 exit0、stopped，未遗留本批Worker。最终制品结果追加后才提交。
原生SQLite实际Worker kill/wait是同宿主证明，远端数据库的lostACK组合不代表远端Worker杀死／
所有网络故障窗口都已验收。内存不是持久分布式默认；高级完整六组验收仍开放。

## 审查中保留的判定

- 高级根／成员保存明确拒绝并继续开发；代价是这些组合暂不能选择外置会话。
- 跨权威租约／迁移／保留／FIFO留在完整目标；代价是独立权威共享数据不能当成共享会话租约。
- 继续可信宿主的原namespace／实际结束证据契约；代价是尚无企业身份体系约束宿主凭据。
- 未执行真实模型质量／完整M1或外部采用；代价是不能据此声称AgentScope质量／生产对齐。
- Reviewer未独立重跑最终验收，由作者检查真实输出；代价是验证独立性弱于另一个执行者重跑。

四项P2已修复，无待办独立Minor；这些判定不删减完整R01–R26目标。
