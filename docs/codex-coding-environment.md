# Codex Coding：保留环境与共享启动日志

dev102 提供显式 `DockerCodingEnvironment`、借用原 `PostgresEffectJournal` 的
`PostgresRunnerJournal`，以及 Local／PostgreSQL 共用的纯启动阶段规则。
这些组件补齐环境资源与共享证据基础；原 Action 准入和 Temporal History 尚未接通，
完整 Coding Runner 未验收。环境／控制快照保持 `execution_admitted=false`。

## 保留的 Docker 环境

```python
from ralf_agent.codex_environment import DockerCodingEnvironment

# private_root 是新建的绝对路径、空且属当前用户的 0700 目录。
environment = DockerCodingEnvironment(
    private_root, "coding-example",
    docker_executable=explicit_docker_path,
    docker_host=explicit_unix_endpoint,
)
prepared = await environment.prepare()  # 创建未启动容器，或核对原容器
observed = await environment.inspect()
stopped = await environment.stop()      # 必要时 kill，再检查原容器
assert stopped["stopped"] and stopped["pid"] == 0
await environment.aclose()              # 停止后释放租约；保留容器和工作区
```

构造仅校验声明和固定资产。`prepare()` 使用现有固定镜像、`--pull=never`，不下载
Codex、镜像或模型，不启动业务 Turn。私有 root 固定原 container ID／generation、
目录／配置物理身份与独占 lease；workspace／session state 分别挂载，元数据、
lease 和 seccomp 留在挂载外。Docker 客户端使用专用空配置，不继承宿主凭据。
运行条件包含非 root UID 10001、只读根、零 capabilities、no-new-privileges、
资源上限和 dev101 精确 seccomp；外层 bridge 与原生命令禁网分别验证。

冷重开只接受原身份和同一 container ID／generation。创建回执丢失时只查询原
名字／generation 标记的未启动容器，不导入未知已执行环境，不创建替代环境恢复。
`stop()` 的整容器证据来自原 ID 的实际状态，本地 attach／reader 关闭不算停止。
`aclose()` 保留容器、工作区与状态；停止或实际命令关闭失败时保留 owner／lease。

`transport_argv()` 只返回原容器的 `docker start --attach --interactive` 参数。
调用方须在启动前重新 `inspect()`，连接结束后停止整个环境。参数不是业务准入：
已取得的原始 argv 仍可重启已停容器，当前**没有旧启动许可失效门禁**。未来原
Engine／History 必须绑定阶段 grant、epoch、generation 和已应用取消顺序。
lease、检查后的 stopped 状态和原容器身份不能代替这一保护。

实际命令由真实线程／Popen 所有者串行管理，等待者取消不等于线程退出。全事件
循环取消窗口的 P2 修复与复验状态见[本批记录](../architecture/reviews/2026-10-14-codex-environment-journal.md)。

## 共享 PostgreSQL 启动证据

显式导入 `ralf_agent.postgres_runner_journal.PostgresRunnerJournal`，借用已初始化的
原 `PostgresEffectJournal`，再 `await journal.initialize()` 固定 dataset 身份及表路由。
`await journal.aclose()` 只关闭视图，原 EffectJournal／连接仍由原 owner 关闭。
依赖、容量及完整 DispatchEnvelope 在业务 RPC 前校验。

`begin(scope, effect_key, binding, envelope=original_envelope)` 在原 EffectJournal
事务中一起写入原 dispatch intent 与启动记录。`binding["dispatch"]` 固定 scope、
Run／Action／attempt／effect、epoch、tool manifest、arguments 和操作摘要。
独立连接共享锁与容量，原未知写效果按原 target 阻止新启动；缺原生记录的既有
effect intent 不能被补成可执行的新任务。初始化路由先在私有 staging 校验，再在
原 owner mutex 内跨事务提交后发布；失败不修改借用 owner。该 P1 已由同一
审查者实际复验闭环，原失败和先前检查日志保留在本批记录。

两种日志共用 `runner_journal_state.py` 的有限 JSON 校验与阶段规则：
`intent → thread_submitted → thread_confirmed → turn_submitted → turn_confirmed`。
首次提交阶段返回的一次许可与原业务授权不同，提交无回执不重发。句柄不可替换，
观察追加有界且去重，取消只保存意图。默认最多 1000 效果，每输入 64 KiB、每效果
1000 观察／1 MiB；不保存凭据或认证挑战。既有 Local 元数据／记录身份保留。

共享数据库不等于 Activity／Update／History 已接入。日志不调度后续观察，不回复
原生等待、不决定 Run 终态，不提供旧 worker fence 或原生 session continuation。

## 有限证据与下一门槛

实际固定环境通过准备、控制读回、受限原生命令读写／拒绝、存活 setsid 后继及同 ID
整容器停止；冷重开保留原 ID／generation 与 workspace。心跳停止观察仅为有限
0.4 秒窗口。最终受影响源码 301 passed／零跳过，含 PG 39 项检查及其中 17 个
实际服务案例；P1／P2 由同一审查者复验闭环。独立安装／制品登记见
[本批记录](../architecture/reviews/2026-10-14-codex-environment-journal.md)。

下一步按[原 Action 委托契约](../architecture/specs/delegated-coding-action-contract.md)
接原审批、阶段准入、停止证据采纳与历史版本拒绝。专用原生认证／provider、业务
Turn、builtin read／apply_patch、完整 G3／G5／G7／G8 和 R13 仍开放。dev99 第一
阶段保持冻结，本批未下载资产或重复模型评测。
