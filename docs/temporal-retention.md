# Temporal／PostgreSQL 冗余效果副本清理

`TemporalEngine.compact_effect_evidence` 是显式SDK维护入口，处理一个指定Run的一页
已采纳效果。它复用原执行权威、完整封存树和原`PostgresEffectJournal`，不新建清理服务、
业务命令或调度器。默认Local的独立入口见[工作消息压缩](local-retention.md)。

```python
# engine、runtime 是该Run原发布的SDK Facade与Worker Runtime。
# runtime.journal 必须是已initialize的原PostgresEffectJournal。
cursor = None
while True:
    page = await engine.compact_effect_evidence(
        run_id, runtime=runtime, limit=100, after_effect_key=cursor
    )
    print(page["removed_records"], page["removed_payload_bytes"])
    cursor = page["next_after_effect_key"]
    if cursor is None:
        break
```

## 准入与保留

首期要求所选公有部署、成功终态、原namespace UUID／执行epoch／Scope／发布一致，
并且原整树已经完成效果采纳、实际调用停止和完整封存。`ready`、额度退休或成功状态
单独为真均不足以放行；审批、unknown、活动后代、缺seal以及不匹配组件均拒绝。
维护只读原History，不创建新的seal、grant、退休或Update／Signal。

每个Action沿原target advisory transaction lock重读主效果，要求`state=adopted`、
主result摘要有效，才删除与主行**result原字节、source及对应evidence摘要全部相同**的副本。
主效果result、不同来源／结果、坏摘要、冲突记录、其他Scope／Run全部保留。
原命令、History、Registry、业务库和资源启动／实际停止证明均不删除。
原SDK的begin、observation和重复控制仍重取原回执，不能重新派发已完成业务。

原连接、初始化解析的实际schema、backend身份、Runtime与Scope在await后复核；
改变`search_path`不会把清理切到另一数据集。每次DELETE后、该Action提交前还会向
原Temporal服务重查namespace UUID，RPC等待上限10秒；失败即回滚当前Action。
最后返回前再次检查原namespace与组件身份。旧selected历史仍要求匹配不可变SDK／Worker，
不能把当前维护方法当成历史实验发布迁移器；默认未选择部署及自定义Journal当前拒绝。

## 分页、故障与计量

`limit`必须是1–1000的整数（不接受bool），默认100；`after_effect_key`是可空非空字符串。
按原effect_key排序，满页返回最后扫描位置，可能还需一个空页确认结束。
`scanned_records`包含本页检查后保留的坏摘要等主行，不等于删除量。

**每个Action独立事务，整页不保证原子。** 后续Action校验失败、服务故障、调用取消或
最终检查失败时，前面已提交的Action可能已清理；报错不代表整页零修改。
已提交删除不能因后续namespace变化撤销；当前事务的提交前检查失败会回滚。
跨Temporal与PostgreSQL没有分布式原子事务，维护期间应保持原部署配置固定。
响应丢失后可从原位置安全重试；晚到的相同原ACK可能重建同一副本，再清理仍安全。
不能凭清理数量确认业务完成或释放未解决义务。

返回值另含所选Run／epoch、根Run／epoch及原`seal_digest`，作为本次观察的关联信息。
`removed_payload_bytes`仅计已删除副本result的UTF-8字节，不含source／索引／维护开销，
不等于数据库磁盘缩小。主回执和History仍含原内容；此入口不提供完整Run遗忘、隐私擦除、
TTL归档、VACUUM或全库清理，也不会自动后台运行。

普通Agent与顺序Workflow的实际服务证据见[本批验收](../architecture/reviews/2026-10-18-temporal-effect-retention.md)。
其他既有编排复用原完整树守卫，未新增全拓扑服务验收；安全备份恢复仍归P3-5。
