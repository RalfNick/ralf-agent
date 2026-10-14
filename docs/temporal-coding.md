# Temporal 原 ToolAction 的有限 Coding 委托

当前 dev109 的选定发布为 native protocol 2／binding 14；原 protocol 11 的描述保留其历史范围。旧选定 Run 使用匹配旧 Worker。新的模型连接见[连接指南](codex-model-connection.md)。

dev106 已验收原生 Agent／顺序 Workflow 的有限显式 Coding 委托，包括
per-Agent Runner 选择、SDK／JSON／TOML 装配、原 History 阶段准入和共享 PostgreSQL
资源证据。最终检查、安装、旧 Worker 与故障窗口以
[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)为准。
本页协议 11 拒绝图／并行／Team／Dynamic／嵌套 Coding；完整 R13、G1–G8 与第二阶段未关闭。
专用原生认证不可用，未执行真实 Coding 模型任务，不声明任务质量通过。

## dev107 可选组合入口（有限验收通过）

本页保留 dev106／协议 11 的验收范围与示例。另一个显式入口
`coding_execution=True, coding_composition=True` 发布协议 12，用于一层原 Agent 子 Run
的静态串行图；配置、实际子 Run 审批和 owned close 说明见
[Temporal Coding 组合指南](temporal-coding-composition.md)。原 History 重放、取消、关闭与有限故障门槛已分别通过，
见[dev107 验收记录](../architecture/reviews/2026-10-14-temporal-coding-composition.md)。
这不改变本页协议 11 的范围，也不代表原生认证／真实 Coding 质量通过。

## 权威与发布

Temporal Workflow／History 保留原 Run、ToolAction、审批、一个 attempt／预算预留、
结果采纳和终态。`TemporalRuntime(coding_execution=True)` 或
`TemporalProfile.execution={"coding_execution": True}` 显式选择此入口。
发布为 `temporal-3`／`binding_protocol=11`、`dispatch_admission=history-1` 与
`coding_execution_protocol.version=1`，固定实际工具／Runner／journal 身份和实现摘要。
省略或设置 `False` 保留原默认声明与发布字节；Local 发布也不因此升级。

Runner 的异步 History 入口与 Local 共用原生执行循环及纯阶段规则。History 只运行
纯状态规则；Activity 通过原 SDK Workflow handle、固定 namespace／epoch／请求和
实际 invocation 回调原 History。阶段 grant 要求原 Tool claim 与原进程 owner，
早到或重投的 Activity 不能自行取得新原生许可。

`PostgresRunnerJournal` 必须借用 **同一个** `runtime.journal`，该所有者必须是具体
`PostgresEffectJournal`。相同 DSN 或相等 identity 的另一对象不能代替它。
原 dispatch 和 resource intent 在该 EffectJournal 的连接／锁／事务内记录；原生
回执先写 PG，再由 History 采纳。PG 存储证据，实际 owner 管理调用排空和停止，
两者均不决定业务结果或预算，不建立第三套执行权威。

## 固定部署前提

安装 `ralf-agent[temporal]`，由宿主提供 Temporal Service、PostgreSQL 与 SDK Client。
以下示例只装配并展示定义，使用 `offline-echo`；它不请求 Coding 工具，不证明原生
认证或任务质量。示例不依赖仓库 examples。

首部署限定同宿主、原私有根目录及同一个 Docker Unix 端点。恢复必须保留原 Scope、
Profile／release、服务 namespace／队列、PG dataset、根目录与 Docker 物理身份；
新 Worker 查询或停止原资源，不能创建替代容器、换 workspace 或追加 Thread／Turn。
跨宿主／跨 daemon 接管未交付。

使用前创建 `/private/tmp/ralf-temporal-coding/runner-a`，属于当前用户、权限 `0700`、
无符号链接；长期恢复应改用调用方保留的私有持久目录。把示例 Docker 路径和 socket
改为实际固定位置。原生 Codex／镜像／seccomp 配置由代码固定，镜像须已明确准备；
不自动安装或下载，见[环境指南](codex-coding-environment.md)和
[固定检查](codex-coding-preflight.md)。

PG／History Runner 固定发布 `configuration_readonly=True`，由工厂选择，不能通过
Profile 关闭。原 writable workspace／state 两个目录 bind 保持；第三个精确 file bind
把原 `state/config.toml` 以 readonly 挂载到 `/home/ralf/.codex/config.toml`，阻止原生
App Server 改写或替换配置。容器检查固定三个 mount 的源、目标、RW 与 propagation；
原配置内容／inode／owner／mode 校验继续生效，不通过修补漂移后的文件绕过检查。
Local 环境省略或 False 时保留原 identity／create argv。


`tools/codex-coding-postgres` 接受一项完整配置或 `{"tools": [...]}`，最多 16 项。
每项字段见下例；名称不同、根目录物理上不相同或嵌套，所有项使用相同
`fixed_dependencies`。它是非空、有界 JSON 依赖身份，不包含凭据或认证。
此工厂不接受 Local 的 `journal_path`、env、mounts 或原生配置覆盖。
成本为非负整数；`request_timeout` 是有限秒数 `(0, 60]`。
DSN 通过指定环境变量读取，不写入 Profile、release 或日志。

## SDK 装配与选择

```python
import asyncio

from temporalio.client import Client
from ralf_agent import (
    AgentBindingDescriptor, AgentDefinition, AgentSpec, BindingSelection,
    BoundDefinition, TemporalProfile, TemporalRuntimeBuilder, WorkflowSpec,
)

profile = TemporalProfile(
    "coding-temporal", "1",
    {"default": {"adapter": "offline-echo"}},
    components={
        "effect_journal": {
            "adapter": "postgres",
            "config": {
                "dsn_env": "RALF_CODING_DSN", "backend_id": "coding-effects-v1",
                "initialize": True, "timeout": 10,
            },
        },
        "tools": {
            "adapter": "codex-coding-postgres",
            "config": {
                "name": "coding_a",
                "description": "Execute one approved contained Coding task.",
                "cost": 1,
                "runner_root": "/private/tmp/ralf-temporal-coding/runner-a",
                "fixed_dependencies": {"deployment": "temporal-coding-v1"},
                "docker_executable": "/usr/local/bin/docker",
                "docker_host": "unix:///var/run/docker.sock",
                "request_timeout": 30,
            },
        },
    },
    execution={"coding_execution": True},
    binding_components=[{
        "role": "runner", "component_id": "runner-a", "version": "1",
        "component": {"adapter": "registered-tool", "config": {"name": "coding_a"}},
    }],
)

bindings = AgentBindingDescriptor(runner=BindingSelection.ref("runner-a", "1"))
agent = AgentSpec("coding-a", "Handle the approved Coding task.", tools=("coding_a",))
single = AgentDefinition(agent, bindings)
sequence = BoundDefinition(
    WorkflowSpec("coding-sequence", steps=(agent,)),
    {"sequence/steps/0": bindings},
)


async def main():
    client = await Client.connect("127.0.0.1:7233")
    assembly = await TemporalRuntimeBuilder().abuild(profile)
    try:
        await assembly.start_worker(client, task_queue="coding-temporal-v1")
        engine = assembly.create_engine(client, task_queue="coding-temporal-v1")
        # 提交 single 或 sequence 时使用该 engine 的原 submit/drive/approve API。
        # Echo 不会提出 Coding 调用；实际调用仍须原 Action 的明确审批。
    finally:
        await assembly.aclose(wait_timeout=30)


asyncio.run(main())
```

多 Runner 时把 `config` 改为 `{"tools": [entry_a, entry_b]}`，声明第二个不同根目录／
名称与 `registered-tool` 引用，并让第二 Agent 显式选择其工具和 Runner。顺序绑定
路径为 `sequence/steps/0`、`sequence/steps/1`；各资源借用同一个 PG journal view。
`registered-tool` 借用已注册的实际 Runner，不创建或重复关闭资源，也不自动授予工具。

`inherit()` 从有效工具授权中选择唯一 Coding Runner；`ref(...)` 必须精确匹配
已授予工具的实际资源；`disabled()` 拒绝所选 Coding 工具。一个 Agent 不能同时选
不同 Runner 的 Coding 工具。带 Runner 角色的 descriptor 使用 schema 3，省略角色
保留旧字节。工具参数仅为 `{"task": "..."}`，类型为 `queryable_write` 且必须审批。

## JSON／TOML

保存下面任一格式，通过
`TemporalProfileCatalog.from_file(path).default_profile` 取得 Profile，再调用
`await TemporalRuntimeBuilder().abuild(profile)`。使用 Catalog 的相同 Profile 身份
恢复，不以当前默认别名替代原版本。

```json
{
  "kind": "temporal-profiles",
  "schema_version": 1,
  "default": {"name": "coding-temporal", "version": "1"},
  "profiles": [{
    "name": "coding-temporal",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "execution": {"coding_execution": true},
    "components": {
      "effect_journal": {
        "adapter": "postgres",
        "config": {
          "dsn_env": "RALF_CODING_DSN", "backend_id": "coding-effects-v1",
          "initialize": true, "timeout": 10
        }
      },
      "tools": {
        "adapter": "codex-coding-postgres",
        "config": {
          "name": "coding_a",
          "description": "Execute one approved contained Coding task.",
          "cost": 1,
          "runner_root": "/private/tmp/ralf-temporal-coding/runner-a",
          "fixed_dependencies": {"deployment": "temporal-coding-v1"},
          "docker_executable": "/usr/local/bin/docker",
          "docker_host": "unix:///var/run/docker.sock",
          "request_timeout": 30
        }
      }
    },
    "binding_components": [{
      "role": "runner", "component_id": "runner-a", "version": "1",
      "component": {"adapter": "registered-tool", "config": {"name": "coding_a"}}
    }]
  }]
}
```

```toml
kind = "temporal-profiles"
schema_version = 1
[default]
name = "coding-temporal"
version = "1"
[[profiles]]
name = "coding-temporal"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.execution]
coding_execution = true
[profiles.components.effect_journal]
adapter = "postgres"
[profiles.components.effect_journal.config]
dsn_env = "RALF_CODING_DSN"
backend_id = "coding-effects-v1"
initialize = true
timeout = 10
[profiles.components.tools]
adapter = "codex-coding-postgres"
[profiles.components.tools.config]
name = "coding_a"
description = "Execute one approved contained Coding task."
cost = 1
runner_root = "/private/tmp/ralf-temporal-coding/runner-a"
docker_executable = "/usr/local/bin/docker"
docker_host = "unix:///var/run/docker.sock"
request_timeout = 30
[profiles.components.tools.config.fixed_dependencies]
deployment = "temporal-coding-v1"
[[profiles.binding_components]]
role = "runner"
component_id = "runner-a"
version = "1"
[profiles.binding_components.component]
adapter = "registered-tool"
[profiles.binding_components.component.config]
name = "coding_a"
```

内置声明先纯预检，再异步构造：原 EffectJournal 先取得，RunnerJournal view 借用它，
随后登记各 owned Runner 和 borrowed references。构造仅核对资源、初始化 PG 与
注册工具；不会创建原生容器或提交 Thread／Turn。同步装配和 Local Builder 不支持
此 PostgreSQL 工厂；未显式启用 Coding、错用 Local `codex-coding` 或缺少原 journal
均拒绝。

## 恢复、停止与关闭

阶段 grant 只执行一次。Activity 重投、超时或丢失回复不形成新 attempt，也不重新
提交原生启动。PG resource intent 覆盖 prepare 前窗口；恢复先读取原请求／资源证据，
再查询或停止原环境。已创建意图却没有可信 container ID，且原 namespace 的实际
缺席与原 owner 结束无法确认时，保留未决记录并拒绝继续；不能猜测容器或创建替代。

原生完成候选、环境 fenced、原实际调用者结束和效果分类分别保存。成功需要原候选
及停止门禁；取消／异常先处理原 native stop，Run 可保持 `cancelling`。
interrupt ACK、Activity 返回、超时或 Worker Task 消失不单独证明整容器与原调用者
结束。已派发效果仍未知时，停止证明不清除 unknown 或预算 hold。

Assembly 拥有工厂取得的 PG connection、共享 journal view、各 Runner 和 Worker；
SDK Client borrowed。关闭先隔离新业务，在原 Worker／Client／PG 尚可用时查询待停
资源、向原 History 采纳停止证据，再排空实际调用、关闭 Worker 和逆序清理资源。
`await assembly.aclose(wait_timeout=30)` 的超时不强制释放资源；遇到
`CloseIncomplete` 或停止失败，保留同一个 Assembly，在修复原依赖后于同一事件循环
再次 `aclose`。不能先关闭借用的 Client，或换新 Runner／新 Run 代替原清理。

构造失败的 `ralf_agent.runtime_builder.RuntimeBuildError.cleanup` 同样保留清理 handle；
修复原资源后调用 `await failure.cleanup.aclose(wait_timeout=30)`。Profile Host 的 owned
清理遵循同一停止次序；自定义 SDK 工厂借用的资源仍由其实际调用方负责关闭。

真实受保护原生控制探针已通过：原配置内容与 inode 保持、原 CID 实际移除、
History 取消终态／重放和 PG pending 清空。此前未保护配置的两次真实失败与原容器
手动清理分别保留；不能用该手动清理作为成功路径的停止证据。此探针没有认证／模型
业务调用。最终源码与安装八案例矩阵及其余交付门槛仍待本批登记确认。

原生控制／环境证据与固定 process-peer 的业务协议证据分开登记。真实 Temporal／PG
服务和 Worker 恢复证明有限执行边界，固定 peer 不证明真实 Codex 任务质量；最终
验证状态见[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)。
