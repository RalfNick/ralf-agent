# 示例与独立工程模板

[项目首页](../README.md) · [文档目录](../docs/README.md) · [首用教程](../docs/getting-started.md)

第一次使用建议通过 `ralf init` 生成自己的工程。安装 wheel 即可生成模板；本目录的 `.py` 示例需要源码仓库，在仓库根目录运行。下列示例使用离线 Provider 验证执行链路，真实模型接入见[模型指南](../docs/model-adapters.md)。

## 选择一个 starter

在已安装 SDK 的环境中，从目标目录的父目录执行。使用新的目录名，`init` 不覆盖非空目录。

| 目标 | 生成命令 | 后续指南 |
| --- | --- | --- |
| 审批、业务工具与跨进程恢复 | `ralf init my-agent` | [首用教程](../docs/getting-started.md) |
| 接入自己的模型 | `ralf init my-model --template model` | [先填写模型与凭据配置](../docs/model-adapters.md) |
| Python 之外的声明式装配 | `ralf init my-config --template config` | [JSON／TOML 配置](../docs/runtime-assembly.md) |
| 文档证据问答 | `ralf init my-rag --template rag` | [记忆与 RAG](../docs/recall-and-rag.md) |
| 文档摄取与更新 | `ralf init my-ingest --template ingest` | [摄取指南](../docs/document-ingestion.md) |
| Embedding 与混合检索 | `ralf init my-hybrid --template hybrid` | [混合检索](../docs/hybrid-retrieval.md) |
| 工具与 MCP | `ralf init my-mcp --template mcp` | [受管理工具](../docs/managed-tools.md) |
| 静态依赖图 | `ralf init my-graph --template graph` | [Workflow](../docs/static-workflows.md) |
| 动态规划 | `ralf init my-plan --template plan` | [Plan／Team](../docs/orchestration.md) |
| 多 Agent 团队 | `ralf init my-team --template team` | [Plan／Team](../docs/orchestration.md) |
| 持久用户输入 | `ralf init my-input --template user-input` | [用户输入](../docs/user-input.md) |

生成后进入工程目录，按生成的 README 运行。审批示例默认工厂为 `agent_app.runtime:create_engine`；恢复时从工程目录导入原工厂。完整模板列表使用 `ralf init --help` 查看；不同模板的依赖和验证边界见各自指南。

## 运行源码示例

先按[安装指南](../docs/installation.md)从源码安装 SDK，再在仓库根目录运行：

| 示例 | 命令 | 预期行为 |
| --- | --- | --- |
| 交互式工单 | `python examples/oncall.py` | 显示待批操作；输入 `APPROVE` 后执行本地测试变更 |
| 自定义恢复工厂 | `python -m examples.custom_runtime --db .ralf/custom.sqlite` | 提交只读查询并输出原 Run；通过同一工厂 `resume` 推进 |
| 自定义 Harness／执行器 | `python -m examples.execution_components --db .ralf/components.sqlite` | 停在审批；加 `--workflow` 运行顺序工作流 |
| 本地知识问答 | `python -m examples.knowledge_agent --query '缓存连接失败怎么恢复'` | 返回文档版本、来源与摘录；无证据时拒答 |
| Plan 组合 | `python -m examples.h3_combinations plan-and-execute --database .ralf/plan.sqlite` | 运行离线组合并显示等待结果 |
| Team 组合 | `python -m examples.h3_combinations team --database .ralf/team.sqlite` | 运行离线团队并显示等待结果 |

只读自定义工厂的观察与恢复示例：

```bash
ralf --db .ralf/custom.sqlite --factory examples.custom_runtime:create_engine --format text inspect RUN_ID
ralf --db .ralf/custom.sqlite --factory examples.custom_runtime:create_engine --format text resume RUN_ID
```

将 `RUN_ID` 替换为实际值。该只读示例不需要审批；交互式工单与执行器示例需检查待批操作后显式批准。示例使用本地测试数据库，不要替换为生产工具来试验审批流程。

## 离线评测

```bash
python examples/evaluate.py
python examples/evaluate_planning.py --fixture evals/planning-fixtures.json
```

工单评测检查关闭重开后的审批恢复、业务写入次数与工具顺序；规划 fixture 验证对应离线案例。离线通过不代表真实模型的业务质量。完整任务和真实模型评测方法见[任务评测](../docs/task-evaluation.md)与[规划评测](../docs/planning-evaluation.md)。
