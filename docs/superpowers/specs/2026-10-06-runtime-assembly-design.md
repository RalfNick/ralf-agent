# 可替换执行端口与版本化运行配置

目的：让使用者通过公共契约接入自己的执行器、知识上下文和召回策略，通过配置装配默认组件，并在配置升级后找到旧任务的原配置。延续 dev7 本地可靠性，不扩展为分布式调度或图 Workflow。

## 接口与兼容

- ExecutionEngine 定义 submit、async drive、status/events、approve/cancel/reconcile、async wait_for_threads 和 close。CLI 工厂按方法契约校验，使用 close 管理生命周期，不要求 LocalEngine 继承关系。可选 RuntimeDiagnostics 返回 RunDiagnostics(snapshot, manifest, release_digest, budget)，用于丰富文本诊断；缺少时仍能执行和输出普通结果。默认 SQLite 只读观察保持原行为。
- KnowledgeContextPort 定义 identity、limit、max_chars、async references/validate。默认 KnowledgeContext 不变；知识流程可直接实现端口，不必继承 Facade。原引用协议与派发校验继续生效。
- MemoryRecallPolicy 保持配置 DTO；新增纯同步 RecallPlanner.plan(scope, namespace, session_id, text) -> MemoryRecallPolicy。固定策略与 planner 互斥。每个新模型 Action 规划一次并保存实际查询配置，未知恢复不重新规划。
- LocalEngine 可选 runtime_profile 身份；仅启用配置装配时增加 Manifest 字段。无新配置的 dev7 Manifest、local-4、调用方摘要及执行 Schema v1 保持不变。

## 配置与装配

- RuntimeProfile 含 name/version/providers/components，全部非秘密有限 JSON，以独立快照固定配置；identity 含 kind/name/version/digest。组件声明为 adapter/config。
- RuntimeCatalog 保存不可替换的 name/version 配置，显式选择默认版本；同版本不同内容拒绝。resolve 要求身份摘要精确相符。
- JSON/TOML 配置 schema_version=1；不 eval、不动态 import 工厂。未知键、重复键、非有限 JSON、未知 adapter 和未保留版本明确拒绝。引用凭据使用环境变量名称，不把实际密钥写入 Run。
- ComponentRegistry 显式注册 kind/name/factory(config, BuildContext)。RuntimeBuilder 默认装配 SQLite/LocalEngine、空工具注册表、原生 Harness/Executor/Context；内置 offline-echo、chat-completions、bounded-recall 和 SQLite 词法知识适配器。用户 Python 工厂只通过显式注册接入。
- BuildContext 明确管理被工厂声明 own 的资源。RuntimeInstance 先关闭执行引擎，成功后关闭附属资源；失败保留待重试资源，活动调用不能因换配置释放 Coordinator。

## 历史解析

ProfiledEngine 根据原 Run Manifest.runtime_profile 选择 RuntimeCatalog 中对应版本，再用 RuntimeBuilder 构造原配置。当前默认只控制新提交。观察不依赖旧配置存在；继续缺失配置明确报 DefinitionMismatch，不尝试当前默认。

本地 router 同时保留一个执行实例：旧实例有活动任务/真实线程时切换被拒绝；空闲时先安全关闭旧实例再构造新实例。它不是多 worker 调度器，不修改正在执行对象的组件。无 profile 的历史 Run 只能使用显式 legacy_factory，不能偷偷套用当前配置。

## 验收

真实非继承组件、CLI JSON/text、默认 Manifest 兼容、版本升级后原回执和原响应、跨进程 catalog 恢复、缺失/改写版本拒绝、取消期间线程所有权、构造/关闭失败的资源管理均要有行为证据。默认配置模板可脱离仓库运行。真实收费模型、Graph/并行 Workflow、MCP/沙箱和 Temporal 仍按后续阶段验收。
