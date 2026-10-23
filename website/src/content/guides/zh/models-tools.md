---
title: 模型与工具
description: 注册普通 Python 函数，连接真实模型，用 LocalEngine 驱动一次任务。
locale: zh
slug: models-tools
sources: [docs/sdk-model-tools.md, docs/getting-started.md, docs/model-adapters.md, docs/completion-verification.md, README.md]
---

## 把函数注册为工具

`ToolRegistry.tool` 从支持的 Python 注解中生成参数 Schema。函数仍然是普通的可调用对象；注册时必须明确 `effect`，注解推导不授予任何权限。

```python
from relf_agent import ToolRegistry

tools = ToolRegistry()

@tools.tool(effect="read_only", description="Read a ticket")
def lookup(ticket: str):
    return {"ticket": ticket, "status": "open"}
```

复杂类型或约束需要显式 Schema 或自定义适配器。默认值会被校验并冻结到注册身份；需要改变定义时重新注册并为新任务使用新配置。

## 一次工具往返发生什么

1. Agent 声明允许的工具名，Provider 接收描述与模型上下文。
2. 模型提出工具名及 JSON 参数；框架检查 Schema、允许范围、额度和宿主授权。
3. 如需审批，保存原 Action 与摘要并暂停；批准后执行器调用原工具。
4. 工具结果形成回执并进入后续模型上下文，模型继续决策或给出最终输出。

普通 Python 函数仍可直接调用；只有通过框架派发的路径才具有这些执行记录。注册工具不等于自动把它暴露给所有 Agent，也不会把业务函数放进隔离环境。

## 连接模型并运行

在进程环境设置 `OPENAI_API_KEY` 和 `RELF_MODEL`；模型名使用当前账户实际支持的值。在新的工作目录将下面的完整示例保存为 `ticket_agent.py`。它使用真实 Provider，会产生供应商用量；如需先验证无密钥工具循环，运行[离线应用测试](/zh/docs/testing/)。

```python
import asyncio
import os
from relf_agent import (
    AgentSpec, LocalEngine, OpenAIChatProvider,
    SQLiteStore, ToolRegistry,
)

tools = ToolRegistry()

@tools.tool(effect="read_only", description="Read a ticket")
def lookup(ticket: str):
    return {"ticket": ticket, "status": "open"}

spec = AgentSpec(
    "assistant", "Read the ticket and summarize its status.",
    ("lookup",),
)

async def main():
    provider = OpenAIChatProvider(model=os.environ["RELF_MODEL"])
    with LocalEngine(
        SQLiteStore(".ralf/agent.sqlite"),
        providers={"default": provider}, tools=tools,
    ) as engine:
        run = engine.submit(spec, "Check INC-001",
                            command_id="request-001", budget=16)
        print(await engine.drive(run.run_id))

asyncio.run(main())
```

运行 `python ticket_agent.py`。成功时输出包含 `state='succeeded'` 和工单摘要的快照。模型行为可能不同；失败时按[审批与恢复](/zh/docs/recovery/)排查，并检查实际工具回执，不能假定模型一定调用 `lookup`。重复原命令回读原 Run；新输入或配置使用新命令 ID。

这里的 `spec` 是 `AgentSpec` 声明，由 Engine 提交并推进。[会话完整示例](/zh/docs/sessions-memory/)会另外创建提供 `open_session` 的 `Agent` 入口，两者是不同对象。

Provider 只提出模型响应与工具调用，由引擎负责授权和执行。不同兼容端点仍需单独验证协议与工具调用契约。更多适配器见[模型接入指南](repo:docs/model-adapters.md)。

## 约束最终输出

工具参数 Schema 约束输入，Agent 的 `output_schema` 约束最终结果。将上例的 `spec` 定义替换为：

```python
spec = AgentSpec(
    "assistant", "Read the ticket. Return ticket and status as JSON.",
    ("lookup",),
    output_schema={
        "type": "object",
        "properties": {
            "ticket": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["ticket", "status"],
        "additionalProperties": False,
    },
)
```

同时把提交命令改为 `command_id="request-structured-001"`，再运行 `python ticket_agent.py`。定义变化代表新请求，继续复用 `request-001` 会触发 `IdempotencyConflict`。保留数据库与原定义，以便恢复旧 Run；重复命令不会重新生成已经保存的响应。

本地输出校验与 Provider 的原生结构化输出是不同层，后者只在对应适配器和型号支持时显式配置。合法 JSON 也不证明工单已处理；需要业务完成证据时，配置 `ToolReceiptVerifier` 等完成规则，检查当前节点的工具回执。详见[完成验证](repo:docs/completion-verification.md)。

## 声明写操作的边界

| 效果类别 | 适用情况 |
| --- | --- |
| `read_only` | 读取业务信息 |
| `idempotent_write` | 下游以稳定幂等键处理重复写入 |
| `queryable_write` | 可根据原效果身份查询实际业务结果 |
| `unqueryable_write` | 无法自动查询的业务写入，需要保守处理未知结果 |

写工具可以声明 `requires_approval=True`。需要宿主上下文时显式指定 `context_parameter`，由执行器注入；模型不能自行提供宿主上下文。

```python
@tools.tool(
    effect="idempotent_write",
    requires_approval=True,
    context_parameter="context",
    version="1",
)
def apply(value: int, *, context):
    return business_service.apply(
        value, idempotency_key=context.effect_key,
    )
```

这里的 `business_service` 由应用提供。下游必须真正实现相应幂等或查询契约；仅声明效果类别不等于获得跨系统 exactly-once 保证。

模型不可伪造 `context.effect_key`。工具的超时、取消与异常也不能证明业务没有执行；响应不确定时，保留原 Action 并按效果类别恢复或核验。

## 保持组件身份与生命周期

凭据留在环境或可信宿主中。工具、Provider、上下文与记忆发生身份变化后，创建新的任务；旧 Run 仍需原配置。Python 扩展是可信宿主代码，隔离、权限与服务关闭由部署者显式配置。

已有 MCP、HTTP 或 CLI 工具可通过[集成与扩展](/zh/docs/integrations/)接入。继续阅读[审批与恢复](/zh/docs/recovery/)，理解写操作在超时和进程退出后的处理方式。

方法签名与返回值见 [API 与 CLI 参考](/zh/docs/api-reference/)，端点验证见[测试与评估](/zh/docs/testing/)，同一应用逐步加入模型、会话和知识见[连续应用教程](/zh/docs/app-tutorial/)。
