# Local 原 Action 的 Coding 委托

dev103 增加显式 SDK 工具描述符、`CodexCodingRunner` 与原 Local ToolAction 的
有限集成。仅支持根级、未使用 per-Agent 能力绑定的 Agent 和顺序 Workflow。
图、Team、动态编排、嵌套成员、Temporal 与声明工厂尚未接入，显式选择这些组合
会在模型调用前拒绝。完整 R13 和 Coding G1–G8 继续开放。

当前 Runner 不读取、挂载或注入宿主认证；其身份明确记录 `credentials=unavailable`。
真实原生业务 Turn 和模型质量尚未验收。真实 Docker 的控制查询／限制／停止证据与
结构化假服务的业务协议测试分开登记，不能把后者视为真实模型或认证通过。

## 显式 SDK 装配

新接口使用模块导入。原 `ToolRegistry` 与普通工具的默认路径保持；资源由调用方
拥有，注册只借用 Runner，不关闭 Runner 或其启动日志。

```python
from ralf_agent.codex_runner import CodexCodingRunner
from ralf_agent.delegated_coding import register_coding_tool
from ralf_agent.runner_journal import RunnerJournal
from ralf_agent.tools import ToolRegistry

# 两个私有绝对路径由调用方管理；runner_root 属当前用户且权限为 0700。
# fixed_dependencies 是调用方固定的有限 JSON 身份，不能包含凭据。
journal = RunnerJournal(journal_path, identity=fixed_dependencies)
runner = CodexCodingRunner(
    runner_root, journal=journal,
    docker_executable=docker_path, docker_host=docker_unix_endpoint,
)
tools = ToolRegistry()
register_coding_tool(tools, runner, name="coding", cost=1)
```

工具参数仅接受 `{"task": "..."}`，不接受任意 argv、环境变量、原生配置或路径挂载。
任务文本最多 8192 字符；启动日志和传输另有有限 JSON 字节上限，超限失败。
工具固定 `queryable_write`、审批必需及完整 Runner 身份。把它加入原 AgentSpec 的
`tools` 后，按原 `submit → drive → approve → drive` 调用，审批绑定实际参数与环境。
直接调用 handler 或通用 PythonToolExecutor 始终拒绝；有效 DispatchEnvelope 本身
也不能授予启动权。

固定镜像、Docker 端点和实际原生版本的前置条件见
[环境指南](codex-coding-environment.md)与[固定配置](codex-coding-preflight.md)。
镜像目前是本机明确构建的候选资产，未发布公开镜像；构造不会下载或启动业务。
这里的装配展示结构接口，尚非安装后可直接调用真实模型的 Coding starter。

## 原执行权威与恢复

显式委托发布使用 `local-10`／`delegated_execution_protocol=1`，首次接受时在原
事务中升级 SQLite Schema 14。未选择委托工具的发布保留原 kernel；新建默认数据库
仍为 Schema 1。自定义 ExecutionStore 必须显式提供原事务内的升级与预算预留查询
契约；仅提供普通持久化端口不足以启用此路径。公共 `DelegatedExecutionStore` 的
`delegated_pending(scope)` 返回至多 10000 个唯一 Run ID 的 tuple，覆盖尚未停止／fence
的原 Run；关闭不依赖 SQLite 私有扫描。准备须同步完成为 None，预算回读须符合原
reservation 身份／类型／状态；缺失、惰性返回或组件替换都会拒绝启用或关闭。

整个原生 Turn 共用一个原 Action、effect key、attempt 和执行额度预留。原 Run
保存完整请求、一次 `prepare / thread/start / turn/start` 准入、原环境、Thread／Turn、
停止证据和独立效果分类；RunnerJournal 保存有限启动阶段及回执。阶段准入先于原生
请求，原生句柄先进入启动日志，再由原 Run 采纳。提交无回执保留 unknown，恢复
不会再发送 Thread／Turn，也不会通过 resume 追加 Turn。

执行取消后，原 Run 保持 `cancelling`，直到原 container ID／generation 实际停止且
旧启动参数失效。仅 interrupt 回执、RPC 关闭或 Python Task 完成都不足以确认停止。
取消终态仍保留未知效果案件，并阻断同一工具和参数的新执行，直到显式核验。
核验只确认效果，不把取消任务变回成功。

`stop_existing()` 只核对并停止原资源；冷恢复不得创建替代环境。已知原启动记录的
元数据或资源不可核验时保持待停止，不能把文件缺失当成已结束。停止或真实资源关闭
失败时，Engine 保留 Coordinator／证据接收方；先处理原 Run，再重试关闭。

成功必须同时具有原 Turn completed、最终原 Thread 读回、原容器停止／移除与传输
实际关闭证据，随后才复用原 Tool ResultCommit。结果包含有限文本、工作区普通文件的
相对路径／大小／SHA-256、原句柄和停止证据；用量记录为 unknown，不解释成零费用。
产物清单不等于完整 ArtifactStore 发布或文件传输；原工作区由调用方保留。

## 所有权和未交付能力

先等待或驱动原 Run 完成停止处理，再 `await runner.aclose()`、关闭启动日志和 Engine。
共享 Runner 每次只拥有一个委托操作；关闭失败应保留原资源并重试，不能强行释放租约。
Engine 不关闭借用 Runner。受影响检查、安装兼容、故障窗口和真实环境证据在
[dev103 记录](../architecture/reviews/2026-10-14-local-coding-delegation.md)分别登记。

尚缺 per-Agent runner 绑定、JSON／TOML 工厂、图／Team／动态／Temporal 集成、共享
History 准入与控制记录、专用认证、真实业务质量、跨宿主恢复、完整工具隔离和硬费用上限。
这些仍按[委托契约](../architecture/specs/delegated-coding-action-contract.md)验收。
