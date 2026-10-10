# 每Agent能力绑定契约 — 目标v1.7

日期：2026-10-08；状态：完整目标契约；dev25交付H1a，dev26交付Local H1b、dev27交付Session H1c、dev28交付Facts/Knowledge范围H1d、dev29交付Local纯完成verifier H1e、dev30交付Local limits H1f子集，完整H1/H2尚未实现。
本文落实[AgentHarness设计](../viewpoints/harness-runtime.md)的H1，
约束后续代码/适配器与兼容测试。现有AgentSpec及Harness API保持不变。
已交付与拒绝矩阵见[绑定使用教程](../../docs/agent-bindings.md)：Local原生Agent/顺序流程/图/Team/Dynamic/嵌套成员支持provider、decision_policy、context、facts、knowledge、tool_set；Session增加独立后端与允许的namespace选择，详见[H1c教程](../../docs/session-bindings.md)。Facts/Knowledge增加允许的namespace只读视图与来源校验，详见[H1d教程](../../docs/data-bindings.md)。稳定声明路径与父子发布已固定；模型Planner仍固定宿主槽位。其他资源selector、Temporal绑定、环境角色和H2耐久Turn/SessionAdmission仍待实施。

## 1. 声明与解析对象

新增BindingSelection为显式三选一：
inherit继承宿主默认；ref选择已注册component_id/version及允许的资源选择器；
disabled禁用可选能力。缺省字段等价inherit；null拒绝，不能暗指关闭。
不可缺失的provider、decision_policy、context若解析为disabled，在提交前拒绝。
Session可显式关闭以使用stateless Run；Session Facade或共享会话请求需要Session角色，
此时disabled在提交前拒绝。关闭会话记忆不会关闭Run执行事实保存。
Session解析必须生成规范资源身份/namespace/SessionKey，绑定选择不能绕过原占用。
会话binding_revision、续接/rebind和关闭行为遵循[Facade/Session契约](agent-facade-session-contract.md)。
关闭工具表示有效工具集为空，不能禁用工具治理而继续执行工具。

AgentBindingDescriptor包含：
schema_version=1、provider、decision_policy、context、session、facts、knowledge、
artifacts、tool_set、workspace、sandbox、skills、verifier、stage_policy和limits。
以上字段为目标命名；最终公共DTO必须严格拒绝未知字段并验证有限JSON。

AgentDefinition为新增有版本包装：
kind=bound_agent、schema_version=1、spec=原AgentSpec声明、bindings=AgentBindingDescriptor。
独立DefinitionCodec负责它；旧AgentSpec不增加默认字段，不改变原asdict或请求摘要。
provider继承时沿用spec.provider逻辑槽位，显式ref固定该槽位的实际组件；
原spec不因解析被重写，执行阶段通过ResolvedBindingSet路由到固定Provider。
调用方spec.tools仍为允许工具名称上界；绑定工具集从中选择并接受宿主准入，
不能通过tool_set附加原Agent未声明的业务工具。

ResolvedBindingSet包含声明摘要、每角色component_id/version/identity/backend_id、
接口与能力版本、有效非秘密配置、资源选择器、作用域引用和限制。
运行时对象不写入此对象；资源句柄由装配器在本进程/Worker中根据固定描述取得。

宿主RuntimeProfile增加绑定注册/默认映射时使用新增配置schema_version=2；
已有schema_version=1和无绑定入口行为保持不变，禁止原地扩展已接受Profile。
新的版本化定义可用于显式AgentRef；旧父定义内联AgentSpec继续按旧编码。
Workflow/Team采用BoundDefinition包装：kind=bound_definition、schema_version=1、
definition=原父定义、agent_bindings=逻辑成员路径到BindingDescriptor的映射。
原父定义内联AgentSpec保持不变，映射只增加能力选择而不暗改目标/指令。
路径按声明结构固定，例如graph/nodes/research、team/members/reviewer、
sequence/steps/0、dynamic/members/worker；拒绝不存在的路径和重复/冲突映射。
动态节点选择固定member引用，不能用临时数组位置定位绑定。
不将新对象塞进旧AgentSpec字段，或静默降级丢失绑定。

## 2. 单向准入与请求身份

顺序为：可信Scope验证→规范化调用方请求→按command_id查历史回执→
选择声明/默认Release→解析绑定→能力/政策/Schema验证→记录接受意图和固定Release。
同命令同请求始终返回原回执，不依赖当前默认组件或别名还能否解析。
同命令不同声明、输入、绑定选择、Session或显式限制是idempotency_conflict。

调用方请求保存声明而非解析后组件身份；首次接受的Release保存解析事实。
临时可变别名只用于第一次解析。组件不存在/能力不足，返回明确的准入错误，
不创建可执行工具Action或开始付费调用；持久拒绝回执遵循命令契约版本。

组件可选择，不意味着权限可选择。可信Scope、执行权威、强制HostPolicy、
凭据提供者和全局上限不能被Agent绑定覆盖。
有效工具权限是Agent声明、绑定目录与宿主授权共同允许的集合。
有效额度为Agent/父Run/宿主各自上限的约束；额度角色不混成美元余额。

## 3. 资源与租户范围

每个资源选择器都经宿主验证，组件必须说明可服务的workspace/principal/
namespace/session边界。相同backend_id不等于可以访问所有租户或知识库。

共享Client可以由宿主池化；查询范围/绑定视图按Agent固定且不能在挂起期间
被另一个Agent的参数替换。没有全局可变current_agent/context指针。
并行调用显式传递不可变InvocationContext/ResolvedBindingSet引用。

默认子Session隔离，父子调用身份和Session关联可恢复。
Facts/Knowledge共享策略显式选择private_agent、team或workspace并受宿主授权；
共享范围不由Agent名称、模型输出或外部消息自授。
遗留namespace策略继续保持；新分享策略不会自动搬迁旧事实。

凭据使用宿主解析的secret_ref/授权用途，不写入Release/上下文/事件/产物。
owned与borrowed资源明确，构造失败逆序清理并保留失败重试句柄；
关闭按Facade契约区分独立Agent与借用Runtime；默认drain不等于取消业务。
等待审批/核验的耐久Run/Session占用保留，真实handler未退出或关闭失败不释放归属。
关闭后的在线句柄依赖明确，RunRef通过显式Reader/attach重连。

## 4. 调度、策略与动态选择

Facade/Resolver只选择定义与组件，不提交Action/预算/审批状态。
执行权威将固定绑定传给模型、上下文和工具阶段，继续独立验收结果。
纯策略只产生数据提案；I/O通过受管理阶段执行。

Team/Workflow使用固定AgentRef/成员定义。动态Planner只能选择本Run发布
已经允许且固定的成员，不按自由字符串临时查当前最新Agent。
子Run固定成员绑定与父关系，继承宿主授权上界及分配预算，而非父Agent所有工具。
允许的委派目标、资源范围与工具政策在父发布中声明；子Agent不能借独立绑定
把父任务变成访问宿主所有资源的代理。
子Run可选不同知识/策略；父Run版本变化不能修改已接受子Run。

工具/Skill按固定Release内能力集选择；新增未知版本不能运行中注入。
后续若支持动态目录激活，必须有独立版本化激活契约、准入和事件；H1不提供。

## 5. 本地/Temporal与恢复

Local支持首批按Agent绑定；Temporal在同一绑定种类验收前明确拒绝。
CapabilityDescriptor报告supported_binding_roles/definition_versions/required_stage_kinds，
而不是仅返回一个supports_bindings布尔值。
RuntimeBuilder与Temporal worker都使用同一角色/Schema/权限案例；各自持有执行权威。

默认无绑定Local/Temporal原Manifest和旧Activity/Action快照字节保持不变。
开启绑定的新Release增加固定descriptor版本和对应身份，使用新增定义封装。
不同绑定版本、资源选择器或实现身份漂移在新派发前拒绝；
已收到响应/效果先记录，再拒绝后续采纳，不能变成不知道调用是否完成。
重复控制返回历史回执；不重建审批摘要，不用新绑定替换历史已批准参数。

恢复找不到原组件时保留原Run/Action证据，报definition_mismatch或明确缺失错误。
不回退到最新组件，不复制同Session新Run来规避原未知写效果阻断。
迁移是独立显式操作，不由Facade.run/resume自动完成。

## 6. H1验收案例

- 同Engine内研究/操作/审核Agent使用不同Knowledge/Context/Tool集合，不产生新权威。
- 覆盖inherit/ref/disabled、null/未知字段、缺必需角色、接口/Schema版本和能力不足。
- 同command_id找回原Run：默认别名移动、组件登记移除仍能先返回原回执；
  绑定声明改变则冲突，拒绝时无模型/工具派发。
- 同backend上的不同知识库/namespace并行访问不串范围；跨Scope选择被拒绝。
- Agent可收紧工具/额度，不能扩展HostPolicy；Skill、模型输出和远程消息不能升级权限。
- 共享client与独立绑定视图分别验证；异步等待后身份/范围漂移拒绝且保留收到证据。
- 原有本地审批/结果、Graph/Team/Plan/DAG/nested、旧Temporal History通过实际旧wheel升级。
- 新绑定在审批重启、动态成员选择、子Run取消和预算结算后仍固定。
- 不支持的Temporal绑定提交前拒绝；支持的角色使用相同本地/实际Worker案例验收。
- 安装包默认Agent与独立替换组件可运行；owned/borrowed关闭和构造失败检查通过。
- 基础依赖不增加厂商SDK；fixture只证明契约，真实任务质量另行报告。

这是完整H1的验收要求。dev25只验收上述H1a子集；不把H1a测试当成完整H1或H2验收。

## 7. 与H2的接口边界

H1提供不可变资源身份、绑定引用与原Release；H2提供SessionAdmission/Turn和Supervisor。
H1的资源关闭原则不等于已实现Agent上下文退出；AgentHarness也不持有共享池的隐含所有权。
新增能力一项项按后端声明验收，当前raw drive/close保留原行为。

## dev29 H1e 已交付范围

Local `verifier` 支持纯同步 `CompletionVerifier` 的 inherit/ref/disabled；回执、重试与恢复契约见[完成验证](../../docs/completion-verification.md)。显式选择使用 local-bindings-5；无验证器的旧继承发布身份保持兼容。此端口独立于动态 PlanVerifier；dev62 已提供 Temporal 纯验证绑定，受管理 async/model 验证仍待交付。

## dev30 H1f 已交付范围

Local `limits` 支持纯同步 AgentLimitsPolicy；有效决策／上下文／工具Action caps 在首次接受时固定，与宿主限制及AgentSpec取最小值。ref/disabled 不能删除宿主限制；批次超量整体拒绝。显式选择用 local-bindings-6；无策略旧发布保持兼容。参考[使用与边界](../../docs/agent-limits.md)。此角色不代表共享预算、实际费用、deadline或分布式并发治理。

虚拟并行节点只投影已接受的上限。受管理子 Run 在接受及恢复时验证父级原成员上限，
包括模型 Planner、绑定和嵌套成员；重新调用策略不能采纳更宽松的发布。
存在 limits 的父子关系固定原成员身份，未配置 limits 的旧关系字段与回执形状保持兼容。

## dev61 Temporal H1f 限制采纳子集

宿主 limits 及目录中的 limits 策略增加显式 limits_protocol=1 和 temporal-3。固定登记包含策略 JSON 身份及纯 Python 方法指纹，原角色 descriptor 与稳定路径不变。只配置宿主限制而无 BindingCatalog 时，inherit/disabled 声明也必须可用；disabled 不能移除宿主与 AgentSpec。

每实际 Agent 节点第一次推进时，原 Run History 保存限制请求意图。Worker 只产生严格完成的 AgentLimitProposal；History 独立核验原请求摘要、策略集合、合法字段／有限类型，再与原 AgentSpec 取交集。接受前安全纯提案可以重试，接受后 caps 是恢复事实，不因重启重新计算。Parent 不拥有或计算这些阶段。

普通及 managed Context／model 消费 caps，决定数与累计工具 Action 数在原状态机检查；超限批次全部拒绝，原模型响应和计费证据保持。纯工具批次规则返回数据判定，由原 Workflow 状态机提交 agent_limit_exceeded，避免跨 SDK 沙箱异常身份影响失败状态推进。取消后的限制响应仅保存迟到证据。

dev63 已接通 Temporal 纯 decision_policy；外置 Session 数据与环境角色、父级共享配额、全局容量、真实费用和质量仍是独立能力。实际交付与验收见[指南](../../docs/temporal-agent-limits.md)。

## dev62 Temporal H1e 纯完成验证子集

显式 completion_protocol=1／temporal-3 固定策略身份及方法指纹。原 History 在 mandatory final_output 校验后冻结当前节点原类型输入、候选及已提交工具回执；纯 Activity 的 accept/reject/retry 必须对应原 Scope／请求摘要。只有 accept 进入原记忆／节点完成；取消后的迟到结论只留证据。retry 不重置原决策、工具额度和预算，并保留受保护反馈尾组。Agent ref 替换可选宿主完成规则，disabled 只关闭补充规则；强制 Schema、授权、审批和 limits 保持。绑定子 Run 控制引用使用含 agent_bindings 的原 request_release_digest。详见[指南](../../docs/temporal-completion-verification.md)。

### dev63 Temporal DecisionPolicy

DecisionPolicy 复用公共纯 Harness prepare/propose。固定 host/ref/inherit 选择、identity及两个实际方法、原请求/响应/提案证据，原 History 校验并采纳；必需角色disabled拒绝。实际准备工具只能是原描述的无重复子集，mandatory Schema／权限／审批／限制保持。只支持编译器零参数super闭包及可验证Python基类方法，不允许直接类访问或其他opaque捕获。默认无额外策略的旧发布保持；源代码/解释器变更保留原Worker，不宣称跨版本指纹相等。九类绑定当前已包含decision_policy，外置Session、环境角色和完整H1/H2继续开放。见[指南](../../docs/temporal-decision-policy.md)。

### dev64 默认 Session 数据核验前置

内存/SQLite 增加精确 scoped message receipt，同步与异步端口共用结果契约；Local 独立数据复用原保存恢复，同库默认保持。完整 Temporal 外置数据责任见[目标规格](temporal-session-data-contract.md)，原 Run/Parent 承担数据完成门禁，Session Coordinator 保留占用/静默责任。规格与 SPI 不构成 Temporal 第十类绑定或完整 H1/H2/H3 交付。
