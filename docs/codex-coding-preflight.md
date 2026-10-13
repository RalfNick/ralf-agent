# Codex Coding：配置与环境启动前检查

dev102 将这些控制基础用于具体保留的 `DockerCodingEnvironment`，并增加共享 PG
启动证据，见[环境／日志指南](codex-coding-environment.md)。同 ID 冷检查和实际
整容器停止已有有限证据；原始 Docker argv 仍可重启，原 Action 准入与失效门禁
尚未接入。下列 dev101 环境／资产记录保留，控制通过仍不授业务执行权。

dev101 增加固定版本的 `CodexCodingProfile`、只读 `CodexControlProtocol` 和
`CodexControlProbe`，并随包提供实际验证的 seccomp 文件。这些组件供下一步原
Action 委托集成使用；**尚无可运行 Coding Agent 工厂，完整 Runner 未验收**。

## 组件与使用边界

```python
from ralf_agent.codex_coding_profile import CodexCodingProfile
from ralf_agent.codex_control import CodexControlProbe

profile = CodexCodingProfile()  # 纯构造，不下载、启动或读取宿主配置
config_text = profile.config_text
# 由环境所有者将 config_text 放入专用容器的固定配置位置。
# argv 必须来自其已验证环境；此接口不替调用方创建隔离环境。
probe = CodexControlProbe(argv, env=explicit_environment)
snapshot = await probe.verify()  # 一次连接；成功、失败、取消均关闭本地传输
assert snapshot["control_verified"] is True
assert snapshot["execution_admitted"] is False
```

接口使用显式子模块导入。探针只发送 initialize／initialized 和八个稳定配置查询；
`configRequirements/read` 按原生协议发送 null。此连接拒绝 Thread／Turn、配置写入、
所有原生请求和未审查通知；允许的启动通知仅为精确的 bundled-bwrap／未信任工作区
警告及 disabled remote-control 状态，仍有数量上限。收到最终响应后已记录的协议错误
也会导致检查失败。警告不授予权限，不自动信任项目、不回复审批、不重试。

Profile 核对完整有效配置、129 个配置来源、精确三个层、92 个特性、四个权限档案、
零 MCP／插件及五个已禁用系统技能。三个配置层分别为固定工作区的**空且禁用**项目层、
固定用户配置层和空系统层。任何额外／修改层、有效 hook／provider 配置、分页残留、
未知技能或错误均拒绝。权限库存仍包含原生宽权限档案；后续业务准入必须固定使用
`ralf-coding-v1`，不能把库存当授权。

四个 removed 特性的原生 enabled 值仍为 true，尽管配置写 false：
`resize_all_images`、`terminal_resize_reflow`、`tool_search_always_defer_mcp_tools`、
`tui_app_server`。它们作为固定版本例外明确登记；无业务调用时不能证明其行为无影响。

探针拥有启动的本地进程与 stdio，不拥有容器或业务 Run。停止 docker attach 不证明
容器停止；环境所有者必须另行实际检查／停止／保留证据。检查成功既不认证对端二进制，
也不证明真实工具隔离、认证、模型可用、Run 授权或恢复。

## 固定环境与实际证据

本批实际环境为 Codex 0.144.4 linux-arm64、Alpine 3.22.6、Docker Engine 29.0.1／
Desktop 4.53.0、Linux 6.12.54-linuxkit；固定镜像 ID：
`sha256:0a38a968acc4f11ab75cfd4b65a1c2f1982a18bfc27d9fb0dc1045bef5e79d43`。
这不是公开可拉取镜像，也不表示其他宿主版本自动兼容。

原默认 seccomp 拒绝用户命名空间，原生命令未执行。基于准确上游策略增加 12 条
明确 namespace／Bubblewrap 设置规则后，实际非 root、零 capabilities、只读根目录、
no-new-privileges 组合通过有限原生命令探针：

- 允许工作区 input 读取、solution 写入和准确字节测试。
- 十个受保护／相邻／穿越／符号链接位置的读写均被拒绝。
- 外层 bridge 下控制 listener 可达，受限原生命令 AF_INET socket 被拒绝。
- 原生命令创建 setsid 后继；整容器 kill 后 PID 为零、Docker top 无进程、心跳停止。

受保护目录须预先创建，并只读允许准确 Codex trampoline 二进制。原生 proc 挂载受
宿主内核拒绝，明确重试无 proc 的路径仍使用受限文件／网络策略。专用 per-UID
synthetic mount registry 与会话／工作区状态必须由实际环境实现正确配置。

包内 `_codex_coding_seccomp.json` SHA-256：
`569e7aa0a4d8ed2b0bfada839187309d880c21350c36eaa2b55f15c0c85b41aa`。
源码／sdist 的 `tools/verify_codex_seccomp.py BASELINE PROFILE` 可离线校验原基线、
精确增量与最终字节；来源和 Apache-2.0 归属见 `tools/codex-seccomp-provenance.json`。
校验文件不安装系统策略或修改 Docker 全局配置。

## 后续交付门禁

真实控制读回与上述原生命令证据分别成立；当前尚未在真实模型 Turn 中证明 builtin
read／apply_patch、全部能力继承／AGENTS 来源、凭据边界、专用认证、完整取消／恢复。
dev102 已增加保留环境与共享 PG 阶段日志，Local／Temporal 原 Action 准入、停止
采纳、旧启动失效和 History 接入仍待集成。下一步沿
[委托 Coding Action 契约](../architecture/specs/delegated-coding-action-contract.md)实现，
保留各自唯一执行权威。详见[本批验收](../architecture/reviews/2026-10-14-codex-coding-preflight.md)。
