# 一个工单，逐步加入 Agent 能力

[文档目录](README.md) · [安装](installation.md) · [扩展方式](extending.md#先选择扩展方式)

本文面向 **0.1.0a6 及后续维护源码**的 Local 基础 SDK，使用 `relf_agent` 导入和 `relf` 命令。先按[安装指南](installation.md)准备对应环境，再按[首用教程](getting-started.md)用现有 starter 完成审批与恢复，使用同一个工单 `INC-001` 学习组件组合。这里没有新的框架入口或适配器，只有应用代码。

使用历史公开 a2 包时，保留独立环境，改读[固定 a2 提交的原教程](https://github.com/RalfNick/relf-agent/blob/3a92720b63c5ac5aa27edc33a18b8d03396a81ff/docs/support-journey.md)，并下载[同一提交的原示例](https://github.com/RalfNick/relf-agent/blob/3a92720b63c5ac5aa27edc33a18b8d03396a81ff/examples/support_journey.py)。a1–a5 使用旧导入 `ralf_agent`，不能运行本页链接的 a6 示例；其他历史包使用各自归档内的教程和代码。不要通过给旧环境添加新模块来续跑旧 Run。

遇到错误时从[现象与下一步](recovery-guide.md#按现象定位下一步)定位。相同命令回读历史结果、观察超时后继续等待、恢复原匹配配置，是这条路径的共同规则。

## 准备同一个应用文件

安装 a6 SDK 或当前维护源码后，将 [support_journey.py](../examples/support_journey.py) 下载／复制到自己的工作目录。若使用冻结 a6 wheel，也可下载[固定 a6 提交的示例](https://github.com/RalfNick/relf-agent/blob/ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239/examples/support_journey.py)。文件仅依赖已安装 SDK 和标准库，不导入 `examples`；源码包也包含该文件。wheel 不包含仓库 examples，无需为运行它复制整个仓库。

后续命令均在这个文件所在目录执行。所有步骤使用同一工单与只读 Python 工具；不同阶段使用独立 SQLite 文件，避免把新的定义或配置偷偷用于旧 Run／Session。默认目录 `.ralf/support-journey/` 保存执行记录、Session、知识和 Facts，不需要额外数据库服务。

| 阶段 | 增加的现有能力 | 主要代码 |
| --- | --- | --- |
| `agent` | Provider＋Python 工具＋单 Agent | `provider_for`、`tools_for`、`AgentSpec` |
| `session` | 持久 Session 与跨进程 Turn | `agent.open_session`、`session.submit` |
| `rag` | 本地文档与词法检索 | `SQLiteKnowledgeStore`、`KnowledgeContext` |
| `memory` | 显式长期 Facts 与召回 | `SQLiteMemory.put_fact`、`MemoryRecallPolicy` |
| `workflow` | 先诊断、后整理答复的顺序编排 | `WorkflowSpec` |

## 1. 离线 Agent 与自己的工具

```bash
python support_journey.py agent --command-id agent-1
python support_journey.py agent --command-id agent-1
```

第一条应得到 `succeeded`、工单状态和 `model_calls: 2`。第二条找回相同 Run／结果，`model_calls: 0`。离线 Provider 复制测试数据和引用，仅证明执行与装配，不代表模型推理或诊断质量。

修改 `tools_for` 中的 `lookup_ticket` 可接入自己的只读业务查询。此例仅提供 `INC-001`。写工具仍需要原效果类别、审批和核验契约，按[工具 SDK](sdk-model-tools.md)接入；不要直接把只读声明改成生产写操作。

## 2. 同一应用显式接入真实模型

先用自己的凭据管理方式提供 `DEEPSEEK_API_KEY`，再将占位型号换为账户支持的实际值：

```bash
python support_journey.py agent --provider deepseek-chat --model YOUR_MODEL --data-dir .ralf/support-live --command-id live-1
```

也可选择 `--provider chat-completions`，使用 `OPENAI_API_KEY` 与对应型号。缺少配置时明确失败，不降级为离线结果；真实调用可能收费。其他协议继续使用[已有 Provider](model-adapters.md)，在 `provider_for` 中替换即可。

真实与离线运行分开数据目录。更换模型、指令或工具后使用新命令／Session；保留原配置用于恢复历史任务。后续命令默认仍使用离线 Provider，也可以显式选择同一真实模型。本轮安装验证没有调用在线模型，不增加线上型号兼容或质量结论。

## 3. 跨进程继续同一个 Session

```bash
python support_journey.py session --command-id turn-1
python support_journey.py session --command-id turn-2 --input 'What should we check next?'
```

两条命令是不同进程，使用同一 `INC-001` Session。第二次结果中的 `session_records` 应大于零，表示已有保存记录进入当前模型上下文；它不是语义记忆质量评分。相同命令重复执行返回原回执。

先完成或处理原 Turn，才能提交下一 Turn。此例只有有限只读工具；需要审批的应用沿用[首用教程](getting-started.md)，不要通过新建 Run 绕过 busy 或未知效果。

## 4. 加入本地 RAG

```bash
python support_journey.py rag --command-id rag-1
```

结果的 `knowledge` 应包含 `cache-recovery`、文档版本和 `local://runbooks/cache-recovery`。这是 SQLite 内的来源标识，不是远程请求。示例以创建 CAS 导入一条运维手册，已有版本、已删除来源不会被启动过程覆盖或复活。

当前使用词法检索，不下载 Embedding。要接入已有语义检索服务，替换 Knowledge／Retriever 组合即可，参考[混合检索](hybrid-retrieval.md)；不要把词法命中当成语义质量。

## 5. 加入显式长期 Facts

```bash
python support_journey.py memory --command-id memory-1
python support_journey.py memory --command-id memory-2
```

示例由可信宿主首次写入 `support` namespace 下的 `response-style=concise`，结果的 `facts` 展示实际召回值。重启不覆盖已有值；namespace 与 Agent 名称对应，不能把别人的记忆传入当前 Scope。

这里演示显式写入与持久召回，**没有自动提炼、冲突修订或遗忘**。若需要已有的自动提炼，请显式选择[受管理记忆](managed-memory.md)，配置来源字段 allowlist；不要把模型声称的内容直接当作已核验事实。

## 6. 复用这些组件组成 Workflow

```bash
python support_journey.py workflow --command-id workflow-1
```

`WorkflowSpec` 先运行 `triage`，再由 `support` 整理答复；前一步输出成为后一步输入。模型、工具、知识和 Facts 沿用前面的装配方式，工具仍全部只读。默认离线结果证明两个步骤可以执行，不代表真实规划、团队协作或通用业务正确性。

## 继续定制与恢复

- 替换模型：`provider_for`；替换业务接口：`tools_for`。
- 替换知识／记忆：`run` 中注入相应端口，保留 Scope、namespace、CAS 和来源校验。
- 改为图、Plan／Team：使用[已有编排定义](orchestration.md)，另开配置与数据目录，按所选组合验证。
- 进程重启后，以相同文件、原数据目录、原阶段和原命令继续原任务。配置变化不是恢复；观察和取消规则见[Agent API](agent-api.md)。

示例共用一个 SQLite 连接，Knowledge／Memory 借用它，Runtime 拥有 Engine 并负责排空后关闭。遇到 `CloseIncomplete` 时保留原资源并按[恢复指南](recovery-guide.md)处理，不能强制释放租约。Temporal／Coding、函数指纹专项和 S2 不在本教程验收范围。
