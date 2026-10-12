# 可替换的 Workspace 写入（dev77 候选）

在[只读 Workspace](workspace.md)基础上，提供 `WritableWorkspacePort`、
`InMemoryWritableWorkspace`、`FileSystemWritableWorkspace` 和
`WritableWorkspaceToolSource`。这是显式启用的文件 CAS 与效果回执链路；
审批、预算、Run／Action 和恢复仍由原 Local／Temporal 管理。
当前相关契约和六类实际 Temporal＋PostgreSQL 重启通过，最终冻结／安装／审查待完成。

## 从默认实现开始

Memory 无额外依赖，适合测试；实例拥有独立、稳定的数据集身份，重新创建不能恢复旧可变数据。
版本在每次写入后递增，避免 A→B→A 让旧版本重新有效。

```python
from ralf_agent import InMemoryWritableWorkspace, Scope

scope = Scope()
files = InMemoryWritableWorkspace(version="app-1")
try:
    created = files.write_text(scope, "note", "A", expected_version=None, effect_key="create")
    changed = files.write_text(
        scope, "note", "B", expected_version=created["file_version"], effect_key="replace"
    )
    assert files.query_write(scope, "create") == created
    assert (
        files.write_text(scope, "note", "A", expected_version=None, effect_key="create") == created
    )
    assert files.read_text(scope, "note")["text"] == "B"
finally:
    files.close()
```

POSIX 文件默认保留真实文件、单根写租约与 SQLite 下游回执。root 必须先存在；
启用写入时创建受保护 `.ralf/workspace-writes` 元数据。它不包含另一套执行引擎。

```python
from pathlib import Path
from ralf_agent import FileSystemWritableWorkspace, Scope

root = Path("write-workspace")
root.mkdir(exist_ok=True)
files = FileSystemWritableWorkspace(root, version="app-1")
try:
    receipt = files.write_text(Scope(), "note", "durable", expected_version=None, effect_key="demo")
    assert files.query_write(Scope(), "demo") == receipt
finally:
    files.close()
```

`expected_version=None` 只允许创建；替换必须提供原 `read_text` 返回的 version。
同 Scope／效果键／请求返回原回执，同键不同请求拒绝。回执确认历史写入，不能证明文件现在仍是该正文。
`query_write` 只查询或核验已发生效果，不重新执行文件修改。
未确认的旧写入保留目标占用，不能通过新效果键盲目覆盖。

正文必须是 UTF-8、无 NUL，默认上限1MiB，可配置至16MiB；
效果键为非空 UTF-8，最多256字节。默认1024回执，满后明确拒绝新效果，保留旧回执。
Memory 继续限制4096文件／64MiB总正文。仅写既有父目录内的普通文件；
`.git`／`.ralf`、越界路径、symlink／hardlink 和特殊文件拒绝。

## 受管理工具与每 Agent 选择

```python
import asyncio
from ralf_agent import (
    InMemoryWritableWorkspace,
    ToolPolicy,
    ToolRegistry,
    WorkspaceBindingResource,
    WritableWorkspaceToolSource,
    register_tool_source,
)


async def main():
    port = InMemoryWritableWorkspace(version="app-1")
    source = WritableWorkspaceToolSource(port, version="tools-1")
    try:
        tools = ToolRegistry()
        await register_tool_source(
            tools,
            source,
            policies={
                "workspace_write_text": ToolPolicy(
                    "policy-1",
                    effect="idempotent_write",
                    effect_key_argument="effect_key",
                    requires_approval=True,
                    reconciler=source.reconcile,
                )
            },
        )
        selected = WorkspaceBindingResource(tools, names=["workspace_write_text"])
        assert selected.registry is tools
    finally:
        await source.aclose()
        port.close()


asyncio.run(main())
```

模型只提供 `path/text/expected_version`，效果键由原 InvocationContext 注入；
调用方不能提供保留字段。原生写策略支持 idempotent_write 和明确保留键，
核验器使用该 Source 的受管理 query；其他核验语义请实现独立、版本化的 ToolSource。
SDK 的审批开关由宿主固定，默认声明写入始终需审批。

WorkspaceBindingResource 借用原 Registry／Source／Port；没有第二个根或 close 权限。
ref 与 AgentSpec／tool_set 原授权取交集，disabled 同时去掉 native read/write 工具，保留业务工具。
显式 Source2 选择使用 Local kernel12；Temporal 发布 protocol2，旧 dev76 Worker 不支持此 opt-in。
Source1 与继承的旧默认发布保持原格式。多个根使用固定前缀和分别注册的资源。

## JSON／TOML 默认装配

已有 Profile 可以选择：

```json
{
  "tools": {
    "adapter": "workspace-read-write",
    "config": {"root": "files", "version": "app-1", "max_bytes": 1048576, "capacity": 1024}
  }
}
```

Local 使用 `RuntimeBuilder.abuild`；Temporal 使用原 `TemporalRuntimeBuilder.abuild`。
`workspace/registered-tools` 按[绑定指南](workspace.md)重用该 Registry。
配置只接受已有 read 声明字段及 capacity；`requires_approval` 只控制读取，
写入审批固定开启，不接受 `write_requires_approval=false`。
root 为宿主固定值，未知字段／非法容量在资源创建前拒绝。关闭先排空 Source 真实线程再关闭 Port／租约。
Temporal 业务写仍需要原 PostgreSQL EffectJournal，见[Temporal 配置](temporal-profiles.md)。

## 恢复证据与边界

文件写入按临时正文和目录项 fsync→持久意图→同设备 rename→父目录 fsync→
原 inode／正文／祖先核验→准确回执提交推进。断在 rename 后时，核验原临时 inode 和正文；
不能只凭相同文本制造回执。原请求可以完成仍符合 CAS 的写前意图，查询本身不执行它。

独占租约在真实线程仍可能执行时保留，观察等待取消不会释放它；关闭失败需重试。
Root、元数据目录、锁与数据库身份移动需要显式处理，不能静默续接。
未知写入按真实父目录与文件地址保护大小写／Unicode别名；若原目标尚不存在，
同一实际父目录的新写入暂时拒绝，其他目录可继续，原请求恢复后释放。
SQLite 每次连接验证 DELETE＋EXTRA；编辑保留原 rwx 权限，新文件0600，
不复制 setuid／setgid／sticky、所有者或 ACL。租约只覆盖准确根，宿主需排除重叠可写根。
它不对任意外部文件写入提供事务，也不构成 Sandbox、企业身份或跨主机分布式租约。
append/delete/mkdir、selector／ACL、GC、Skills／Coding Runner 和完整 R13/H4 仍开放。
实际 Temporal 的阻塞原生写入取消／关闭／第二写者窗口尚未直接验收；离线线程测试不能替代。
[子集验收记录](../architecture/reviews/2026-10-12-workspace-writes.md)区分实际证据与未完成门槛。
