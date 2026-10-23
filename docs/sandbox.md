# 原生 Sandbox 工具

`SandboxProvider` 是可替换的异步端口；`DockerSandbox` 提供受限的本地 Docker
默认实现，`SandboxToolSource` 接入已有工具注册、审批、预算和结果采纳。
Local Engine／Temporal History 继续是各自唯一的执行权威。

## 显式接入

宿主先安装并启动 Linux Docker Engine，准备本地不可变镜像 ID；产品不会启动
Docker、拉取镜像或注入宿主凭据。镜像带隐式 Volumes 时拒绝使用。
以下代码可放入已有异步应用；用实际 Unix socket 和镜像 SHA256 替换参数。

```python
from relf_agent import (
    DockerSandbox,
    SandboxToolSource,
    Scope,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)

provider = DockerSandbox(
    "/absolute/path/to/docker.sock",
    "sha256:" + "YOUR_INSTALLED_IMAGE_SHA256",
    version="sandbox-v1",
    scopes=[Scope()],
)
await provider.aopen()
source = SandboxToolSource(provider, version="tool-v1", max_timeout=30)
registry = ToolRegistry()
await register_tool_source(
    registry,
    source,
    policies={
        "sandbox_run": ToolPolicy(
            "1",
            effect="read_only",
            requires_approval=True,
        )
    },
)
# 将 registry 注入原 Engine；宿主负责按此顺序关闭自有资源。
# await source.aclose(wait_timeout=30)
# await provider.aclose(wait_timeout=30)
```

模型只能传入 `argv` 和可选 `timeout`。argv 是 1–64 个普通字符串，总计最多
65536 UTF-8 字节，第一项是容器内绝对可执行路径；不隐式启动 shell。
`["/bin/sh", "-c", "..."]` 是宿主允许的显式容器内 shell 调用。
省略 timeout 使用 Source 的宿主默认值，不能超过宿主配置。

默认配置为 UID 65534、无网络、只读 root、全部 capabilities 丢弃、
no-new-privileges 和 Docker 内置 seccomp；禁止宿主挂载、设备、privileged。
`/workspace` 与 `/tmp` 各提供 32 MiB 临时 tmpfs，完成后删除容器。
默认内存 256 MiB、CPU 1、PID 64、并发 4、输出合计 1 MiB。
`read_only` 表示此固定配置没有外部业务、网络或宿主持久文件效果。
原生退出码、stdout、stderr 和停止证据仍需业务 Verifier 判断任务正确性。

## Profile 配置

Local `RuntimeBuilder.abuild` 与 Temporal 的异步装配共用显式
`tools/sandbox-docker` 声明。普通同步 `build` 在创建执行存储前拒绝该入口。

```json
{
  "adapter": "sandbox-docker",
  "config": {
    "version": "sandbox-v1",
    "socket_path": "/absolute/path/to/docker.sock",
    "image": "sha256:YOUR_INSTALLED_IMAGE_SHA256",
    "max_timeout": 30,
    "requires_approval": true,
    "prefix": "isolated_"
  }
}
```

可选配置还包括 scopes、lease_root_path、api_version、memory_bytes、nano_cpus、
pids_limit、max_calls、max_output_bytes、scratch_bytes、control_timeout 和 cost。
未知字段、动态镜像标签、非法限额或策略在 native I/O 前拒绝。
原资源账本拥有 Provider 和 Source；部分创建失败按逆序清理。
SDK 直接构造的 Source 借用 Provider，退出不会关闭其他 Agent 共享的 Provider。

## 完成、取消与恢复

调用取消只结束调用方等待；Source 保留实际端口操作。
关闭 Source 请求停止自己仍拥有的原始调用；等待超时抛 `CloseIncomplete`，
可以重试，不能据此确认原生操作结束。全局事件循环取消时，实际 Docker 控制
线程仍保留到停止、查询和清理完成，不能以 asyncio Task 结束代替停止证据。

原生地址绑定版本、镜像、Docker daemon、socket 身份、Scope 和原 Action 身份。
重复派发通过原生资源 FD 租约拒绝；崩溃后查询既有原生容器。
创建或启动回包丢失时查询原 ID，禁止盲目重复启动。
Run 的已采纳结果和审批继续存于原执行权威。
默认原生租约目录按宿主 UID 隔离，0600 锁文件保留以避免重新创建 inode 的竞态；
租约保留治理尚待后续实现。

自定义 Provider 实现固定普通 JSON identity 与原生异步
run／observe／stop／aclose；返回原 `SandboxResult`／`SandboxObservation` DTO。
Source 拒绝惰性返回值、错误调用身份、输出超限和运行期间配置变更。
未知启动或无效结果仍保留原执行 Owner 的责任，直到取得停止证据。失败后
有界查询同一原调用，确认停止／不存在才释放占用；原异常和业务未知回执保留。
内部其他Owner的未启动拒绝不能当作Source自身未进入handler的证明。只有
可信端口的 `SandboxExecutionRejected(handler_not_started=True)` 才能撤销责任。
同一 Source 拒绝同时跨两个活跃事件循环调用；原循环结束后可恢复关闭。

原生 timeout 是当前调用或冷恢复观察的相对窗口，不包含控制器离线时间，
不提供离线自动停止 watchdog。control_timeout 是 httpx 阶段和无进展超时，
响应字节另有限额，并非整个 HTTP 请求的绝对时间上限；持续慢速响应仍可能
占用线程，关闭会保留责任并返回 CloseIncomplete。容器清理后尚未被原 Action
采纳的 read_only 结果可能重试，不承诺所有故障窗口永久恰好一次执行。
用于这一 read_only Source 的 Provider 必须由可信宿主明确声明无网络、无宿主
挂载、无持久文件；声明不能证明任意 Python 实现的隔离强度。

## 每 Agent 能力绑定

`SandboxBindingResource(registry, names=["isolated_sandbox_run"])` 借用已经注册的
原生 Source 工具；通过 `BindingCatalog.register("sandbox", "isolated", "1", resource)`
装入宿主目录，Agent 使用 `AgentBindingDescriptor(sandbox=BindingSelection.ref("isolated", "1"))`。
`disabled()` 只移除原生 Sandbox 工具，`inherit()` 保留已有 grants。
选择与原 tool_set、Workspace、Skills 独立相交，不能新增 AgentSpec 未授予的工具。
资源选择不执行命令、不拥有或关闭 Provider；不支持模型选择镜像、挂载或 Scope。

Profile `binding_components` 使用 role `sandbox`、adapter `registered-tools` 和
config `{"names": ["isolated_sandbox_run"]}`，Local／Temporal 共用声明。
Local 显式绑定发布 local-bindings-14；Temporal 有原生 Sandbox 工具时发布
sandbox_binding_protocol 1／binding_protocol 4，自动使用原 ToolExecutionOwner，
旧 Worker 必须在业务 I/O 前拒绝新发布，旧协议维持原身份。
旧82 Worker 会在 Workflow 构造阶段拒绝 binding_protocol 4，此时还没有
可查询的 RALF Run 状态；History 记录 WorkflowTaskFailed，需要兼容 Worker
接管或操作员处理，不能把这种拒绝当作已提交的 failed Run。

六种原编排的 Local／Temporal 真实审批、重启与已采纳结果恢复均已通过。
Temporal 单 Agent 额外验证取消后真实线程与 History 停止证据；Local 单 Agent
验证 Coordinator 保留至真实结束。原生运行进程崩溃后恢复查询同一容器。
本批固定安装、旧版兼容、全量回归与唯一最终独立审查已通过；
详细成绩和延期问题见[验收记录](../architecture/reviews/2026-10-12-sandbox-native-tools.md)。
共享持久工作区、远程沙箱、Artifact 传输和外部 Coding Runner 属于后续能力。
