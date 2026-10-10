# H3 高级编排与 Temporal 数据上下文

范围：dev43 / 07e8e16 → dev44。本轮继续既有能力清单，不新增执行权威。

## 交付

- Local 串行／并行 Agent 图、Team、动态 Plan/DAG、嵌套成员复用原受管理上下文／产物协议。Schema11 首次准入原子启用；默认原生 Schema8/10 与原发布保留。
- 并行节点保留原 Run Actions，辅助证据存于 execution 投影；摘要预算按节点隔离。取消／失败后明确恢复已收到辅助回执。
- Temporal 显式 temporal-2 注册，将计划、产物读／写派发／核验、摘要响应和快照采纳分阶段交给 History；写／摘要单次，纯阶段有界重试。temporal-1 默认分支保持。
- 固定 Scope／实际后端／Provider、产物字节／摘要及知识版本验证在真正模型派发边界执行；晚到／非法摘要回执结算一次，未知回执保留预算与远程不确定性。
- 每 Run 的 context_stages/context_artifacts 为原权威纯查询；并行 Local 带 workflow_node，Temporal 不隐式遍历子 Run。

## 已复现与修复

实际 Service 暴露新 context 阶段 Activity ID 取错工具尝试的问题，已用独立 ID 修复。测试 Worker 固定模块导入，避免 __main__ 与正常导入生成不同工具发布身份；没有削弱发布检查。
本地取消后的恢复测试暴露并行摘要回执遗留，已增加原节点证据结算。
新增 RED→GREEN 验证产物读取 await 期间 Provider 更换会在派发前拒绝，以及已完成但类型错误的摘要回执结算后使用固定回退。

独立最终审查提出四项 Important，均补充复现测试后修复：

- 真实 KnowledgeContext 的 `references(scope, text)` 接口签名统一；原来源在产物等待期间变更时阻止模型披露。
- 产物写超时保留 outcome_unknown，不会被后续工具成功清除；子 Run 未确认停止时父额度不释放。
- 准备 I/O 结束后由原 History 原子授权模型、摘要和产物写；取消先接受时拒绝尚未获准的调用。此前获准的操作仍属在途，采集晚到证据。
- 并行根 Action 留有受管理上下文而整个节点 execution 投影丢失时拒绝查询／恢复，不能将缺失解释为无记录。

没有 Critical 或延期 Minor。语义摘要质量和多机产物部署没有在本轮作质量／生产结论；默认能力与后续验收边界继续明确列出。

## 验证

最终完整回归 **2809 passed／72 skipped**（389.44s）；服务配置相关跳过与离线基线明确区分。Ruff、全仓格式和 Git 空白检查通过。四项独立审查问题均经 RED→GREEN 修复，最终针对性回归 97 passed；没有待修 Important 或延期 Minor。
十二个真实进程退出场景：图／并行／Team／动态 DAG × 产物提交／摘要回执／快照采纳；原工具效果八次，摘要四次，产物一次；无重复已确认效果。杀进程时其他在途模型可能留下未知额度，不声称全部自动归零。
真实持久 Temporal Service 1.32.0／CLI1.9.1：五类 native/parallel/Team/dynamic-DAG/nested Worker kill／restart 和父子 History replay、模型 Activity 产物读取等待期间取消；另运行原 temporal-1 自定义上下文真实服务场景，共 7 passed。服务测试夹具实现固定后重新完整通过，运行中修改夹具产生的发布身份拒绝未被忽略。
实际 dev43↔dev44 wheel 六项原生／summary／data 审批双向恢复，各一次业务效果；最终已安装契约 93 passed。已安装 Basic／Knowledge × 图／Team／动态 DAG 六项统一 Runtime 入口 smoke 通过。实际旧 wheel 只读／可写打开 Schema11 均拒绝，原 Schema8/10 双向恢复保持。两个原纯策略类 AST 未改，依赖与现有公开导出保留。wheel／sdist 使用本机已安装构建依赖、`--no-isolation` 成功构建；隔离环境引导依赖下载未验证。

## 保留边界

高级／Temporal 自动长期记忆写阶段、Temporal 每 Agent 能力绑定／共享 Session、远程产物默认适配／GC、History 大载荷治理、语义摘要／检索／真实质量及完整 H3 尚未完成。
原始工具结果留在执行权威；卸载降低模型输入，不降低总存储。跨机器必须由宿主注册共享产物后端，同机 SQLite 示例不能当成共享分布式存储。
