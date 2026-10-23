# 固定命令 JSON CLI 工具

`CLIToolSource` 把可信 CLI 程序接入原 ToolSource／ToolRegistry，适用于已有脚本、
内部运维命令和离线业务工具。审批、额度、effect key、未知效果与恢复仍由原
Local Engine／Temporal History 管理。它提供 POSIX 进程管理；容器隔离、
Workspace 权限与外部 Coding Agent 属于后续能力。

## 开箱即用

```sh
relf init cli-app --template cli
cd cli-app
python -m agent_app run --value 3 --command-id first-change
python -m agent_app approve RUN_ID ACTION_ID --digest DIGEST --command-id approve-change
python -m agent_app resume RUN_ID
```

Run、Action 与 digest 来自首次返回的 pending 条目。新模板使用版本2的读取→确定性规划→批准写入流程。读取和规划证据先持久化，
等待审批／重启时不会重复读取；写入命令在批准前不启动，
使用下游 SQLite 幂等键去重，重复控制和提交保留原回执。模板使用自己的异步
run／approve／resume 管理装配与清理，主 `relf --factory` 的同步契约保持。
源码 checkout、模型、Redis、PostgreSQL 和 Temporal 均不是本地示例的依赖。

## 独立注入

```python
from relf_agent import CLIToolSource, ToolDescriptor, ToolPolicy, register_tool_source

source = CLIToolSource(
    ToolDescriptor("lookup", "Lookup", {"type": "object"}),
    ["/absolute/path/to/program", "fixed-argument"],
    version="lookup-v1",
    cwd="/absolute/workspace",
    env={},
)
await register_tool_source(
    registry,
    source,
    policies={"lookup": ToolPolicy("1", effect="read_only", requires_approval=False)},
)
```

程序通过 stdin 读取一个 UTF-8 JSON 对象，stdout 返回一个有限 JSON 值。
模型输入只进入 JSON stdin；executable／argv／cwd／env 由宿主固定，默认环境为空。
不隐式使用 shell；宿主显式选择的解析器或解释器仍是可信程序。stdout 默认限制
1 MiB；输入也限制 1 MiB，双方可设置 1–16777216 字节。timeout 为 (0,300] 秒。
非零退出、无效 JSON／UTF-8、重复键、过量输出或输出 Schema 不符均拒绝。
转义孤立 surrogate 的值或键也会在返回前拒绝。stderr 被丢弃，不写入公开错误。配置副本与 identity 固定，argv／依赖文件的实际
完整性由宿主管理；行为版本不能证明任意文件系统不可变。

直接注册借用 Source，使用者负责 `await source.aclose()`；取消等待之后仍可用
`await source.wait_for_calls()` 等待真实处理器停止。原 ambient tracker 与 Source
实际任务均保留到 root 进程等待和进程组清理结束，关闭后拒绝新调用。
脱离原进程组的外部任务不在本适配器的隔离保证内。

## 声明工厂

Local `RuntimeBuilder.abuild` 与 `TemporalRuntimeBuilder.abuild` 共用异步
`tools`／`cli-json` 工厂，构造／发现不启动程序。配置根为 `tools` 列表，1–256 项；
每项必须提供 descriptor、command、version、policy，另可提供 prefix、cwd、env、
timeout、max_input_bytes、max_output_bytes。未知字段和重复本地名称在分配前拒绝。
每项 Source 由原 owned ledger 管理，部分构造失败也会关闭已拥有的 Source。

```json
{
  "adapter": "cli-json",
  "config": {
    "tools": [{
      "descriptor": {
        "name": "lookup", "description": "Lookup",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"}
      },
      "command": ["/absolute/path/to/program"],
      "version": "lookup-v1",
      "policy": {"version": "1", "effect": "read_only", "requires_approval": false}
    }]
  }
}
```

声明应保留非敏感固定配置，凭据不放在 argv 或字面 Profile 中；凭据引用另行推进。
API 的显式环境值不出现在 Source identity，identity 只保留环境键和摘要。
policy 使用已有 ToolPolicy 字段；JSON 工厂不接受 Python reconciler，queryable_write
需宿主自定义注册。idempotent_write 的 effect_key_argument 必须是 flat Schema
中已声明的字符串字段；框架从调用方 Schema 移除并注入原 Action effect key。
Temporal 写工具继续要求真实耐久 EffectJournal，CLI 适配器不代替该存储。

业务已写但回包损坏时，幂等工具可携原 key 重试；unqueryable_write 保留核验等待，
不自动再次派发。退出 0 不能证明任意外部业务正确性，下游核验／业务 Verifier
继续属于应用契约。验收范围见[本批记录](../architecture/reviews/2026-10-11-cli-tools.md)。

SDK cwd=None 选择当前目录；其他 cwd 使用非空字符串／Path。声明 cwd 必须是
非空文本路径，省略时使用装配 base_dir；异常值在分配前拒绝。固定 executable
必须非空，后续 argv 允许空字符串。保留已生成版本1应用及原程序以恢复旧Run，
新模板不会覆盖使用者应用。完整 R12 仍包含其他工具、隔离和运行器能力。

升级SDK时同样保留已固定的工具执行路径。模板使用`sys.executable`选择CLI解释器；
更换虚拟环境会改变工具argv，从而按原发布契约拒绝恢复。需要固定原工具解释器
或保留原应用环境，不能通过删除身份检查实现自动迁移。
