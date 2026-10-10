# dev43 推荐数据上下文：实现、恢复与取舍

基线 ec9b5f5 / dev42；日期 2026-10-10。目标是同步能力文档，然后交付一套可替换、
可本地运行的 H3 起步组合；不扩展另一套执行权威，不推送或发布远端。

## 实现

- `recommended_profile` 返回原 RuntimeProfile：Local Basic、Local Knowledge、Managed Memory，版本 `1`。
  工具、Provider、上下文、数据和绑定仍走原工厂／SDK。默认 offline-echo 不代表真实任务质量。
- `ManagedDataContext` 为新增纯策略，继承已有受管理历史摘要协议，原策略 hook 内容和身份保持不变。
  新策略预测产物引用，压缩模型输入；Engine 执行 I/O。原始消息、工具结果与效果证据继续留在 Run。
- 产物意图、派发标记、精确读取回执独立保存于原 Run；只允许未派发、明确不存在的产物写入。
  写后失确认按固定引用读回；无有效回执不能生成业务模型快照。
- Session／Facts／Knowledge 引用为有来源 digest 的确定性摘录，明确不完整；原验证凭据保留。
  模型派发前先核验产物，再完成原 Knowledge／Facts 校验，避免后续 await 绕过事实版本检查。
- 默认 SQLite 产物工厂 owned，SDK 注入 borrowed；自定义 sync/async ArtifactStore 工厂可替换。
  非法配置在创建执行库前拒绝。新增 Local／AgentRun 的离线产物证据观察接口。
- Schema10 仅 opt-in 开启；原默认、旧 Schema1–9 与旧 ManagedContextPipeline 身份保持兼容。

## 独立审查与修复

一次独立只读审查发现三个 Important，无 Critical／Minor。全部经独立复现 RED→GREEN 修复：

1. 初始 async get 返回 NotFound 前收到取消，仍会 put；改为派发事务中再次检查终态／取消。
2. 产物读取置于最后事实校验之后，使版本变化未被发现；调整为原来源校验之前进行产物 I/O。
3. writing 降为 prepared 可误判未派发；增加与意图绑定的独立派发证据及带派发身份的回执校验。

相关测试 197 passed；修正观察测试后相关 60 passed。最终完整回归 **2773 passed／66 skipped**（364.54s），Ruff／格式／Git 空白检查通过；wheel 与当前 165 个 Python 模块内容一致，运行／可选依赖声明不变。跳过项仍需要显式外部服务或模型配置，本轮未调用真实模型。

完整回归还暴露了已有远程绑定观察测试的时序假设：仅观察到 succeeded，就直接认为 Session
已经 idle。失败库中 Run 最终成功；确定性延迟结束清理的复现显示 succeeded／hosting=1／busy
可以同时成立，托管结束后 busy 释放。该测试改为确认成功并等待已有 `settled(runtime)` 再
移除当前绑定目录，与同组已有测试一致；没有修改等待／取消或 Session 占用的生产语义。

## 实际恢复证据

最终 wheel 外部进程使用真实 SQLite，分别在已提交的意图、写入派发／失确认、产物回执和
模型响应窗口 `os._exit(71)`；新进程恢复原 Run，四个窗口业务效果均只发生一次。
已保存模型响应的恢复不要求在线产物存在；没有模型响应时，已派发产物丢失会阻止新披露。

实际 dev42↔dev43 wheel：Schema1 的审批、重复批准与恢复双向成功；已有历史摘要 Schema8
和模型选择记忆 Schema9 的审批恢复也双向成功，各库业务写入一次。dev42 的只读／可写
Store 均拒绝 Schema10。297 个旧公共导出全部保留，新增两个；旧 excerpt/model 上下文身份相同。
最终安装包通过 150 项契约测试，安装后的文档 Agent 示例及 Local Knowledge 的真实 SQLite
摄取／检索／原始来源验证／摘录链路通过。上述脚本均未调用真实模型或网络数据库。
三个推荐组合也分别通过两个持久 Session Turns 和新 Runtime 重启续接的安装后测试。

## 取舍与后续

用户已授权原特性分支连续开发和本地提交，因此省略设计／整合确认菜单。未作合并、推送或发布。
新增组合首期限定原生／顺序 Local，保留旧高级／Temporal 拒绝边界。
模型上下文卸载保留原始执行证据，不能当成执行数据库存储压缩。
复用原摘要日志避免额外状态机，但新增策略必须满足旧完整组覆盖和恢复校验。
引用摘录不保证语义完整；大文件、GC、远程产物适配、语义质量与高级／Temporal 自动阶段仍需后续验收。
这次是 H3 的默认组合与数据投影子集，不标记完整 H3、M1、AgentScope 对等能力或企业验收完成。
