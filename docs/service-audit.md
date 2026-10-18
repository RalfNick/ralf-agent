# 服务身份与脱敏审计

`A2AApplication` 继续使用宿主异步 `authenticate(headers) -> Scope` 和同步
`engine_for_scope(scope)`，由原执行权威检查任务与资源授权。审计不会授予权限；
拒绝的请求不能因持有 Task ID、事件游标或审计引用而访问原任务。

## 默认使用与替换

```python
from ralf_agent import A2AApplication, ServiceAudit

audit = ServiceAudit()  # 默认最多1000条内存观察，不访问网络或磁盘
app = A2AApplication(
    engine_for_scope=engine_for_scope,
    spec=spec,
    inbox=inbox,
    authenticate=authenticate,
    url="http://127.0.0.1:8000/rpc",
    audit=audit,
)
records = audit.sink.records  # 不可变DTO元组；环形缓冲溢出见 audit.sink.dropped
failures = audit.failures    # sink失败次数，不含异常原文
```

`LocalA2AService(..., audit=audit)` 也可传入相同配置。省略 `audit` 保持关闭，
不改变原 Agent Card、RPC 请求／响应、业务状态、取消和资源关闭契约。

宿主可实现同步 `AuditSink.emit(record: AuditRecord) -> None`：

```python
import json
from dataclasses import asdict

class JSONLineSink:
    def __init__(self, stream):
        self.stream = stream

    def emit(self, record):
        self.stream.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")
        self.stream.flush()

# stream由宿主打开、设置访问权限并关闭；这是替换示例，不新增日志服务。
audit = ServiceAudit(JSONLineSink(stream), key=stable_secret_key)
```

sink是**借用资源**，框架不会关闭它。方法必须同步完成并及时返回；磁盘阻塞、
持久性、故障上报、访问权限和安全保留由宿主负责。原生async、generator方法在
构造时拒绝；意外的awaitable／其他非None结果计入失败，不执行其惰性主体。
需要异步持久日志的宿主应自行提供受管理的有界交接，不能把仅入队解释为耐久写入。

## 记录语义与脱敏范围

每条 `AuditRecord` 仅包含以下固定字段：

| 字段 | 内容 |
| --- | --- |
| `version`, `event_id`, `timestamp` | 固定格式版本1、独立UUID、宿主墙钟秒数；不表示业务顺序 |
| `operation` | 已知RPC方法；任意未知方法统一为`unsupported` |
| `outcome` | `rpc_ok`、`unauthorized`、`not_found`、`invalid_request`、`rpc_error`、`internal_error`、`disconnected`、`cancelled`、`timeout`之一 |
| `scope_ref` | 已认证Scope的HMAC引用；无可信身份时为空 |
| `request_ref`, `task_ref`, `message_ref`, `command_ref` | RPC请求、Task、message、显式命令／原控制回执的分域HMAC引用；未知时为空 |

正文、工具参数、结果、错误详情、认证header/token、游标、原始身份与ID均不入记录。
默认每个实例生成随机32字节密钥，只在本实例内关联。宿主传入至少32字节的秘密
`key` 才能跨重启关联；应安全保存、控制使用与轮换，密钥不进入记录。
关联按`scope_ref`与其他引用一起判断，不把同名跨Scope命令视作同一命令。

`command_ref`记录显式控制命令或原返回回执，不从观察者重建新的业务身份。
默认合成的取消命令、仅按message读取原Task等路径可能没有完整命令／message引用。
中断前未收到原结果时，Task引用也可能为空；可通过已知message回读原权威回执。

`rpc_ok`仅表示RPC方法已返回，**不证明HTTP送达、业务完成、命令耐久接受或审计耐久写入**。
记录发生在最终响应发送前；响应大小限制、发送失败和调用方断连可能使结果无法送达。
超时／取消同样只是观察事实，不能推断原业务没有执行，应沿原message／command回读。
公共发现Card和非RPC路径的404不记录为业务审计。

## 故障与验收边界

审计是best-effort观察：sink异常、意外的惰性返回或sink自行抛出的`CancelledError`
只增加失败计数，不改变已接受的业务回执，不自动重试业务。调用方真正的Task取消
仍正常传播；既有Run的托管和恢复责任保持原契约。进程崩溃可能遗漏记录，默认缓冲
重启即丢失、满容量丢弃最旧观察。需要强制耐久审计的宿主应单独验收其入口与存储策略。

这套观察不替代命令／效果日志，也不提供清理它们的权限。完成数据维护沿独立的原权威入口：
[Local工作消息压缩](local-retention.md)与[Temporal／PG冗余效果副本清理](temporal-retention.md)，
均保留原效果、幂等及恢复证据，不能用审计引用授予删除权限。

## 所选实际证据

普通Agent已在真实HTTP／Temporal／PostgreSQL组合验证两位有效调用者、七类越权拒绝、
宿主重启、原控制／消息回执、一次效果与审计关联；同一440产品wheel两场景2项通过。
资源授权交集隔离安装另52项通过。范围与原始证据见[验收记录](../architecture/reviews/2026-10-18-temporal-scope-audit.md)。
该测试宿主认证适配与结构化Provider不证明通用认证平台、耐久合规日志或真实模型质量。
后续442产品wheel同包重跑上述真实身份审计2项，并验收PG保留；[P3-4门槛核对](../architecture/reviews/2026-10-18-temporal-effect-retention.md#p3-4门槛核对与后续)保留各原制品归属。
