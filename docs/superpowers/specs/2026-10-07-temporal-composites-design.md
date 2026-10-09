# dev17 distributed composition, RAG and execution governance

用户要求继续实现分布式 DAG/Team/RAG、治理与真实质量，原架构及继续实施授权有效。本轮原地保留旧增量，不提交/发布。架构扩展按独立组件实施及一次最终新上下文审查。

## Authority and compatibility

新增 TemporalParentState + 独立 ParentWorkflow，以 History 保存子调用意图、稳定身份、绑定、观察、计划修订及额度。原 native Run/registry Workflow、请求及默认 native manifest 不变。父级不调用 LocalEngine/SQLite，不以 PostgreSQL 为执行权威。成员支持 Agent/sequence、Agent-node静态图、Team/Dynamic 嵌套，最多8层/256组件；不支持直接 Tool/Transform graph节点，预检明确拒绝。

Worker runtime 默认提供规则/模型 flat/DAG Planner、Sequential/Router/Supervisor、CompleteVerifier，可通过原结构化端口替换。runtime.orchestration_release 返回包含组件注册的扩展发布，runtime.manifest 保留原 native 身份；显式 facade 使用扩展 release。原发布在原注册仍可用时继续恢复。

父级 History 先保存 escrow 与稳定 child command/Run ID，再以 registered control Activity 保留 scoped registry 身份，再 start_child_workflow(ABANDON)。原子采纳时固定 child request/release/depth。注册/观察/取消控制 Activity 借用 Temporal Client，明确绑定 parent Scope/child记录，只返回已完成有限证据；模型/工具仍归子 History。读观察可重复，业务 Activity 单次 dispatch。child startup/recovery不得生成新command或Run。

Parent snapshots 汇总 child等待/未知，approve/reconcile 使用实际 childRun/action/digest；取消传播使用稳定内部ID，不重开终态。parent credit cap 在 child终态且quiescent、无待采纳/未知时结算，未知保留整个子cap；child spent汇总，父结果不覆盖晚到证据。父实际终态继续接受观察以完成资源证据，不取消业务线程或隐藏未知。

DAG复用现有pure dependency/binding/condition compiler，采纳模型提案保存received/adopted及revision。明确 max_children/max_concurrency/max_revisions；pending-only patch CAS 保留已派发/完成节点和绑定，重复命令返回原回执。Verifier可有限replan，模型Planner只使用一个已预留cap的tool-free child，不隐藏Provider调用。

## RAG evidence boundary

TemporalRuntime(knowledge=KnowledgeContextPort) 可注入默认 KnowledgeContext，包括PG/Qdrant组合。接收输入的Scope由Run权威提供。独立 Context Activity 检索/validate、有限 references、ContextBuilder消息，先将实际snapshot持久化History，再调用模型；模型派发前再validate固定引用与组件身份。重启复用已接受snapshot；更新/删除/跨Scope证据拒绝新模型派发。context失败无模型费用，消息工具组仍完整。Knowledge生命周期借用宿主；不在Workflow直接访问外部存储，不提供共享Session写入。

## Execution governance

新增不可变 TemporalExecutionPolicy(version,max_children=256,max_concurrency=32,max_depth=8,run_timeout_seconds=None,approval_timeout_seconds=None,allowed_tools=None)。构造时有限类型校验，注册identity固定入发布。限制在dispatch前执行；期限使用History timer，审批期限从首次pending起算。deadline请求取消且保留晚到证据/真实线程hold；审批过期不执行业务工具。该治理是版本化执行限制，不宣称OIDC/企业ACL/globalquota/retention已完成。

## Adoption and quality

新增独立 temporal starter：显式Service/worker、离线默认、无需付费模型，提供Agent/DAG/Team/RAG示例及子审批恢复提示。可替换真实Provider/Knowledge，optional extra不进入base依赖。新增端到端业务任务质量评测：不同故障原因、证据不足、歧义/拒绝、正确工具参数/停止/批准/恢复、usage/latency。默认not_run，offline成绩标注runtime fixture；真实调用仅在Provider/model/call/cost配置确定后执行，hard currency bounds不能证明时failclosed。

## Verification

TDD纯状态/扩展契约、真实两个Worker、DAG/Team/嵌套/审批/取消/未知效果/patch/kill恢复、PG/Qdrant检索与snapshot重启、实际timer拒绝。最终完整suite、installedstarter/contracts、实际dev16 native/parent/12+1模板/History升级、SDK字节与deps元数据。一次新审查，重要问题RED→GREEN。临时服务验收后停止。
