# MCP HTTP 工具接入

`MCPHTTPTransport` 提供固定目标的 HTTP JSON／POST SSE 工具传输，可替换现有
stdio Transport；Agent／Workflow仍使用相同MCPToolSource、授权、审批和效果协议。
每次发现或调用独立握手，调用前在同一远端Session重新校验固定工具描述。

## SDK

```python
from ralf_agent import (
    MCPHTTPTransport,
    MCPToolSource,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)

transport = MCPHTTPTransport("https://your-mcp.example/mcp", version="business-v1")
source = MCPToolSource(transport)
tools = ToolRegistry()
try:
    names = await register_tool_source(
        tools,
        source,
        policies={
            "lookup": ToolPolicy("1", effect="read_only", requires_approval=False),
        },
        prefix="business_",
    )
    # 将 names 放入 AgentSpec.tools 或 GraphNode(tool=names[0])。
    # 先结束／排空使用 tools 的运行，再关闭应用拥有的传输。
finally:
    await transport.aclose()
```

直接注册借用Source／Transport，应用负责关闭；工厂拥有其创建的Transport。
支持协议2025-11-25、2025-06-18、2025-03-26。发现最多32页、256工具，分页游标
不跨Session；远端工具描述变化在tools/call前拒绝。远端annotations不能授予权限。
发现时input／output Schema中`$ref`／`$dynamicRef`仅允许`#`本地片段；不会下载外部Schema。
此准入递归检查整个Schema树，包括示例数据；需要外部Schema资源的服务应预先内联或使用显式离线注册的自定义传输。

## 声明装配

Local／Temporal原异步Builder使用`tools/mcp-http`：

```json
{
  "adapter": "mcp-http",
  "config": {"servers": [{
    "url": "https://your-mcp.example/mcp",
    "version": "business-v1",
    "prefix": "business_",
    "policies": {"lookup": {
      "version": "1", "effect": "read_only", "requires_approval": false
    }}
  }]}
}
```

config仅包含1–32个servers；每项必须url/version/policies，另可有prefix/headers/
timeout/max_message_bytes/max_operation_bytes。每个policies明确选择1–256个工具，
使用原ToolPolicy基本字段。同步build在分配前拒绝并提示abuild。构建先纯预检，
再拥有Transport并发现；Schema保留effect key及名称冲突继续按原Registry规则校验。
部分发现失败排空已拥有资源。可查询写的Python reconciler由SDK显式提供。

## 数据与生命周期

固定HTTP(S) URL禁止凭据、query、fragment、空白／控制字符；禁环境代理、重定向、
自动业务重试和压缩。显式头被复制，发布仅保存头名和值摘要；不把秘密写入字面Profile。
JSON framing及Accept／MCP-Session-Id／MCP-Protocol-Version／Last-Event-ID由传输拥有，
宿主不得覆盖。远端Session ID仅存在于这次操作，不作为Run／发布身份。

默认每消息1 MiB、整个操作8 MiB；消息可设1–16777216字节，操作必须覆盖消息且
不超过67108864字节。操作额度包括发送JSON及消费的响应字节；清理不采纳响应正文。
接受有限UTF-8 JSON，拒绝重复键／surrogate／非有限数字／错RPC ID及错误结果。
SSE事件、注释和多行data同样有界，CRLF完整计量；整个操作合计最多100条额外消息，ping可回复，其余服务端请求
明确拒绝，不执行sampling／elicitation等隐藏能力。

调用方取消或超时不证明远端业务已停止。原Source和ambient线程归属保留实际socket、
response、Client退出；关闭停止准入并排空，可取消后再次等待。timeout默认30秒，
范围(0,300]；socket I/O与操作间deadline不是硬墙钟或DNS上限。
HTTP Session DELETE是best-effort，405允许，失败不覆盖已确认回包；实际Client仍须退出。

写操作使用原保留字段与effect key。提交后响应丢失不能解释为未执行：Local按原幂等
恢复规则处理；Temporal保留未知效果，query只核验，不重发原handler，包括idempotent工具。
需要可核验的SDK reconciler或宿主业务回执才能解除等待。恢复不通过新握手偷偷重发写请求。

本批未提供GET流恢复、持久跨操作Session、OAuth、旧HTTP+SSE端点fallback、resources/
prompts/tasks和所有MCP服务的兼容保证。依赖这些能力的服务需替换Transport或后续适配。
协议参考[官方传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)和
[生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)。
[本批验收](../architecture/reviews/2026-10-11-mcp-http.md)记录真实服务／安装／恢复证据。
