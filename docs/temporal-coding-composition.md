# Temporal 串行 Agent 图的有限 Coding 组合

当前 dev110 选定组合为 version 4／binding 17，扩展一层 Agent 成员的 Team／Dynamic；见[当前编排指南](temporal-coding-orchestration.md)。本文 protocol 12／13 和 dev109 version 3／binding 15 描述历史范围。旧选定 Run 使用匹配旧 Worker，见[连接指南](codex-model-connection.md)。

本文记录 dev107 已通过有限验收的显式组合入口。最终 wheel 在真实 Temporal／
PostgreSQL 上通过 11 条串行执行、审批重启、取消、故障恢复与 owned close 路径，
原 History 均使用实际 namespace 重放；原协议 11 的两条安装后兼容路径另行通过。
原生进程对端是确定性测试 peer，未调用真实 Coding 模型。完整 R13、G1–G8 和
第二阶段继续开放，证据与未验收项见[本批登记](../architecture/reviews/2026-10-14-temporal-coding-composition.md)。

本文的 serial／协议12描述 dev107 历史已验收范围。dev108 的同一显式开关发布
协议13／版本2，并提供[有界并行及共享资源背压](temporal-parallel-coding.md)。
旧12 Run必须使用其原匹配Worker／wheel续接，不能由新发布静默替代。

新入口复用 [dev106 原 ToolAction 的 Coding 委托](temporal-coding.md)：父图保留原
History 调度与子预算，实际 Agent 子 Run 保留自己的审批、ToolAction、一次 attempt、
原生 grant 和结果采纳。PostgreSQL 保存原资源证据；Runner 复用原执行循环。
组合入口增加原父子链接、SDK execution epoch／namespace 身份和独立的物理停止证据。

## 显式发布与有限拓扑

SDK 使用 `TemporalRuntime(coding_execution=True, coding_composition=True)`；Profile
使用同名的两个布尔 execution 标记。`coding_composition=True` 必须同时开启
`coding_execution=True`，无效声明在工厂取得资源前拒绝。

选中入口发布 `temporal-3`／`binding_protocol=12`，保留原
`coding_execution_protocol.version=1`，另加
`coding_composition_protocol.version=1`、`topology="serial-agent-graph"` 与完整实现摘要。
省略或设置组合开关为 `False` 保留原默认／协议 11 的声明和发布字节。
协议 12 下的独立 Agent 和 sequence 继续使用 dev106 的有限执行规则。

组合范围只允许静态 `GraphWorkflowSpec`、`max_concurrency=1` 和全部为 `AgentSpec`
的节点；只委托一层原 Agent 子 Run。Team、Dynamic、嵌套、并行、直接 Tool／transform
节点、planner／verifier Coding 和图 patch 继续拒绝。每个有效叶子都核对工具与 Runner
选择，宿主注册了某个 Coding 工具并不自动授予节点使用它的权限。

`runner=BindingSelection.ref(...)` 必须精确匹配该 Agent 已获授工具的实际 Runner；
`inherit()` 从有效工具授权中选择唯一 Coding Runner。一个 Agent 不能同时选不同
Runner 的 Coding 工具，不同串行 Agent 可以分别选不同的原 Runner。
`disabled()` 仅适用于有效工具集不含 Coding 的 Agent；保留 Coding 授权时会拒绝，
不会静默换用其他执行器。图绑定路径是 `graph/nodes/<node_id>`，投影后对应实际子
Agent 的 `agent` descriptor。

## 资源与超时

组合入口要求 SDK 提供 `workflow.Info.original_execution_run_id`。未提供该 API 的旧
SDK 会在取得 Provider、PG 或 Runner 资源前拒绝选中入口，Worker 注册也重新核对；
例如 [SDK 1.10.0 的官方源码](https://raw.githubusercontent.com/temporalio/sdk-python/1.10.0/temporalio/workflow.py)
尚无该字段。本批实际使用 SDK 1.34.0，未据此推断该 API 最早出现的版本。Profile
声明本身保持纯数据，未选中的默认／协议 11 路径不调用这个新能力检查。

安装、原私有根目录 `0700`、固定 Docker Unix 端点、readonly 原生配置及镜像前提沿用
[dev106 部署说明](temporal-coding.md#固定部署前提)。同一组工具使用相同的
`fixed_dependencies`，各工具名称和物理根目录必须不同且不嵌套。
`tools/codex-coding-postgres` 继续借用同一个具体 `PostgresEffectJournal`；Runner
引用不另造资源。DSN 只通过声明的环境变量读取，不放进 release 或日志。

以下配置显式选择 `request_timeout=30`。它是原 Runner 操作的整体截止时间，包含
精确 SDK 身份／阶段验证的等待，不只是容器内的执行时间。不要沿用旧机械 fixture
中的 5 秒作为部署建议；有效范围仍为 `(0, 60]`。`aclose(wait_timeout=30)` 是关闭
观察的等待上限，不能据此推断原调用或容器已经结束。

## SDK Profile 与静态图

把根目录、Docker 路径、socket 和服务地址改为实际固定值，并设置
`RALF_CODING_DSN`。示例使用 `offline-echo`，只展示装配和图定义；Echo 不会提出
Coding 工具调用，不证明原生认证或真实模型任务质量。

```python
import asyncio

from temporalio.client import Client
from relf_agent import (
    AgentBindingDescriptor, AgentSpec, BindingSelection, BoundDefinition,
    GraphNode, GraphWorkflowSpec, TemporalProfile, TemporalRuntimeBuilder, ValueRef,
)

profile = TemporalProfile(
    "coding-serial-graph", "1",
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
    execution={"coding_execution": True, "coding_composition": True},
    binding_components=[{
        "role": "runner", "component_id": "runner-a", "version": "1",
        "component": {"adapter": "registered-tool", "config": {"name": "coding_a"}},
    }],
)

graph = BoundDefinition(
    GraphWorkflowSpec(
        "coding-serial",
        nodes=(
            GraphNode(
                "first",
                agent=AgentSpec("first", "Handle the approved task.", tools=("coding_a",)),
                input=ValueRef("input"),
            ),
            GraphNode(
                "second",
                agent=AgentSpec("second", "Review the first result.", tools=("coding_a",)),
                depends_on=("first",), input=ValueRef("first"),
            ),
        ),
        output=ValueRef("second"), max_concurrency=1,
    ),
    {
        "graph/nodes/first": AgentBindingDescriptor(
            runner=BindingSelection.ref("runner-a", "1")
        ),
        "graph/nodes/second": AgentBindingDescriptor(runner=BindingSelection.inherit()),
    },
)


async def main():
    client = await Client.connect("127.0.0.1:7233", namespace="default")
    assembly = await TemporalRuntimeBuilder().abuild(profile)
    try:
        await assembly.start_worker(client, task_queue="coding-serial-graph-v1")
        engine = assembly.create_engine(client, task_queue="coding-serial-graph-v1")
        root = await engine.submit(graph, "Review this task", command_id="graph-001", budget=24)
        observed = await engine.drive(root.run_id, wait_seconds=10)
        print(root.run_id, observed.state, observed.pending)
    finally:
        await assembly.aclose(wait_timeout=30)


asyncio.run(main())
```

第二节点依赖第一节点真实结果和普通子预算结算。仅获得第一节点的物理停止证据，
尤其效果或费用仍未知时，不会开放第二节点的新业务。需要第二个 Runner 时，把
工具配置改成 `{"tools": [entry_a, entry_b]}`，登记不同的根目录／工具／引用，再让
对应 Agent 显式选择第二项。

## JSON／TOML Profile

保存任一格式，用
`TemporalProfileCatalog.from_file(path).default_profile` 取得 Profile，再调用
`await TemporalRuntimeBuilder().abuild(profile)`。下面两份声明对应上面的 SDK Profile；
图定义仍由上述 `BoundDefinition(GraphWorkflowSpec(...), ...)` 提交。

```json
{
  "kind": "temporal-profiles",
  "schema_version": 1,
  "default": {"name": "coding-serial-graph", "version": "1"},
  "profiles": [{
    "name": "coding-serial-graph",
    "version": "1",
    "providers": {"default": {"adapter": "offline-echo"}},
    "execution": {"coding_execution": true, "coding_composition": true},
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
name = "coding-serial-graph"
version = "1"
[[profiles]]
name = "coding-serial-graph"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.execution]
coding_execution = true
coding_composition = true
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

## 审批实际子 Run

Coding 工具仍是必须审批的 `queryable_write`，参数为 `{"task": "..."}`。父图
pending 条目的 `run_id` 指向实际子 Run；审批使用该 ID、该 Action 和该 digest，
不能把父图 ID 当成工具的 owner。先展示并核对待审批项，再向原 owner 提交确认：

```python
async def approve_reviewed_pending(engine, item, *, command_id):
    # item 必须是调用方已经核对并明确同意的原 pending 条目。
    return await engine.approve(
        item["run_id"], item["action_id"], item["digest"],
        command_id=command_id, approved=True,
    )
```

审批后用原 root 的 `drive`／`status` 观察依赖推进。公开 Facade 的 `pending()` 会
读取原子 Run 的新诊断并检查链接，使用方式见[组合 Agent API](temporal-agent-api.md)。
重试保留原请求、command ID、Scope、Profile／release、namespace 和队列；一次
Activity 重投不能创建新 attempt 或重新提交 Thread／Turn。

## 原命名空间、停止与 owned close

使用实际 SDK Client，`client.namespace` 必须是原命名空间。原 History 还固定该
命名空间的 UUID、父子 SDK epoch 与完整请求；仅名称相同、最新 Workflow ID、
reset／替代 execution 都不能代替原身份。保存实际服务 History 后，用原名称重放：

```python
from relf_agent import replay_temporal_history

# history 是原 SDK handle.fetch_history() 取得的 History。
await replay_temporal_history(history, namespace=client.namespace)
```

`await engine.cancel(root.run_id, command_id=...)` 在原父 History 记录停止意图，关闭
新的业务选择与委托，再取得每个原已派发子 Run 的物理停止证据。子启动回复不明
不能当成未启动。原 native fence 与实际 owner 结束均未证明时，父图保持 stopping／
`cancelling`；容器消失、SDK 取消 ACK 或调用方超时不能单独完成该证明。

物理停止与预算结算分开。原效果仍未知时，叶子 reservation 与整个子 cap 继续
保留；取消终态不把 unknown 改成零，不确认 EffectJournal，也不解除写排他。
成功结果与后续节点仍要求原结果证据及正常结算。

取消某个 `submit` await 只结束调用方观察，真实 SDK 提交仍由 owned Assembly 的
机械所有者保留。Assembly 关闭先禁止新提交并排空这些实际 SDK 操作，再逐个关闭
Registry 中已经接受的原 graph submission admission。关闭请求只针对当次已接受
的 submission，不设置永久的 Profile／manifest tombstone；重建相同 Profile 可以
接受新的 command ID。每次新的 close 扫描使用新的内部 nonce，避免 SDK Update
去重返回旧扫描；调用方不需要手工构造该 nonce。

随后通过原 Workflow 的 SDK query／Update 汇聚停止证据，扫描 PG 中包括已 fenced
的原资源，再排空实际 owner、关闭 Worker 和清理 owned 资源。已关闭 admission 的
迟到原 Start 不会取得业务许可；关闭不补造 Run 或容器来完成清理。使用借用的自定义
宿主时，调用方负责相同的实际 SDK 提交排空屏障。

关闭超时、调用方取消或 `CloseIncomplete` 时保留同一个 Assembly、原账本与原
停止任务；修复原依赖后，在同一事件循环再次 `await assembly.aclose(wait_timeout=30)`。
先保留 borrowed Client、原 Worker／History receiver 和 PG，直至停止证据完成采纳；
不以新 Runner、新 Run、新根目录或新容器替代原清理。

首批仍限定同宿主与原 Docker Unix 端点。原 Docker create intent 已写入、但完整
CID 尚未保存的窗口继续保留原停止义务和未知费用，不能据超时猜测不存在或重复
prepare。跨宿主接管、专用原生认证和真实 Coding 模型任务质量均未由本入口交付。

原 History 重放、取消、owned close、有限故障窗口与安装兼容已按本批范围登记。
有限 peer 成功、原生控制与认证／任务质量分别记录，不能相互替代；未覆盖的
实际 Start RPC 不确定性、SDK reset 和跨宿主恢复不由纯规则测试推定完成。
