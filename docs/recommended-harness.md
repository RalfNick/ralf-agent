# 推荐 Local Harness 组合

dev43 提供三个版本为 `1` 的起步 Profile，复用现有 Agent／Runtime、绑定、原 Run 日志及工厂：

| 组合 | 默认能力 | 应用需要补充 |
| --- | --- | --- |
| `local-basic` | SQLite 执行／会话／Facts、Schema 完成验证、有界召回、自动历史摘要与数据投影、SQLite 产物 | 真实模型与业务工具 |
| `local-knowledge` | Basic 加 SQLite lexical KnowledgeContext | 导入知识、语义检索及答案／引用质量验证 |
| `managed-memory` | Basic 加 allowlist 最终结果提炼，写入指定 Agent 的 Facts namespace | 业务字段、保留策略及事实正确性验证 |

默认模型为 **offline-echo**，只验证装配与恢复。不会自动读取模型密钥、下载模型或访问网络。
dev44 将 **Local Basic／Local Knowledge 的数据上下文**扩展到串行／并行图、Team、动态 Plan/DAG 和嵌套成员。`managed-memory` 的自动长期记忆写入仍限原生 Agent／顺序 Workflow，不能作为高级编排默认组合。
Temporal 显式装配同一个纯策略，按原 History 协议运行；不直接使用 Local Profile 工厂，也不增加每 Agent Temporal 绑定。H3 尚未整体验收完成。见[高级编排与 Temporal 指南](composite-temporal-context.md)。

```python
import asyncio
from ralf_agent import Agent, AgentSpec, Runtime, RuntimeBuilder, recommended_profile


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

Managed Memory 的默认 `agent_name="assistant"` 必须与 AgentSpec 名称一致；其他名称传 `agent_name="support"`。
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

该能力 opt-in 开启语义 Schema **10**；dev42 及以前代码拒绝该库。高级 Local 编排首次准入启用 Schema **11**，dev43 拒绝该库。普通默认仍为原 Schema，
旧 Schema 1–9 可读取／恢复；退回旧代码需保留旧库或做显式迁移，不可编辑版本号绕过检查。
当前无自动 GC、S3／对象存储适配、后台保留任务或统一 Artifact 能力选择角色。
