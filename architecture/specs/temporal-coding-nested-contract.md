# Temporal Coding 递归成员与原祖先关闭契约

基线 dev112／`e86fdc6`。本批关闭第二阶段 Local／Temporal 公共组合一致性中明确未交付的顺序及嵌套成员 Coding 门槛。第一阶段 dev99、未选定默认发布保持冻结；daemon 已发送请求的负向完成、跨宿主恢复及复杂真实模型质量仍是独立门槛。

## 组合与执行权威

Team／Dynamic 的声明成员接受现有 Agent、顺序 Workflow、静态 Agent 图、Team 和 Dynamic。静态 GraphNode 继续只接受现有 Agent 节点，不增加新的图节点 DTO。顺序 Workflow 在一个原 TemporalRunWorkflow 中推进各步骤；复合成员在自己的原 TemporalParentWorkflow 中采纳计划、分派子预算和管理直接后代。

每层 History 只授予、观察和采纳自己的直接 child；SDK parent、原 execution epoch、namespace UUID、Scope、request／release digest、command／call／member／revision、cap 与 depth 对应原不可变 child intent。沿既有 execution policy 限制 depth、child 数量和并发；不通过扁平化丢弃原父级身份或预算。递归投影每个实际 Agent 绑定，不将模型占位成员作为工具授权。

每层固定定义树并递归验证并发、隐藏 planner／verifier 禁止 Coding，以及所有实际叶的有效绑定。隐藏辅助 Agent 仍使用原注册槽并纳入关闭。原 parent link 字段保持，depth 为原父 depth＋1；只在新版本允许递归，旧选定发布由对应不可变 Worker 续接。

## 准入与容量

根继续由 scoped Registry 接受并固定 namespace／epoch。嵌套 parent 不创建新的根级 Registry 准入：逐层核对实际原父 History 的已派发 child intent、固定 SDK epoch 与完整投影，回溯到唯一已接受的根。根准入关闭或任一祖先 cancelling／cancelled／failed 时，嵌套 parent 不开启新业务，沿自己的原停止意图排空。

叶 Action 仍拥有单次审批、attempt、prepare／Thread／Turn grant 和 PG 原资源证据。每层父预算与未知费用按既有 escrow 传播。已结算不替代物理停止，全部原后代实际结束并被每层采纳后才释放该 child 的父内资源占用。dev111／112 的物理根容量继续保护跨父实际 Runner；不在树上新增全局调度权威。

## 控制与关闭

普通恢复和取消只控制固定原 epoch，不转向同名最新 Workflow，不重试 CREATE／START 或重授 native grant。owned close 首先耐久关闭原根 Registry 准入，再从原 History 枚举原完整后代树，包含旧计划 revision、未创建 PG 资源的辅助 Agent，以及顺序成员尚未执行的步骤。

每个直接 edge 均核对原 child request、cap、depth、parent link、epoch。取消所有可证明的原后代，叶按原 stop 门槛退休；复合节点依次采纳直接后代的完整物理停止证明。沿原祖先逐层收尾，不能用一个叶停止替代整个 subtree 停止。

PG 资源可能位于任意叶层级。关闭前与重扫时必须证明其精确原请求属于当前根已接受的完整父子链；外来、断裂、循环、过深、重名而 epoch 不同的链均失败关闭，不能把 unknown resource 当作新根或跳过。发现或证明失败时尝试其他独立义务，保留具体原责任并支持同配置重试。

关闭需要取得完整 tree 的全部 child evidence。存在未知 descendants、lost owner 或未排空 Activity 时保留 CloseIncomplete。原 receiver 在最后停止证据采纳前保持可用。观察超时不取消业务，也不作为结束证明；物理关闭不清除未知效果和费用。

## 发布与验收

新 selected native6／binding22、composition7／binding23，topology 为 `bounded-recursive-orchestration`。旧20／21由 immutable dev112 Worker 续接，未选定默认保留。新增纯遍历与 SDK ancestry／tree 控制 helper 加入手列指纹库存；History 不导入 SDK I/O，PG 不推进 Run。

验收必须包括 SDK／JSON／TOML 的顺序及递归声明、每 Agent 绑定投影、depth／并发／隐藏 Agent 越权前置拒绝、原 immediate edge 与 ancestor chain 错配、旧 revision、重复控制请求、物理停止与费用独立、全循环取消与 owned close 失败重试。真实 Temporal＋PG 至少覆盖顺序成员审批重启、两层嵌套成员运行取消／关闭和原 History replay；安装包与 immutable112 原21恢复分别验收。机械 native peer 不计作新模型质量成绩。

职责分工：根集成 SDK ancestry／tree 关闭与公共文档；独立任务实现 pure topology／link／proof；独立任务更新显式版本门槛、Worker marker 与兼容测试。共享版本和契约由根统一，不允许各任务自行删减 invariants。
