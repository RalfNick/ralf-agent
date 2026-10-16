# P3-3 既有 HTTP 入口的持久事件分页

日期：2026-10-16。用户明确批准“允许独立推进 P3-3，保留全部验收门槛”。开发顺序调整已写入[冻结矩阵](../../docs/phase3-support-matrix.md)；不改变 P3-2／S2 的原 360 秒失败、未执行矩阵、原 Worker 恢复责任及后续阶段要求。

## 本批交付

- 原 A2A JSON-RPC 入口显式选择 `enable_run_events=True`，广告扩展 `urn:ralf:a2a:run-events:v1`，提供 `tasks/events`；默认关闭，原标准 streaming 仍为 false。
- `A2AClient.get_events(task_id, cursor=..., limit=...)` 读取原 `EventEnvelope`，核对 Task、连续序列、完整 envelope 与末游标。不改变已有 `A2AClientPort` 必需方法。
- 复用 TaskControlBridge 的原 Scope、模式和方法绑定检查，通过 RunEventSubscription 读取原 Engine。HTTP 没有另一个执行权威、数据库、生产者队列或业务取消责任。
- 每页有限记录及字节；响应超过字节限额时只返回可装入的前缀，其末游标只指向已返回事件。单条过大拒绝，不静默丢弃。游标按已消费事件保存，重读允许重复。

使用入口与边界见[指南](../../docs/http-events.md)。原基础制品保持不可变；本批本地候选放在 `dist/p3-events-20261016/`，包版本未因内部增量另行递增，制品通过独立目录及 SHA 区分。

## 验证

1. 首次新增测试为 10 failed：缺少 `enable_run_events` 入口，确认后才实现。补充拒绝／字节测试时曾有 17 passed／1 failed：600字符×3尚未触发4096字节响应边界，改用1200字符，使测试真正命中前缀返回；没有据此修改产品限额或放宽预期。
2. 源码七个受影响非socket模块 **101 passed**；真实 loopback HTTP模块另一次 **3 passed**，均零失败／错误／跳过。覆盖原A2A兼容、控制、服务生命周期与订阅，以及新HTTP分页、重读、SQLite权威关闭／重开、游标越权／坏请求、非法远端结果、await后漂移、ASGI请求取消与响应字节边界。
3. 独立wheel在仓库外安装，复制必要测试：新接口 **18 passed**、真实HTTP另一次 **3 passed**，均零失败／错误／跳过。426产品源码／wheel／安装目录逐字节一致；运行前后产品和复制测试无漂移，导入路径无checkout。依赖复用已有本机安装，无下载。
4. 原基础包与候选在独立解释器中运行同一无调用脚本，默认Agent Card和普通空工具Temporal发布声明完整相同。仅证明该默认对照，不扩称全部历史、所有模板或选中Coding协议兼容。
5. 独立只读代码及文档审查无阻塞；修正指南中4,000,000字节的单位精度。受影响Ruff、格式及Git空白检查通过。未重复整个阶段回归，未调用真实模型／Temporal／PG。

三项真实HTTP包括原提交去重／取消、满Inbox控制和新游标重连；新用例在Inbox容量1时关闭首个client，再连接读取，确认原业务仍running，显式取消并结束原Provider后读取至`run_cancelled`，序列无缺口。该证据不证明socket关闭瞬间服务器立即中止挂起backend Query；ASGI请求Task取消的私有读清理由独立单测覆盖。

第一次网络验证调用因自动权限审查超时而未启动；工具允许的窄范围单次重试成功。这不是产品失败或服务超时。源码与安装的HTTP验证分开登记，不合并宣称一次阶段全绿。

本批证据目录：`/private/tmp/ralf-agent-p3-events-20261016/`，包括产品／复制测试哈希、安装隔离信息、18项安装XML／日志、3项安装HTTP XML与默认对照结果；制品目录含 `verification.json` 和 `SHA256SUMS`。wheel SHA256：`bc0119351cb3c218b273fef1cffb0b2903f2630021e7de9b2ed50d5bf4f14ea2`。

## 尚未关闭

阶段门槛关闭数为0；P3-3尚缺原业务审批、核验／恢复的hosted控制链路、执行权威累计命令容量耗尽后的必要控制入口，以及所选Local／Temporal安装服务整体验证。HTTP分页不是新增SSE订阅服务，也不代表企业身份权限、保留或框架恢复交付。

下一批沿同一入口完善审批与恢复控制，优先复用原SDK幂等命令及host wakeup，预计一个开发／受影响验证批次；累计命令容量与最终服务验收分别按实际发现和原门槛推进，不预估完整阶段工期。只本地提交，不推送。
