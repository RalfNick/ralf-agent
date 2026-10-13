# Codex Runner：协议与启动证据基础

dev102 新增[保留 Docker 环境与共享 PostgreSQL 启动证据](codex-coding-environment.md)：
环境支持原容器停止／冷检查，PG 视图借用原 EffectJournal 同事务保存完整原
dispatch 与启动意图，Local／PG 共用纯阶段规则。原 Action 准入、旧启动失效与
Temporal History 尚未接通；日志许可不授业务执行权，下文历史协议边界保留。

dev101 的后续配置／控制组件与原生命令探针见[启动前检查](codex-coding-preflight.md)。
下文保留 dev100 基础边界；默认传输仍使用原六方法，控制模式单独显式启用。

dev100 提供 `CodexProtocol`、`CodexRPCTransport` 和 `RunnerJournal`。这批是首个 Codex
委托链路的通信与持久启动基础；**完整 Coding Runner、Agent 绑定、配置工厂尚未交付**。
实际隔离工作区和 Local／Temporal 版本化停止门禁按
[Runner 契约](../architecture/specs/runner-capability-contract.md)继续推进。

| 显式模块接口 | 已实现 | 不由它决定 |
| --- | --- | --- |
| `ralf_agent.codex_protocol.CodexProtocol` | 固定 0.144.4 生成 Schema 子集，有界参数／响应验证 | 对端二进制认证、授权、有效环境和隔离 |
| `ralf_agent.codex_rpc.CodexRPCTransport` | POSIX stdio，有界请求／通知／事件、乱序关联、迟到响应隔离、进程组清理 | 业务重试、审批、握手顺序、Run 状态、逃逸后继或远端任务停止 |
| `ralf_agent.runner_journal.RunnerJournal` | 独占 SQLite 证据，阶段／句柄固定，一次提交许可，独立取消意图 | Release 有效性、调度、原生恢复和终态采纳 |
| `ralf_agent.postgres_runner_journal.PostgresRunnerJournal`（dev102） | 借用原 EffectJournal，共享事务原 dispatch／启动意图、有限阶段推进、固定句柄；失败初始化路由 P1 已复验修复 | History 准入、旧 grant 失效、原生停止与结果采纳 |

Local Coordinator 和 Temporal History 保持各自 Run／Action 权威。dev100 不修改已有引擎、
执行数据库 schema、Activity 或取消行为。构造不自动下载或调用模型，transport 显式
`start()` 才创建进程，必须提供固定 argv 与环境字典。

通信仅允许 `initialize`、`thread/start`、`thread/read`、`thread/resume`、`turn/start`、
`turn/interrupt`；通知仅 `initialized`。原生 notification／server request 单独提供，
不自动批准或回复。默认每帧 1 MiB、256 个事件及相应在途请求／通知额度、30 秒等待，
JSON 最多 64 层。超时或观察取消不重发业务请求，也不证明 Turn 停止。

Schema 的 `external_version` 是生成来源版本，不认证对端。Thread 的 `cliVersion`
可为创建时版本。Schema 通过也不授予权限：原生 `sandbox`／`config` 参数还需已验证
Profile 限制。支持范围为 POSIX；先同步 `Popen` 固定 PID／原始管道，再使用公开
asyncio 管道接口接入。启动取消也等待真实关闭；超时或信号拒绝保留原所有者供同一
循环重试。进程组清理不证明逃逸后继或远端任务全部停止。

## 持久启动顺序

宿主提供可信 `Scope`、稳定 `effect_key`、原 Run／Action／操作／Release 摘要及固定
adapter／schema／环境依赖。Journal 固定和比较有限 JSON，不验证完整授权身份。

1. `begin(scope, effect_key, binding)` 保存意图，其 `execute` 仅表示新建意图。
2. `mark_thread_submitted(..., binding=binding)` 提交后，仅本次 `execute=True` 允许
   一次 `thread/start`；重复调用／重启返回 `False`。
3. `record_thread(..., thread_id=..., process_epoch=...)` 固定确认的 Thread。
4. `mark_turn_submitted(...)` 提交一次许可，再发送一次 `turn/start`。
5. `record_turn(..., turn_id=...)` 固定 Turn；后续查询原句柄、导入证据。

提交但无回执保持不确定，包括提交后实际未发送的保守窗口。没有阶段重置，重启或
Activity 重试不能再获许可。安全续接需后续契约与执行权威另行证明。
`request_cancel` 只存取消意图，`record_observation` 保存宿主筛选的证据；空 interrupt
回执只表示受理，不转换成成功／cancelled／停止证明。迟到原回执仍可保留为证据。

Journal 使用 POSIX flock、SQLite DELETE／EXTRA；需要已有非符号链接父目录下的规范
绝对路径，单硬链接元数据，重开核对物理身份／依赖。默认 1000 个效果，每输入 64 KiB，
每效果最多 1000 条观察／1 MiB 记录。关闭失败让旧对象不可写、保留租约供重试。
无自动清理／迁移，证据位于 Runner 无写权限的宿主私有目录，不保存凭据或认证挑战。

## Schema 来源与验证

本地 Codex 0.144.4 darwin-arm64 原生二进制 SHA-256：
`3302acbda5f53de1a71ebdb0c0f2aae0d47f9324aa9fb6b4e78a47014fd51c7d`。
本批只生成 Schema 和读取帮助，没有原生业务循环／真实模型调用。

以下为源码 checkout／sdist 维护命令，wheel 消费者直接使用包内 Schema：

```sh
codex app-server generate-json-schema --out /absolute/private/codex-schemas
python tools/generate_codex_protocol.py /absolute/private/codex-schemas /absolute/private/subset.json
```

dev101 脚本固定完整输入的 canonical JSON digest，仅允许对象键顺序／空白差异，
拒绝内容变化与重复键／非有限数；原产物保留七个原始审查生成来源 digest，并非后续
每次原始文件字节 digest。不用 `--experimental`，脚本仅读文件；`--control` 生成独立
只读控制子集，使用明确的 canonical 来源摘要。
派生包内 Schema SHA-256：
`5d2ba8cdee699144bd0ec23760146c6f45919fa9ac6ec5b61004dc3ea7b2a275`。
Schema 来自 Apache-2.0 的 OpenAI Codex 发行版生成产物；升级需重新审查。

测试采用真实本地有限假服务进程，验证通信／回收、持久阶段及接受 Turn 后丢失回执。
不替代真实 Codex、容器隔离或 Temporal History 验收。后续按
[实施计划](superpowers/plans/2026-10-13-codex-runner-foundation.md)和
[阶段门槛](delivery-gates.md)补实际受限 read/write/test 与原权威集成。
