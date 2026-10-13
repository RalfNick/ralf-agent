# Local Coding 的显式 Runtime Profile

Coding Profile 在原 Local RuntimeBuilder 中装配有限的 `CodexCodingRunner`。
一个 Profile 可声明 1–16 个独立 Runner；每个工具名称对应自己的私有根目录和
RunnerJournal。`runner/registered-tool` 只借用该工具已经注册的实际 Runner，
不另造资源，也不重复关闭。原 Local Engine／SQLite 继续拥有审批、预算、阶段授权、
结果、unknown 与终态。

本页展示声明和装配。示例使用 `offline-echo`，不会请求 Coding 工具；装配成功不表示
原生认证、真实模型 Turn 或模型质量已经通过。真实执行仍须遵守
[原 Action 委托](local-coding-delegation.md)和
[委托契约](../architecture/specs/delegated-coding-action-contract.md)。

## 固定资源的前提

以下三个格式使用相同的路径。使用前把 Docker 可执行文件和 Unix socket 改为当前
宿主的实际固定位置，并准备根目录：

```sh
mkdir -p /private/tmp/ralf-coding-profile/runner-a /private/tmp/ralf-coding-profile/runner-b
chmod 700 /private/tmp/ralf-coding-profile /private/tmp/ralf-coding-profile/runner-a /private/tmp/ralf-coding-profile/runner-b
```

Runner 根目录必须存在、属于当前用户、权限为 `0700`，且不是符号链接。
各 Runner 的根目录不能相同、嵌套或通过物理别名共享；journal 路径和 `.owner` 租约
路径也不能冲突。Journal 的父目录须已存在，路径组件不能是符号链接；journal 文件
由工厂创建或核对。所有配置路径须为规范的绝对路径。需要长期保留冷恢复证据时，
将示例 `/private/tmp` 路径换为由调用方保留的私有持久目录。

示例假定 `/usr/local/bin/docker` 是已有、可执行的 Docker 客户端，
`unix:///var/run/docker.sock` 是实际 Docker Unix 端点。声明不自动寻找客户端、
安装 Docker、下载资产、读取宿主认证或挂载调用方指定路径。

原生环境使用代码固定的 Codex 0.144.4 候选配置、seccomp 和镜像 ID：
`sha256:0a38a968acc4f11ab75cfd4b65a1c2f1982a18bfc27d9fb0dc1045bef5e79d43`。
该镜像必须已在选定 Docker 端点中明确准备；它不是公开可拉取镜像。
镜像、版本和原生配置不能在此 Profile 中覆盖。环境前提与有限真实控制证据见
[固定配置检查](codex-coding-preflight.md)和
[环境／日志指南](codex-coding-environment.md)。

每项必须显式提供 `name`、`description`、`cost`、`runner_root`、`journal_path`、
`fixed_dependencies`、`docker_executable`、`docker_host` 和 `request_timeout`。
成本为非负整数；请求超时为有限秒数，范围 `(0, 60]`。
`fixed_dependencies` 是非空、有界的有限 JSON 身份，不能放凭据；它只固定 journal
依赖身份，不被解释为执行配置、环境或认证。额外的凭据、env、mounts、原生 config
等顶层字段会被拒绝。

## SDK Profile

```python
import asyncio

from ralf_agent import (
    BindingSelection, RuntimeBuilder, RuntimeProfile, Scope,
)


def runner_entry(name, suffix):
    return {
        "name": name,
        "description": "Execute one approved contained Coding task.",
        "cost": 1,
        "runner_root": f"/private/tmp/ralf-coding-profile/runner-{suffix}",
        "journal_path": f"/private/tmp/ralf-coding-profile/runner-{suffix}.sqlite",
        "fixed_dependencies": {"deployment": f"coding-profile-v1-{suffix}"},
        "docker_executable": "/usr/local/bin/docker",
        "docker_host": "unix:///var/run/docker.sock",
        "request_timeout": 30,
    }


def runner_reference(component_id, tool_name):
    return {
        "role": "runner",
        "component_id": component_id,
        "version": "1",
        "component": {
            "adapter": "registered-tool",
            "config": {"name": tool_name},
        },
    }


profile = RuntimeProfile(
    "coding-local", "1",
    {"default": {"adapter": "offline-echo"}},
    components={
        "tools": {
            "adapter": "codex-coding",
            "config": {"tools": [
                runner_entry("coding_a", "a"),
                runner_entry("coding_b", "b"),
            ]},
        },
    },
    binding_components=[
        runner_reference("runner-a", "coding_a"),
        runner_reference("runner-b", "coding_b"),
    ],
)


async def main():
    scope = Scope()
    runtime = await RuntimeBuilder().abuild(
        profile, "/private/tmp/ralf-coding-profile/runs.sqlite", scope=scope,
    )
    try:
        a, _ = runtime.binding_catalog.resolve(
            "runner", BindingSelection.ref("runner-a", "1"), scope,
        )
        b, _ = runtime.binding_catalog.resolve(
            "runner", BindingSelection.ref("runner-b", "1"), scope,
        )
        assert a is runtime.tools.get("coding_a").handler.runner
        assert b is runtime.tools.get("coding_b").handler.runner
        assert a is not b
    finally:
        await runtime.aclose()


asyncio.run(main())
```

该装配打开／核对 journal、固定物理依赖和注册工具，不创建 Docker 容器，不提交
Thread 或 Turn。所有工具描述符固定为 `queryable_write` 且必须审批；参数仅接受
`{"task": "..."}`。工具绑定名称不自动授予 Agent 工具权限，Agent 仍需显式选择工具。

## JSON

保存为 `runtime.json`。该文件与上述 SDK Profile 等价：

```json
{
  "schema_version": 2,
  "default": {"name": "coding-local", "version": "1"},
  "profiles": [{
    "name": "coding-local",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "components": {
      "tools": {
        "adapter": "codex-coding",
        "config": {
          "tools": [
            {
              "name": "coding_a",
              "description": "Execute one approved contained Coding task.",
              "cost": 1,
              "runner_root": "/private/tmp/ralf-coding-profile/runner-a",
              "journal_path": "/private/tmp/ralf-coding-profile/runner-a.sqlite",
              "fixed_dependencies": {"deployment": "coding-profile-v1-a"},
              "docker_executable": "/usr/local/bin/docker",
              "docker_host": "unix:///var/run/docker.sock",
              "request_timeout": 30
            },
            {
              "name": "coding_b",
              "description": "Execute one approved contained Coding task.",
              "cost": 1,
              "runner_root": "/private/tmp/ralf-coding-profile/runner-b",
              "journal_path": "/private/tmp/ralf-coding-profile/runner-b.sqlite",
              "fixed_dependencies": {"deployment": "coding-profile-v1-b"},
              "docker_executable": "/usr/local/bin/docker",
              "docker_host": "unix:///var/run/docker.sock",
              "request_timeout": 30
            }
          ]
        }
      }
    },
    "binding_components": [
      {
        "role": "runner",
        "component_id": "runner-a",
        "version": "1",
        "component": {"adapter": "registered-tool", "config": {"name": "coding_a"}}
      },
      {
        "role": "runner",
        "component_id": "runner-b",
        "version": "1",
        "component": {"adapter": "registered-tool", "config": {"name": "coding_b"}}
      }
    ]
  }]
}
```

## TOML

保存为 `runtime.toml`。表层级与 JSON 中的两个 Runner 及两个借用引用对应：

```toml
schema_version = 2

[default]
name = "coding-local"
version = "1"

[[profiles]]
name = "coding-local"
version = "1"

[profiles.providers.default]
adapter = "offline-echo"

[profiles.components.tools]
adapter = "codex-coding"

[[profiles.components.tools.config.tools]]
name = "coding_a"
description = "Execute one approved contained Coding task."
cost = 1
runner_root = "/private/tmp/ralf-coding-profile/runner-a"
journal_path = "/private/tmp/ralf-coding-profile/runner-a.sqlite"
docker_executable = "/usr/local/bin/docker"
docker_host = "unix:///var/run/docker.sock"
request_timeout = 30

[profiles.components.tools.config.tools.fixed_dependencies]
deployment = "coding-profile-v1-a"

[[profiles.components.tools.config.tools]]
name = "coding_b"
description = "Execute one approved contained Coding task."
cost = 1
runner_root = "/private/tmp/ralf-coding-profile/runner-b"
journal_path = "/private/tmp/ralf-coding-profile/runner-b.sqlite"
docker_executable = "/usr/local/bin/docker"
docker_host = "unix:///var/run/docker.sock"
request_timeout = 30

[profiles.components.tools.config.tools.fixed_dependencies]
deployment = "coding-profile-v1-b"

[[profiles.binding_components]]
role = "runner"
component_id = "runner-a"
version = "1"

[profiles.binding_components.component]
adapter = "registered-tool"

[profiles.binding_components.component.config]
name = "coding_a"

[[profiles.binding_components]]
role = "runner"
component_id = "runner-b"
version = "1"

[profiles.binding_components.component]
adapter = "registered-tool"

[profiles.binding_components.component.config]
name = "coding_b"
```

从 `ralf_agent.runtime_config` 导入 `load_catalog`。两种文件均通过 `load_catalog("runtime.json").default` 或
`load_catalog("runtime.toml").default` 取得 Profile，再调用
`await RuntimeBuilder().abuild(profile, db_path)`。单 Runner 也可把一项的全部字段直接
放进 `codex-coding` 的 `config`，但不能混用这种形式与 `tools` 数组。
所有声明统一纯预检之后才取得资源；内置声明中的无效字段、重名、词法路径冲突、
缺失工具引用以及同步 `RuntimeBuilder.build` 会在 journal／执行数据库资源获取前
拒绝。实际根目录权限、物理别名和可执行文件检查发生在异步构造中，先于任何 journal
获取；构造仍由原 RuntimeBuilder 负责失败清理。

## 根级 Agent 与 sequence 的选择

在上面已装配的 Profile 中，可以声明一个独立 Agent，或让 sequence 的两个 Agent
分别选择自己的工具和 Runner。以下只是定义；原模型提出工具调用后仍须经原
`submit → drive → approve → drive` 流程，不能直接调用 handler 或 Runner 来授予执行权。

```python
from ralf_agent import (
    AgentBindingDescriptor, AgentDefinition, AgentSpec,
    BindingSelection, BoundDefinition, WorkflowSpec,
)

bindings_a = AgentBindingDescriptor(runner=BindingSelection.ref("runner-a", "1"))
bindings_b = AgentBindingDescriptor(runner=BindingSelection.ref("runner-b", "1"))

agent_a = AgentSpec("coding-a", "Handle the approved Coding task.", tools=("coding_a",))
agent_b = AgentSpec("coding-b", "Handle the next approved Coding task.", tools=("coding_b",))

single = AgentDefinition(agent_a, bindings_a)
sequence = BoundDefinition(
    WorkflowSpec("coding-sequence", steps=(agent_a, agent_b)),
    {
        "sequence/steps/0": bindings_a,
        "sequence/steps/1": bindings_b,
    },
)
```

`runner=BindingSelection.inherit()` 继承当前 Agent 已获工具中唯一的实际 Coding Runner；
同时选择来自不同 Runner 的 Coding 工具会拒绝。`ref` 必须匹配该 Agent 已获工具的
实际资源。`disabled()` 拒绝获授 Coding 工具；它不会静默改用普通执行器。
使用 Coding 工具的 bound Agent 必须有显式 runner 字段。显式 runner descriptor 使用
schema 3；省略 runner 的旧 descriptor 字节和原 Runtime Profile schema 1／2 保持。

本入口支持 Local Agent 和顺序 Workflow，包括上述 runner-bound 声明；dev105 支持
图／Team／Dynamic 和嵌套，具体配置与恢复见[组合指南](coding-composition.md)。
Temporal 显式 Runner descriptor（包括 inherit、ref、disabled）仍会拒绝，
不提供此工厂对应的 Temporal History 集成。

## 所有权与可重试关闭

每项按 `context.own(journal)`、`context.own_async(runner)` 的顺序登记。
两个示例按声明顺序创建，因此清理顺序为 Runner B、journal B、Runner A、journal A。
引用工厂不登记额外所有者；保留原 Caller-owned Runner 的自定义 tools 工厂仍可使用
同步纯借用，调用方自行拥有该 Runner 和 journal。

内置 `codex-coding` 必须用 `abuild` 构造，再用 `async with` 或
`await runtime.aclose()` 关闭。
关闭先阻止新工作、处理原 Engine 中待停止的委托 Run，并在原 SQLite／Coordinator
仍可接收停止证据时关闭拥有的 Runner／journal，最后关闭 Engine。
原容器停止或实际资源关闭失败时保留原租约、资源账本和可重试 Runtime；保留同一个
handle，在修复原资源依赖后、同一事件循环中再次 `await runtime.aclose()`。
不能用新 Runner、重建环境或另一个 Run 代替原停止处理。

构造中途失败或取消也按原资源账本清理已取得的资源。若清理失败，
`ralf_agent.runtime_builder.RuntimeBuildError` 的 `cleanup` 保存重试 handle。
下面的片段放在调用方的异步函数内：

```python
from ralf_agent import RuntimeBuilder
from ralf_agent.runtime_builder import RuntimeBuildError

builder = RuntimeBuilder()
db_path = "/private/tmp/ralf-coding-profile/runs.sqlite"
try:
    runtime = await builder.abuild(profile, db_path)
except RuntimeBuildError as failure:
    cleanup = failure.cleanup  # 保留该 handle；修复原资源依赖后在同一事件循环重试。
    await cleanup.aclose()
    raise
```

关闭重试只处理原资源。启动回执丢失、unknown 和冷恢复不会追加新的 Thread／Turn；
专用原生认证、真实业务质量和 Temporal 能力仍未由这些装配示例验收。
