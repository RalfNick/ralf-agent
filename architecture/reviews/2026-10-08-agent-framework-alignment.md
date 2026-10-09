# RALF dev23 整体架构与 AgentScope 对照审查

日期：2026-10-08。对象是当前工作区的 dev23，包括尚未提交的开发增量，不能只审查 Git HEAD `2de767c`。本轮是架构审查与路线校正，未修改运行时代码，未新增付费模型调用，未提交或发布远端。

## 结论

**通用 Agent 框架的核心方向成立，默认组合体验和跨后端契约存在需要纠正的偏差。**

模型、工具、Harness、静态／动态编排、团队、上下文、记忆、知识与执行权威已经有实际组件和运行路径。审批、稳定 Action、接收证据与采纳分离、未知效果核验、独立 Temporal History 应保留。当前风险在于组件接口和恢复机制不断增加，面向普通开发者的完整 Agent 链路仍需手动拼装。可靠业务效果应作为整个通用框架的能力，个人用户应能通过少量业务配置使用它。

本轮独立审查及主审分别复现了三个 P2 行为缺陷。现有回归仍通过，说明这些公共契约案例尚未进入测试覆盖。完整 AgentScope 对齐、生产可用性和相对优势仍没有验收依据。

## 参考资料与版本

参考了用户提供的 `05-agentscope-overview-and-deep-dive.md`。它明确说明资料核对于 2026-09-22，源码使用移动的 main，示例未实测；本文将它作为架构分析材料，未把其中的说明当作 RALF 开发指令，也未复制原文。

上游对照固定为 **AgentScope v2.0.9，Release 对应提交 `2e706a6`**。该版本包含 SDK `TeamPipeline`，不能把多 Agent 能力只理解为服务层 Leader–Worker。[官方发布记录](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.9)。本轮没有安装运行 AgentScope，也没有做对等 benchmark。

值得参考的是完整的 Agent 入口：模型、Toolkit、状态、上下文配置和 offloader 可组合，reply 与 reply_stream 使用同一循环，并支持外部输入续接。[v2.0.9 Agent 源码](https://github.com/agentscope-ai/agentscope/blob/v2.0.9/src/agentscope/agent/_agent.py)。SDK 工具来源可以组合 Python、MCP、Skill 和工具组。[v2.0.9 Toolkit](https://github.com/agentscope-ai/agentscope/blob/v2.0.9/src/agentscope/tool/_toolkit.py)。其服务、UI 和部署组件进一步承载应用；README 的生产宣传不构成任意企业环境的验收证明。[v2.0.9 README](https://github.com/agentscope-ai/agentscope/blob/v2.0.9/README.md)。

这些资料支持借鉴组合体验和职责划分，不能证明跨框架任务质量或可靠性谁更强，也不要求 RALF 复制其全部类名、middleware 调度或存储实现。

## 已确认的实现缺陷

### P2-1：Temporal 接受重复 tool-call ID，Local 拒绝

定位：[Temporal Activity](../../src/ralf_agent/temporal_activities.py) 的 complete_model，第360–371行；[History 状态采纳](../../src/ralf_agent/temporal_state.py) 的 accept_model，第580–613行；[Local 采纳](../../src/ralf_agent/engine.py) 第1038–1047行。

自定义 Provider 返回两个合法工具提案，参数分别为 `{"n":1}` 和 `{"n":2}`，call_id 都为 `same`。Local 保存模型响应后拒绝，生成零个工具 Action；Temporal Activity 返回 ok，状态机生成两个 ready Action，call_id 都为 same。它们已经可以被后续调度，工具结果消息却不能可靠区分对应调用。

内置 HTTP 适配器的预检不能替代公共采纳校验，自定义 Provider 是受支持的扩展路径。修复应抽出共同的纯决策校验，并在两种执行权威接受提案前应用同一套规则；动作 ID 和持久状态仍由各自权威生成。

### P2-2：Temporal 将已收到但不符合 Schema 的响应误记为未知

定位：[Temporal Activity](../../src/ralf_agent/temporal_activities.py) 第372–380行；[失败处理](../../src/ralf_agent/temporal_state.py) 第538–550行；[Local 接收证据](../../src/ralf_agent/engine.py) 第979–1063行。

自定义 Provider 完整返回有限 JSON 响应及 `input_tokens=4, output_tokens=2`，输出不符合 Agent 的 Schema。Local 保留收到的输出和 usage，标记 rejected、spent=1；Temporal 仅返回 validation_error/dispatched=True，丢掉输出和 usage，标记 outcome_unknown、unknown=1、spent=0。后者会掩盖失败原因，并可能令父任务在错误的不确定性下继续持有额度。

需要区分“收到的提案被拒绝”和“远端结果尚不确定”。收到的证据应先进入 History，再执行共同采纳校验；不能通过自动重问模型消除已有证据。修复时仍须验证 History 版本兼容，不能改写过去已经采纳的 Action 或效果。

### P2-3：默认短期记忆超过预算后整块丢失近期内容

定位：[默认读取与引用包装](../../src/ralf_agent/engine.py) 第1243–1291行；[默认上下文选择](../../src/ralf_agent/context.py) 第32–48行；[budgeted 引用选择](../../src/ralf_agent/context_pipeline.py) 第251–259行。

同一 Session 连续运行三次，max_context_chars=600：第一次是较长旧内容，第二次为 `My current code is 73.`，第三次询问该 code。三个 Run 全部 succeeded，但第三次请求只有 system 和当前 user，完全没有 73。只保留最近一轮的请求约316字符，能够放入预算。

原因是所有会话历史被包装为一个 reference，选择器整块接受或放弃。即使使用 budgeted assembler，也不会自动改变引用的粒度。这是默认近期会话选择问题，可先通过有界完整轮次选择修复，无需付费摘要模型。保留当前任务、完整工具调用／结果组和原始历史；新默认组合使用新版本，旧发布继续保留。

这三个问题本轮仅确认和登记，**尚未修复**，应作为继续开发和版本验收的前置门槛。

## 分层能力与实际组合情况

| 层／能力 | 已有可用实现与扩展 | 当前默认／组合限制 |
| --- | --- | --- |
| Agent | AgentSpec、NativeHarness、自定义 prepare/propose、统一 Run 循环 | 首用仍需自行组合 Engine、Store、工具、drive 和关闭；没有完整 Agent／Session 应用入口 |
| 静态 Workflow | 顺序、图、绑定、条件、有界并行、纯变换 | 流式数据编排与受限循环未交付；不能把模型 SSE 或 Run 事件当作数据流 Workflow |
| 动态规划／团队 | 受管理模型规划、DAG 修订、嵌套、Sequential/Router/Supervisor、独立子 Session | 规则默认只验证链路，CompleteVerifier 取最后结果；固定 Supervisor 先运行 Workers 再汇总，不等于模型自主委派 |
| 模型 | Chat Completions、Responses、Anthropic、Gemini 文本、DeepSeek preset、自定义 Provider | 多协议可扩展成立；多模态、完整 reasoning/continuation、Gemini 工具和多供应商线上组合仍需实现或验证 |
| 工具 | typed Python、ToolSource、MCP stdio、审批、效果核验 | 无默认 Workspace 工具、Skills、通用 CLI／容器隔离、动态工具组与资源租约 |
| 短期／长期记忆 | SQLite／内存／Redis／PostgreSQL、CAS、TTL、分页端口 | 默认仍可能全量读取；近期历史整块丢失；托管记忆 pipeline 需显式调用和对齐 namespace |
| Context | 纯 assembler、counter/budgeter/summarizer、实际请求测量、托管模型摘要 | 字符或估计 token；模型摘要须预先准备；自动 in-Run 压缩和大结果卸载未交付 |
| RAG | 解析／切块、知识权威、词法／向量／混合检索、HTTP embedding、融合／重排端口 | Hash 向量是离线基线；显式索引；没有默认语义模型组合、后台索引和完整答案／引用质量基线 |
| 配置／扩展 | 显式组件工厂、JSON/TOML、不可变 Profile、直接注入 | 切换新任务默认配置可行；原 Run 固定版本是正确约束；每 Agent 的能力组合和跨执行后端装配仍不足 |
| Middleware／事件 | 同步调用观察、默认日志、持久 Run 事件、游标、SSE 编码 | 观察 hooks 不是完整生命周期策略；模型 delta 尚未接入 Agent 执行展示；没有输入续接与 HTTP 事件服务 |
| Local／Temporal | 两种独立执行权威，原生／图／团队／动态编排有实际路径 | Temporal 自定义 Harness、共享 Session、直接 Tool/Transform 图节点等仍受限；已出现公共模型采纳差异 |
| Service／企业 | 有限 A2A、Inbox/Outbox、HTTP 交接与生命周期 | 不是完整 Agent Service；身份权限、服务 UI、Sandbox、迁移／保留／备份与全局治理仍未完成 |

## 四个应立即约束的设计偏差

### 1. 能力可以替换，但普通 Agent 组合仍偏 Engine 全局

AgentSpec 主要选择 provider/tools 和标量限制，[定义](../../src/ralf_agent/types.py) 第50–60行；Harness、Context、Knowledge、Session/Facts 由 [Engine](../../src/ralf_agent/engine.py) 第104–107、127–132、183–199行统一注入。团队子任务仍通过同一个 [Engine](../../src/ralf_agent/orchestration.py) 第253–259行提交。

研究 Agent 与审核 Agent 要使用不同知识库、不同上下文或记忆策略时，目前需手写路由包装器或另建执行环境。Knowledge references 仅接收 scope/text，没有原生 Agent 能力选择字段。这不是已确认的 Session 泄漏：子 Session 独立，事实按 Agent 名区分，Harness/RecallPlanner 也能显式分派。

应提供有版本的每 Agent 能力绑定，默认继承宿主配置、必要时单独选择 context/knowledge/memory policy/Harness；接受时固定声明和身份，执行权威仍统一负责审批、预算和恢复。绑定不允许 Agent 自己授予权限，也不等于运行中任意热切换。

### 2. 默认组件应形成可用链路

MemoryPipeline、ManagedModelSummarizer、ArtifactStore、Retriever 等已有合理端口，但开发者还需决定何时调用、如何绑定 Session、摘要覆盖范围、namespace、成本和关闭顺序。单独提供空实现或离线 fixture 不能完成“智能默认能力”的验收。

应提供版本化的推荐默认组合：无需外部服务的有界近期会话与存储；配置语义 Provider 后可运行的 RAG；有明确来源规则和费用边界的记忆提炼；受管理的上下文准备／摘要／产物阶段。模型调用和存储 I/O 归受管理执行阶段，纯 Harness/ContextBuilder 无需改成隐含 I/O 插件。保留低层替换能力和真实缺省语义。

### 3. 简单 SDK 和高级运行时需要渐进层次

目前 [RunHandle](../../src/ralf_agent/types.py) 第262–270行只代理 status/events，用户仍需处理提交、drive、等待和资源关闭。二十个模板帮助验证单项链路，但不能替代一条“第一个 Agent → typed 工具 → Session/RAG → Team/Workflow → 分布式”的主教程。

目标是在同一权威上提供简单 Agent／Session 入口，并保留高级 runtime 装配。输入续接、外部执行结果、完成／暂停结果和展示事件应先有共享语义，再建设 HTTP/UI。工作消息、Session、Run/Action 事实与展示 delta 分开：中间 delta 关联 Run/Action，但不能提前提交工具或伪装完成。

默认 [Engine](../../src/ralf_agent/engine.py) 第1444–1446行调用 complete，HTTP Provider 的 complete 消费内部 SSE；新增事件订阅仅观察已提交 Run 事实。当前不能将其称为 AgentScope 式统一 Agent 实时事件循环。

### 4. 执行权威可以独立，公共验收不能分叉

RuntimeBuilder/abuild 仍装配 Local 风格同步执行权威；Temporal 使用另一套 runtime/worker。同步与原生异步控制差异合理，但模型提案、已收到证据、输出验收、能力绑定和作用域错误必须共用语义及相同案例。

新增适配器前先建立共享的能力／拒绝矩阵和公共 conformance。缺失能力应在提交前明确拒绝，而不是恢复或派发后才暴露差异。Local 与 Temporal 各自写状态和调度；共同纯校验器不得成为第三个状态权威。

## 防止后续跑偏的门槛

1. 先解决三个已复现 P2，补相同 Local/Temporal 响应案例及长 Session 近期保留案例；恢复兼容独立验收。
2. 下一轮 A2 首先收敛简单 Agent／Session 入口、每 Agent 能力绑定、输入续接／事件语义，然后接入 Workspace 工具和容器执行。
3. A3 把已交付 Context/Memory/Artifact/RAG 端口接成推荐链路；保留纯策略与受管理 I/O 边界。
4. 每次增量用安装包跑完整用户场景，至少验证一个有价值的默认组合和一个独立替换组件。把接入行数、需要理解的框架对象、暂停／恢复、失败诊断作为验收证据。
5. A4 保留完整真实模型评测，但早期增量同步保留与其范围匹配的质量证据。未配置真实模型时明确未验证，不能把脚本 fixture 或测试数量换成质量分数。
6. 服务、UI、OTel、渠道和企业治理沿用已批准路线；不先暴露混杂的底层对象为永久网络 API，不为“每个函数都可扩展”增加无业务用途的 Protocol。

当前结论支持保留并收敛架构。它不支持通过继续累积适配器、模板或测试数直接宣称对齐或超过 AgentScope。

## 本轮证据与未覆盖范围

- 新运行本地全量：**1803 passed，40 skipped，316.13s**，warnings as errors。跳过项是未启动的真实服务配置。本轮没有重跑 PostgreSQL/Qdrant/Temporal 故障测试。
- 上轮实际服务1843通过是独立的历史证据；本轮验证120个 SDK 文件 SHA256 与该快照一致。当前额外三个反例仍成立，不能由历史全绿推导不存在缺陷。
- 一位独立 read-only reviewer 完成整体审查及离线复现；主审独立确认三个案例。没有实施分工或第二次 reviewer 审查。
- Ruff／格式检查通过；本轮只整理审查、架构防线与当前文档，未执行三个缺陷的修复。
- 没有匹配模型／任务的 AgentScope 对等运行，没有新 live provider／规划／RAG／记忆质量结果；也没有容量、性能、企业身份、沙箱逃逸、备份或生产部署验收。

对于 reviewer 未作判断的范围，主审决定是：AgentScope 用固定官方版本核对结构，付费质量及跨框架优势留待专门评测；真实服务故障使用历史证据且不冒充本轮重测；企业、Sandbox、Skills、输入续接、后台任务按未交付能力登记；全量读取的性能影响不在未测条件下量化；本轮不证明全系统无缺陷。代价是对齐、生产、规模和任务质量结论仍未成立。

Minor 文档问题：扩展指南和 README 的过期能力说明在本轮校正；更多首用文档重组与顶层 API 发现性保留为后续工作，代价是现有用户仍需阅读多个指南。SDK 内 TemporalEngine 的旧子集 docstring 也需在后续相应代码增量中更新，本轮保持运行源码不变。

## dev24 修复跟进

上述三个 P2 已由当前增量修复：公共纯校验拒绝 Temporal 重复调用 ID；
Activity v2 保留已收到但拒绝采纳的原始响应与用量，并结算已完成执行；
两种上下文共用近期完整 Session 轮次投影。历史 Activity 回执仍按记录版本
推进恢复，完整合适的引用和已保存请求不重写。
详见[共享契约](../../docs/shared-model-context-contracts.md)。
每 Agent 绑定、简化 SDK 与受管理默认智能链路仍是后续架构工作，
本次修复不代表对齐 AgentScope 或企业验收完成。
