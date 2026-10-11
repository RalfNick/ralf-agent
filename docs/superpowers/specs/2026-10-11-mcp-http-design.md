# MCP HTTP 工具传输设计

基线为已提交 dev73／7f82970。持续开发、本地提交、不推送沿用户授权执行。
本增量覆盖 R12/H4 的固定目标 MCP HTTP 子集，复用 MCPTransport、MCPToolSource、
ToolPolicy、真实线程追踪和原执行权威；不将外部 MCP 会话当作 RALF Run。

选用每次操作独立握手的有界传输，与现有 stdio 的独立会话边界一致。常驻共享连接
需要额外会话租约、重连与流路由，本批不引入；用户仍可替换 MCPTransport。

## 接口与固定身份

`MCPHTTPTransport(url, *, version, headers=None, timeout=30,
max_message_bytes=1048576, max_operation_bytes=8388608)` 实现既有 async
`request(method, params, *, expected_tool=None)`，`wait_for_calls()`、`aclose()`。
只接受 tools/list 的空参数和 tools/call 的明确名称／参数／固定描述。
方法、URL、头不可由模型输入选择。URL 和头沿 dev73 的纯校验；另拒绝宿主提供
Accept、MCP-Session-Id、MCP-Protocol-Version、Last-Event-ID，避免覆盖握手状态。
identity 固定 kind=mcp-http/version=1、行为版本、URL、头名及值摘要、全部上限；
瞬时会话 ID 不进入发布或诊断。超时(0,300]，消息上限1–16777216字节，
操作上限不小于消息上限且不大于67108864字节，普通整数拒绝bool。

## 握手、调用与数据

每操作拥有一个 sync httpx.Client，禁环境代理、重定向、压缩和自动业务重试。
请求固定 POST；Accept 声明 application/json、text/event-stream。支持返回 JSON
及 POST SSE；有限 UTF-8 JSON、重复键／孤立surrogate／非有限数拒绝。
initialize 请求2025-11-25，接受2025-11-25／2025-06-18／2025-03-26；核对tools能力。
initialized通知必须202且空正文。之后所有请求携带协商版本；若初始化返回Session ID，
必须为1–256个可见ASCII字符，后续携带原ID，禁止非初始化响应更换ID。

JSON-RPC 单对象，jsonrpc=2.0、响应id普通整数与请求一致、result/error二选一，
result必须对象；错误统一脱敏。发现的input／output Schema中$ref／$dynamicRef只允许#片段，外部资源拒绝，避免默认验证器在传输边界之外读取网络。SSE接受LF／CRLF／CR、分块UTF-8、BOM、注释、
空data及多行data；逐事件和整个操作字节有界。只采纳message／默认事件的JSON-RPC。
整个操作合计最多100条通知／服务端请求；ping回{}，其他服务端请求回-32601，回复POST必须202空。
不授予sampling／elicitation／roots能力，不从服务端内容隐式运行本地工具。

tools/list最多32页／256工具，不重复名称或游标，全部页在同一初始化Session消费。
tools/call先在该Session重新发现并比较规范化固定ToolDescriptor；不符在业务调用前
拒绝。回包仍由MCPToolSource验收content／structuredContent／输出Schema。
HTTP404／错误／EOF／断流／超时不自动重发tools/call，尤其写请求已提交但无回包时，
由原未知效果与幂等／核验协议恢复。新操作重新握手，不继承旧游标。

HTTP Session DELETE作为best-effort清理，405允许；清理失败不覆盖已确认结果，
但实际response／Client关闭必须结束后才释放线程归属。取消／超时不证明远端业务停止。
本批不提供GET恢复流、持久Session、OAuth、旧HTTP+SSE端点fallback、tasks/resources/
prompts或完整MCP客户端一致性。无法处理的协议返回类型化失败，不能伪装工具成功。

## 生命周期与装配

沿原source／ambient实际ThreadExecutionTracker，使用和dev73相同的register/begin/
finish/withdraw规则；关闭停止准入、设置停止请求并排空真实处理器与Client退出。
已取消等待、已关闭原循环和队列未派发均有实际测试。socket timeout与操作间deadline
不承诺硬墙钟上限／DNS限时／远端取消。SDK借用传输；工厂在发现前own_async。

异步 `tools/mcp-http` 声明 config={servers:[1..32]}；每项必须url/version/policies，
可有prefix/headers/timeout/max_message_bytes/max_operation_bytes。policies为1–256
明确名称到原ToolPolicy基本字段。纯预检校验结构、URL、头和Policy；发现后校验
保留effect key的实际Schema与本地名称冲突。部分构建失败排空原owned ledger。
同步装配分配前提示abuild。支持原Local／Temporal工具链路，不新增状态机。

## 验收

真实本机HTTP JSON／SSE协议、分页、错误、固定描述、严格字节／编码、停止／关闭；
原MCP stdio、CLI／HTTP及默认发布兼容；Local审批／响应丢失／幂等一次效果；实际
Temporal＋PG审批重启／History replay；安装核心／扩展包、22个原模板及旧73恢复。
一次最终独立只读审查、统一Important RED→GREEN、冻结全回归／制品／服务退出后
本地提交。完整R01–R26/H1–H5/M1继续开放，不调用真实模型。

协议依据：[固定版本传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、
[生命周期](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)，读取于2026-10-11。
