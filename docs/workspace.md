# 可替换的只读 Workspace

dev77候选的[受管理CAS写入](workspace-writes.md)是显式Source2增量；本页Source1只读默认与dev75/76历史边界保持。

Dev75沿 R13/H4 增加 `WorkspacePort`、`FileSystemWorkspace`、
`InMemoryWorkspace` 和 `WorkspaceToolSource`。这是文件数据与工具接入能力；
dev76 的每 Agent `workspace` 只读绑定复用原工具授权；写入、Skills、Sandbox 和 Coding Runner 仍待交付。
`Scope.workspace` 是宿主范围字段，不是物理目录，也不是认证系统。

## 默认声明：沿原 Workflow 执行

宿主先创建目录和文件，再选择固定 root；模型只提供该目录内的相对地址。
配置不创建 root，也不读环境变量中的目录或凭据。

```python
import asyncio
from pathlib import Path
from ralf_agent import (
    GraphNode,
    GraphWorkflowSpec,
    RuntimeBuilder,
    RuntimeProfile,
    ValueRef,
)


async def main():
    root = Path("workspace")
    root.mkdir(exist_ok=True)
    (root / "note.txt").write_text("业务说明", encoding="utf-8")
    profile = RuntimeProfile(
        "file-reader",
        "1",
        {"default": {"adapter": "offline-echo"}},
        {
            "tools": {
                "adapter": "workspace-read",
                "config": {
                    "root": "workspace",
                    "version": "documents-v1",
                    "max_entries": 100,
                    "max_bytes": 1048576,
                },
            }
        },
    )
    flow = GraphWorkflowSpec(
        "read",
        [GraphNode("read", tool="workspace_read_text")],
        output=ValueRef("read"),
    )
    async with await RuntimeBuilder().abuild(profile, "runs.sqlite") as runtime:
        handle = runtime.submit(flow, {"path": "note.txt"}, command_id="read-1")
        done = await runtime.drive(handle.run_id)
        assert done.state == "succeeded", done.error
        print(done.result["text"], done.result["sha256"])


asyncio.run(main())
```

同一声明可交给 `TemporalRuntimeBuilder`，在原 Agent 工具循环中调用。
Temporal 当前不支持直接 Tool 图节点；使用原 Agent-node 图或原生 Agent。
`requires_approval=True` 可让三项只读工具均等待原审批协议；`cost` 为原执行额度。
默认允许可信装配 Scope；显式 `scopes` 必须包含该 Scope，否则在分配文件资源前拒绝。
相对 root 与装配 `base_dir` 拼接，最终 root 的符号链接不会被提前 resolve 掩盖。

JSON/TOML 中 `tools/workspace-read` config 只接受：`root`、`version`，以及可选
`scopes`、`max_entries`、`max_bytes`、`prefix`、`requires_approval`、`cost`。
`scopes` 是1..256个不重复的 `{workspace, principal}` 对象。结构与边界纯预检
不触碰文件系统；真正打开发生在原 async 装配阶段。同步 build 在创建 Store 前拒绝。

## SDK 替换与注入

```python
from ralf_agent import InMemoryWorkspace, Scope

port = InMemoryWorkspace(
    {"docs/note.txt": "业务说明"},
    version="documents-v1",
    scopes=[Scope()],
)
try:
    snapshot = port.read_text(Scope(), "docs/note.txt", max_bytes=1048576)
    assert snapshot["bytes"] == 12
finally:
    port.close()
```

`WorkspacePort` 是同步协议：`identity`、`stat(scope,path)`、
`list(scope,directory="",max_entries=100)`、`read_text(scope,path,max_bytes=1048576)`、
`close()`。Scope、路径、返回值、错误、稳定身份和实际资源生命周期共同构成契约。
可将内存或自定义实现传给 `WorkspaceToolSource(port, version="tools-v1")`，
通过原 `register_tool_source` 选择工具及显式 read_only `ToolPolicy`。
这条 SDK 路径仍经过原 Registry／Action；自定义 port 自身负责实际范围与数据契约。
注册自定义 async 工厂时先 `context.own(port)`，再 `context.own_async(source)`；
原register_tool_source还支持可选纯validate_tool_policy(descriptor,policy)，必须同步完成并返回None；Workspace源在发布handler前拒绝write类别、effect key及reconciler。
逆序清理先排空 source，再关闭 port。Source 借用 port，单独 `aclose()` 不关闭它。
现有 `tool_set` 可限制每个 Agent 可见的工具名；这不等于已交付 Workspace 绑定角色。

三项工具分别为 `workspace_stat`（path）、`workspace_list`（directory）、
`workspace_read_text`（path）；只允许声明的字段，文件根和读取限额由宿主固定。
stat 返回 path/kind/size/version；list 返回 path/entries；read_text 返回
path/text/bytes/sha256/version。Source 复核返回地址、字节、摘要、目录条目及原身份。
空文件合法；支持UTF-8且无NUL的文本，无效UTF-8或含NUL内容拒绝，不承诺识别全部可解码二进制。返回内容与 identity 均为独立 JSON 快照。

## 文件策略、恢复与生命周期

路径最多4096 UTF-8字节／128段；禁止绝对、空文件路径、`.`、`..`、空段、
反斜线、ASCII控制字符／DEL，以及任意大小写的 `.git`／`.ralf` 段。list 的空目录选择根；
保护条目不属于允许视图，扫描仍独立受限于 `max_entries+3` 原始条目。
目录限额1..1000，超过限额拒绝，不静默截断。文本限额1..16777216字节。
内存实现复制至多4096个文件、每文件16MiB、总文本64MiB，拒绝文件／目录冲突。

文件实现一次捕获host path，先按词法规范化并核对原目录，再固定真实 root／device／inode／目录 FD。规范化root在分配FD前验证UTF-8和4096字节上限，初始化各步骤异常均清理FD。通过 FD 相对路径及 nofollow
打开各层；拒绝符号链接、多硬链接文件、特殊文件和跨设备子树。读前后检查 root、
完整canonical根地址链、目录内祖先地址及文件／目录版本；普通替换、祖先符号链接或写入竞态使本次结果拒绝。list 也复核各条目。
不创建 UUID 文件或其他隐式元数据。root 身份相同可重新装配；移动／替换需显式新发布。
版本表示元数据修订，sha256 表示实际读到的内容；它们不是写入效果回执。
这些是可信宿主文件系统上的读取策略，无法代替沙箱或防恶意并发写入的原子事务。

非法调用／配置为 ValidationError；宿主范围拒绝为 AuthorizationDenied；
不可读／不安全／过大数据为 WorkspaceError；固定资源改变为 DefinitionMismatch。
操作错误不返回绝对宿主路径或原 OS 诊断。处理器已经开始后抛异常，仍沿原执行
权威保留未知结果；声明层提前拒绝范围不兼容，SDK 自定义 port 需正确实施范围策略。

取消等待者不结束底层同步读取。Source 与原 ambient tracker 均持有真实处理器；
排队取消不派发，已运行的读取退出后才释放。关闭 source 等待实际退出，port 的
close 在仍有读取时拒绝并保留 root FD，退出后可重试。文件 I/O 无硬墙钟时限，
网络挂载或故障设备可能拖长关闭；这不表示业务 Run 已取消或文件资源已释放。

已经由原 Action 接受的结果在重启／重复 drive 后沿证据恢复，不重新读取新文件。
新的 Action 才读取当前文件；Workflow／Temporal History 继续是唯一执行权威。
真实服务及安装证据见[本批验收](../architecture/reviews/2026-10-11-workspace-read.md)。
写入的跨进程独占租约、意图／回执／未知效果核验、分页目录、企业 ACL、Skills 和
Runner 仍在[剩余能力清单](remaining-work.md)中，不以此子集标为完整 R13/H4。

延后Minor：Unicode C1控制字符路径仍可接受；完整Unicode category Cc策略待后续。目前限额先检查字符数，再有界编码／分段，拒绝过大值时不会先复制整个输入；这不等于整个解释器RSS配额。

## 每Agent只读Workspace绑定（dev76）

`WorkspaceBindingResource(registry, names=...)`借用已注册的单一Workspace Source，固定原工具的完整manifest、root、Source版本和额度。资源本身不读取文件、不创建或关闭客户端。SDK替换WorkspacePort仍通过原WorkspaceToolSource完成。以下示例只组装声明，不调用模型：

```python
import asyncio
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    InMemoryWorkspace,
    Scope,
    ToolPolicy,
    ToolRegistry,
    WorkspaceBindingResource,
    WorkspaceToolSource,
    register_tool_source,
)


async def binding_example():
    port = InMemoryWorkspace({"note": "业务说明"}, version="binding-demo-v1")
    source = WorkspaceToolSource(port, version="1")
    registry = ToolRegistry()
    try:
        await register_tool_source(
            registry, source, policies={"workspace_read_text": ToolPolicy("1", effect="read_only")}
        )
        resource = WorkspaceBindingResource(registry, names=["workspace_read_text"])
        catalog = BindingCatalog(scope=Scope())
        catalog.register("workspace", "project-files", "1", resource)
        definition = AgentDefinition(
            AgentSpec("reader", "Read the permitted note", tools=("workspace_read_text",)),
            AgentBindingDescriptor(workspace=BindingSelection.ref("project-files", "1")),
        )
        print(definition.bindings.workspace.to_dict())
    finally:
        await source.aclose()
        port.close()


asyncio.run(binding_example())
```

向已有Profile的`binding_components`添加以下声明即可复用同一工具Registry。Local同步／异步和Temporal装配均支持；原`tools/workspace-read`默认文件源仍按async装配，资源不重复分配根目录：

```json
{
  "role": "workspace",
  "component_id": "project-files",
  "version": "1",
  "component": {
    "adapter": "registered-tools",
    "config": {"names": ["workspace_read_text"]}
  }
}
```

`ref`只从原AgentSpec和tool_set交集中保留资源列出的Workspace工具，至少须匹配一个；其他根工具被排除，业务工具保留。`disabled`移除Workspace工具并保留业务工具。`inherit`保持原授权和发布记录。它们不会新增工具、改名或把同名工具重映射到另一根；多根应用先注册明确前缀，再分别绑定各Source的名称。一个资源至多256个不重复普通工具名，每名128字符／512 UTF8字节，拒绝ASCII控制字符和DEL；这些限额不会额外限制无关业务工具。

Local原生／顺序／图／Team／动态／嵌套实际成员沿原descriptor路径使用绑定。Temporal需要宿主catalog注册Workspace资源以启用protocol1，包含disabled-only选择；缺协议、越Scope、原Source/root/额度或工具manifest不匹配在接受或派发前拒绝。显式选择使用Local kernel11；继承默认不改变旧发布。已接受工具结果仍从原Action/History恢复，源内容后续变化不触发重复读取。

没有subroot selector、每路径ACL或写入能力。业务Python工具仍是可信宿主代码，Workspace选择不隔离其任意文件访问，不构成Sandbox。生命周期仍由原工具装配排空Source再关闭port，绑定资源不拥有任何一个。安装和冻结验收证据见[本批证据](../architecture/reviews/2026-10-11-workspace-bindings.md)。
