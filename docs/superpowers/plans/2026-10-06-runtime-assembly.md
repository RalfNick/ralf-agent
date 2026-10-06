# 可替换执行端口与版本化装配实现计划

> 本轮在当前工作区按 executing-plans 逐项执行，采用测试先行和单人实现。交付前按 requesting-code-review 的明确要求，委派一次独立只读复核；复核者仅新增故障复现，不修改实现。

**Goal:** 默认组件能通过配置直接装配，用户能实现公共端口，并在默认配置升级后恢复旧任务的原版本。

**Architecture:** Engine/Knowledge 接口与具体类分离；RecallPlanner 是纯查询策略。RuntimeProfile/Catalog 固定声明，Registry/Builder 构造明确组件，ProfiledEngine 根据已接受 Run 身份选择原配置。

**Tech Stack:** Python 3.11+ 标准库 JSON/TOML、现有 asyncio/SQLite，无新增运行依赖。

**Spec:** [运行装配设计](../specs/2026-10-06-runtime-assembly-design.md)。

## Global Constraints

- dev8；默认 local-4、ExecutionStore v1、原调用方请求摘要与默认 Manifest 不变。
- 配置不允许动态 import/eval 或内嵌默认 Provider 密钥；只通过显式注册适配器。
- 配置版本不可覆盖；原 Run 缺失 profile 不能回退新默认。
- 资源先完成执行归属退出再关闭；原生默认与自定义端口都必须运行。
- CLI 观察仍是默认 Scope 的只读 SQLite；公共执行端口不宣称 Temporal 或远程 Read API 已交付。

## Review Focus

- 配置/DTO 被调用者修改，默认别名移动，原已接受版本不能改变。
- 参数形状错误、重复 JSON 键、秘密字段、非法 adapter 在外部调用前拒绝。
- planner/knowledge 真实 await 中身份变化；未知模型恢复沿用原快照及查询。
- 组件构造/附属资源关闭失败、活动线程/任务阻止换版本，不泄漏/提前释放执行权。
- CLI 不要求 .store 或继承 LocalEngine；缺少可选诊断仍可 JSON/text 输出。

## Task 1: 公共扩展端口

**Files:** ports.py/types.py、engine.py、recall.py、retrieval.py、cli.py/cli_views.py；tests/test_runtime_ports.py。

**Interfaces:** ExecutionEngine、RuntimeDiagnostics/RunDiagnostics、KnowledgeContextPort、RecallPlanner/FixedRecallPlanner；LocalEngine(recall_planner=None,runtime_profile=None)。

- [x] RED：非继承知识与 CLI Engine；纯 planner 按任务规划、未知重试不再规划；不合法组件/配置、诊断与默认 Manifest。
- [x] GREEN：结构化校验与默认实现、公共诊断 DTO、CLI 端口、optional Manifest 身份。
- [x] 定向验证既有 CLI、知识恢复和默认组件行为。

## Task 2: 配置与组件装配

**Files:** runtime_config.py/runtime_builder.py；tests/test_runtime_config.py/tests/test_runtime_builder.py。

**Interfaces:** RuntimeProfile(name,version,providers,components={})、RuntimeCatalog.register/set_default/resolve；load_catalog(path)；ComponentRegistry.register(kind,name,factory)；RuntimeBuilder.build(profile,db_path,scope=Scope()) -> RuntimeInstance。

- [x] RED：JSON/TOML、不可变版本/副本、显式适配器、非法配置与密钥；默认离线实际执行、知识库与自定义组件装配、失败清理。
- [x] GREEN：严格声明及加载、内置适配器、资源所有权与关闭重试。
- [x] 定向真实 SQLite/CAS/恢复验证。

## Task 3: 历史配置解析与开箱路径

**Files:** runtime_router.py、cli.py/starter.py；tests/test_runtime_router.py；独立配置示例和教程。

**Interfaces:** SQLiteRunReader.status/events/profile_identity；ProfiledEngine(catalog,builder,db_path,scope=Scope(),reader=None,legacy_factory=None)。CLI --config/--factory 互斥，run --spec --input --command-id。

- [x] RED：新默认 v2 与旧 v1 共存、原回执、缺失/改写版本、跨进程恢复、活动任务/线程阻止切换、legacy 默认拒绝。
- [x] GREEN：按保存身份解析、固定数据库路径、端口 CLI 与 JSON/TOML 独立运行。
- [x] 更新公开 API、支持清单、兼容/生命周期/未交付能力。

## Task 4: 验证与交付

- [x] 全套 pytest -q -W error；Ruff lint/format、Git 空白检查、文档链接和片段。
- [x] 自审真实边界，保留新增故障回归；不以 Protocol 存在宣称后端已交付。
- [x] 仓库外 wheel，实际 dev7 默认 Run 兼容、配置 v1/v2 恢复及资源故障；核对制品与版本，恢复 editable。
- [x] 本地提交与实际结果记录。

验证为 macOS／Python 3.12.7，完整测试 645 passed；独立复核 25 项回归和既有 47 项定向测试通过。实际 dev7 → dev8 安装恢复保持原回执／Manifest 并只写一次；安装包配置历史、原审批版本、缺失 profile 与关闭失败重试均有实际证据。完整结果与未交付门槛见 [实现进度](../../implementation-progress.md) 和 [Review](../../../architecture/reviews/2026-10-06-runtime-assembly.md)。本轮只做本地保存，没有远程发布。
