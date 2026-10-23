# Temporal 期限与执行策略配置

日期：2026-10-14。`TemporalExecutionPolicy` 已能直接注入 SDK `TemporalRuntime`。dev114 已将其接入 Temporal Profile 的 `components.execution_policy`，源码与安装包的配置／实际恢复验收通过；仅本地提交，不代表已公开发布。阶段要求见[支持矩阵](phase3-support-matrix.md)。

## 策略职责

策略由原 Temporal History 采纳，约束 Run 期限、审批期限、后代数量／并发／深度和工具允许集合。它不创建新的 Run 状态机，不承担调用者认证，也不替代每 Agent 能力绑定、宿主授权、效果核验或实际处理器生命周期。

| 字段 | 缺省值 | 约束与用途 |
| --- | --- | --- |
| `version` | `"1"` | 非空版本文本；参与策略身份 |
| `max_children` | `256` | 原生整数 1–256；拒绝 bool |
| `max_concurrency` | `32` | 原生整数 1–32；拒绝 bool |
| `max_depth` | `8` | 原生整数 1–8；拒绝 bool |
| `run_timeout_seconds` | `null` | 有限正数，不超过 86400 秒；`null` 不增加 Run 期限 |
| `approval_timeout_seconds` | `null` | 有限正数，不超过 86400 秒；`null` 不增加审批期限 |
| `allowed_tools` | `null` | 工具名称列表；`null` 不增加此策略的 allowlist，空列表表示不允许任何工具。原能力绑定／授权仍生效 |

内置 `bounded` 工厂复用这些字段校验；拒绝未知字段、非有限数、bool 期限和越界容量。在 Profile 装配的准备阶段完成校验，不能先创建 Provider、连接数据库或启动 Worker，再发现内置配置无效。

省略整个 `execution_policy` 声明保留既有默认行为和发布声明。显式声明即使字段采用默认值，也固定了一个策略身份；不要为了追求相同摘要而删除显式策略。策略变更使用新的不可变 Profile 版本，原已接受 Run 继续使用原发布。

## SDK 与声明示例

现有直接注入方式：

```python
from relf_agent import TemporalExecutionPolicy, TemporalRuntime

runtime = TemporalRuntime(
    providers=providers,
    tools=tools,
    execution_policy=TemporalExecutionPolicy(
        run_timeout_seconds=300,
        approval_timeout_seconds=120,
        max_concurrency=4,
    ),
)
```

`providers`、`tools` 和服务生命周期由应用显式装配。以下是已支持的完整 JSON Catalog；离线 Echo 用于验证入口，不证明模型业务质量：

```json
{
  "kind": "temporal-profiles",
  "schema_version": 1,
  "default": {"name": "governed", "version": "1"},
  "profiles": [{
    "name": "governed",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "components": {
      "execution_policy": {
        "adapter": "bounded",
        "config": {
          "run_timeout_seconds": 300,
          "approval_timeout_seconds": 120,
          "max_concurrency": 4
        }
      }
    }
  }]
}
```

对应 TOML：

```toml
kind = "temporal-profiles"
schema_version = 1

[default]
name = "governed"
version = "1"

[[profiles]]
name = "governed"
version = "1"

[profiles.providers.default]
adapter = "offline-echo"

[profiles.components.execution_policy]
adapter = "bounded"

[profiles.components.execution_policy.config]
run_timeout_seconds = 300
approval_timeout_seconds = 120
max_concurrency = 4
```

装配继续使用原 `TemporalProfileCatalog.from_file(...)` 和 `TemporalRuntimeBuilder.abuild(...)`，示例见[Profile 指南](temporal-profiles.md)。`execution_policy` 是 Temporal 组件声明，不能放到只接受布尔开关的 `execution` 字段，也不作为 Local Profile 的隐式策略。

## 替换与资源所有权

`ComponentRegistry` 已开放 `execution_policy` 种类，支持同步工厂和显式 `register_async` 工厂。自定义工厂应返回 `TemporalExecutionPolicy`，通过自身 validator 提前检查配置；错误返回值明确拒绝；显式返回 `None` 不能将声明降级为省略策略。

```python
from relf_agent import ComponentRegistry, TemporalExecutionPolicy

registry = ComponentRegistry()

def validate_policy(config):
    TemporalExecutionPolicy(**config)

def policy_factory(config, context):
    return TemporalExecutionPolicy(**config)

registry.register(
    "execution_policy", "business-policy", policy_factory,
    validator=validate_policy,
)
```

Profile 使用 `adapter="business-policy"` 选择此工厂。validator 必须同步返回 `None` 或抛验证错误；任意自定义工厂的 I/O 和副作用仍由实现者承担，不能把内置预检保证推广到未经验证的第三方行为。

策略本身是不可变值，没有需关闭的客户端。工厂创建附属资源时，沿原 `BuildContext.own/own_async` 登记 owned 资源，未登记为 borrowed；Assembly 沿原创建循环排空真实工作，再关闭 owned 资源。借用的 Temporal Client 不由 Assembly 关闭。

## 期限、等待与恢复

Run 期限属于业务执行策略。已有 Temporal 实现到期后提交原 Run 的取消语义并记录 `deadline_exceeded`；审批期限从原审批等待开始固定，到期仍未批准时记录 `approval_expired`。重复驱动不能刷新审批期限。调用方等待超时、取消观察或 HTTP 断连不应改变业务期限或替代显式取消。

到期或终态不证明实际模型、工具或线程已经结束。保留原预算预留、未知效果和资源占用，晚到证据按原 Action／History 采纳；排空、结算与物理停止分别验证。不能因为 Run 显示 cancelled 就启动另一份可能重复写入的业务操作。

重启必须保留原 Profile、策略、Scope、namespace、队列与数据身份，并使用匹配的原 Worker。默认别名变化不能更新已接受 Run 的期限。实验 Coding／编排发布还包含精确源码指纹；声明默认兼容不代表当前 Worker 可代替任何旧 Worker，需遵守原发布匹配门槛。

本批已验证内置预检、SDK／JSON／TOML、同步／异步替换及 owned 清理。源码／安装各 313 项受影响检查通过、2 项其他远程配置跳过；各 4 项实际 Temporal／PG 场景零跳过，核对重启前后原到期事件、Action 时间与完整 TimerStarted 记录一致、重复审批一次写入、晚到原回执和 owned 关闭。默认 Profile 与完整 Manifest 字节相同；选定 Coding 编排的 Worker 指纹发生变化，旧 dev113 原发布由当前 Worker 明确拒绝，须保留匹配的不可变 Worker。见[验收登记](../architecture/reviews/2026-10-14-temporal-policy-profiles.md)。Local Run／审批期限、部署准入容量、HTTP 管理、身份 ACL、保留清理和框架备份恢复属于后续必需批次，本入口不会自动补齐这些能力。
