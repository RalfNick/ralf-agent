# dev88 完整已采纳模型历史验收

基线 `c8696e8`，当前实施对应 [规格](../../docs/superpowers/specs/2026-10-13-complete-model-history-design.md) 与 [计划](../../docs/superpowers/plans/2026-10-13-complete-model-history.md)。状态：本批子集验收通过；本地提交以 Git 记录为准，不推送远端。

## 实现与范围

新增纯 ModelHistoryPolicy 和默认 CompleteModelHistory，原 Local 与 Temporal History 保存完整已采纳 assistant/工具/反馈。Local local6、Temporal joint7 和 model_history_protocol1 是显式门槛；旧默认和 dev87 续接仍使用原行为。SDK/Registry/Local 与 Temporal Profile 支持同步/异步装配和自定义纯策略。

本次是一次 Agent 执行的完整历史，包含已采纳无工具最终响应与验证重试，不提供跨 Session Turn 的 native transcript，也不交付 DeepSeek thinking/Responses reasoning 的新适配器。Agent 切换沿原独立交互及固定成员发布，不串用另一个模型 owner。

## 审查与修复证据

唯一独立审查报告：`/private/tmp/ralf-agent-dev88-icnl2ig4/review.md`，5 Important、0 Critical、0 Minor；原107测试通过未覆盖这些缺口。

- 绑定 Agent/sequence 的顶层 Manifest 缺门槛，retry 重复 normalized assistant：改用原步骤门槛；两有效 RED。
- 普通 Provider 原参数被 Action 默认值改写：新模式保存原 Harness 提案参数，真实默认只作用 Action；Local/Temporal RED。
- Temporal 工具轮有限 JSON 输出丢失：工具轮与最终轮共同保存 raw/canonical 映射；有效 RED。
- Local 同实现方法换到另一实例未被固定：同时固定真实方法绑定与可执行指纹；有效 RED。
- DataContext 在 opaque 检查前生成 excerpt：所有原 references 在替换策略/投影前做公共检查；Local 默认/custom 两 RED、Temporal两 RED。

实际 Worker 在原 final/验证后、下轮 Context/Plan 未获派发许可前退出，最初真实探针失败。新 joint7 仅 SDK TimeoutError 的已封锁、未获许可 READ 可重建一次；已授予、第二次未知、业务错误和旧1–6保持失败/原行为。纯测试与实际 Worker 窗口证明边界，不重试模型或摘要未知调用。

旧完成验证探针还有过期 override 签名，不接原 dispatch_guard/on_end；实际 dev87 与 dev88 均复现同一 TypeError。测试夹具转发原参数后18实际场景通过；没有为修复夹具改变旧产品协议。初始失败日志完整保留。

## 验证证据

证据目录 `/private/tmp/ralf-agent-dev88-icnl2ig4`。

- 实际新 Temporal 八项：8 passed/63.18s，receipt/verified × native/graph × ordinary/managed READ；原 JSON/签名、原 request_digest、两次模型/结算、采纳去重、Worker kill/wait、恢复正常关闭与所有 root/child History replay。
- 三个真实 Local 进程在事务提交后 os._exit(77)，新进程恢复；raw final/签名、retry 原 assistant 一次、两次模型/结算及重复控制无新增效果。
- 独立核心安装：368 passed、8 skipped（15.76s）。八项跳过需要未安装的 Temporal SDK；核心安装没有 Temporal/Redis/PostgreSQL 等可选依赖。
- 实际 Temporal 最终源码 35 passed（266.66s）、独立安装 35 passed（283.38s），均无跳过。包含本批八项、既有续接八项、完成验证十八项及自定义上下文一项。SDK 版本字符串修复在这组验证之后，没有改变行为；最终安装包产品字节另行核对。
- 旧87默认身份/声明相同；同一普通/local5审批 Run 在旧87→source88→旧87原回执及完整快照相同，最终安装88也读取相同快照和预算。观察重新 drive 会增加既有 revision，比较使用原 query 口径，不删字段。
- 旧87 Local 拒绝新 local6 发布，模型文件不存在；旧87 Temporal 纯 Manifest 校验器拒绝 joint7。本项不是实际旧 Worker 恢复证据。
- 构建后的 301 个产品 Python 模块在源码、wheel、sdist 与独立安装中逐字节相同，1151 个声明的源码/文档/例子/测试/评测文件进入 sdist。最终文档完成后重新构建并复核；构建产物日志不等于公开发布。
- 自有 Temporal 服务 PID20829 已 SIGTERM，原 session68646 返回 TEMPORAL_STOPPED、exit0，已等待实际退出。
- 初次全回归：6020 passed、463 skipped、1 failed（716.92s），失败为 SDK __version__ 未同步包声明。修正版本后原测试及相关配置十一项通过（5.68s）；最终重新运行全回归：6021 passed、463 skipped（897.57s）、exit0。初次失败单独保留，不计为通过。

MockTransport/离线 HTTP 仅证明协议与运行契约，不代表真实模型质量。实际 Redis/PostgreSQL/Qdrant、本批模型质量、对等框架评测及独立开发者采用均不据此验收。完整 H3、M1 和 R01–R26 仍 active。

静态验收：Ruff 检查、800文件格式检查、Git 空白、相对文档链接和新增文件凭据扫描通过。最终产品冻结302文件；没有付费模型请求或远端推送。
