# H3 语义知识、相关召回与 Plan／Team 组合

Plan／Team 可显式选择[父任务完成政策](parent-completion.md)：纯业务回执规则先检查原证据，可追加独立受管理模型阶段。安装包内库存参考组合提供真实工具、合法停止和模型替换；原通用推荐版本1／2不自动注入库存业务真值。整批验收状态仍以能力清单和验收记录为准。

dev89跨Session原生模型历史子集已验收。已有H3组合可显式接入同一个 `model_history` 策略的session模式，原业务/Planner/成员历史各自独立，知识/记忆召回始终使用当前任务。完整原生历史不会被默认摘要替代；产物投影需显式许可。使用与限制见[模型历史](model-history.md)和[本批验收](../architecture/reviews/2026-10-13-session-model-history.md)。该子集不关闭语义质量、长会话治理、完整H3/M1或外部采用门槛。

Dev86 端到端任务评测子集已验收：源码5681 passed／447配置跳过（830.34s）、独立核心安装161；源码三次重复RAG24/24、Plan15/15、Team15/15及安装CLI／SDK例子、旧85默认／原Plan回执兼容与298模块一致通过。复用原执行权威，新增最终模型请求可见引用、实际成员／工具回执、独立Embedding计量和观察式恢复；2项Important／1项Minor经有效RED统一修复。离线／MockTransport不构成真实模型质量；完整H3／M1／R01–R26及外部采用保持开放。见[任务评测指南](task-evaluation.md)与[本批验收](../architecture/reviews/2026-10-13-task-evaluation-chains.md)。

dev47 增加显式 Profile，以及 `recommended_harness` 起步定义；dev49 增加 `semantic-memory`，复用已有
AgentHarness／Runtime、模型、工具、子 Run、审批和恢复协议。没有新增执行权威。
旧 `local-basic`／`local-knowledge`／`managed-memory` 的版本 `1` 声明及
ManagedDataContext 实现身份保持兼容。

dev48 可在语义 Profile 中显式配置[HTTP 重排](http-reranking.md)，沿原 Hybrid 来源校验；
省略 `reranker` 时保留原保序行为。服务、模型、鉴权和限额均由调用方声明。

| Profile | 默认能力 | 应用补充 |
| --- | --- | --- |
| `semantic-knowledge` | SQLite 知识与向量索引、显式 HTTP Embedding、lexical/vector 并行召回、RRF、来源回读、相关上下文 | Embedding 服务、知识导入与索引、真实生成模型、答案及引用验证 |
| `memory-recall` | 有界 Facts／Session 召回、词项相关排序、自动上下文与产物投影、来源化结果观察写入 | 对齐 Agent namespace、业务字段 allowlist、事实正确性和保留策略 |
| `semantic-memory` | 显式 HTTP Embedding、有界原始 Facts 候选语义排序、TaskRecallPlanner、保序上下文及来源观察写入 | 对齐 namespace、Embedding／生成模型、业务字段与真实记忆质量；全库索引须显式替换 memory_store |
| `plan-and-execute` | 相关上下文、规则规划起步、显式可选 ModelPlanner、Schema 完成验证；显式 version="2" 的默认规则 DAG 串接成员结果 | 业务成员、工具、真实规划模型与 PlanVerifier |
| `team` | 相关上下文、固定 Supervisor 汇总起步、独立受管理成员 | 成员能力、工具、业务汇总和验证 |

所有 Profile 的生成 Provider 默认 `offline-echo`，只验证接线。语义 Profile **没有默认
语义模型、Hash 降级或自动下载**；保留内置语义角色时必须声明兼容 HTTP Embedding，使用 `abuild`。
显式 `version="2"` 允许完整替换 `knowledge` 或 `memory_store` 声明，替换后由所选适配器负责其配置，不要求无关的顶层 embedding。
离线／词法替换只验证替换协议，不能按 Profile 名称认定语义能力。版本 `1` 的声明与校验保持。
构造不发送请求，
显式索引与检索才调用选定服务。执行额度不能保证真实模型或 Embedding 的费用上限。

## 开箱运行与自定义编排

```python
import asyncio
from ralf_agent import Runtime, RuntimeBuilder, recommended_harness, recommended_profile


async def main():
    profile = recommended_profile("plan-and-execute", version="2")
    instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
    async with Runtime(instance, owned=True) as runtime:
        run = await runtime.submit(
            recommended_harness("plan-and-execute", version="2"),
            {"task": "Analyze this task and write an answer"},
            command_id="one",
        )
        print(await run.wait())


asyncio.run(main())
```

这是可运行的离线装配例子，offline-echo 只回显数据；真实业务需替换 Provider、工具和验证器。
`recommended_harness("plan-and-execute")` 的版本 `1` 默认 researcher／writer，使用原 flat RulePlanner；
显式 `version="2"` 且未传 `planner`／`plan_mode` 时选择既有规则 DAG：首成员收到任务，后续成员直接收到前一成员结果。
writer 不会额外收到原任务；若需要原任务，researcher 的结果应显式保留它，或自定义 Planner／ValueRef 输入映射。
显式提供任何 `planner` 或 `plan_mode` 时按原 Spec 处理，版本 `2` 不覆盖调用方选择。
`recommended_harness("team")` 默认 researcher／reviewer／synthesizer，使用原
SupervisorTeam。researcher／reviewer 按当前受限并发额度执行，再由 synthesizer 汇总。
默认指令不提供搜索、代码执行或工具，工具与授权仍由宿主配置。

传 `members={"lookup": AgentSpec(...), "answer": AgentSpec(...)}` 可替换成员，也支持原
Workflow／Graph／Team／Dynamic 嵌套定义。Team 默认把最后一个注册成员选为 supervisor；
可传 `strategy="sequential"` 或完整 `strategy_config`。规则 Plan 默认按注册顺序调用全部成员；
版本 `1` 的 flat Plan 后续输入由原 Planner 提案决定，不隐式把先前步骤输出连接到下一步。需要依赖输出时
使用 `plan_mode="dag"` 或自定义 Planner／ValueRef。

`planner="model"` 配合 plan-and-execute Profile 中注册的 ModelPlanner，模型通过受管理的
无工具 `@planner` 子 Agent 提案；默认 Echo 无法生成合法计划，必须替换 Provider。
`planner="dag-model", plan_mode="dag"` 使用已有 DAG 模型规划器。
`child_budget`／`max_steps`／`max_revisions`／`max_concurrency` 等直接传给原 Spec。
`agent_bindings` 使用现有 `team/members/...`／`dynamic/members/...` 稳定路径，不增加另一种绑定语言。

CompleteVerifier 默认取最后结果，SchemaVerifier 验证输出结构；二者不能证明业务正确。
实际业务应配置原 `plan_verifiers`／`verifier` 扩展与停止条件。组合不会额外授权工具或读写资源。

## 显式语义知识库

```python
from ralf_agent import AgentSpec, Document, Runtime, RuntimeBuilder, recommended_profile

profile = recommended_profile(
    "semantic-knowledge",
    embedding={
        "type": "openai",
        "config": {
            "model": "YOUR_EMBEDDING_MODEL",
            "dimensions": 1024,
            "base_url": "https://YOUR_EMBEDDING_SERVICE/v1",
            "api_key_env": "APP_EMBEDDING_KEY",
        },
    },
    knowledge_namespace="manuals",
    # provider={"adapter": ..., "config": ...},  # 显式配置生成模型
)


async def answer():
    instance = await RuntimeBuilder().abuild(profile, "knowledge-runs.sqlite")
    async with Runtime(instance, owned=True) as runtime:
        hybrid = instance.knowledge.retriever
        hybrid.store.put(
            instance.scope, "manuals", Document("guide", "Your guide text"), expected_version=0
        )
        await hybrid.retrievers["vector"].index_document(instance.scope, "manuals", "guide")
        run = await runtime.submit(
            AgentSpec("answer", "Answer using evidence; identify uncertainty"),
            "Your question",
            command_id="question-1",
        )
        print(await run.wait())
```

已有 IngestionCoordinator／Parser／Chunker 可以替换上面的基础导入。知识提交不等于向量就绪；
文档修改或删除后，检索会回读原知识库，拒绝旧版本／TTL／Scope／文本 digest 的来源。
模型、维度、索引后端和 namespace 应在新 Profile 版本中发布；旧 Run 要恢复原组合。
`components` 按完整组件声明覆盖，可替换为 Redis／PostgreSQL Facts、PG／Qdrant Hybrid 或自定义端口；
每个远程组合仍需各自验证，不能据此保证任意数据库组合兼容。

## 完整角色替换与工厂注入（版本 2）

下面以应用注册的 SQLite 词法适配器完整替换语义知识角色，实际导入并运行一次 Agent。
它无需 Embedding 服务，只证明声明→工厂→知识来源→运行→owned 关闭链路；不证明语义检索或答案质量。
工厂签名与资源账本沿用[装配协议](runtime-assembly.md)，自管客户端可被工厂捕获并按 borrowed 生命周期管理。

```python
import asyncio
from tempfile import TemporaryDirectory

from ralf_agent import (
    AgentSpec,
    ComponentRegistry,
    Document,
    KnowledgeContext,
    LexicalRetriever,
    Runtime,
    RuntimeBuilder,
    SQLiteKnowledgeStore,
    recommended_profile,
)


def application_knowledge(config, context):
    store = context.own(SQLiteKnowledgeStore(context.path(config["path"])))
    return KnowledgeContext(LexicalRetriever(store), namespace=config["namespace"])


async def main():
    registry = ComponentRegistry()
    registry.register("knowledge", "application-lexical-v1", application_knowledge)
    profile = recommended_profile(
        "semantic-knowledge",
        version="2",
        components={
            "knowledge": {
                "adapter": "application-lexical-v1",
                "config": {"path": "manuals.sqlite", "namespace": "manuals"},
            },
            "recall_planner": {"adapter": "task-text"},
        },
    )
    with TemporaryDirectory() as directory:
        builder = RuntimeBuilder(registry, base_dir=directory)
        instance = await builder.abuild(profile, directory + "/runs.sqlite")
        async with Runtime(instance, owned=True) as runtime:
            instance.knowledge.retriever.store.put(
                instance.scope,
                "manuals",
                Document("guide", "Inventory stock is seven units."),
                expected_version=0,
            )
            run = await runtime.submit(
                AgentSpec("assistant", "Answer using supplied evidence"),
                "What is the inventory stock?",
                command_id="stock-one",
            )
            print(await run.wait())


asyncio.run(main())
```

版本 `2` 提供 `recall_planner` 时移除预置 `recall_policy`；反向替换 `recall_policy` 时移除预置 planner。
调用方同时声明两者仍非法，不能静默丢弃一项。替换是完整声明覆盖，需在新 Profile 版本中保存实际适配器身份。
同理，`recommended_profile("semantic-memory", version="2", components={"memory_store": ...})`
可选完整 `indexed-recall-async` 或应用注册的记忆端口；所需 Embedding／索引配置写在该角色声明内。
`indexed-recall-async` 的独立 `embedding_provider`／`vector_index`／`fact_index_catalog` 工厂与显式 rebuild
见[全库索引](fact-indexing.md)。Hash 是显式离线词项基线，替换为它不会获得真实语义质量。

## 相关事实召回和上下文扩展

`ReferenceSelector.select(task, references) -> list[int]` 是同步纯策略，声明 JSON identity。
`RelevantDataContext` 接受独立 selector；只允许返回有界、唯一的原候选索引。
拒绝 awaitable、generator、上下文管理器等惰性返回、布尔值、重复／越界索引和参数修改。
实现／方法／配置固定到上下文身份；模型摘要的 fallback 与 finish 保存并消费原选择，恢复时不再排序。
Engine 仍保存完整原始候选，并负责源版本、TTL、Scope 和知识验证。

默认 OverlapReferenceSelector 优先 Session，由已有预算器保留完整近期轮次和原生 task／result；
普通 Facts 按 key／value 的任务词项重叠排序，正相关 Facts 与 Knowledge 从 Fact 开始轮流选入，
保持 Knowledge 相对语义／RRF 顺序，零相关 Facts 最后补入。混合来源顺序声明为
`relevant-fact-first-alternating-v1`，使事实有机会在有限上下文内竞争；可替换 selector 调整偏好。观察事实只按允许字段值排序，来源 Run
元数据不用于相关评分。它只排序**已经有界读出的候选**，不是全库搜索、语义记忆召回或自动信念修订。
摘要／摘录依旧有不完整标记；不保证语义信息完整保留。

默认最多选择 32 条引用，可配置至 256；输入候选上限 4096 条／1 MiB canonical 字符。
Session 超出总预算时只保留完整近期轮次，最新完整轮次放不下则不选入，并在
`session_projection` 记录省略；不会把孤立答案当成完整轮次。

```python
from ralf_agent import RelevantDataContext, OverlapReferenceSelector

context = RelevantDataContext(
    artifact_store,  # SDK 注入的资源由调用方关闭
    selector=OverlapReferenceSelector(max_references=16),
    mode="model",
    provider="summary",
    summary_max_chars=512,
)
```

Profile 对应 `context_assembler.adapter="relevant-data"`；异步产物用 `relevant-data-async`／abuild。
嵌套 `config.selector={"adapter":"overlap", "config":{"max_references":16}}`；
自定义工厂注册 `registry.register("reference_selector", "my-selector", factory, validator=...)`。
selector 工厂必须同步完成；这是可信宿主扩展协议，不能隔离任意 Python 插件的 I/O。
产物工厂复用已有 owned／borrowed 关闭，装配失败会清理 owned 资源。

memory-recall 默认写 namespace 为 `agent_name="assistant"`，读取仍遵循原 Agent 名称／Facts 绑定。
请对齐实际 Agent 名称，或使用宿主允许的 FactsView／每成员 stage_policy；不会自动跨 namespace 搜索。
默认 allowlist 保存整个 `result` 的来源观察，业务应替换 fields，只保留所需字段。

替换 `memory_store` 只改变召回资源，不自动修改 `stage_policy` 的观察写目标；默认写目标仍来自执行库。
需要向自定义后端提炼时，完整覆盖 `stage_policy`，在 `sourced-memory.config.memory` 声明该后端，
并显式设置 `namespace`／`fields`。异步目标使用 `sourced-memory-async` 和 `abuild`。
相同客户端可由宿主工厂共享，但 owned／borrowed 归属仍需按原资源账本声明。

## 历史证据与当前开放范围

测试覆盖 HTTP 协议与确定性同义词向量、真实 SQLite 索引／来源失效、有限上下文下相关 Facts、
默认及自定义／嵌套 Plan／Team、模型 Planner 夹具、审批／重复命令／重启、八个 OS 退出恢复窗口。
dev47 当时仅新增 Temporal 纯 Activity／History 集成测试，复用原 temporal-2；该批未运行真实 Temporal 服务、
远程数据库或真实生成／Embedding 模型。Local Profile 不直接替代 Temporal Worker 装配。
后续 dev48 已交付显式 HTTP 重排适配；dev56／57 已交付 memory／SQLite／Redis／PostgreSQL 全库扫描、
显式索引构建／激活与原事实来源核验的召回子集；查询分页仍限全库排序 top256 窗口，不等于全库枚举。
dev58 已接通 Temporal Facts／namespace 的原 Context 采纳，dev69 以后另有显式 Temporal Profile 装配，
Local Profile 仍不直接替代 Worker。相应证据见[HTTP 重排](http-reranking.md)、[全库索引](fact-indexing.md)
及[剩余矩阵](remaining-work.md)。这些交付不能证明真实语义召回、重排或最终答案质量。
自由记忆合成／修订／遗忘、索引自动增量／修复／删除传播／治理、业务 oracle、最终配置重复质量和
答案／引用验收仍开放。版本 `2` 的本轮最终回归／安装／兼容证据尚待完整验收，不在此填写通过数量。
