# 第一次使用 Relf-Agent

[文档目录](README.md) · [安装与可选依赖](installation.md) · [核心概念](concepts.md)

本文面向 **0.1.0a2 Alpha 本地候选**，需要 Python 3.11+。本教程使用本地 SQLite；先用离线项目完成提交、审批和恢复，再接入自己的模型与工具，不需要 Redis、PostgreSQL、Temporal 或 Docker。[基础能力入口](basic-capabilities.md)列出默认组合与定制路径；知识问答可从 [RAG 模板教程](recall-and-rag.md) 开始；无需改 Python 的版本配置从 [运行装配模板](runtime-assembly.md) 开始。其他平台与部署组合的验证范围见[实现清单](implementation-status.md)。

真实模型可用 `ralf init my-model-agent --template model` 生成独立项目，先替换 model/协议/凭据环境变量；配置限制与验证等级见 [模型接入](model-adapters.md)。生成模板不执行收费请求，也不表示账户与型号已验证。

当前已验证源码和原 wheel 的安装路径；公开 a2 原包及仓库改名后的下载入口见[安装指南](installation.md#从公开-alpha-安装)。PyPI 尚未发布，不要把 `pip install ralf-agent` 当作已验证的安装方式。

## 1. 安装：wheel 使用者与源码开发者

两种方式任选其一，均在独立虚拟环境中安装。

**已有 wheel：** 将下面的占位路径替换为实际获得的文件；安装会解析 httpx／jsonschema 等运行依赖。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0a2-py3-none-any.whl"
ralf --version
```

**从源码开始：**

```bash
git clone https://github.com/RalfNick/relf-agent.git
cd relf-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

如果要修改框架并运行测试，安装 `python -m pip install -e '.[dev]'`，然后按 [贡献指南](../CONTRIBUTING.md) 验证。本文步骤不需要仓库的 `examples` 目录，wheel 使用者也能执行。

## 2. 生成自己的离线项目

选择一个不存在的目录，从其父目录执行 init；源码使用者可在仓库外创建项目。已有空目录也可以作为目标，但不能在目标目录内执行 `ralf init .`，避免替换当前工作目录。

```bash
ralf --format text init ../my-agent
cd ../my-agent
python -m agent_app --db .ralf/runs.sqlite --ticket INC-001
```

生成的 `agent_app/runtime.py` 提供工具注册、离线 Provider、业务效果保存及 `create_engine(db_path)`；`agent_app/__main__.py` 是入口。它们使用安装好的 SDK，自身不依赖框架仓库。离线 Provider 产生固定提案，不需要模型密钥，也不代表真实模型的质量。

首次运行提交后会停在 `waiting_approval`，输出 JSON 中包含 `run_id`、`pending` 和提交回执。下面的 `RUN_ID` 要替换为实际值：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text inspect RUN_ID
```

`inspect` 显示状态、待批操作及可复制的批准／恢复命令。它只读取默认 Scope 的 SQLite，不加载工厂、不取得执行租约。提供 `--factory` 是为了诊断中的恢复命令指向原项目配置。

## 3. 审批并跨进程恢复

检查待批工具、参数和操作摘要，再执行 `inspect` 给出的命令。也可以手工填写：

```bash
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine approve RUN_ID ACTION_ID --digest OPERATION_DIGEST --command-id approve-001
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine --format text resume RUN_ID
ralf --db .ralf/runs.sqlite --format text inspect RUN_ID
```

批准回执的 `applied` 表示决定已保存；`resume` 推进工具执行和结果保存。完成后应看到 `succeeded`。审批和恢复是不同进程，执行数据库保留原 Run、Action 和业务效果证据。

再次运行同一工单入口，默认 `command_id` 为 `starter:INC-001`，会找回原提交。相同 ID 改变 AgentSpec、输入、budget 或 session_id 会冲突；新任务应使用新的命令 ID。具体恢复边界见 [恢复指南](recovery-guide.md)。

## 4. 修改为自己的 Agent

先在生成项目的 `agent_app/runtime.py` 中修改固定定义与工厂，再从同一模块导入工具实现。已经开始的 Run 继续使用原配置；调整工具、模型、记忆或上下文身份后，为新任务创建新的 Run。

| 修改内容 | 需要保持的契约 |
| --- | --- |
| AgentSpec／Workflow | 指令、工具、决策限制和输出 Schema 明确；顺序入口或串行静态图，图可自定义依赖、条件与输入映射 |
| Python 工具 | JSON 参数 Schema；读／写效果类别；写操作的 effect_key、审批和核验方式 |
| 授权 policy | 同步执行，成功返回 None，拒绝抛 AuthorizationDenied；其他返回值拒绝 |
| Provider | 异步 complete 返回 ModelResponse；只提出决策，工具由引擎执行 |
| Harness／ToolExecutor | 默认原生策略与 Python 执行器；需要领域策略或业务派发适配时按[组件指南](execution-components.md)注入 |
| 记忆 | 会话／长期记忆独立注入；稳定 backend_id、Scope 隔离、CAS 和去重 |

接入实际模型时可用 `OpenAIChatProvider` 替换离线 Provider，并在进程环境中提供 `OPENAI_API_KEY` 和模型名。真实调用产生供应商用量；不要把密钥加入 ToolSpec.config、Provider.identity 或版本库。兼容的服务需要单独验证响应和工具调用契约。完整端口要求见 [扩展指南](extending.md)，常用 SDK 调用见 [API 参考](api-reference.md)。

预算 `budget` 使用整数 execution credits，每个真实尝试预留和结算；它不是金额，也不是 Token 上限。本教程仅使用 Local 默认链路。Temporal、MCP、沙箱和向量检索已有可选实现，各自需要显式配置、依赖及对应的验证条件；不需要为运行本教程先接入它们。已交付范围与未验收项见 [实现清单](implementation-status.md)。

## 5. 命令使用习惯

`--db`、`--factory` 和 `--format` 属于全局参数，放在子命令前。默认输出 JSON；`--format text` 面向阅读。保留命令 ID 和 Run ID，便于在进程重启后找回原回执。

```bash
ralf --db .ralf/runs.sqlite events RUN_ID --after 0 --limit 100
ralf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine cancel RUN_ID --command-id cancel-001
```

事件下一页的 `--after` 使用上一页最后一个 `seq`。取消停止后续调度，不撤销已发出的业务操作。不要通过删除数据库或换一个 Run 来解决未知写效果。
