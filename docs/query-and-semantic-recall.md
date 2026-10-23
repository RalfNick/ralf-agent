# Query transform 与语义 Facts 召回

dev49 沿原 Retriever／RecallMemoryStore 增加组合能力，原 Run／History 继续保存已接受的引用和模型响应。
默认不开启网络改写或模型下载。原七类 Profile 省略新选项时保持原声明与组件身份。

## 查询改写

```python
from relf_agent import AliasQueryTransform, QueryTransformRetriever, KnowledgeContext

transform = AliasQueryTransform({"car": "automobile"})
retriever = QueryTransformRetriever(my_retriever, transform)
knowledge = KnowledgeContext(retriever, namespace="manuals")
```

`IdentityQueryTransform` 保留原文；`AliasQueryTransform` 合并空白，按区分大小写的字面替换映射
同时替换，不链式二次替换、不解释正则。默认保留原查询，`include_original=False` 可只用改写词。
匹配字面子串，词边界或中文分词规则由使用者自己的 transform 提供。
替换文案不成为模型指令或来源证据。

`QueryTransform`／`AsyncQueryTransform` 的 `transform(text)` 返回1–4个唯一、非空的 tuple 查询，
单条最多4096字符、总共16384字符，Unicode 必须可编码。
已有 Retriever 依次查询并共用128候选／64000字符预算；同一来源 ID 只保留一次，冲突正文失败。
返回条数／字符仍受原 RetrievalQuery 控制。来源会在后续查询等待前后复核；分支失败不会自动回退。
校验前及最后一次等待后检查完整候选的 TTL，校验器不能修改传入证据。原生 Lexical／Vector／Hybrid
及嵌套组合固定公共资源对象和来源方法，即使 backend_id 相同也不能在已注册包装器内更换。
原生组合最多128个捕获资源／16层嵌套。自定义适配器的私有资源／后台任务由自己的端口与所有权契约管理。
SDK 子组件全部借用；自定义异步改写可调用模型，但属于检索准备，未形成独立持久化模型 Action。

Hybrid 组合配置可显式添加：

```python
query_transform = {"type": "aliases", "config": {"aliases": {"car": "automobile"}}}
# recommended_profile("semantic-knowledge", embedding=my_http_embedding,
#                     query_transform=query_transform)
```

现有 Hybrid 工厂同步／异步模式保持；离线词法组合可选择 `sqlite-lexical-query`，配置字段与
`sqlite-lexical` 一致，并增加上述 `query_transform`。SDK 可以替换为自定义 sync/async 端口；
JSON／TOML 内置声明支持 `identity`／`aliases`；dev50 增加显式 `model`，见[模型查询改写](model-query-transform.md)。其他类型由应用自定义工厂装配。

## 语义长期记忆召回

```python
from relf_agent import AgentSpec, RuntimeBuilder, recommended_profile

profile = recommended_profile(
    "semantic-memory",
    embedding={
        "type": "openai",
        "config": {
            "model": "YOUR_EMBED_MODEL",
            "dimensions": 1024,
            "base_url": "https://YOUR_SERVICE/v1",
            "api_key_env": "APP_EMBED_KEY",
        },
    },
)
# instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
# instance.memory.put_fact(instance.scope, "assistant", "preference", "事实内容",
#                          expected_version=0)
# run = instance.submit(AgentSpec("assistant", "依据事实回答"), "问题", command_id="one")
# result = await instance.drive(run.run_id)
# 最后 await instance.aclose()
```

推荐组合包括 SQLite Facts、`TaskRecallPlanner`、原受管理记忆观察和 RelevantDataContext，
其中 `OrderedReferenceSelector` 优先保留近期 Session，再保留检索原顺序，避免词项策略覆盖语义排序。
生成模型默认仍是 offline-echo，真实业务需另选 Provider。改 Agent 名称需同步 `agent_name` 与事实 namespace。
不是提供商无关的向量协议认证；适用原 HTTP Embedding 协议，服务／模型／鉴权与维度需显式配置。

`SemanticMemoryStore(backend, embedding, transform=None, ...)` 可借用 SQLite／Redis／PostgreSQL
等实现原 `recall/validate_facts` 的 sync/async 原生后端，也支持用户 EmbeddingProvider。
Hash 仅是显式离线基线，新的语义 Profile／工厂拒绝 Hash 自动降级。
直接 SDK 装配 LocalEngine 时需设置 `recall_planner=TaskRecallPlanner()`。
手动 `facts/put_fact/inspect_fact` 保留原存储语义，不做语义查询；真正排序的是带当前文本的 `recall`。

先按原后端位置和扫描限额取得有界候选，清除词项 text 过滤，再验证来源并计算查询／候选 Embedding。
多个改写查询取最大 cosine，等分按原候选顺序；分数有限，维度与非零范数必须符合声明。
默认最多256候选、64000候选字符，最多262144配置上限；单 Embedding 文本32768字符、
总文本262144字符、向量值总数400万。完整输入／Unicode先校验再调用服务。
源数据在改写后、Embedding后和原模型披露前复核；TTL还独立验证。
确定性／自定义旧路径空候选不调用 transform 或 Embedding；dev50 原生 ModelQueryTransform 先校验提案再读取候选，空候选仍调用改写模型，但不调用 Embedding。失败不回退词项匹配。
`min_score` 可设[-1,1]，默认-1保留候选；分数不是事实可信度。

**这是候选窗口内的语义排序，不是全库向量索引。** 窗口之外的相关事实可能漏召回，`next_cursor=None`
不表示全库扫描完成；不支持排序游标或 `max_pages>1`。记录、版本、TTL、CAS 与来源仍属于原后端，
不创建第二套事实、持久向量缓存或后台任务。后端字符限额限制返回数据，不保证内部数据库字节扫描上限。

## 配置、生命周期与恢复

`memory_store.adapter="semantic-recall-async"`，config 包含 `backend` 组件声明、`embedding`，
可选 `query_transform/max_candidates/max_candidate_chars/min_score`；配 `recall_planner.adapter="task-text"`。
JSON／TOML 使用原嵌套声明语言；FactsBindingResource 可在外层提供每 Agent 授权 namespace，
适配器自身不递归包裹资源。使用 `abuild`，错误内置配置在建库前拒绝，不发送 bootstrap 请求。

dev122 修复了该 namespace 包装将候选窗口缩为一条的问题。`SemanticMemoryStore`
声明 `recall_mode="window"`；绑定视图单次传递完整查询及扫描额度，保留多条排名结果，
并在添加来源信息后再次执行字符限额。过大的结果省略且计入 `skipped`，不补查或生成分页游标。
第三方窗口后端可使用同一元数据；未声明时保持原游标契约。

此修复改变已选择窗口模式的资源发布身份。dev121 已接受的 scoped 语义任务应保留原环境、
数据与匹配组件，不能在升级时静默重绑；新任务使用修复后的发布。旧游标资源身份保持。
本批不增加旧 Temporal History 兼容、语义质量或完整分布式组合的验收结论。

SDK 资源借用，由调用方关闭。工厂后端和新组合的 ManagedEmbeddingProvider 由原装配 ledger 拥有；
新 Embedding 资源明确记录传输与响应流实际释放，失败／重复取消可重试 `aclose`，并阻止新请求。
owned HTTP 不读取环境代理／CA覆盖；有这些宿主配置时使用 SDK 注入自管客户端／EmbeddingProvider。
原 OpenAIEmbeddingProvider 与旧 Profile 维持，新的资源身份含独立生命周期版本。

已持久化模型响应的 Action 恢复直接采纳原引用快照；审批重复不会重复业务写入。
下一 Action 有独立检索。**准备中断可能重复改写／Embedding请求**；execution credits 不计这些服务费用，
没有恰好一次付费请求或费用硬上限。自定义 transform 应提出搜索词，不应执行业务写操作。

本轮 Local 原生与图 Facts绑定、回环 HTTP、实际进程恢复及 Temporal Knowledge Context/History 重放有证据。
TemporalRuntime 尚无 Facts／RecallPlanner 输入路径，因此不宣称 Temporal 语义 Facts 召回。
没有调用真实模型、重跑远程数据库或 Temporal服务，真实召回／答案／引用质量仍待业务评测。
