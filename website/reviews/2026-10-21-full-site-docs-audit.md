# 全站文档、能力说明与双语体验审阅

审阅日期：2026-10-21。范围包括首页能力说明、交互演示、文档导航、全部 10 组中英文指南，以及指南涉及的 SDK、CLI、starter 和仓库技术文档；同时对照 AgentScope、LangGraph、Pydantic AI 官方文档的信息结构和使用路径。本轮只审阅，未修改网站或 SDK，未部署。

结论：目前网站已经能帮助用户理解项目定位、选择基础能力并跑通离线审批示例，但还不能稳定支持新用户独立完成真实应用开发。主要差距是示例之间的衔接、关键能力的操作闭环、进阶资料可达性、API 查询和测试指引。发现 **1 个 P1、3 个 P2、2 个 P3**；没有发现中英文主体说明大面积含义相反或首页明显夸大能力的情况。

## 发现

### 1. P1：技术资料链接使用不存在的 main 引用

位置：[文档侧栏与来源链接](/Users/bytedance/Codex-Projects/ralf-agent/website/src/pages/[locale]/docs/[slug].astro:20)、[来源与编辑入口](/Users/bytedance/Codex-Projects/ralf-agent/website/src/pages/[locale]/docs/[slug].astro:26)，以及指南正文中的 GitHub 链接。

页面统一拼接 `tree/main`、`blob/main`，但只读检查远端 HEAD、`refs/heads/main`、`refs/tags/main` 得到：

```text
ref: refs/heads/feat/m1-local-runtime HEAD
0b9b6c9682c40285d91994cd831aa93d7e814bf1 HEAD
0b9b6c9682c40285d91994cd831aa93d7e814bf1 refs/heads/feat/m1-local-runtime
```

远端未返回 main 分支或同名标签。当前 24 个 HTML 构建产物中，有 234 处链接使用该引用，共 61 个不同 URL，涉及完整技术文档、深入教程、技术来源和编辑入口。用户阅读精选说明后，无法沿这些链接进入当前仓库资料。

建议：集中配置已发布的文档 ref，选择实际存在的标签、提交或分支；统一处理组件和正文 URL，发布前验证引用与文件存在。网站当前尚未入库的页面源码，还需在发布时确认编辑入口对应文件已推送。无需为修链接修改远端默认分支。

现有 [构建检查](/Users/bytedance/Codex-Projects/ralf-agent/website/scripts/check-build.mjs:58) 跳过 HTTP 链接，所以站内链接检查通过不能发现这一问题。

### 2. P2：会话教程无法承接其指向的模型工具示例

位置：[英文会话指南](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/sessions-memory.md:24)、[英文模型工具示例](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/models-tools.md:52)；中文对应页面相同。

会话指南说明应用需先创建 `Agent`，并指向“模型与工具”获取装配方法；后者实际创建 `agent = AgentSpec(...)`，再交给 `LocalEngine`，没有构造 `Agent`。用户沿该路径继续执行 `agent.open_session(...)` 会得到：

```text
AttributeError: 'AgentSpec' object has no attribute 'open_session'
```

两种语言均已通过提取原教程定义复现，未调用模型。真正提供该方法的是 [Agent Facade](/Users/bytedance/Codex-Projects/ralf-agent/src/ralf_agent/agent.py:55)。

建议：在会话页给出完整、可运行的 Agent/Runtime 装配，延续同一个业务例子，并说明异步入口和资源关闭；定义对象使用 `spec`，可运行入口使用 `agent`，减少同名异义。

### 3. P2：缺少持久用户输入能力及其恢复路径

位置：[恢复状态表](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/recovery.md:20)、[会话继续说明](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/sessions-memory.md:22)；中文对应页面相同。

网站没有介绍 `waiting_input`、`request_input`、`send_input` / `send-input`，也没有指向已有的 `docs/user-input.md`。会话页只提示先处理上一轮 input，却未说明如何回答。

这会直接影响需要补充参数、澄清目标的应用：开放问题会保持 Session busy，用户不能用一次新的 `Session.submit/run` 回答旧问题。应向原 Run 的问题提交受 Schema 和 digest 约束的回复；原始 CLI 回复后还需 resume。[仓库指南已有明确契约](/Users/bytedance/Codex-Projects/ralf-agent/docs/user-input.md:209) 和离线 starter。

建议：能力选型表增加“等待用户补充信息”，恢复表增加 `waiting_input`，并提供 `ralf init ... --template user-input` 的问题出现 → inspect → send-input → resume → 查看结果闭环。区分业务审批、用户输入和新的会话轮次。

### 4. P2：英文进阶阅读链路缺少同等语言支持

位置示例：[英文模型适配入口](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/models-tools.md:70)、[英文混合检索入口](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/sessions-memory.md:90)、[英文连续工单教程入口](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/overview.md:70)。

英文页面把关键配置和完整操作委托给 `model-adapters.md`、`hybrid-retrieval.md`、`static-workflows.md`、`support-journey.md` 等仓库资料，但这些文件主体是中文，链接也没有语言提示。即使修复 main 引用，英文用户仍无法获得同等的进阶操作说明。部分仓库文档本身为英文，因此并非所有外链都有此问题。

建议：优先把真实模型接入、会话、混合检索和连续应用路径补齐为双语可执行说明；暂未翻译的技术源标注语言。双语验收应包含“能否完成相同任务”，而不只检查主题、参数和来源哈希相同。

### 5. P3：结构化输出的下一步操作会撞到旧命令身份

位置：[英文结构化输出说明](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/models-tools.md:74)、[原示例命令](/Users/bytedance/Codex-Projects/ralf-agent/website/src/content/guides/en/models-tools.md:64)；中文对应页面相同。

页面让用户替换前面的 Agent 定义，加入 `output_schema`，但保留 `.ralf/agent.sqlite` 和 `command_id="request-001"`。若原示例已提交，新定义会改变请求摘要；再次运行同一命令 ID 会触发：

```text
IdempotencyConflict: command_id was already used for a different request
```

已用原示例及替换后的定义，在临时 SQLite 库和离线 Provider 下复现；换用新命令 ID 可提交，没有模型请求。SDK 对变更请求拒绝复用身份的行为正确，问题出在教程连续操作说明。

建议：该步骤明确同步换成 `request-structured-001` 等新的 command ID，解释新定义代表新请求；不要通过删除原数据库规避身份约束。

### 6. P3：API 查询、应用测试和评估的现有材料缺少入口

位置：[官网文档结构](/Users/bytedance/Codex-Projects/ralf-agent/website/src/lib/site.ts)、仓库 [API Reference](/Users/bytedance/Codex-Projects/ralf-agent/docs/api-reference.md)、[模型兼容检查](/Users/bytedance/Codex-Projects/ralf-agent/docs/sdk-model-tools.md:132)、[业务评估](/Users/bytedance/Codex-Projects/ralf-agent/docs/business-evaluation.md:12)。

官网覆盖十个主题，但缺少明确的 API/CLI Reference、应用测试和评估入口。模型页要求自行验证协议和工具调用，知识页要求验证回答质量，却没有把用户带到仓库已有的 `ralf-check-model`、model-check starter、`ralf-evaluate-business` 和任务评估材料。用户难以判断方法签名、默认值、返回值、出错契约，以及如何把离线回归和真实模型质量验收分开。

建议：先整理现有资料，提供 Reference 入口及一条最小应用测试路径，不必一次扩成大量新页面。分别说明离线业务回归、模型协议兼容和真实任务质量的目标、命令、预期输出、限制与费用条件。

## 对使用者的帮助程度

以下是基于任务走查的定性判断，不是用户研究或转化率测量。

| 使用者任务 | 当前帮助 | 主要差距 |
| --- | --- | --- |
| 理解项目定位、判断是否适合 | 较好 | 可以再增加经过验证的 SDK 版本和支持范围快照 |
| 无密钥跑通第一个审批示例 | 较好 | 当前离线路径和业务效果边界说明清楚 |
| 接真实模型并加入业务工具 | 基本具备 | 进阶资料链接失效；修改输出约束时缺少新命令提醒 |
| 开发多轮、补充输入的应用 | 不完整 | Agent 装配衔接错误；持久输入入口缺失 |
| 导入自有文档并开始词法 RAG | 较好 | 摄取和查询有具体命令；语义检索、Facts 深入装配依赖外部资料 |
| 独立查 API、编写测试、验收效果 | 偏弱 | 缺少 Reference 与测试/评估的清晰路径 |
| 英文用户完成进阶开发 | 不完整 | 关键深入资料为中文 |

现有优点值得保留：首页能力与文档入口能对应；离线起步门槛低；明确区分业务成功与审批/执行回执、执行额度与费用、Local 默认路径与实验性扩展；没有把离线检索结果写成真实模型质量，也没有声称所有协议或后端组合均已验收。桌面文档目录、当前主题语言切换和移动端十主题导航也可正常使用。

## 对照其他开源项目文档

比较的是组织方法和任务可完成性，不是框架性能、生产可用性或功能排名。

| 官方文档 | 值得借鉴的做法 | Ralf-Agent 应采取的具体改进 |
| --- | --- | --- |
| [AgentScope 2.0.10 Quickstart](https://docs.agentscope.io/en/versions/2.0.10/quickstart) 与 [版本化入口](https://docs.agentscope.io/en/versions/2.0.10/index) | 版本明确；安装、版本验证、模型与工具装配、首次 Agent 调用构成一条路径 | 固定经过验证的 SDK/ref；从模型工具到 Session 使用同一套可运行入口 |
| [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) 与 [API Reference](https://docs.langchain.com/oss/python/reference/overview) | 暂停与继续作为独立操作指南，交代前提、身份、恢复步骤和约束；参考查询独立组织 | 补齐持久用户输入和恢复步骤，并建立可直接定位的 API/CLI 查询入口 |
| [Pydantic AI Testing](https://pydantic.dev/docs/ai/guides/testing/) 与 [Agent Reference](https://pydantic.dev/docs/ai/api/pydantic-ai/agent/) | 测试替身、阻止真实请求等测试方法有专门说明；方法签名、参数和返回值可查询 | 基于 Ralf 自有离线 Provider、starter 和评估工具写测试指南；不把离线通过当作模型质量证明 |

其他项目也不代表每个示例已在本次实际运行。建议借鉴 Tutorial / How-to / Reference / Explanation 的分工：一个连续教程帮助起步，短操作指南解决具体任务，Reference 支持查询，概念页解释执行契约。现有十个主题可以保留，不需要靠增加页数弥补断点。

## 建议实施顺序与验收

1. **先修正确性和可达性：**统一文档引用、修复 Agent/AgentSpec 衔接、补充结构化输出的新命令身份。验收应从干净目录连续执行中英文教程的前后两步，并检查目标仓库 ref 和文件存在。
2. **再补使用闭环和语言等价：**增加持久输入路径，整理一个模型 → Session → RAG/Facts → 工作流的连续应用例子；让英文用户可完成同样任务。关键步骤带文件位置、命令、预期结果和失败后的下一步。
3. **最后完善开发维护支持：**增加 API/CLI Reference、应用测试与模型/业务评估入口，展示最后验证的 SDK 标签或提交与日期，以及 Local/Temporal 和可选能力的支持边界。

这次审阅发现的问题说明，上轮“没有剩余 P1/P2”的结论覆盖不足：示例定义可构造、离线 starter 可运行、来源哈希一致，并不能证明教程前后步骤能直接衔接，或远端文档链接可达。后续应把跨页连续操作和真实引用检查加入验收。

## 本轮验证与限制

- 重新执行 `npm run docs:check`：10 组双语指南与所记录来源一致；这不是语义准确性的保证。
- 重新执行 `npm test`：5/5 通过。
- 检查已有构建产物：24 页，1129 个站内链接/资源/锚点通过；本轮没有重新构建。外链不在该检查范围。
- 两种语言的 Session 对象衔接分别复现 AttributeError；结构化输出连续修改在临时数据库中复现 IdempotencyConflict，并验证新 ID 可提交。均未调用在线模型。
- 只读核验 Git 远端默认分支及 main 分支/标签；统计当前 HTML 中对应链接。
- 浏览器走查英文会话 → 模型工具 → 同主题中文切换；390px 下移动目录含十个主题，页面无整体横向溢出。
- 全部 20 篇指南及其关键实现由独立只读审阅再次核对。对照官方文档采用上述直接链接。
- 未新增真实付费模型、Temporal 服务、远程数据库或 Docker 的运行验收；未改动其他任务正在修改的 SDK 文件。
