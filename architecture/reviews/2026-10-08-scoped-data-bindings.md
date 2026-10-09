# dev28 Local H1d — Facts／Knowledge 范围绑定

日期：2026-10-08。基线为本轮保存的 dev27 未提交 SDK 快照；Git HEAD 2de767c 不包含全部历史增量。本轮继续 H1 的资源范围契约，不增加执行权威或重写 AgentSpec。

## 实现与默认组合

FactsBindingResource 与 KnowledgeBindingResource 由宿主登记允许的 namespace。Local 原生、顺序、并行图、Team、Dynamic 和嵌套成员使用不可变视图，固定 Scope／范围／组件身份，并复用原同步／异步存储和检索端口。默认内存／SQLite 有离线实现；Redis／PostgreSQL／Vector／Hybrid 的原端口与工厂继续可替换。

Facts 视图只读，逻辑 Agent namespace 映射到固定物理 namespace，引用附带来源和值摘要；不开放 MemoryPipeline 写入或自动信念修订。Knowledge 使用原生 KnowledgeContext 包装可替换 retriever，保留来源版本／摘要／过期校验；自定义 Context 仍可原样登记，但框架不猜测其范围语义。允许范围并非企业来源 ACL，元数据不是针对任意可信 Python 的加密签名。

来源身份、实际委托客户端、Knowledge retriever 对象和配置在 await 前后复核。选出的视图不能再次登记或作为宿主默认数据组件；资源包装器不拥有借用客户端。JSON／TOML 两个 wrapper 复用原 sync／async 工厂和 actual-client own／own_async，校验与冻结配置发生在创建客户端前。

数据 Resource 使用 local-bindings-4；未选择新包装器时，原生、H1a、H1b、H1c 发布身份保持。Session refs 按声明识别，混合 kernel4 不丢失实际地址准入，纯数据 refs 不强制自定义 Store 具有 Session 准入端口。能力探测独立报告三种 namespace selector 角色。

## 独立审查与一次修复

一次独立上下文审查比较本轮七个 SDK 文件与 dev27 的130模块快照；审查者运行61项离线契约。发现 P1：视图隐藏原 `_method_backend` 守卫，稳定 proxy 的真实异步客户端变化仍能触发模型；以及 P2：按 max_items 预留来源空间，稀疏且能放入预算的事实被后端永久跳过。

一次 TDD 修复覆盖 facts／recall／validate_facts 的委托守卫，以及内存／SQLite 的实际预算、连续分页和来源快照变化。专项先复现 **7 failed／1 passed**，修复后新增与原数据契约合计 **56 passed**。没有第二轮审查，使用完整回归和最终安装包验证修复。

Facts 默认桥接每次读取一个来源候选，按实际追加元数据计算字符预算；不适合当前页但适合空页的记录通过来源游标／快照保留，游标不存记录载荷或创建另一份执行状态。每次读取／重读计入 scan_limit，来源不前进或快照变化时拒绝。代价是可能增加远程往返，legacy 后端仍可能全量读取；不把该桥接宣传为大规模检索性能优化。

审查未裁定的事项按边界分别处理：完整／安装／旧新 wheel／真实 Redis／PG 由本轮根代理提供实际证据，不称为审查者服务认证；真实质量仅报告26次实测，不推断框架对等；来源 ACL／加密防伪／MemoryPipeline 写／跨权威租约／Temporal 绑定／其他角色／H2 未交付；与本轮无关的 dev13–27 历史保持；文档和发行包最终检查在审查后完成。

## 验证证据

资源阶段与原 recall／Knowledge 契约 **185 passed**；初步组合、配置、实际 Redis、旧 Session 和复合故障契约 **101 passed／1 PG skipped**，另补实际 retriever 同身份替换 **RED2→GREEN**。最初测试夹具的路径／包装／Profile 序列化误用已纠正；顺序会话和结果携带前步数据的原语义保留，隔离只约束直接数据召回范围。

修复后完整回归：**2055 passed／44 skipped，283.03秒**。修复前为2047 passed／44 skipped。最终 wheel 在源码 checkout 之外通过 **211项绑定契约，12.98秒**；安装包真实 Redis **1 passed**，PostgreSQL **1 skipped（未配置服务）**。配置依赖跳过不计为通过。

Ruff／格式／Git 空白及文档链接检查通过。131个 SDK 模块在源码／wheel／sdist／安装目录中逐字节一致；最终发行包的教程与脱敏报告和当前源文件一致，排除私有验证目录、真实凭据及业务数据库。文档／METADATA 更新后的包与已测试 SDK 字节相同，不再次重复已通过的模型或运行契约。

真实 dev27 wheel 创建9个旧审批任务：原生、H1a Agent／顺序、H1b Graph／Team／Dynamic／嵌套、H1c namespace Session 与1.1MB有效原生 Schema。最终 dev28 返回原提交／重复审批回执，保持原 Manifest，每个任务产生一次测试业务效果。dev27 对新 scoped-data 发布以 DefinitionMismatch 拒绝，Run 和零写入保持；dev28 执行原审批后写一次。证据依赖测试业务幂等键，不保证任意外部操作恰好一次。

## 真实 DeepSeek 质量

固定配置、完整冻结8个业务案例各跑两次：**10/16**。六个修复样本 **0/6**，模型正确诊断后未请求 apply_fix、未进入写审批，业务写入为零，却回答 resolved。缺输入／拒绝样本 **10/10**。新 Facts／Knowledge 范围值与引用提取 **4/4**，只是有限合成来源任务。

总计 **26次调用、15,742输入／735输出 token**，不重试、不修改 oracle、不对子集额外付费复测。试验发生在最终身份／分页修复前；稳定无分页路径的输入未改变，修复后没有再次声称模型质量已通过。[报告](../../docs/live-model-quality-dev28.md)保留全部分数、限制和机器可读结果；密钥仅临时 stdin／进程使用，未保存或传入 Agent 上下文。

本轮说明业务 Verifier／完成证据约束是实际采用门槛：Run.succeeded 和合法 JSON 不能代替业务效果。完整 M1、复杂 RAG／记忆质量、独立采用和 AgentScope／LangGraph 对等实验仍未完成。

## 使用与后续

[数据绑定教程](../../docs/data-bindings.md)提供默认／替换／配置／生命周期／来源／分页边界；[剩余清单](../../docs/remaining-work.md)从 R01 移除已交付的 Local 数据范围子集，R10/R26 明确保留业务完成验证缺口。其余 H1 资源角色与 Temporal 绑定、H2 统一入口、推荐受管理数据组合继续按原顺序推进。

代码、报告和安装包保留本地。未提交、推送或发布；本轮只进行上述已授权模型调用。
