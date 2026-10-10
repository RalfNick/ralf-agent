# dev46 Temporal 自动记忆与每 Agent 绑定验收

基线 5528670／dev45。实现沿 H1/H3 既有契约，原 History 权威不变。

## 实现与边界

- AgentDefinition／BoundDefinition、声明路径和 scoped BindingCatalog 复用；provider／context／knowledge／tool_set／stage_policy 五类选择进入实际 Agent 与原子树。其他角色／资源 selector 在接受前拒绝。
- 新能力显式 temporal-3；原 temporal-1／2 发布保持。catalog／实际实例／方法、Scope、写目标与 namespace 在 await 前后固定。
- History 记忆规则与 Worker I/O 分离。来源、selector 请求／响应、字段采纳、准确初读、CAS 派发与核验分别保存；模型仅选择宿主允许字段，不生成持久值。
- selector／CAS 单次尝试与独立额度。取消由原 History 授权边界阻止新派发；晚到证据仍记录。显式根 drive 通过原未知子 Run 控制递归核验，不重新派发模型／CAS。
- CAS 超时后事实准确匹配不等于远程已停止；子额度仍由父级持有。记忆未知额度也不能宣称已 quiescent。观察接口没有记忆 I/O。

## 已观察证据

绑定首批 10 项 RED→GREEN，相关回归 82 passed。记忆阶段新增 9 个初始失败，随后规则／模型、预算、取消与回执测试通过。真实服务复现 Facade 拒绝绑定定义，已接入原入口；JSON 传输将元组变列表的身份误判有 8 项失败复现，改为规范化摘要比较后通过。实际 sandbox 采纳中纯类型引用固定，恢复不跳过来源校验。

初步真实 Service：六类编排 × 两种 Worker 退出窗口，加读取取消，13 passed；随后平层／嵌套根子恢复及 CAS 在途超时三项通过。针对性最终回归 125 passed。并行恢复仅证明夹具的已记录窗口，不代表所有同时崩溃交错。

真实 localhost Temporal Service 最终 **26 passed**：原 16 项记忆恢复与 6 项 temporal-2 上下文恢复，加四项 temporal-3 每成员上下文／产物策略切换和 Worker 重启。实际父子 History 均重放；未调用外部模型。产物测试仍观察到服务载荷警告，卸载仅投影模型上下文，不缩减原 History，容量不是本轮验收结果。

安装后的最终 wheel **151 passed**，Python 模块逐字节匹配当前源码；wheel／sdist 构建通过，新模块、指南与恢复测试进入 sdist。dev45↔dev46 原生／纯自定义上下文／managed-context 六项双向审批 JSON 快照恢复，通过独立 wheel 进程、真实 Activity 调用和 SQLite 审计证明原状态规则兼容；这是离线状态快照验证，不是跨版本在线 Worker 部署升级。原三类 manifest 完全一致，旧 wheel 拒绝 temporal-3，两个原 Policy 类 AST 不变。

最终全量 **2919 passed／92 skipped（438.06s）**；未配置真实服务／模型等对应项跳过，额外已配置 localhost 服务的 26 项单独通过。Ruff、格式与 Git 空白检查通过。

## 保留范围

不证明语义记忆质量、业务任务质量或整体 AgentScope 对齐；本轮未调用真实模型和 Redis／PostgreSQL 服务。Temporal Session／Facts 自动召回、其他绑定角色／resource selector、语义修订／撤回／遗忘、多事实跨库原子性、长期容量／保留／部署升级仍待完成。没有推送或发布。

## 独立 review 与修复

一次新上下文只读 review 给出三项 Important，无 Critical／Minor；均接受并在同一修复阶段 RED→GREEN，不以第二次审查替代测试。

- 相同顺序 AgentSpec、输入和结果会复用前一成员上下文：temporal-3 的缓存摘要包含 node 与原绑定；纯／managed 两种测试通过重建状态继续运行验证实际上下文及阶段。旧协议摘要不变。
- catalog Knowledge 在 references／validate await 期间替换方法仍可通过：宿主固定 catalog 中 references／validate 和 context 方法，每次 await 后复核；三项替换测试拒绝派发。
- 历史产物使用当前成员策略，切换 plain 时查询崩溃或 managed 时误标：每个新协议阶段记录原策略与绑定；两项查询／恢复测试保持原目标，旧协议取原 root 策略。

七项复现初跑均失败，修复后相关 145 项通过；最终安装契约 151 项包含这些用例。全量还发现旧协议绑定 wrapper 在拒绝前进入 transport，已恢复显式 temporal-3 前置门槛。新增真实 Worker 重启也复现纯上下文准备只有单次尝试会因进程退出失败；仅 temporal-3 只读 context Activity 改为最多三次，原 temporal-1／2 不变。

## 决策与代价

以下按 ledger 的记录顺序保留完整 rulings；没有待办 Minor。

1. 在当前特性分支连续开发并最终本地提交，沿用用户授权；代价是共享分支历史，计划与最终差异用于审查，不推送。
2. 首写 CAS 改用既有 expected_version=0，修正文稿 None；代价是同键冲突保守失败，不覆盖目标。
3. 显式根 drive 沿原未知子 Run 控制恢复，temporal-3 quiescence 包括保留额度；代价是证据不足／停止未知时继续持有父额度，不让观察查询触发恢复。
4. temporal-3 只读上下文准备最多三次；代价是自定义 Knowledge 读取端口必须可重复读取，不能在准备里写业务效果或隐式调用模型。
5. 用已安装构建依赖与缓存旧 wheel 离线验收；代价是干净依赖 bootstrap 仍由 CI 验证。
6. 独立 reviewer 读冻结工作区快照，最终门槛后提交；代价是快照非不可变 commit，修复后的测试及完整树比对覆盖后续变化。
7. 真实模型选择用途与语义记忆质量继续未证明，仅离线有限夹具；代价是采用前仍需质量验收。
8. Redis／PostgreSQL 部署与跨机器持久性本轮不验证，共享 SQLite 仅为故障夹具；代价是生产共享后端需独立门禁。
9. History 容量／payload 卸载／保留／Continue-As-New 单独交付，原载荷保留；代价是长任务可能超过服务容量。
10. 共享 Session／Facts 召回、其他角色和资源 selector 明确未支持；代价是对应组合拒绝，不能静默继承替代。
