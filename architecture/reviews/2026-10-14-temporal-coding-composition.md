# Temporal 串行 Coding 图验收记录

本批基于已验收的 dev106，扩展显式选择的串行静态 Agent 图。有限串行图范围已通过本批验收；本文件不表示完整 R13、第二阶段或 R01–R26 已完成。

## 范围与权威

`coding_composition=True` 依赖 `coding_execution=True`，发布 `temporal-3`／binding protocol 12。原父子 Workflow／History 管理调度、审批、结果、预算和终态；原 PostgreSQL EffectJournal 记录资源证据，SDK 提交 owner 管理真实调用排空。没有新增业务状态机。

首期仅支持 `max_concurrency=1` 的静态 Agent 图和一层原子子 Run。支持继承或精确引用 Runner；禁用 Runner 不授予工具权限。直接 Tool、并行、Team／Dynamic、嵌套及图修订继续拒绝。Agent／顺序 Workflow 和省略新选项的旧发布保持既有行为。

原始 namespace UUID、请求、父子链接和 SDK epoch 固定，重启不创建替代子 Run／Thread／Turn。物理停止与财务结算分别采纳；未知效果及整个子级额度继续保留。owned 关闭先排空真实 SDK 提交，再关闭已有提交的准入，最后采纳原后代停止；失败保留原接收器、PG 和账本。

## 审查与集成修复

- 统一入口登记和执行侧的完整请求摘要。
- 用真实 SDK DataConverter 复现并修复子请求和本地发布的 tuple／list 表示差异；规范 JSON 比较仍拒绝 boolean／number 等实质变更。
- 独立审查复现 Registry close Update ID 的生命周期去重问题。新关闭使用新 nonce，同次运行的关闭 Task 保持，重建相同 Profile 不复用旧关闭结果。
- 重放入口支持显式原 namespace，不绕过 Workflow 的身份校验。
- 独立审查确认父图在财务已结算、物理证明尚未采纳时可能提前无限等待。修复后继续观察原子 Run；物理已停止但额度未知时允许休眠，保留额度，避免轮询。确定性调度复现及最终安装服务矩阵已闭环。
- 所选新协议提前检查 SDK 的 `Info.original_execution_run_id` 能力，并在发布／Worker 校验时复查；旧协议不因此更改。未把整个 SDK 版本区间视为实际服务测试范围。

## 验证登记

实际使用 Temporal Python SDK 1.34.0、Temporal server 1.32.0 和 PostgreSQL 16。
没有注入模型密钥或远程服务配置。最终 wheel 在 checkout 外运行以下 11 条路径，
全部通过、零跳过；保存原 root／child Histories，并以实际 namespace 成功重放。

| 实际路径 | 证据范围 |
| --- | --- |
| 串行两 Agent 与精确 Runner 引用 | 两个原资源、正常结果与额度结算、固定原父子 SDK epoch |
| 审批 Worker 替换 | 原子 Run 审批后原执行续接，不新增业务执行 |
| 运行取消 | 原物理停止后父级终态，不启动后续节点，未知子 cap 保留 |
| claim／prepare／Turn grant 后进程崩溃 | 原授权和资源恢复，按窗口验证原生调用计数 |
| 结果回执响应遗失 | 恢复原效果证据，不重复 Thread／Turn |
| 审批期间 owned close | 零原生调用，已有 submission admission 关闭 |
| 原生停止失败后关闭重试 | 原资源和接收器保留，修复依赖后同循环关闭 |
| PG 已 fencing、父级采纳失败 | 包括已 fenced 原资源的完整重扫与停止采纳重试 |

最终安装矩阵为 **11 passed / 328.17s**。原协议 11 的 Agent 与绑定顺序 Workflow
另行实际安装验证 **2 passed / 19.02s**。最后父图等待修复同时通过源码／安装各
84 项定向检查及源码精确绑定图实际服务复验 1 项；不把重叠检查相加。

冻结版本的全量回归覆盖 587 个测试模块：最初 9064 passed／662 skipped，另有
66 failed／42 errors，均涉及沙箱拒绝本机 Unix／TCP socket。对相同冻结测试逐项
授权本机网络复验，106 passed、2 项因未配置真实 PG／Qdrant 跳过，核对后为
**9170 passed／664 配置依赖跳过、无未解决失败**。保留最初失败，不宣称原单次
全量运行无条件全绿。安装后相关检查为 **2290 passed／429 配置依赖跳过**。
这两组较宽回归发生在最后父图等待修复之前；该单产品文件增量使用上述独立定向
检查、真实服务及最终 wheel 的完整 11 条矩阵验证，没有重复不受影响的全量检查。

包与兼容检查：378 产品 Python 模块在源码、最终 wheel 和物理安装中逐字节一致；
374 个旧模块保留，348 个旧模块未修改，新增四个组合模块。dev106 的 117 个原生
执行／PG 方法及函数体保持，三份原生 JSON 资产保持。默认发布、旧协议 11 完整
Coding 协议字节与已验收 dev106 一致。真实旧 dev106 Worker 在注册前拒绝新协议，
未发生业务 I/O；7 份保存的旧 History 在最终源码及安装中均重放通过。SDK／JSON／
TOML 示例解析为相同 Profile 身份；没有宣称三种声明形式均各跑真实服务矩阵。
最终 sdist 另核对源码、文档、测试及夹具内容，不用 wheel 代替 sdist 验证。

最终 wheel SHA-256：
`2d69c626ab3d66ffeedc1d417c250fd4ee0d369140521db8c58ff7262a5ad97f`。
独立审查的关闭去重 P1 和提前等待 P2 已由同一审查者复验；Ruff、格式及 Git
空白检查通过。实际服务仅本机临时部署，收尾后关闭并移除本批自有容器。

这是执行协议验证，不是实际 Coding 模型质量成绩。5 秒叶节点测试配置超时、namespace 重放配置、序列化边界和诊断夹具的失败均保留，未并入成功评分。默认 30 秒原生期限覆盖执行及固定 SDK 校验；Worker 死亡后等待原 Activity 期限，不提前宣布原调用结束。

## 仍开放

真正不确定的 SDK Start RPC 分派、实际 reset／错误 namespace 管理操作矩阵、
重建相同 Profile 的真实 SDK close 去重矩阵尚未分别获得服务证据；现有确定性原
Registry／SDK 去重传输和身份规则测试不能替代这些实际窗口。

真实原生认证和 Coding 任务质量、跨宿主接管、Docker create／CID 遗失的完整恢复、并行／Team／Dynamic／嵌套 Temporal Coding，以及完整 G1–G8／R13／第二阶段仍未关闭。第一阶段 dev99 的四条业务链路保持冻结。

使用方式见 [串行图指南](../../docs/temporal-coding-composition.md)；协议见 [组合契约](../specs/temporal-coding-composition-contract.md)。
