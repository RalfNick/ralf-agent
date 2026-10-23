# 推荐 Local Harness 组合

从下表选择最小 Local 组合，再按需替换模型、工具和数据组件。默认离线，不会自动调用收费服务。历史验收保留在文末，当前支持范围见[实现清单](implementation-status.md)。

dev47 另增加显式 `semantic-knowledge`、`memory-recall`、`plan-and-execute`、`team`，dev49 增加 `semantic-memory`，
以及保持原 Spec／绑定路径的 `recommended_harness`。
见[语义检索、相关召回与编排组合](h3-intelligent-combinations.md)。原三个版本 `1` 组合保持兼容。

dev43 提供三个版本为 `1` 的起步 Profile，复用现有 Agent／Runtime、绑定、原 Run 日志及工厂：

| 组合 | 默认能力 | 应用需要补充 |
| --- | --- | --- |
| `local-basic` | SQLite 执行／会话／Facts、Schema 完成验证、有界召回、自动历史摘要与数据投影、SQLite 产物 | 真实模型与业务工具 |
| `local-knowledge` | Basic 加 SQLite lexical KnowledgeContext | 导入知识、语义检索及答案／引用质量验证 |
| `managed-memory` | Basic 加 allowlist 最终结果提炼，写入指定 Agent 的 Facts namespace | 业务字段、保留策略及事实正确性验证 |

默认模型为 **offline-echo**，只验证装配与恢复。不会自动读取模型密钥、下载模型或访问网络。
dev44 将 **Local Basic／Local Knowledge 的数据上下文**扩展到串行／并行图、Team、动态 Plan/DAG 和嵌套成员。dev45 的 `managed-memory` 也支持这些 Local 实际 Agent 的规则／模型选择写入，见[高级记忆与恢复](composite-memory-stages.md)。
Temporal 显式装配同一个纯策略，按原 History 协议运行；不直接使用 Local Profile 工厂，dev46 另以显式 temporal-3 支持五类每 Agent 绑定与自动记忆，见[Temporal 记忆绑定](temporal-memory-bindings.md)。H3 尚未整体验收完成。见[高级编排与 Temporal 指南](composite-temporal-context.md)。

```python
import asyncio
from relf_agent import Agent, AgentSpec, Runtime, RuntimeBuilder, recommended_profile


async def main():
    profile = recommended_profile("local-basic")
    instance = await RuntimeBuilder().abuild(profile, "runs.sqlite")
    async with Runtime(instance, owned=True) as runtime:
        agent = Agent(runtime=runtime, definition=AgentSpec("assistant", "Answer clearly"))
        run = await agent.submit("hello", command_id="hello-1")
        print(await run.wait())
        print(await run.context_artifacts())


asyncio.run(main())
```

配置真实模型，使用 `provider={"adapter": "deepseek-chat", "config": {"model": "deepseek-chat", "api_key_env": "DEEPSEEK_API_KEY"}}`。
工厂在明确选择该 Provider 时才读取指定环境变量。替换模型、工具、知识／记忆后端或上下文，向
`recommended_profile(..., components={...}, binding_components=[...], name="my-app", version="1")`
传入已有组件声明。覆盖以完整组件声明为单位；同名版本不能偷偷替换已接受的配置。
JSON／TOML 使用普通 Profile 的 `context_assembler.adapter = "managed-data"`，不增加另一种配置语言。

显式 `version="2"` 接续版本化替换：提供 `recall_planner` 时移除预置 `recall_policy`，反向替换同理；
调用方同时提供两者仍拒绝。`semantic-knowledge` 完整替换 `knowledge`、`semantic-memory` 完整替换
`memory_store` 后，不要求无关的顶层 Embedding；所选角色负责自己的配置和来源／生命周期契约。
保留内置语义角色仍要求显式 HTTP Embedding，不自动降级 Hash。版本 `1` 保留原声明与校验。
应用可通过 `registry.register(role, adapter, factory)` 注入自管端口，`RuntimeBuilder(registry)` 采用其声明；
同步工厂 `(config, context)` 用 `context.own` 接管自建 close 资源，异步工厂用 `register_async`／`own_async`／`abuild`。
完整可运行的自定义词法替换和版本 `2` Plan 例子见[H3 组合](h3-intelligent-combinations.md)。
显式 `recommended_harness("plan-and-execute", version="2")` 在未指定 planner／plan_mode 时使用既有规则 DAG，
后成员直接消费前成员结果；原任务若仍需要应放在前成员结果或显式输入映射中。显式选项及旧版本行为保留。
本轮版本 `2` 最终组合验收仍待完成，离线／词法例子不证明语义或业务质量。

Managed Memory 默认写 namespace 为 `agent_name="assistant"`；若按 Agent 名称召回应显式对齐读取 namespace，其他目标传 `agent_name="support"`。高级成员继承共同写 namespace，不会自动按成员命名切换；可用每成员 stage_policy 绑定选择不同后端与 namespace。
默认保存整个最终结果，是显式选择该组合后的基础观察记录；业务使用应替换 `stage_policy` 的
`fields` allowlist，只提炼需要保留的字段。存储值包含来源 Run／Release／字段／digest 和
`completed-result-observation` 信任标记，不能把模型说法当成已核验事实。

## 自动上下文与大结果

`ManagedDataContext(artifact_store, ...)` 仍是纯 ContextBuilder；所有保存／核验由 Engine 完成。
默认超过 8192 canonical 字符的工具消息卸载为产物，模型收到固定引用、256 字符预览及不完整标记；
原工具配对、调用 ID、完整结果与效果证据保留在执行日志。**这减少模型输入，不压缩 Run 数据库。**
超出 1 MiB 产物端口上限会明确失败，当前不支持任意大小文件／blob。

超过 1024 canonical 字符的 Facts／知识／Session 引用变为确定性摘录，保留完整来源 digest、
知识出处和不完整标记；Session 优先最新完成记录，Knowledge 优先内容。原始 Facts／Knowledge
引用仍独立保存并在派发前进行版本／TTL／Scope 校验。摘录不能保证语义完整或答案质量。
历史完整组采用既有 excerpt 摘要；`mode="model"` 可选原受管理模型摘要，原 Run 预留 1 credit，
响应独立保存，未知结果保留额度并采用已固定 fallback，不重新调用。

可配置 `tool_result_chars`、`preview_chars`、`reference_chars`、`summary_max_chars`、
计量器与预算、摘要 Provider／超时及产物 namespace。预览／引用元数据自身也占用上下文预算，
最新完整工具组仍放不下时明确失败。

SDK 注入的 ArtifactStore 是 **borrowed**，调用方负责关闭；Profile 默认 SQLite 产物工厂是
**owned**，随 Runtime 关闭。可注册 `registry.register("artifact_store", "custom", factory)`，
在 `managed-data.config.artifacts` 指定适配器；异步工厂使用 `register_async`、
`managed-data-async` 与 `abuild`。工厂用 `ctx.own`／`ctx.own_async` 声明所有权。
自定义后端必须返回精确内容寻址引用，身份包含实际 `backend_id`，实现 scoped immutable put/get 契约。

使用 `ArtifactReference.from_dict(...)` 与后端 `get(scope, ref)` 可取回原工具消息内容；业务工具
返回的 JSON 已序列化为工具消息文本。模型不会自动获得无限读取权限；按需求注册有界读取工具。

## 恢复边界

原 Run 先记录产物意图，再记录派发，精确读回后独立保存回执。写后丢失确认时读取固定引用核验；
重启不会重做业务工具。已派发产物缺失／被删除／内容不符会拒绝继续披露，不重新写入或调用模型。
尚未派发且后端明确不存在时才写入。已保存的模型响应可直接采纳，恢复不依赖产物仍然在线。
取消或终态恢复不会新增产物写入，离线证据可通过 `context_artifacts()` 查询。

并行图各节点保留独立的产物派发记录。两个节点同时读到同内容不存在时，可能各调用一次
`put`；后端应按内容和完整元数据原子去重，返回同一引用。全局 API 调用次数不保证为一。
恢复时核对原 frame 的意图、派发与回执；不能把同内容的两次独立首次派发误判为恢复重写，
也不能用存储已去重掩盖同一 frame 的重复派发。业务工具的效果去重仍按原 effect_key 验证。
派发记录先于后端 I/O；进程在两者之间退出时，记录数可能多于实际调用数。
恢复测试应分别观察派发与真实调用，验证调用身份及回执，不能假设两个计数总相等。

该能力 opt-in 开启语义 Schema **10**；dev42 及以前代码拒绝该库。高级 Local 编排首次准入启用 Schema **11**，dev43 拒绝该库。普通默认仍为原 Schema，
旧 Schema 1–9 可读取／恢复；退回旧代码需保留旧库或做显式迁移，不可编辑版本号绕过检查。
高级自动记忆首次准入启用 Schema **12**，dev44 拒绝；原生／顺序记忆仍按已有 Schema7/9，组合数据上下文启用 Schema10。显式终态根 resume 可恢复原已结束子 Run 的记忆证据，不重新派发写入。
上述 Schema10–12 是原批次兼容边界，后续显式角色启用各自版本门槛。
dev84 已交付第十四类独立 `artifacts` 绑定的 Local／Temporal 子集，可独立于 Context 策略选取
宿主允许的存储／namespace 或 disabled；dev83 仍拒绝该新角色，旧发布不自动升级，见[Artifact 绑定](artifact-bindings.md)。
自动 GC、S3／对象存储、binary 传输、后台保留／全局磁盘治理仍开放，独立绑定不等于完整 R18/H3。

## 历史验收记录

Dev82 子集已验收：纯可替换 SkillSelector／LexicalSkillSelector、SkillDirectoryRetriever、JSON／可选 SKILL.md 声明，通过原 KnowledgeContext 自动提供被动目录；正文仍走原授权 skill_get，不增加工具权限或执行权威。最终源码5089 passed／386配置跳过（845.08s (0:14:05)），核心155／SDK271安装、真实源码8／安装8、旧81双向恢复／22模板／旧Worker业务I/O前拒绝及281模块一致通过。三项Important经10项有效失败复现统一修复，无新增延期Minor；自有Temporal实际退出并等待。完整R01–R26、语义选择、插件激活、Sandbox／Runner及真实质量仍开放。见[本批记录](../architecture/reviews/2026-10-12-skill-discovery-context.md)。

Dev81 子集已验收：原生写真实生命周期及显式可替换 ToolExecutionPort／tracked owner，原 Temporal History 分别保存独占调用身份、实际结束与效果回执；容量拒绝／RPC失败／观察者取消的通知保持受管理重试。最终源码5021 passed／378配置跳过（758.54s），核心67／SDK232安装、真实源码8／安装8、旧80双向恢复／22模板／旧Worker执行前拒绝及278模块一致通过。三项Important经3项RED→GREEN统一修复，无新延期Minor；原自有服务停止并实际等待退出。完整R01–R26、Sandbox／Runner与质量目标仍开放。 见[本批记录](../architecture/reviews/2026-10-12-native-write-lifetime.md)。
