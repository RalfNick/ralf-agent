# Local 冗余工作消息压缩

`LocalEngine.compact_messages` 是显式SDK维护入口，每次只处理一个指定Run。
它复用原Scope、SQLite Coordinator和命令事务，压缩普通成功Agent的冗余工作消息；
没有后台清理、全库扫描或新增HTTP端点。

```python
receipt = engine.compact_messages(
    run_id,
    command_id="compact-original-run-001",  # 重提必须复用这个身份
)
print(receipt.outcome)
# removed_messages: 本次删除的冗余消息数
# removed_bytes: messages字段规范JSON序列化减少的UTF-8字节数
# state_revision: 原Run维护提交后的版本
```

## 保留内容与准入

当前仅支持原生`SQLiteStore`及其默认持有中的Coordinator、普通`succeeded` Agent，
Session地址须为默认Run地址。跨Scope、显式共享Session、父子／图／Team／动态编排、
Session Turn、自动上下文／记忆等辅助恢复stage、期限／准入标记及未知Run扩展、自定义Store或Coordinator
均明确拒绝，不能用终态、TTL或外部进程退出推断安全。

即使Run显示成功，仍有活动drive、队列调用者、实际handler线程、未结预算或未知效果
也会拒绝。校验与保存位于同一原SQLite事务；原release检查后再次核对Scope、资源与revision，
防止检查期间切换身份／组件后仍执行维护。

只保留`messages`前两条初始系统／用户消息，移除后续工作消息副本。
以下数据全部保留：原输入、最终结果与错误、definition／manifest／release身份、
所有Actions及其模型请求／响应／工具效果／尝试回执、所有原events、commands、budgets、
reservations和其他表。Session／Facts／Knowledge／Artifact数据不清理。
完整执行证据仍可用于原回执重放、核验、排障和恢复。

实际压缩时，原Run增加固定`message_compaction`摘要、`messages_compacted`事件，
并保存`compact_messages`命令回执。原事件序列前缀不删除，已有事件游标仍可续读。
相同command重提返回原回执；换command再次压缩返回零新增删除量。同ID用于另一种
请求仍按原幂等契约冲突。事件／回执提交失败时，消息修改也一并回滚。

## 使用限制

这是工作副本的**逻辑压缩**，不是完整Run遗忘、隐私擦除或完整归档。
原Action请求／响应与Session可能仍保存同一内容；`removed_bytes`不扣除新增维护标记，
也不等于SQLite文件物理减少的字节数。不隐式执行VACUUM、不删除库文件或业务数据库。

未选择的组合需继续保留原数据；不能绕过原权威直接改JSON或按TTL删除events／commands。
Temporal History、PostgreSQL主效果回执及资源证明均不由此入口清理。
所选远程保留由[Temporal／PG独立维护入口](temporal-retention.md)提供，不沿本地消息事务删除。
安全备份恢复与阶段整体验收仍待，见[当前清单](remaining-work.md)。
