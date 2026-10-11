# 受管理工具节点与 MCP

版本：0.1.0.dev11。ToolSource 将远程工具装配到现有 Registry；Agent 工具调用与显式图 Tool 节点使用相同的审批、预算、稳定 Action、效果核验和独立回执采纳。默认实现是 POSIX MCP stdio；Python 3.11+，无需新增依赖或模型密钥。

## 1. 安装后直接运行

```sh
ralf init my-mcp-agent --template mcp
cd my-mcp-agent
python -m agent_app --value 3 --command-id first-change
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
# 核对参数后，复制 inspect 输出的批准命令
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine resume RUN_ID
```

将 RUN_ID 换成提交返回的 ID。模板包含一个真实的离线 MCP 子进程和独立 SQLite 业务回执库。它按框架注入的 effect_key 去重，写操作需要审批；重新提交相同命令返回原 Run。它验证工具链路，不验证模型任务质量或所有外部 MCP 服务。

## 2. 无模型的异步业务节点

```python
import asyncio
from ralf_agent import (
    GraphNode,
    GraphWorkflowSpec,
    LocalEngine,
    SQLiteStore,
    ToolRegistry,
    ToolSpec,
    ValueRef,
)


async def read_order(arguments, context):
    # Replace with an actual async service call.
    return {"order_id": arguments["order_id"], "state": "ready"}


tools = ToolRegistry()
tools.register(
    ToolSpec(
        "read_order",
        "Read an order",
        {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
            "additionalProperties": False,
        },
    ),
    read_order,
)
flow = GraphWorkflowSpec(
    "order",
    [GraphNode("read", tool="read_order")],
    output=ValueRef("read"),
)
with LocalEngine(SQLiteStore(".ralf/order.sqlite"), providers={}, tools=tools) as engine:
    handle = engine.submit(flow, {"order_id": "ORDER-1"}, command_id="read-1")
    print(asyncio.run(engine.drive(handle.run_id)))
```

Tool 节点允许 async 或同步 handler；同步调用走真实线程归属管理。输入必须是匹配 ToolSpec 的 JSON 对象，输出可按节点 Schema 验收。外部结果先保存回执，再采纳并完成节点；完成前崩溃不会再次派发已保存的效果。Tool 节点直接返回工具结果，不制造模型 Action 或会话 assistant 消息。依赖、条件和映射与[静态图](static-workflows.md)一致，当前仍串行。

Tool 节点的外部效果不可藏在纯 Transform 中。未知写效果继续等待核验；取消允许保存迟到证据，但不会执行后继节点。

## 3. 选择性接入 MCP 工具

```python
from ralf_agent import (
    MCPStdioTransport,
    MCPToolSource,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)


async def build_tools(peer_command):
    source = MCPToolSource(
        MCPStdioTransport(
            peer_command,
            version="business-server-1",
            timeout=30,
            # env={"PATH": "/usr/bin:/bin", "SERVICE_TOKEN": "..."},
        )
    )
    tools = ToolRegistry()
    names = await register_tool_source(
        tools,
        source,
        policies={
            "lookup_order": ToolPolicy(
                "1",
                effect="read_only",
                requires_approval=False,
            )
        },
        prefix="orders_",
    )
    return tools, names
```

peer_command 是明确的 argv，例如 `["/absolute/python", "/absolute/server.py"]`；不经过 shell。默认仅传入 PATH，所需凭据通过显式 env 提供；不要把秘密放入 command 参数。工作目录在构造时固定，行为版本需要反映服务、依赖和影响行为的配置变化。身份只记录环境字段名，密钥值不进入 Manifest；换密钥导致行为变化时也需要更新版本。

可以把返回的工具名加入 AgentSpec.tools，或者直接使用 GraphNode(tool=...)。注册只接入 policies 中明确选择的工具；同名冲突、缺失工具或无效策略会使整批注册失败。描述、输入／输出 Schema、宿主策略和源身份固定在工具 Manifest。

远端 annotations 不能授权。ToolPolicy 默认 `unqueryable_write`、审批开启、cost=1；可信宿主显式确认读操作后才能选择 read_only。`queryable_write` 需要自定义 reconciler。`idempotent_write` 需要 effect_key_argument，且下游服务必须真正按这个参数去重：

```python
policy = ToolPolicy(
    "1",
    effect="idempotent_write",
    requires_approval=True,
    effect_key_argument="request_id",
)
```

保留参数必须是远端 Schema 中声明的 string 属性。框架从调用方 Schema 移除它，拒绝调用方伪造，并注入 InvocationContext.effect_key。此默认映射要求平坦 object 根 Schema；带根级条件、引用或属性数量约束的 Schema 需要使用自定义 Source 做明确映射。

## 4. 独立替换与生命周期

ToolSource 的 identity 是非空 JSON，list_tools 与 call_tool 是 async：

```python
from ralf_agent import ToolDescriptor


class OrdersSource:
    identity = {"kind": "orders-source", "version": "1"}

    async def list_tools(self):
        return (
            ToolDescriptor(
                "lookup_order",
                "Read order state",
                {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                    "additionalProperties": False,
                },
            ),
        )

    async def call_tool(self, descriptor, arguments, context):
        return {"order_id": arguments["order_id"], "state": "ready"}
```

自定义 Source 可接 HTTP、RPC 或其他协议；来源对象由宿主管理，框架不会关闭借用连接。实际调用前后检查源身份，输入／结果必须是有限 JSON。影响隐藏依赖的改变需要诚实地更新版本。

MCPTransport 则负责 `async request(method, params, *, expected_tool=None) -> dict`。tools/call 前必须校验 expected_tool；默认 stdio 在同一会话中重新发现并比对固定描述；tools/list 会在该会话内消费所有分页，返回完整的有界工具列表，避免临时游标跨会话失效。自定义传输需要落实同等行为、身份和关闭契约；dev74提供[MCP HTTP候选子集](mcp-http.md)，OAuth／持久会话仍未交付。

stdio 每次操作启动独立会话，按 initialize → initialized → tools/list 或 tools/call 执行，结束时终止进程组并回收直接子进程。操作在框架跟踪的真实 worker 中运行；取消 asyncio Task 不能提前释放 Coordinator，服务退出前按[关闭指南](recovery-guide.md)等待真实工作结束。这是可信进程管理，未提供沙箱隔离。

默认限制：256 个工具、32 页、每条 JSON-RPC 消息 1 MiB、每个响应最多 100 条额外消息；整体超时大于 0 且不超过 300 秒。支持四个明确协议版本；ping 可响应，sampling／elicitation 等服务端请求返回不支持。结果保留 MCP content／structuredContent；isError、协议错误和输出 Schema 不符不会被视作成功。无自动写重试。

## 5. 兼容与后续能力

原 Agent／顺序 Workflow／Graph v1 的声明、默认身份和回执保持兼容。包含 Tool 节点的计划使用 v2；没有 Tool 的计划保持 v1。旧运行时会拒绝 v2，不能把历史任务在执行中迁移成新计划。生成的 MCP 工程以服务脚本摘要固定默认 peer 版本，修改脚本后需保留旧实现才能继续旧 Run。

本增量是 G2 工具路径的一部分。并行、动态 Plan、ChildRun／团队、MCP HTTP／OAuth／资源／提示、持久连接、CLI 沙箱、分布式执行与真实模型质量仍按[实现清单](implementation-status.md)交付。AgentScope 的组件组合和资源边界提供了参考，源码独立实现；这不表示整体能力已经达到 AgentScope。

[只读Workspace](workspace.md)提供文件／内存替换、三项受管理读取工具与async声明；root与caps由宿主固定，所有Action仍沿原执行权威。

工具源可选实现纯同步validate_tool_policy(descriptor, policy)；原注册路径仅接受完成后的None并在发布handler前拒绝惰性返回。Workspace源据此固定read_only，仍保留原PolicyGate／审批／效果协议。
