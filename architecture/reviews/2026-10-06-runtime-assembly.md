# 公共端口与版本化装配 Review

日期：2026-10-06；基线：`f0a5283`／dev7；修订：dev8／local-4。

## 本轮交付

ExecutionEngine 提供公共控制和关闭契约，CLI 不要求继承 LocalEngine 或访问 .store；RuntimeDiagnostics 是可选丰富观察端口。KnowledgeContextPort 支持应用直接实现知识流程，RecallPlanner 是同步纯规划接口，MemoryRecallPolicy 保持配置 DTO。原模型 Action 的实际计划、引用和请求快照固定，未知恢复不重新规划。

RuntimeProfile 保存不可变有限 JSON 声明，RuntimeCatalog 按精确身份解析原版本。ComponentRegistry 显式注册同步组件工厂，RuntimeBuilder 装配默认或应用组件，RuntimeInstance 管理明确声明的附属资源。JSON/TOML 不动态 import/eval。ProfiledEngine 只保留一个本地实例；默认版本影响新提交，旧 Run 按原 profile 恢复。独立 config 模板和 --config／run --spec 路径可从 wheel 使用。

## 独立复核与修复

独立 reviewer 初次确认以下四项 P2；[故障回归](../../tests/test_runtime_review.py)从 4 failed／1 passed 扩充为 25 passed，全部使用 -W error。修复后复核未发现新的实证 P1/P2；既有定向测试另有 47 项通过。

1. **无 close 的无效 Engine 值阻断清理。** 工厂返回 object() 时，原 cleanup 将它当作资源所有者，无法关闭 store／附属客户端。现在仅 close-capable 返回值拥有执行清理权；其他无效值由 builder 关闭其创建的 authority 和资源。真实 Engine close 失败仍保留句柄，不能越过它释放执行权。
2. **无效 router runtime 的关闭失败丢失句柄。** 原代码在保留 runtime 前尝试关闭，临时异常后 router.close 误报成功，真实租约仍占用。现在先保存 cleanup owner；失败进入 close_failed，拒绝其他操作，router.close 可重试直到真实关闭完成。
3. **重复控制回执触发多余的配置切换。** 新版本正在 drive 时，重放旧 cancel 会尝试关闭活动实例。默认 SQLiteRunReader 现在通过可选 CommandReceiptReader 先查全部控制回执，保持与原内核相同的 Scope 和完整 payload 摘要。approve／cancel／reconcile 的重放不需要原 profile 装配，不改变旧 Run／事件／预算；改参数冲突，跨 workspace／principal 拒绝。
4. **缺少可选诊断导致成功任务的文本输出失败。** 原 router 总是暴露 diagnostics，而基础 Reader 不要求实现它。现在仅在 Reader 提供同步方法时暴露此能力；缺失时 JSON 和 text 均可输出成功结果，真实诊断错误仍正常传播。

Root 还通过实际 RED→GREEN 修复了不完整 close 返回 False 被视作完成、异步 callable 工厂未等待、无效 CLI 工厂租约泄漏、执行 authority 构造错误未脱敏及 CoordinatorBusy 类型被覆盖。实际线程尚活跃时，版本切换仍拒绝，不关闭客户端或交出租约；线程结束并 drain 后才切换。

## 兼容与制品证据

默认 local-4、ExecutionStore／SQLite Schema v1、调用方 submit 摘要与 dev7 Manifest 保留。profile／planner 只在显式启用时增加身份。实际安装 dev7 wheel 创建待批 Run，再安装 dev8：原 handle／receipt／Manifest 完全一致，重复批准、恢复和提交只产生一次业务写入。

仓库外的 dev8 wheel config 模板在新进程恢复原 config-v1，并将新任务交给 config-v2；自定义业务 Registry 同时保存原 Provider／工具版本，重复审批只产生一个效果。移除旧 profile 后原审批回执仍可读取，续跑返回 definition_mismatch。安装包的失败 close 保留实际租约与客户端，修复后重试清理一次。完整集成、制品和文档检查见 [实现进度](../../docs/implementation-progress.md)。

## 能力边界

Catalog 不归档代码、外部服务或数据，不做热监听、运行迁移或 Worker 版本调度。原声明、适配器实现、后端数据及真实 identity 都必须保留。基础自定义 RunReader 未实现 CommandReceiptReader 时，控制请求仍交给原实例处理；CLI status／inspect／events 仍为默认 Scope 的只读 SQLite，远程 Read API 未交付。

BuildContext.own 只管理同步 close 且返回 None 的显式资源；异步客户端和工厂内部未声明资源由应用负责。自定义 Engine、记忆及 executor 内部的后台工作仍需遵守实际完成／资源归属契约。配置摘要不能代替后端 Scope、CAS、去重和恢复行为。

Workflow 仍是固定顺序步骤。Graph／并行、多 Agent、MCP／CLI 沙箱、模型流式及能力协商、Redis／PostgreSQL／托管向量现成适配、容量／保留／迁移及 Temporal 均未交付。完整 M1 的成组故障报告、真实模型质量与外部采用仍待验收；本轮不能据此声明达到 AgentScope 的完整应用能力。
