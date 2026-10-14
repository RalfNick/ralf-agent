# 原 Temporal History 的 Coding 编排契约

适用于 dev110 显式 selected native version 3／binding 16，以及组合 version 4／binding 17。
未选定默认发布保持原字节。旧发布不能通过改标号迁移，必须由匹配的不可变 Worker 续接。

## 唯一执行权威

原父 Workflow History 独占选择采纳、计划 revision、调度、子预算与结果。
原子 Run History 独占其 Agent／Action／attempt、审批、native phase grant 和效果采纳。
Registry 只记录提交接受及停止准入，PG 只记录原资源与效果证据；两者不得推进业务 Run。
所有新增纯规则和 Worker 控制 helper 都有独立完整指纹库存。

## 范围及有效授权

根可为 static Agent graph、Team 或 Dynamic；直接 business 成员必须是 Agent。
sequence／复合成员、直接 Tool／transform 图节点和嵌套组合拒绝。
根 Agent／sequence 的既有单层执行入口仍可使用 native 发布。

每个候选在预留 cap 和记录 child intent 前，按实际声明成员及原绑定计算有效 Tools／Runner。
Dynamic 规划占位 Agent／节点 ID 不能代替成员身份。不同名称引用同一 Runner 时只占一个资源。
隐藏 planner／verifier 必须属于原注册槽，投影其固定 Agent release，不得获得 Coding 授权，
仍作为原子 Run 关联并纳入根停止。

## 容量与推进

子 intent 与 cap 由父 History 原子记录。未准入候选不预留 cap。
原子 Run 已正常结算且原实际 owner 的完整物理停止证明已采纳，才释放 Runner／并发槽。
同根不同资源可并行；Team 稳定扫描队列，保留冲突候选并允许后续独立资源。

相同门槛保护 DAG 依赖、Team done、Planner continuation、verification/replan 与父级完成采纳。
财务结算和物理闭环分开保存；未知效果／费用仍保留，不因物理停止清空。
跨父 Run 全局容量未交付，不将父内互斥宣称为全局互斥。

## revision 和不可变 child

保留完整 version 1 parent link。`planning_revision` 为非负整数，冻结到已接受 child intent。
link 的 scope、成员、命令、call ID、原 request digest、cap、namespace、父 release 与实际 SDK
epoch 均对照原 ledger 校验，不与父级后来可变的 current revision 比较。

replan 不删除旧 children／回执／停止义务。旧 revision 的晚到回执可更新原结算及物理证据，
不得覆盖当前 DAG、成员结果或推进阶段。同 revision 同 member 的早期 call 后到结果也不得
覆盖后来已接受 call 的结果。原已采纳结果保持固定。

Dynamic DAG patch 仅改 pending 节点，并继续校验声明成员、依赖和剩余上限。
所有已调度或已结算节点及其 request／cap／link／epoch 保持原值；静态图 patch 拒绝。
根停止意图、终态或不符合原阶段时不接受新选择、patch 或 replan。

## admission、取消与关闭

三个根类型都先取得 scoped Registry 的原接受与 namespace UUID 绑定，再执行任何业务。
取消／owned close 持久关闭已有提交准入，并枚举全部原 child，包括此前 revision 和无 PG
资源的 hidden Agent。已固定 epoch 不得回退到同名最新 Workflow。

关闭独立尝试每个可证明的原资源，重扫 PG，回到原父 History 采纳停止证据。
部分失败保留具体义务，允许原配置恢复后重试；原 receiver 退出前须完成停止采纳。
观察超时不作为物理停止或业务取消证明，候选结果不作为实际 owner 结束证明。

实际验收登记见[dev110 记录](../reviews/2026-10-14-temporal-coding-orchestration.md)。
本契约不代表真实模型规划质量、复杂 Coding、完整 R13 或第二阶段已通过。
