# 基础能力：先跑通，再定制

[文档目录](README.md) · [核心概念](concepts.md) · [示例与模板](../examples/README.md)

当前优先保障个人开发者能安装、完成任务、接入自己的模型与工具，并在重启后继续运行。复用已有接口与默认实现；不为起步链路新增抽象、适配器或部署服务。

## 起步顺序

1. 按[首用教程](getting-started.md)生成独立项目，跑通提交、审批、恢复与重复提交。
2. 按[模型与工具 SDK](sdk-model-tools.md)接入真实模型和自己的 Python 工具。
3. 按业务需要选择[基础 Harness](recommended-harness.md)、[Workflow](static-workflows.md)或[RAG 模板](recall-and-rag.md)。

希望沿用同一应用时，按[连续工单教程](support-journey.md)依次加入真实模型、Session、RAG、显式 Facts 和顺序 Workflow；[扩展方式表](extending.md#先选择扩展方式)区分端口替换、继承扩展与当前限制。

离线 Provider 用于验证框架装配与执行行为；真实任务效果按模型、工具和业务数据单独验证。已有真实参考任务的冻结证据继续按[验收清单](remaining-work.md)记录的范围引用。

## 默认实现与替换入口

| 基础能力 | 起步实现 | 定制方式与说明 |
| --- | --- | --- |
| 模型 | 离线 Provider；明确配置后使用真实模型 Provider | 替换异步 `complete` 端口，或选择已有协议适配器；[模型接入](model-adapters.md)、[模型替换](model-adapter-contracts.md) |
| 单 Agent | `AgentSpec`、`Agent` 与 Local 执行 | 自定义指令、输出 Schema、工具集合与预算；[Agent API](agent-api.md) |
| 基础 Workflow | 顺序执行与静态图 | 自定义步骤、依赖、条件与输入绑定；[Workflow](static-workflows.md) |
| 工具 | Python 工具与默认执行器 | 注册自己的函数、Schema、读写效果和必要审批；[SDK 指南](sdk-model-tools.md)、[执行组件](execution-components.md) |
| 上下文 | 默认 ContextAssembler；可选现有 managed-data 组合 | 替换上下文策略，按需开启摘要和工具大结果投影；[推荐组合](recommended-harness.md) |
| 短期与长期记忆 | 内存／SQLite 会话与 Facts | 从[Session API](session-api.md)与[记忆召回](recall-and-rag.md)开始；按需使用[Session 适配](session-adapter-contracts.md)、[Facts 适配](facts-adapter-contracts.md) |
| RAG | 本地词法知识检索与现有 RAG 模板 | 替换摄取、Embedding、向量检索和重排组件；[检索与 RAG](recall-and-rag.md)、[知识适配](adapter-contracts.md) |
| 配置与恢复 | SDK、JSON／TOML Profile，本地 SQLite 执行记录 | 自定义工厂与组件所有权；按原配置恢复任务；[运行装配](runtime-assembly.md)、[恢复指南](recovery-guide.md) |

内存、SQLite 和词法检索是低依赖起点，不代表分布式存储或语义质量。Redis、PostgreSQL、向量数据库、MCP、CLI、沙箱、Plan／Team 和 Temporal 已有不同范围的实现，按需要使用对应指南；它们不成为所有基础应用的前置条件。

## 当前开发边界

先修复基础链路中可复现的失败、接入障碍和文档错误；执行相关回归与必要的安装后验证。已有接口能满足的需求，优先补示例和修复，不再增加一层通用封装。

所选 Temporal Coding Session 已在 dev19 按用户修订的 Activity90／整链600秒门槛完成同包18/18验收，原360秒失败及各旧候选失败保留。当前进入0.1.0a2本地发行收尾，不扩功能；新包平台、远端CI及公开安装资格分别取证，不继承旧a1成绩。长期R01–R26仍保留，见[阶段矩阵](phase3-support-matrix.md)与[当前Alpha范围](releases/0.1.0a2.md)。

## 基础用法检查记录（2026-10-16）

| 范围 | 验证结果 |
| --- | --- |
| 默认SDK、工具、Workflow、记忆与starter | 9个现有模块214项通过，包含独立wheel安装后的审批、进程崩溃恢复和RAG运行 |
| 模型与Python工具接入 | 3个现有模块54项通过；README示例在独立安装包中执行两次，Schema、工具往返与原回执复用通过 |
| Local Session与审批 | 4个安装用法场景确认观察超时、持久busy拒绝、继续原Run及跨Turn审批；修正用法下每Turn仅一次SQLite业务写入，重复批准返回原回执 |
| RAG文档更新 | 6个独立进程确认CAS更新后相同命令复用版本1响应、新命令获取版本2 |
| 配置与恢复 | 2个现有模块23项通过；安装包11个独立进程确认新默认／原Profile恢复、回执重放、缺失原版本拒绝和坏配置下的只读观察 |

各行记录不同验证范围，不相加为全量回归。所选基础用法检查已收口，修正了首用文档、等待／审批示例及配置说明；产品代码与原接口未变。没有调用真实模型或外部数据服务，不代表所有模型、后端、真实质量或阶段门槛均已完成。后续以具体使用缺口驱动修复，不为延长本轮排查增加组件或抽象。

### 后续修复：自定义工具 Schema 缺少必填约束

2026-10-16 复现：Python 函数需要参数，但显式 Schema 漏写 `required` 时，Local 会生成无法执行的审批请求，Temporal 模型 Activity 也会采纳该缺参提案。现于原 `RegisteredTool.resolve_arguments` 边界，在 Schema／默认值解析后拒绝缺少函数必填参数的输入；不修改用户 Schema、工具身份或执行权威。默认值、宿主 context、bound method 和 keyword-only 参数保留原语义，接入说明见[工具 SDK](sdk-model-tools.md)。

新增12项回归覆盖缺参拒绝、合法顶层／组合 Schema 原身份、默认值及原审批关闭重开恢复；原命令／批准回读后只发生一次业务写入。源码10模块178项通过，wheel 安装后5模块86项通过，产品425文件与源码逐项一致；安装检查在 checkout 外执行，无源码导入路径，复用现有依赖。Ruff、格式和空白检查通过。Temporal 证据仅为模型 Activity 的公共参数采纳，不是实际 Service／History 验收；本批未调用真实模型或外部服务，也不关闭新的阶段门槛。

后续复核又复现注册后新增 `__defaults__`／`__kwdefaults__` 会让缺参检查放行的问题。现改为检查合并原已捕获默认值后的全部非 context 参数，不依据后来变化的 Python 默认值决定参数能否缺省；原 Schema／工具身份不变。4项新增／参数化用例先失败后通过，相关源码12模块209项、独立安装7模块117项全部通过，包含原审批恢复、重复批准以及真实同步线程取消／关闭检查；425产品文件与安装包逐项一致，Ruff／格式／空白检查通过。验证范围不扩展到真实模型、实际 Temporal Service 或第三阶段门槛。

工具参数冻结边界收口：补充5项签名元数据用例，其中4项先复现失败；隐藏实时签名可放行缺参，额外／非法实时签名也会误拒绝正常默认调用。公共采纳检查现仅使用原 handler 已冻结的参数集合及已合并默认值，移除对实时签名和可变 descriptor 的依赖；未增加字段或公共端口，原合法 Schema／Manifest／审批恢复保持兼容。相关源码10模块187项、checkout外独立安装3模块62项通过，425产品文件与源码一致，Ruff／格式／空白检查通过。本批至此结束工具参数专项，不追加新抽象、角色或服务组合；完整阶段验收状态保持不变。

### 后续说明：默认本地项目的备份演练

[恢复指南](recovery-guide.md#默认本地项目的手工备份演练)补充默认离线 oncall 项目的两库手工备份、原路径恢复及范围限制。直接执行文档中的 Python，在 checkout 外使用已安装包验证4场景：待审批恢复、业务已提交但原回执尚未保存、Coordinator占用拒绝和业务库缺失拒绝。25个子进程全部退出；前两场景保留原Run／命令／Action／事件／额度，重复批准与恢复后业务效果均只写一次，缺失效果库时没有创建空库。备份使用SQLite backup API与原工厂租约，目标目录0700／数据库0600；执行库、默认记忆及本地测试业务库纳入该演练。产品和测试文件均未改动，不重复运行无关回归；没有真实模型或外部服务调用。其余数据组件、真实业务系统、在线一致性与P3-5完整框架备份恢复仍未验收。

后续P3-5另以相同442产品已安装包完成有限[框架数据恢复与版本回退](framework-backup-restore.md)：
Local源码／安装各3项、实际Temporal／PG两次备份恢复的1项完整场景通过。
原基础证据不改写，范围／失败／制品归属见[本批记录](../architecture/reviews/2026-10-18-framework-backup-restore.md)；
这不证明生产灾备、任意Schema降级或全部数据组件组合。

## 基础修复的完整离线回归

2026-10-16 固定产品提交 `b871f61`，在清除模型密钥及真实服务配置的环境中，一次执行全部测试：

```bash
.venv/bin/python -m pytest -q -ra
```

结果为 **12,749 passed／838 skipped，零失败、零错误**，共13,587项；JUnit报告与命令退出码一致。425个产品文件与862个Python测试文件前后哈希一致，另2个JSON夹具与固定提交核对一致，合计864个测试／夹具文件。全量Ruff检查通过，1,293个文件的格式检查通过；结果来自同一次完整运行，未拼接局部重跑。

838项跳过保留原原因，主要依赖真实Temporal／PostgreSQL／Redis／Qdrant／Docker等显式配置。此次是完整离线源码回归；同一产品的独立安装3模块62项沿用上方原批次证据，不改称完整安装矩阵。它不补足真实模型质量、外部采用或P3-2/S2原360秒等服务门槛，不关闭完整M1／第三阶段／R01–R26。基础修复及本次集成验证收口，继续按具体基础使用缺口推进，避免增加新层和未选组合。
