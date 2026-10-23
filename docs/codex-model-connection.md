# Codex Coding 的显式模型连接

连接配置把 Responses endpoint、模型和凭证引用固定到原 Coding Runner。
Local 使用 `tools/codex-coding-connected`；Temporal 使用
`tools/codex-coding-connected-postgres`。两者沿用原 Action 的审批、预算、阶段授权、
一次 attempt、停止证据和结果采纳。连接选择不会授予新的执行权限。

本页说明已实现的声明和资源责任。示例中的 endpoint/model 是配置数据；装配成功、
本地账户认证成功均不证明远端 Responses 兼容、配额可用或真实 Coding 任务质量通过。
示例 `offline-echo` 只用于装配检查，不会提出 Coding 工具调用。

### DeepSeek 协议兼容核验（2026-10-14）

DeepSeek [官方 Responses 指南](https://api-docs.deepseek.com/guides/responses_api/)
已声明原生支持该协议，endpoint 为 `https://api.deepseek.com`。本日独立有界
真实请求使用 `deepseek-flash`／reasoning `low`：文本、SSE 终态与 `tool_choice=auto`
函数调用均返回 HTTP 200；函数参数正确。两次显式指定函数的工具选择请求返回
HTTP 400，服务端说明思考模式不支持该 `tool_choice`。该失败记录保留，不能将
“兼容 Responses”理解为接受全部参数组合。

本次是直接接口 smoke，没有运行新的 Codex Thread／Turn 或质量任务集；既有 dev109
9/9 原生 Coding 质量证据保持其原版本范围。官方接口还不支持服务端
`previous_response_id`／conversation 持久续接，因此恢复仍依赖原原生状态和 RALF
执行权威。凭证通过禁止回显的 stdin 进入测试进程，仅保存非敏感报告，未改全局配置。

## 非敏感连接字段

每个工具条目增加 `connection`，其余字段保持原 Local 或 Temporal 声明格式。
`CodexModelConnection` 的构造、`identity` 和配置读取均不解析凭证。

| 字段 | 含义 |
| --- | --- |
| `base_url` | 固定 HTTPS Responses provider endpoint；拒绝 userinfo、query、fragment 和路径中的 `.`/`..`。 |
| `model` | 固定模型名称。 |
| `credential_env` | 可信宿主环境变量的**名称**，不是凭证值。 |
| `credential_id` | 非敏感凭证引用，参与身份固定；默认 source 不把它解释为外部密钥库查询。 |
| `generation` | 调用方提供的非敏感版本标识，参与身份固定。 |
| `reasoning_effort` | 可选，默认 `low`；接受 `none`、`minimal`、`low`、`medium`、`high`、`xhigh`。是否受远端模型支持仍需实际验证。 |

`api_key`、token、任意认证 header、env 值或额外字段不能放进 `connection`。
默认 `EnvironmentCodingCredentials` 在原 Action 已获准准备资源、完成原生控制检查后，
才从可信父进程读取 `credential_env` 指定的值。凭证不进入 Docker Env/argv、原生配置、
Run/Action identity、History 或 journal。父进程和原生进程的 RAM 不保证零化。

同一连接依次完成固定控制检查、初始空账户读取、一次 API-key 登录和最终账户读取。
登录响应、两条通知和 read barrier 按固定原生协议校验；generic `request` 不能调用
account 方法。后续认证流量会使连接失败，不进入业务事件 inbox。
原生 `account/rateLimits/updated` 是额度观察通知：仅在已认证业务阶段按固定协议
校验并丢弃，不改变执行预算。四类纯进度片段（回答、推理正文、推理摘要、命令输出）
同样在严格校验后丢弃，单连接上限 16,384 项，避免 token 洪峰挤占终态队列。
终态、错误和交互请求继续由原逻辑处理；最终结果仍通过原 `thread/read` 采纳。
这些检查提供本地认证证据，模型请求失败仍按原 unknown/reconciliation 规则处理。

## Local：SDK、JSON 和 TOML

先准备已有 Docker executable、Unix socket、代码固定的镜像与环境资产，以及属于
当前用户、权限 `0700`、无符号链接的 Runner 根目录。配置路径须为规范绝对路径；
journal 父目录须存在。长期恢复应使用调用方保留的持久私有目录。
物理前提见[环境指南](codex-coding-environment.md)。

下面路径是示例，须换为宿主实际固定位置。工厂只核对资源和打开 journal，构造不会
创建容器、解析模型凭证或发送 Thread/Turn。

```python
import asyncio

from relf_agent import BindingSelection, RuntimeBuilder, RuntimeProfile, Scope

entry = {
    "name": "coding",
    "description": "Execute one approved contained Coding task.",
    "cost": 1,
    "runner_root": "/private/tmp/ralf-connected/runner",
    "journal_path": "/private/tmp/ralf-connected/runner.sqlite",
    "fixed_dependencies": {"deployment": "connected-example-1"},
    "docker_executable": "/usr/local/bin/docker",
    "docker_host": "unix:///var/run/docker.sock",
    "request_timeout": 30,
    "connection": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "credential_env": "CODING_MODEL_KEY",
        "credential_id": "coding-primary",
        "generation": "1",
        "reasoning_effort": "low",
    },
}
runner_binding = {
    "role": "runner", "component_id": "native", "version": "1",
    "component": {"adapter": "registered-tool", "config": {"name": "coding"}},
}
profile = RuntimeProfile(
    "connected", "1",
    {"default": {"adapter": "offline-echo"}},
    components={"tools": {"adapter": "codex-coding-connected", "config": entry}},
    binding_components=[runner_binding],
)

async def main():
    runtime = await RuntimeBuilder().abuild(profile, "/private/tmp/ralf-connected/runs.sqlite")
    try:
        runner, _ = runtime.binding_catalog.resolve(
            "runner", BindingSelection.ref("native", "1"), Scope(),
        )
        assert runner is runtime.tools.get("coding").handler.runner
    finally:
        await runtime.aclose()

asyncio.run(main())
```

`runner/registered-tool` 借用已注册工具的同一个实际 Runner，不创建第二个 owner。
Agent 仍需显式选择 `coding` 工具，真正执行仍须原审批。
工厂接受一项完整 `entry`，或 `{"tools": [entry, ...]}`，最多 16 项；不能混用两种形式。
多工具名称、根目录和 Local journal 路径须互不冲突。

JSON 使用 `schema_version=2` 的 Local catalog。将上述完整 `entry` 放入
`profiles[0].components.tools.config`，绑定放入 `profiles[0].binding_components`。
可直接用 SDK 示例中的非敏感数据生成等价 JSON：

```python
import json
from pathlib import Path
from relf_agent.runtime_config import load_catalog

path = Path("runtime.json")
path.write_text(json.dumps({
    "schema_version": 2,
    "default": {"name": "connected", "version": "1"},
    "profiles": [{
        "name": "connected", "version": "1",
        "providers": profile.providers,
        "components": profile.components,
        "binding_components": profile.binding_components,
    }],
}))
json_profile = load_catalog(path).default
# await RuntimeBuilder().abuild(json_profile, 固定的执行数据库路径)
```

等价 TOML 的单工具配置如下，读取方式为 `load_catalog("runtime.toml").default`：

```toml
schema_version = 2
[default]
name = "connected"
version = "1"
[[profiles]]
name = "connected"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.tools]
adapter = "codex-coding-connected"
[profiles.components.tools.config]
name = "coding"
description = "Execute one approved contained Coding task."
cost = 1
runner_root = "/private/tmp/ralf-connected/runner"
journal_path = "/private/tmp/ralf-connected/runner.sqlite"
docker_executable = "/usr/local/bin/docker"
docker_host = "unix:///var/run/docker.sock"
request_timeout = 30
[profiles.components.tools.config.fixed_dependencies]
deployment = "connected-example-1"
[profiles.components.tools.config.connection]
base_url = "https://api.deepseek.com"
model = "deepseek-flash"
credential_env = "CODING_MODEL_KEY"
credential_id = "coding-primary"
generation = "1"
reasoning_effort = "low"
[[profiles.binding_components]]
role = "runner"
component_id = "native"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tool"
[profiles.binding_components.component.config]
name = "coding"
```

## Temporal：原 PostgreSQL owner

`tools/codex-coding-connected-postgres` 用于显式
`TemporalProfile.execution={"coding_execution": True}`。它要求已声明的原
`effect_journal`，并借用同一个具体 `PostgresEffectJournal`；相同 DSN 或相等 identity
的另一对象不能代替该 owner。Local `RuntimeBuilder` 拒绝这个 adapter。

工具条目与上面的 `entry` 相同，但**移除 `journal_path`**；多个工具须使用同一份
`fixed_dependencies`，并保留独立 Runner 根目录。配置不接受 env、mounts 或任意原生
配置覆盖。Temporal 服务、PostgreSQL 和 Docker 前提由部署方提供。

```python
from relf_agent import TemporalProfile, TemporalRuntimeBuilder

pg_entry = {name: value for name, value in entry.items() if name != "journal_path"}
temporal_profile = TemporalProfile(
    "connected", "1", {"default": {"adapter": "offline-echo"}},
    components={
        "effect_journal": {
            "adapter": "postgres",
            "config": {
                "dsn_env": "CODING_DSN", "backend_id": "coding-effects",
                "initialize": True,
            },
        },
        "tools": {"adapter": "codex-coding-connected-postgres", "config": pg_entry},
    },
    execution={"coding_execution": True},
    binding_components=[runner_binding],
)
# 在同一个 async 调用中：
# assembly = await TemporalRuntimeBuilder().abuild(temporal_profile)
# try: ... 使用原 Worker / Engine 接口 ...
# finally: await assembly.aclose()
```

Temporal JSON/TOML 使用 `kind="temporal-profiles"`、`schema_version=1`，通过
`TemporalProfileCatalog.from_file(path).default_profile` 读取。相对于上面的 Local TOML：
把 adapter 改为 `codex-coding-connected-postgres`，删除 `journal_path`，增加：

```toml
[profiles.execution]
coding_execution = true
[profiles.components.effect_journal]
adapter = "postgres"
[profiles.components.effect_journal.config]
dsn_env = "CODING_DSN"
backend_id = "coding-effects"
initialize = true
```

完整 Worker/Engine 接口见[Temporal Coding 指南](temporal-coding.md)。本页新增连接声明
不改变原 History 的执行权威，也不把装配测试或结构化 process peer 当作真实模型质量成绩。

## 所有权、凭证 source 与恢复

Local 工厂拥有其创建的 Runner 和 `RunnerJournal`，Runtime 异步关闭先排空/停止执行，
再关闭 Runner、释放 journal 租约。Temporal 工厂拥有 Runner 和 journal view；view 借用
原 EffectJournal，assembly 最后关闭它所拥有的 EffectJournal/连接。绑定只借用 Runner。
关闭失败保留原资源账本供同一事件循环重试，不能把未确认的停止当作完成。

直接 SDK 使用可显式构造 `ConnectedCodexCodingRunner(root, connection=connection,
credential_source=source, journal=journal, ...)`。自定义 source 实现
`relf_agent.codex_credentials.CodingCredentialSource` 的 `identity` 属性和
`async resolve(connection: dict) -> str`：identity 须为有界非敏感 JSON，resolve 实现须
可验证。source 返回值只供原 startup phase 使用，错误转换为固定非敏感失败。
凭证字符串当前限制为 1–8192 个可打印 ASCII 字符（码点 33–126）。

source 是**借用资源**；其拥有者负责内部客户端、锁和 `aclose`，Runner 不代为关闭。
直接 SDK 注入的 journal 同样由调用方负责在 Runner 关闭后关闭。内置 JSON/TOML adapter
使用默认环境 source，没有 `credential_source`、任意 secret resolver 或密钥库配置字段。
需要自定义 source 时，在可信 SDK 装配中显式提供，不把 Python 对象或凭证塞进声明。

凭证值变化不会读取或改变构造时的 identity；改变非敏感连接/source 身份会被拒绝。
冷恢复和关闭使用原资源/journal/History 证据，不重新解析凭证，不重投登录或业务请求。
恢复须保留匹配的原 Profile、Runner 身份、journal、Scope、namespace 与实际物理资源；
跨宿主接管和真实任务质量应以各自的实际验收证据为准。
