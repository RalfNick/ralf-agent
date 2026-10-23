# 显式模型查询改写 — dev50

`ModelQueryTransform` 借用已有 async `ModelProvider.complete`，提出搜索词；原知识库或 Facts 后端决定返回证据。
它可替换 dev49 的确定性 transform，默认组合仍不开启模型请求。
原生 ModelQueryTransform 配合 SemanticMemoryStore 时，先完成提案及固定组件校验再读取 Facts；空候选也会调用改写模型，不调用 Embedding。旧确定性／自定义路径维持候选优先行为。模型改写不改变原始正文、namespace、版本、TTL 或授权范围。

```python
from relf_agent import ModelQueryTransform, QueryTransformRetriever, KnowledgeContext

transform = ModelQueryTransform(query_provider, max_queries=2, include_original=True)
retriever = QueryTransformRetriever(my_retriever, transform)
knowledge = KnowledgeContext(retriever, namespace="manuals")
# 关闭 query_provider 的责任仍属于创建它的应用。
```

模型只收到系统约束和 `{"query": "当前问题"}` 用户文本，不收到来源正文、Facts namespace、凭据或工具。
用户查询本身可能含敏感数据，是否发送给所选服务由应用决定。额外 `instructions` 是宿主配置，最多4096字符。

模型需返回 `ModelResponse(output={"queries": ["搜索词"]})` 或等价 JSON 文本，不得提出工具。
拒绝重复 JSON 键、额外字段、非有限常数、重复／空白查询及超限响应；失败不自动回退或重试。
输入及单条查询最多4096字符，原始／规范化输出最多32768字符；Unicode 必须有效。
`max_queries` 默认2，可设1–4；保留原查询时最多3，最终最多4条／16384字符。
`include_original=True` 默认把原查询精确放在首位，模型重复原查询时仅保留一份；不做空白归一化或词义去重。
Provider 对象、完成方法、声明身份及输入参数在等待前后复核。同步 Provider 或惰性提案不被接受。

## 配置已有模型

原 `RuntimeProfile.providers` 中显式配置一个 `query` 模型，可采用现有 Chat Completions、Anthropic、Gemini 或 Responses 端口的完成响应契约。
这不等于各线上型号的能力认证；服务必须能遵循 JSON 查询要求。

```python
query_transform = {
    "type": "model",
    "config": {
        "provider": "query",  # 已存在的 RuntimeProfile.providers 别名
        "max_queries": 2,
        "include_original": True,
        "instructions": "保留产品型号与版本。",
    },
}
```

把声明放入 `sqlite-lexical-query` 或现有 Hybrid 的 `config.query_transform`；
Local `semantic-recall-async` Facts 也支持该字段。JSON/TOML 使用相同嵌套结构。
`recommended_profile("semantic-knowledge", embedding=..., query_transform=query_transform)` 可复用该声明；
然后在 Profile.providers 加入命名模型。`semantic-memory` 可修改对应 memory_store 声明，继续使用 `abuild`。
每 Agent 的 Knowledge/Facts 资源包装和 namespace 选择仍沿原 BindingCatalog／宿主允许范围。
缺失模型别名与无效内置参数在创建执行数据库前拒绝；自定义工厂的无关配置不被解释。

工厂使用同一个已装配 Provider，不创建并行客户端；原资源 ledger 保持 owned/borrowed 与失败清理责任。
改写器不关闭 Provider。共享自定义 Provider 应满足应用实际的并发与事件循环契约。
旧八类 Profile 省略新选项时保持原声明、Manifest 与历史恢复身份；旧版本不支持 `model` 声明。

## 恢复、费用与验收范围

改写属于检索准备，未成为独立持久模型 Action。原 Local Run 已记录模型响应后，恢复复用已接受的上下文；
Temporal 复用已接受 Knowledge Activity／History 结果。下一 Action 可独立检索。
接受前中断可能重复改写及 Embedding 服务请求；execution credits 不是费用硬上限。
此能力不创建新的缓存、Facts 索引、Worker 协议或执行权威。

本轮以原生 HTTP Provider、实际 `os._exit` 重启、重复审批与纯 Temporal Knowledge 状态重放验证协议。
TemporalRuntime 尚无 Facts／RecallPlanner 输入路径；模型查询的真实召回、答案和引用质量未在此轮测量。
完整 H3、自动查询策略、全库 Facts 索引和模型／服务兼容矩阵继续见[剩余清单](remaining-work.md)。
