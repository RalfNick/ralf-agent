# 固定目标 HTTP JSON 工具

`HTTPToolSource` 通过原 ToolSource／ToolRegistry 接入可信业务 HTTP 接口。
宿主固定 URL、POST、Schema、版本和显式头；模型只提供 JSON 参数。
授权、审批、effect key、未知效果与恢复仍由原 Engine／Temporal History 管理。

## SDK 注入

```python
from relf_agent import (
    HTTPToolSource,
    ToolDescriptor,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)

registry = ToolRegistry()
source = HTTPToolSource(
    ToolDescriptor("lookup", "Lookup", {"type": "object"}),
    "https://your-business.example/lookup",
    version="lookup-v1",
    headers={},
)
await register_tool_source(
    registry,
    source,
    policies={"lookup": ToolPolicy("1", effect="read_only", requires_approval=False)},
)
# 应用拥有独立 Source；直接注册只借用它。
# 应用退出时先等待执行，再关闭：
await source.aclose()
```

API 不接受运行输入提供 URL、方法或头，不跟随重定向，不自动重试；默认不读取
环境代理、Cookie 或凭据。HTTP(S) URL 不允许凭据、查询、fragment、空白／控制字符。
显式 headers 被复制，identity 仅保存头名和值摘要；不将秘密放入 URL 或字面 Profile。
原实际端点／DNS／服务实现及凭据权限仍由宿主负责。

默认输入和响应正文各限1 MiB，可设1–16777216字节。输入是 canonical UTF-8 JSON，
响应必须为HTTP 2xx、一个有限 UTF-8 JSON 值，并符合可选输出Schema；重复键、
孤立surrogate、非有限数字、无效／过量正文均拒绝。错误不携带URI、头、正文或
服务诊断。Content-Type固定JSON，Accept-Encoding固定identity；压缩响应拒绝，
避免无界解压。显式头禁止Host／Content-Length／Transfer-Encoding／Content-Type／
Accept-Encoding及大小写重复字段。GET、映射、流式业务响应、凭据代理另行支持。

## 生命周期与效果

每次调用拥有同步httpx.Client，沿原ambient和Source实际线程跟踪器执行并关闭。
取消调用方等待不会取消远端业务；Source停止准入、请求停止并等待真实处理器及
客户端关闭。关闭被取消可再次等待。`wait_for_calls()`只等待本Source真实调用。
timeout为(0,300]秒，限制各socket I/O并在操作间检查总deadline；它不是硬实时的
远端停止／墙钟上限。被阻塞的socket等待仍需实际退出，不能提前释放执行权。

下游请求可能已提交但响应丢失。idempotent_write通过原保留字段注入Action的
稳定effect key，下游负责幂等；unqueryable_write保留核验等待，不会盲目重发。
JSON工厂不接受Python reconciler；可查询写入由宿主使用SDK自定义注册。
任何工具成功回包均不替代业务Verifier，也不保证任意操作恰好执行一次。

## async 声明装配

`RuntimeBuilder.abuild`和`TemporalRuntimeBuilder.abuild`共用`tools/http-json`。
组件config只接受1–256个tools；每项必须有descriptor/url/version/policy，另可有
prefix/headers/timeout/max_input_bytes/max_output_bytes。未知字段和重复名称在
分配前拒绝，工厂通过原owned ledger关闭Source，部分构造失败也排空已拥有资源。
同步装配在分配前拒绝并提示abuild。

```json
{
  "adapter": "http-json",
  "config": {"tools": [{
    "descriptor": {"name": "lookup", "description": "Lookup", "input_schema": {"type": "object"}},
    "url": "https://your-business.example/lookup",
    "version": "lookup-v1",
    "policy": {"version": "1", "effect": "read_only", "requires_approval": false}
  }]}
}
```

Temporal写工具仍需耐久EffectJournal；本适配器不增加执行数据库／Authority。
可以用另一ToolSource或显式组件工厂替换接口。CLI完整起步示例见[CLI指南](cli-tools.md)。
本轮[验收记录](../architecture/reviews/2026-10-11-fixed-business-tools.md)区分离线／
本机真实服务／安装恢复证据和未完成门槛。完整R12及框架对齐继续开放。
