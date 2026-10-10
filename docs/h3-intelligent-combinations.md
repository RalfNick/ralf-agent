# H3 语义知识、相关召回与 Plan／Team 组合

dev47 增加四个显式 Profile，以及 `recommended_harness` 起步定义，复用已有
AgentHarness／Runtime、模型、工具、子 Run、审批和恢复协议。没有新增执行权威。
旧 `local-basic`／`local-knowledge`／`managed-memory` 的版本 `1` 声明及
ManagedDataContext 实现身份保持兼容。

dev48 可在语义 Profile 中显式配置[HTTP 重排](http-reranking.md)，沿原 Hybrid 来源校验；
省略 `reranker` 时保留原保序行为。服务、模型、鉴权和限额均由调用方声明。

| Profile | 默认能力 | 应用补充 |
| --- | --- | --- |
| `semantic-knowledge` | SQLite 知识与向量索引、显式 HTTP Embedding、lexical/vector 并行召回、RRF、来源回读、相关上下文 | Embedding 服务、知识导入与索引、真实生成模型、答案及引用验证 |
| `memory-recall` | 有界 Facts／Session 召回、词项相关排序、自动上下文与产物投影、来源化结果观察写入 | 对齐 Agent namespace、业务字段 allowlist、事实正确性和保留策略 |
| `plan-and-execute` | 相关上下文、规则规划起步、显式可选 ModelPlanner、Schema 完成验证 | 业务成员、工具、真实规划模型与 PlanVerifier |
| `team` | 相关上下文、固定 Supervisor 汇总起步、独立受管理成员 | 成员能力、工具、业务汇总和验证 |

所有 Profile 的生成 Provider 默认 `offline-echo`，只验证接线。语义 Profile **没有默认
语义模型、Hash 降级或自动下载**；必须声明兼容 Embedding，使用 `abuild`。构造不发送请求，
显式索引与检索才调用选定服务。执行额度不能保证真实模型或 Embedding 的费用上限。

## 开箱运行与自定义编排

```python
import asyncio
from ralf_agent import Runtime, RuntimeBuilder, recommended_harness, recommended_profile


async def main():
    profile = recommended_profile("team")
    instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
    async with Runtime(instance, owned=True) as runtime:
        run = await runtime.submit(
            recommended_harness("team"), "Analyze this task", command_id="one"
        )
        print(await run.wait())


asyncio.run(main())
```

`recommended_harness("plan-and-execute")` 默认 researcher／writer，使用原 RulePlanner；
`recommended_harness("team")` 默认 researcher／reviewer／synthesizer，使用原
SupervisorTeam。researcher／reviewer 按当前受限并发额度执行，再由 synthesizer 汇总。
默认指令不提供搜索、代码执行或工具，工具与授权仍由宿主配置。

传 `members={"lookup": AgentSpec(...), "answer": AgentSpec(...)}` 可替换成员，也支持原
Workflow／Graph／Team／Dynamic 嵌套定义。Team 默认把最后一个注册成员选为 supervisor；
可传 `strategy="sequential"` 或完整 `strategy_config`。规则 Plan 默认按注册顺序调用全部成员；
flat Plan 的后续输入由原 Planner 提案决定，不隐式把先前步骤输出连接到下一步。需要依赖输出时
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

## 验证范围

测试覆盖 HTTP 协议与确定性同义词向量、真实 SQLite 索引／来源失效、有限上下文下相关 Facts、
默认及自定义／嵌套 Plan／Team、模型 Planner 夹具、审批／重复命令／重启、八个 OS 退出恢复窗口。
Temporal 仅新增纯 Activity／History 集成测试，复用原 temporal-2；本轮未运行真实 Temporal 服务、
远程数据库或真实生成／Embedding 模型。Local Profile 不直接替代 Temporal Worker 装配。
自由记忆合成、全库语义召回、语义重排、自动索引治理、业务 oracle 和答案／引用质量仍待验收。
