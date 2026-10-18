# P3-4：默认 Local 冗余工作消息压缩

在用户授权的原P3-4范围内，交付一个可实际使用的默认SQLite清理切片；
完整P3-4及Temporal／PG保留仍未完成，S2原失败和所有门槛保持。

## 实现

`LocalEngine.compact_messages(run_id, command_id=...)`复用原Scope、持有中的默认
SQLite Coordinator、原`Store.command`事务和revision CAS。每次只处理一个普通成功Agent，
保留前两条初始消息，压缩冗余工作消息尾部；没有自动调度、批量扫描或新HTTP入口。
原输入、最终结果、全部Actions／请求响应／效果回执、events、commands、credits及其他表均保留。
维护标记、追加事件及命令回执原子提交；同command返回原回执，新command再次压缩为零。

首期拒绝活动／真实线程未结束、reserved／unknown义务、共享Session地址、父子编排、
辅助恢复或未知结构、自定义Store／Coordinator。该窄切片不等于所有完成数据的遗忘，
不清Session／Facts／Knowledge／Artifact、Temporal History或PG主效果，
也不保证物理文件缩小或隐私擦除。[使用指南](../../docs/local-retention.md)明确全部边界。

## 验证

最终制品：`dist/p3-local-retention-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `068b90130f25dd9a7a3ada5ec7e55d2c5f3cae6831231a938f6eb3622c149111`。
440产品文件在源码／wheel／安装间一致，920个Python测试副本前后相同；清单位于
`/private/tmp/ralf-p3-local-retention-install-20261018/`。

| 检查 | 原始结果 |
| --- | --- |
| 源码受影响11模块 | **245 passed／零失败、错误、跳过**，JUnit 16.767秒，`/private/tmp/p3-local-retention-source-final-20261018.xml` |
| 隔离wheel相同11模块 | **245 passed／零失败、错误、跳过**，JUnit 14.621秒，安装目录`installed.xml` |
| 审批写入与冷恢复 | 真实一次Python写入后压缩；Actions逐字保留，重复提交／审批／压缩回执不变，重开Engine后模型／工具零重执行 |
| 原子失败窗口 | `save_run`后、维护事件提交前故障，所有原表与命令逐字回滚，关闭重开原库后仍完整，可用同command重做 |
| 未知效果 | 原业务写入后响应丢失，Run为waiting_reconciliation、Action效果未知；压缩拒绝，原数据不变、业务只写一次 |
| 物理线程 | 原Tracker中注册真实阻塞线程，取消其await等待者后仍拒绝压缩；库不变，线程实际结束后同command才可压缩 |
| 身份与所有权 | 检查期间切换Scope的RED已复现；最终在release检查后重新授权，事务不写入。已释放Coordinator、外Scope、未知结构／预算同样拒绝 |
| 旧已安装SDK读回 | 上批439文件wheel（无compact API）打开相同压缩原库，原submit／approve／terminal drive成功，模型／工具0次；`/private/tmp/p3-local-retention-old-reader-20261018.json` |
| 默认声明兼容 | 源码／安装Card及完整普通Temporal发布材料与原验收SHA256 `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`相同；`p3-local-retention-default-compat-20261018.json` |

独立review未发现本窄产品入口的P1/P2，建议的真实线程测试已补。
作者另复现Scope检查期间漂移会错误采纳（1 RED），单行改为再次`_authorized`后，
对应测试及最终245项全部通过，不删除原release校验。

初轮测试错误使用pending的`target_digest`字段，修正为原`digest`后，缺方法的有效RED为11失败；
后续真实未知写用例误将Run断言为outcome_unknown（实际为waiting_reconciliation）造成1失败／207通过，
已修正；原日志保留在`/private/tmp/p3-local-retention-*20261018.log`。
一次检查路径误写不存在的coordinator模块而未运行测试，也保留，不计入验收。

受影响Ruff、格式和Git空白检查通过。无真实模型、Temporal／PG服务调用；
上批审计的100项／2跳过及6项HTTP按其原439文件制品保留，不拼成本440文件同次服务全绿。

## 下一步

原冻结P3-4还缺所选远程身份／审计与完成数据保留证据。
PG主效果result承载原观察／恢复，禁止清空；只考虑原完成封存和固定数据集下可证明重复的副本，
不从测试schema删除搬出通用purger。P3-2/S2继续后置，P3-5／A不自动解锁。
仅本地提交，不推送远端。
