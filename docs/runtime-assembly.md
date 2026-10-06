# 可替换端口与版本化配置装配

dev8 提供公共 ExecutionEngine、知识上下文端口与动态召回规划，并提供 JSON／TOML 配置、显式适配器注册和历史配置解析。默认仍是本地单 Coordinator；这些端口不代表 Graph Workflow、Temporal、多进程或 MCP 已交付。

## 1. 无需修改 Python 的离线开始路径

```sh
ralf init my-config-agent --template config
cd my-config-agent
python -m agent_app --input hello
ralf --config runtime.toml run --spec agent.toml --input question --command-id question-001
```

模板生成运行配置、Agent 声明与可编辑工厂。默认 Provider 是明确标记的 offline-echo，返回输入与版本标签；它验证装配和恢复，没有模型推理、网络或收费调用。

`runtime.toml` 保留 assistant 的 1／2 两个版本。仅修改 `[default]` 的 version 到 2：新命令使用 config-v2，之前提交的 Run 仍使用 config-v1。相同 command_id 和请求始终找回原回执，不把原 Run 升级。

```sh
python -m agent_app --input pending --command-id pending-001 --submit-only
ralf --config runtime.toml resume RUN_ID
```

将 RUN_ID 替换为实际提交结果。跨工作目录时使用同一绝对数据库和配置路径。配置中的相对资源路径以配置文件目录解析；数据库路径在 router 构造时固定。SDK 注入自定义 builder 时，由 builder 的 base_dir 决定相对资源路径。

## 2. 配置形状与版本

```toml
schema_version = 1
[default]
name = "assistant"
version = "1"

[[profiles]]
name = "assistant"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.providers.default.config]
label = "example"
[profiles.components.recall_policy]
adapter = "bounded-recall"
[profiles.components.recall_policy.config]
max_pages = 1
```

JSON 使用同样的 schema_version/default/profiles 结构。Profile 只包含 name、version、providers、components；每个组件只包含 adapter 和可选 config。配置是有限 JSON；重复 JSON 键、未知字段和未注册适配器被拒绝。配置文件上限 1 MB，不执行 Python、不动态导入插件，也不使用 eval。

`RuntimeProfile` 保存独立配置快照，读取 providers/components 返回副本。`RuntimeCatalog.register` 不允许相同 name/version 对应不同内容；`set_default` 只改变新任务选择。原 Run 保存 profile 身份摘要，`resolve` 必须精确匹配。应保留原声明、原适配器代码版本与原数据；Catalog 不归档 Python 代码、外部服务或数据库，也不自动迁移它们。

## 3. 默认组件与显式扩展

| 配置位置 | 内置 adapter | 说明 |
| --- | --- | --- |
| providers.ALIAS | offline-echo / chat-completions | 离线回显；单次 Chat Completions |
| components.tools | empty | 无工具；自己的 Python 工具通过注册工厂提供 |
| components.context_assembler | default | ContextAssembler，当前不接受配置参数 |
| components.harness | native | NativeHarness |
| components.tool_executor | python | PythonToolExecutor，使用已构造的工具注册表 |
| components.session_store / memory_store | sqlite / in-memory | 默认省略时共享执行库；显式 sqlite 可指定 path |
| components.recall_policy | bounded-recall | facts/session 的 RecallQuery 与 max_pages |
| components.recall_planner | fixed | FixedRecallPlanner，接收相同查询配置 |
| components.knowledge | sqlite-lexical | SQLite 知识库与词法 Retriever；默认路径为执行库 + .knowledge.sqlite |

未声明的原生组件使用既有默认实现。in-memory 是临时数据，不能当成重启后可恢复的记忆；默认随机后端身份会在重建时拒绝旧 Run，不建议用于版本切换。知识声明创建存储和检索器，不自动导入文档；摄入与向量配置见 [RAG 教程](recall-and-rag.md)。

```python
from ralf_agent import ComponentRegistry, RuntimeBuilder

registry = ComponentRegistry()


def my_provider_factory(config, context):
    # my_provider 是应用按其生命周期管理的 ModelProvider。
    return my_provider


registry.register("provider", "my-model-v1", my_provider_factory)
builder = RuntimeBuilder(registry)
# 在 Profile 的 providers 中声明 adapter="my-model-v1"。
```

工厂签名为 `(config: dict, context: BuildContext) -> component`，必须同步完成构造；组件本身可以提供异步模型／记忆方法。context 提供固定 db_path、scope、store、base_dir，以及先构造的 tools。应用注册的 factory 可以捕获 SDK 客户端、工具实现和自定义检索器，配置文件只选择已经注册的标识。

各 adapter 的返回对象仍需满足原端口契约和真实 identity/backend_id；配置摘要不能替代组件的版本、Scope、CAS、去重和恢复语义。Redis、PostgreSQL、托管向量库需要自写适配器，目前没有现成实现。

## 4. 模型凭据

Chat adapter 接收 model、base_url、max_output_tokens、token_parameter、timeout 和 api_key_env。api_key_env 默认 OPENAI_API_KEY；指定其他变量后，不回退到默认变量。密钥只在构造时从环境取得，不进入 Profile 或 Run Manifest。内嵌 api_key 等未知字段在构造前拒绝。

自定义工厂也应使用环境或应用的凭据服务；配置声明属于需要保留的非秘密数据。SDK 无法识别自定义任意字段是否含秘密，不能把秘密塞进自定义 config。接入真实 Provider 后可能产生收费调用；本轮验证只使用离线 Provider。

## 5. 历史恢复与生命周期

`ProfiledEngine(catalog, db_path, builder=..., scope=..., reader=...)` 实现公共执行契约。submit 的只读回执查找先于新默认装配；drive／approve／cancel／reconcile 根据原 Run 的 profile 选择原组件。缺少或改写旧版本返回 DefinitionMismatch，观察仍能进行。未保存 profile 的历史 Run 必须显式提供原 legacy_factory，不能自动套用当前配置。原有不带 --config 的 Local SDK／CLI 行为仍保留。

当前 router 一次保留一个本地执行实例。切换版本时先关闭空闲旧实例；正在 drive、真实工具或记忆线程尚未结束时拒绝切换，旧所有者保留租约。它不修改正在执行对象，不实现热切换、队列、多 worker 或分布式调度。

`BuildContext.own(resource)` 只接管显式声明的同步 close 资源，去重后逆序清理；close 必须返回 None。RuntimeInstance 先关闭引擎，成功后才关闭附属资源。附属关闭失败时实例已停止，只允许重试 close；已完成清理的资源不再关闭。构造或清理失败的 RuntimeBuildError 提供 cleanup 句柄，可在故障解除后重试 `.cleanup.close()`；未返回的工厂内部资源仍由工厂自己负责。

async close 客户端需要应用在自己的异步生命周期中管理，不能直接传给 own。服务仍应停止新请求，完成／取消自己的 Task，等待 `wait_for_threads`，再关闭 runtime。自定义执行后端须实现同样的执行归属和关闭语义。

## 6. 扩展知识上下文与召回规划

`KnowledgeContextPort` 包含 identity、limit、max_chars、async references/validate。可以直接实现它，不必继承 KnowledgeContext。引用必须是有限 JSON 记录，来源有效性由 validate 明确检查；SDK 保留额度、固定发布、最终有效期与原快照重试检查。默认 Facade 的来源协议见 RAG 教程。

`RecallPlanner.plan(scope, namespace, session_id, text) -> MemoryRecallPolicy` 是同步纯策略，可按 Agent／输入选择查询。不能执行 I/O 或状态提交。每个新模型 Action 只规划一次，实际查询保存在 context_manifest；未知恢复不重新规划，不替换原查询或原引用。recall_policy 与 recall_planner 互斥，MemoryRecallPolicy 仍是配置 DTO。

## 7. 执行与诊断端口

ExecutionEngine 定义 submit、async drive、status/events、approve/cancel/reconcile、async wait_for_threads 和同步 close。CLI --factory 按方法契约接受代理或自定义实现，不要求继承 LocalEngine，也不要求暴露 .store。

可选 RuntimeDiagnostics.diagnostics 返回 RunDiagnostics(snapshot, manifest, release_digest, budget)，用于丰富文本报告；没有时输出普通结果。CLI status/inspect/events 仍是默认 Scope 的只读 SQLite 观察，不通过自定义工厂执行远程读取。SDK 可通过 RunReader 接入自己的读端口；当前只交付 SQLiteRunReader 默认实现。

## 8. 兼容与剩余工作

dev8 保留 local-4、执行 Schema v1、默认 Manifest 与调用方摘要。只有显式启用 planner/profile 才增加对应身份。默认 dev7 Run 可用原 Local 工厂续跑。已接受的 Profile 不能被原地修改，也不能用新版本替换恢复。

默认 SQLiteRunReader 在激活运行实例前查询 submit／approve／cancel／reconcile 原回执，按可信 Scope 和完整调用参数校验。重放不会关闭正在执行的新版本，也不要求旧 profile 仍可装配；参数变化仍报 idempotency_conflict。自定义 RunReader 可实现 CommandReceiptReader 获得控制回执的独立读取；仅实现基础端口时，控制请求交给原实例处理。diagnostics 是可选能力，缺失时 CLI 仍输出普通结果。

Workflow 仍是固定顺序 AgentSpec。图节点、分支、并行、子 Run、多 Agent、模型流式／能力协商、MCP／CLI 沙箱、企业身份与 Temporal 仍未交付。公共端口支持扩展方向，实际后端必须另做契约验证。
