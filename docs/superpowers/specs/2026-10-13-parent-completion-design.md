# dev92：Plan／Team 业务完成验证

## 目标与授权

推进R10／H3：业务结果必须经过已声明的回执规则，才能作为Plan／Team成功结果发布；可显式替换为独立模型验证阶段。每个阶段有默认实现、SDK／Profile配置、版本固定、预算和恢复证据。用户已授权持续实现R01–R26、独立任务并行、逐批验收及仅本地提交；沿既有架构推进，不再请求重复授权。

基线为dev91本地提交`8ad6664`。当前`PlanVerifier`仅接收子结果，默认取最后结果；Team策略返回done后直接完成。现有库存评测会事后识别假成功，但尚未阻止运行成功。本批补齐父级验证链路，不把库存业务规则当任意业务的通用真值。

## 方案选择

采用新增`ParentCompletionPolicy`组合纯规则与可选受管理模型阶段。直接令旧`PlanVerifier.verify`异步会把I/O藏进规则和Temporal选择Activity；仅给业务成员安装leaf verifier也无法证明跨子Run来源。新组合由原Local事务／Temporal History构造证据、托管模型子Run和采纳结论，规则和阶段只提出决定。

保留原`CompleteVerifier`、`PlanVerifier`、Agent `CompletionVerifier`与`verifier`绑定含义、所有旧默认和原Run身份。新`completion_policy: str | None = None`加到`DynamicWorkflowSpec`和`TeamSpec`，None时不序列化。引擎／Worker的注册参数统一为`parent_completion_policies`，ComponentRegistry增加同名类别。仅显式选中的policy使parent使用新协议。

原Plan verifier先产生候选：原failed／replan维持原语义；原succeeded.result进入新gate。Team的done.result进入gate。新gate的accept仅发布冻结candidate，不修改答案。Plan规划结论needs_input/refused也必须走选中gate；未选中policy维持原路径。

## 公共协议

新增四个职责明确的模块：`parent_completion.py`定义DTO／Protocols／Policy；`parent_completion_rules.py`定义通用回执规则和库存oracle；`parent_verification_stage.py`定义默认模型阶段；`parent_completion_protocol.py`定义共享注册／digest／证据验证工具。公共对象沿`_JsonValue`、canonical和脱离副本惯例，schema_version为整数1，component version为字符串1。未知字段、非有限JSON、惰性返回和不完整证据拒绝。

跨owner共享helper固定为`policy_registration(policy)`（纯注册身份／方法digest，不含有效provider release）、`validate_policy(policy,parent_kind=None)`（验证并返回注册）、`validate_request_bounds(policy,request)`、`gate_verdict(policy,request)`、`prepare_stage_input(policy,request)`、`interpret_stage_output(policy,request,output)`和`validate_verdict(request,verdict)`。gate／prepare／interpret的返回值和证据ID由helper统一校验；有效Agent release由各执行权威的原binding/provider装配补入。helper签名变更必须先通知root和两个权威owner。

```python
ParentCompletionRequest(
    *, parent_id, parent_kind, scope, release_digest, revision,
    task, plan, candidate, children, receipts, constraints,
)
ParentCompletionVerdict(status, *, feedback=None, evidence_ids=())

ParentCompletionPolicy(
    gate, *, model_stage=None, verifier_budget=1,
    max_source_bytes=262_144, max_receipts=256, max_evidence_children=256,
)
```

request序列化字段精确为`schema_version,parent_id,parent_kind,scope,release_digest,revision,task,plan,candidate,children,receipts,constraints`。parent_kind仅dynamic/team；revision为非负整数，Team为0；plan是本次已采纳proposal或None。source_digest由权威计算。

每个child证据为普通JSON对象，字段精确：`id,call_id,role,member_path,run_id,release_digest,state_revision,planning_revision,input,input_digest,input_consumed,result,result_digest,final_action_id,final_snapshot_digest,final_models`。role仅worker；member_path为非空声明路径列表；planning_revision为本次根parent request的来源revision或合法保留节点的原根revision；nested后代继承其顶层child的根来源revision，内部Plan的修订由权威原ancestor／当前plan独立核验。`id="child:"+digest([run_id,release_digest])`。直接／嵌套原child的拥有者、Scope、release、原parent链必须验证；仅succeeded且原执行和预算静止的业务child可成为证据。容器child的final_action_id/final_snapshot_digest/input_consumed为None；native leaf的input_consumed只能由权威检查实际最终模型请求与原input后产生。result/input digest严格对应实际值。没有合法来源就拒绝，不能接受模型自报的Run／回执。

`final_models`是实际原Run内的最终模型Action索引，每条字段精确为`member_path,action_id,snapshot_digest,input_digest,input_consumed`。native child恰一条并与顶层final/input字段一致；sequence／graph容器按原frame/节点归属记录已完成leaf slots，不制造虚拟leaf Run ID或重复child id。容器模型路径为其原member_path的合法步骤／节点后代。原frame不足以证明来源／消费时明确拒绝，不能补造input digest或声明已消费。nested Team／Dynamic的真实子Run沿parent links递归投影，保留各自实际Run身份。

`member_path`统一为逻辑业务成员层级，两个权威使用同一规则：根成员为`[name]`，嵌套成员追加name，顺序步骤追加`["steps",str(index)]`，图节点追加`[node.id]`。它是回执规则的可移植地址，不改变既有AgentBinding配置地址。图的直接工具节点没有模型slot，允许真实container后代路径的回执携带空`consumed_by`；非空消费证明仍只能引用同Run／同path的真实最终模型。默认`require_consumed=True`会拒绝未消费回执，显式False可用于直接工具节点的纯回执验证；权威仍需证明实际节点来源。

每个tool证据字段精确：`id,run_id,member_path,action_id,tool,arguments,result,receipt,effect_key,consumed_by`。`id="tool:"+digest([run_id,action_id])`，arguments为实际采纳参数，receipt/effect_key来自原已提交Action；consumed_by为原最终模型Action标识列表，每个标识为`"model:"+digest([run_id,action_id])`，须属于同实际Run／对应leaf路径的final_models。权威检查原call_id、结果canonical内容和工具→最终模型顺序后生成消费证明。v1要求完整literal工具结果；Artifact投影／摘要不能静默当完整原结果消费。原完整模型历史仍保存在child，不复制密文或全部transcript到验证task。

constraints字段精确为`remaining_steps,remaining_revisions,max_concurrency,verifier_budget,parent_budget`，Team remaining_revisions=0；parent_budget使用原权威快照。冻结前确认业务children无pending／unknown／held／仍运行handler，保留既有取消及静止契约。嵌套证据有界遍历原拥有关系；不能通过普通模型输出指向任意Run。当前plan可合法引用保留节点，但旧revision的无关好回执不能证明新candidate。

Verdict仅accept/reject/replan。accept无feedback；reject反馈可选；replan要求1–4096字符feedback。evidence_ids为最多256个不重复的已存在child/tool证据ID。Team拒绝replan；Plan受revision/step/credits限制，不覆写旧动作、审批或效果。错误证据ID、替代candidate或未声明字段使验证失败。

## 纯规则与模型阶段

```python
class ParentCompletionGate(Protocol):
    identity: dict
    def verify(self, request: ParentCompletionRequest) -> ParentCompletionVerdict: ...

class ParentVerificationStage(Protocol):
    identity: dict
    agent: AgentSpec | AgentDefinition
    def prepare(self, request: ParentCompletionRequest): ...
    def interpret(self, request: ParentCompletionRequest, output) -> ParentCompletionVerdict: ...

ModelParentVerificationStage(
    *, provider="default", instructions=None, bindings=None, version="1",
    model_credits=1, max_context_chars=32_768,
)
```

所有gate/prepare/interpret均同步纯函数；返回具体DTO/JSON，不接受awaitable、generator或context manager。policy注册固定identity和实现digest／原绑定方法；调用前后检查drift。stage.agent固定tool-free、max_decisions=1和有界Verdict Schema，I/O只发生于原Agent执行路径；模型工具提案、invalid Schema／foreign IDs／child失败均明确失败。原Provider续接和预算计量继续复用。

默认stage返回AgentDefinition，显式关闭facts/knowledge/stage_policy/session/model_history/verifier等辅助能力；artifact/workspace/skills/sandbox与工具集同样禁用。required context继承只有在有效Context无模型摘要／外部读取时才允许，或用户配置原catalog中的纯context ref。不得偷偷插入catalog资源。自定义stage可显式选择独立Session/原生history，但必须通过原能力、limits、源和预算检查；不能继承出未计量的辅助模型调用。Profile验证provider alias/ref、context与工具集在任何owned工厂之前完成。

纯gate先执行并记录，非accept零模型调用。accept且无stage直接采纳；accept且有stage冻结prepare结果，驱动唯一verifier child，成功输出经interpret成为提案。模型accept仅在原gate accept时成立；模型reject/replan可收紧决定。模型不得消除缺回执、参数错误或停止失败，也不得替换candidate。proposal收到后可恢复纯解释和采纳，不重新调用模型。

policy的max_source_bytes为1..1_048_576，receipt／child上限1..256。source与prepare结果均按canonical UTF-8限额校验；不能裁剪必要证据后通过。默认verifier_budget=1，无stage不预留；有stage需覆盖有效Agent model credits。模型context与host/绑定limits取交集，超限或不足额度在模型dispatch前失败，未知调用仍使用原held/reconcile证据。

## 默认业务规则

`ReceiptParentCompletionGate(rules, *, required_members=(), candidate_schema=None, on_missing="reject")`要求非空rules。required_members为声明路径列表的序列。每条rule精确为`id,member_path,tool,when,result_schema,argument_bindings,output_bindings,require_consumed`；when/result_schema可为None，require_consumed默认True。

argument_bindings把参数名映射到`{source:"task"|"candidate",pointer:JSONPointer}`；output_bindings把receipt.result中的JSON Pointer映射到相同selector。每个对应值按canonical精确比较；when对candidate应用本地Schema。规则要求同一原工具回执满足全部参数/结果/消费条件；不能拼接多个相似回执。Schema不进行远程resolve。on_missing仅reject/replan，Team选中的replan规则在preflight拒绝。

规则构造输入必填id/member_path/tool，其他字段可以省略并规范化：when/result_schema=None、argument_bindings/output_bindings={}、require_consumed=True。未知字段始终拒绝；声明身份保存完整规范化规则。required_members为无条件要求；条件停止分支应使用显式领域gate或自定义纯gate，不能因规则未匹配就自动绕过必需成员。

`InventoryParentCompletionGate(*, dataset, request_pointer="", researcher_path=("researcher",), writer_path=("writer",), on_missing="reject")`是具体参考能力包。task的request_pointer选择结构化`dataset_id,target,quantity`；dataset为固定原库存，写入policy identity。严格按对应lookup/calculator真实回执、最终请求消费、researcher→writer输入和整数算式验证completed/needs_input/not_found。缺target/quantity不得调用工具；未知SKU须真实negative lookup；库存不足允许lookup但禁止calculator；completed需精确quantity×单价回执与candidate.total。默认组合不猜自然语言任务的业务真值；评测新显式模式提供原instruction和结构化request，旧评测默认保持。

安装后参考例子同时提供纯gate和独立provider模型stage配置、SDK/TOML替换路径，以及伪造合Schema成功的失败示例。新版本推荐Plan/Team可以选择gate，但原version1/2和无业务工具的通用组合不悄悄换成库存规则。

## 原权威托管及恢复

仅新协议记录child.role=worker/planner/verifier，保留旧planning兼容字段。原planner/worker key不变；verifier固定逻辑调用`ChildCall("verdict","@verifier",prepared_input)`，实际key=`r{revision}.verifier.verdict`，Team为r0。source digest不能进入key；source/policy/Agent变化触发原身份冲突，不建立第二个验证调用。普通worker/planner caller无权任意调用@verifier。

新政策的验证Context只接受实际已知纯实现，不因identity自报或artifacts继承而绕过：内建ContextAssembler，或由内建字符／UTF8估算counter、WholeGroupBudgeter与可选Excerpt组成的BudgetedContextAssembler。opaque reader／counter／summarizer不进入验证child。用户可以通过纯prepare定制验证输入，并独立选择已注册的纯context。此受限默认不能当作任意Context纯性的自动证明。

Local用原reserve+submit+link事务、原child命令ID和escrow；Temporal用原child Workflow／注册控制／History。verifier从业务结果、DAG节点、planning source和Session业务聚合排除，但保留独立诊断、实际结束、费用及显式原生history。Dynamic计入max_steps；Team仅允许额外一个稳定verifier child，原业务member不能重派；两者受host children/depth/concurrency限制。

父journal为`parent_completion_stages`，key=`r{revision}`，精确阶段prepared→child_pending→proposal_received→adopted；纯gate可以prepared→adopted。固定source/source_digest、policy注册、gate_verdict、prepared_input/digest、child key/Run/release、received_proposal、adopted_verdict及状态。source、child意图、proposal接收、verdict采纳分别持久保存，事件为`parent_completion_source_recorded,parent_verification_child_intent_recorded,parent_verification_proposal_received,parent_completion_adopted`。恢复先消费已保存journal；已接收不重调模型，已采纳只推进原结果／最终Session保存，不重算gate或制造新verdict。

显式取消／deadline按原child停止和真实静止证据处理；late proposal收费／保留但不得成功或重规划。缺响应维持原unknown，不因超时自动换模型重试。原最终Session保存位于gate之后；成功提交前复核policy／组件／source身份。

完成source冻结后，外部DAG patch在采纳前拒绝；内部有界重规划仍通过原verdict与revision转换进行。Temporal在原History内部另外固定business_plan和original_child_ids，在adopt及最终发布前独立复核当前计划／结论、原业务来源及静止状态。只允许稳定verifier的已声明额度／步骤、同原settled child的revision递增，以及具有精确原intent／committedreceipt／handler-end证据的root Session额度结算作归一；不得整体忽略constraints或预算。停止结论保存原adoptedproposal，children／receipts为空，不借用旧revision工作。已有feedback只发送给紧接的一轮，原PlanVerifier之后再次replan时清除已消费字段，旧journal保留。

Plan的replan保存一次feedback，下一PlanningRequest新增可选`verification_feedback={revision,feedback,evidence_ids,source_digest}`；默认None不序列化，原request字节不变。下一Rule／Model／DAG planner实际收到该输入；不能只写diagnostics。旧revision证据保留，当前plan来源明确。Team只有accept/reject，本批不实现同member隐式repair loop或durable send_input。

## 发布、配置与兼容

Local仅选中新policy的parent manifest增加`parent_completion_protocol=1`、`orchestration.version="3"`及policy/stage有效release；parent kernel local-8／bound parent local-bindings-16，native leaf维持旧协议。旧Local必须在任何业务I/O前拒绝新定义／发布；实际旧wheel验证。

Temporal非空显式policy registry发布`kernel=temporal-3,binding_protocol=9,parent_completion_protocol=1`。新protocol9需完整兼容已有context lifetime、sandbox/artifact、完整原生history和跨Session源选择；不能只放宽白名单或让后置manifest构造覆盖回8。旧Worker在任何Activity前拒绝9。`ralf-parent-completion-v1`patch与显式release共同选择新Workflow分支，旧History不产生新验证Activity／child。

新增Activity `ralf.temporal.parent_completion.v1`仅执行pure gate／prepare／interpret over frozen source及原snapshot；模型I/O仍在固定verifier child。原selection/control maximum_attempts=1保持。新registration含identity/implementation_digest/gate_registration/stage_registration/effective_agent_release；无stage后两者为None。

Profile配置：`components.parent_completion_policies={adapter:"configured",config:{policies:{name:{gate,model_stage?,verifier_budget?,max_source_bytes?,max_receipts?,max_evidence_children?}}}}`。gate声明adapter=receipt-rules/inventory，stage adapter=model；config字段对应上述构造参数，bindings使用原AgentBindingDescriptor。SDK可注册自定义gate/stage/工厂，无任意module导入。sync/async RuntimeProfile和TemporalProfile用同一声明验证；spec选未注册policy在submit前拒绝。

## 必须验收与开放边界

1. 有效RED/GREEN：伪造成功、错误参数/结果、旧或foreign来源、未消费工具结果、缺成员、未知／仍执行证据、非法model proposal/ID、policy/provider drift、限额、Team replan、late cancel及无效配置零I/O。
2. Local flat/DAG Plan与Team实际业务链：纯规则及受管理模型stage、accept/reject、Plan有界replan和实际反馈、缺输入／未找到停止、nested/绑定/Session/原生history。
3. Local独立进程退出窗口：source、child submit、model receipt/adoption、proposal接收、verdict采纳、最终save；一个稳定child、原回执／预算／效果和无重复已完成调用。
4. 实际Temporal／独立Worker：模型回执／gate采纳窗口、业务审批、cancel／真实stop、未知预算、final Session、native history和完整History replay；实际PID、队列、关闭/reap。服务缺失为配置跳过。
5. 安装后SDK/TOML与独立stage替换、原dev91默认／原Run及旧Worker拒绝、制品模块字节、完整回归／静态、一次独立审查、自有服务正常关闭、本地提交。
6. 库存评测保留独立oracle和原两步评分；新多revision评分严格核对当前lineage和保留的旧回执，不能删检查换GREEN。fixtures／MockTransport继续model_quality=null；真实重复模型质量、费用、外部采用、durable send_input、Team repair和完整R10／H3／M1／R01–R26继续开放。

## 根Session写响应丢失的完成证据

完成验证不能要求已经丢失的Activity响应作为唯一写入证据。原Session权威已采纳的固定save intent、精确提交回执及实际handler结束证明可以共同证明原写已完成；普通ACK仍校验原revision和stop。仅允许归一原固定1credit根写，不改变foreign／duplicate／changed allowance／未结束写／计划或业务来源漂移的拒绝边界。该窗口须覆盖原端口离线恢复，以及实际Worker退出后的History恢复，不能用正常ACK路径代替。
