# Temporal 根会话与成员私有会话验收

状态：dev67 本批最终验收通过；基线 ae9854e/dev66；只本地提交，不推送。

落实[原计划](../../docs/superpowers/plans/2026-10-11-temporal-session-trees.md)与
[完整外置 Session 契约](../specs/temporal-session-data-contract.md)。原 Parent 负责根读、
聚合证据、写额度、回执与成功；原 Native History 负责成员私有保存。
Coordinator 只管理 Turn／占用／Conversation 投影；拓扑与存储均不调度业务。

## 实际范围

- 显式 CompositeSessionTopology，固定配置／方法／身份，纯同步提案和不可移除的 Scope／namespace／代际校验。默认 native/save-v1 不改发布。
- 根会话与独立私有成员源分开；结构化路径、原 Agent 声明与根 binding revision 固定成员地址。
- 原 Parent 读根后才派发；普通／managed Context 保护原根及私有快照，只读取一次。摘要、大结果、RAG、自动规则／模型记忆和每 Agent 绑定复用原阶段。
- 原聚合保存先预留额度，精确 CAS/message receipt 收到与采纳独立；子孙及真实处理器必须停止，取消不反转。
- 实际 SQLite/Redis/PostgreSQL、独立 namespace、History-only 根／私有远程源、混合源，两 Turn 与所有原 History replay。
- 独立 Worker kill/wait 覆盖根读采纳、私有保存、根聚合/提交/收到回执等窗口；真实 handler 活跃时 busy、CloseIncomplete 和迟到通知被验证。

## 唯一独立审查与修复

Fresh-context Astra 只读审查 dev67 整批；独立运行110相关测试通过，无二次 review。
发现一项 P1：Activity 根读取超时可清除 Action，实际线程仍在读，导致 Turn 释放且关闭误报。
状态2项 RED，真实 Worker/ThreadedMemoryAdapter1项 RED；修复后原 SessionExecutionOwner
拥有完整 read Future、保护观察取消，并通过原 session_execution_ended Update 送达精确结束证据。
根读改为单次尝试；无许可的迟到派发拒绝、无实际处理器启动的容量拒绝能够结算。
相关30和82通过，真实 blocked-reader1通过。最终 full/安装/服务另列。

Deferred minor：temporal_session_tree_protocol.py 的 propose_manifest docstring 仍描述候选未发布；
构造器与公共指南已说明显式发布，留作后续注释修订。

## 最终门槛

最终源码完整回归、修复后整批实际服务、安装包／core／模块与 METADATA、
旧新默认及 native-v1 History、指南和自有服务关闭证据已完成，最终快照见下。此前源40/417.34s、
安装206及实际23/238.78s均为 review 修复前范围，不能替代最终版本。
无真实模型调用；不以 scripted planner/RAG/记忆的契约证明模型质量。

## 保持开放

Temporal Profile／starter、跨权威租约／FIFO／输入续接／数据迁移、环境角色、
全量既有原生读者生命周期治理、容量／保留／企业身份、真实质量与外部首用仍待交付。
同宿主 SQLite Worker kill 不等于远端数据库所有网络／服务故障窗口；完整 H1/H2/H3/M1 和 R01–R26 保持开放。

## 实现判定与代价

- 原 Parent 读／保存一起开放，避免读已开放而保存仍提前成功；代价是较紧密的实现／测试依赖。
- 跨权威租约／FIFO／迁移是后续协议；代价是多个独立执行权威共享数据仍需额外协调。
- 改变自定义 Team call ID 不自动继承旧私有会话；代价是连续交互需要稳定 ID。
- 公共 graph/team/call ID 继续拒绝斜杠；代价是未来放宽验证须补路径兼容测试。
- Scripted 结果只证明运行契约；代价是当前无真实质量／对等性能结论。
- 最终 full／制品／兼容／文档必须验证后才提交；代价是证据不足时此批保持未提交。
- 全量原生读取处理器治理未由本 review 认证；代价是尚不宣称所有读路径的关闭安全。


## 最终冻结快照

- 完整源码 **3801 passed /267 configured skips**，508.59s，7679 exit0。未配置服务跳过不作为真实服务通过。
- 最终安装契约 **198 passed**，9.80s；最终安装真实服务 **41 passed**，455.60s，57843 exit0，包含实际 Temporal/Redis/PostgreSQL/-Werror、独立 Worker kill/wait、全部 History replay、根读/写真实线程取消、源替换、自动压缩/卸载/RAG/记忆。
- 源码实际41/469.59s（50658 exit0）在主读者修复后、最后重复拒绝分支前；最终安装41重新覆盖全矩阵，不以旧源码范围冒充最终冻结产品。
- 同一P1修复补充：无许可迟到派发拒绝、没有处理器启动的容量拒绝结算；重复读取拒绝不能释放第一次处理器。后者1RED→最终相关83 passed7.15s。原 full70721因后续修复主动中断/exit2，不记作通过。
- 226 Python模块在源码/wheel/core安装一致；dev67版本与METADATA匹配。fresh core-only可完成图根/成员两Turn、SQLite原生保存；optional SDK/Redis/PG/tokenizer/PDF不存在。
- 真实安装 dev66→67→66 默认审批与 native save-v1 Session/Turn/原History/单次工具通过；旧66 Worker新协议在原 Workflow激活、业务Activity前拒绝。Local66→67→66→67 默认Profile/Artifact/typed Session/21 starter/审批单次业务效果通过。
- 安装指南原代码在实际Temporal+离线EchoProvider闭环；不构成真实模型质量。
- Ruff/824格式/空白通过；最终sdist文档及226模块与冻结源码/wheel一致。自有PG65460、Temporal92718均正常exit0，PGstopped=0；本批所有Worker/测试已退出。

完整能力未完成；下一批优先审计原生/私有Context读取生命周期，再推进Temporal配置装配。
唯一待办Minor是候选发布docstring，无其余独立Minor。上列所有判定及代价保持；不删除R01–R26目标。
