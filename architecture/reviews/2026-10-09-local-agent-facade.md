# dev31 — Local stateless Agent facade / H2a

日期：2026-10-09；基线：da55f97（dev30），当前未提交 dev31 增量。
完整理想 Harness、H1/H2、AgentScope 对齐与企业可用均未完成。

## 架构与实际交付

- AgentHarness 固定现有原生／绑定／顺序／图／团队／动态／嵌套声明；狭义 Harness 仍是纯 prepare/propose 策略。
- Agent 提供独立或共享入口；Runtime 用 RunTaskSupervisor 持有实际 Local drive；模型、工具、采纳和持久状态仍由原 LocalEngine 负责。
- AgentRun 为在线句柄；旧 RunHandle DTO 保持原公开语义。RunRef 固定原 Scope／权威 locator／Release；WaitResult 独立表达观察原因。attach/status/wait 不恢复派发。
- 超时和取消 wait 仅终止观察；显式控制通过持久 parent/call 关系唤醒原根流程。控制到达暂停 drive 尚未退出时，Supervisor 保留唤醒请求。
- borrowed Agent 仅关闭入口；Runtime drain 自己托管的工作后关闭 owned 资源，borrowed Engine 保持开放。审批和 unknown effects 保留 RunRef；超时／取消 close 的等待不取消清理、真实线程或提前释放 Coordinator。
- 资源关闭失败可重试，资源收尾阶段禁止继续操作；清理不重新读取已关闭的执行资源。上下文退出的业务异常保持主异常。
- Profile 同步／异步工厂复用可信 Scope 与既有 owned/borrowed 资源责任；拒绝不支持的 authority 后清理真实已构造资源。清理失败保留 RuntimeBuildError.cleanup。

没有新增执行权威、业务状态、SQL 表、基础依赖或模型质量结论。
新增 LocalEngine.parent_run_id 仅从已有父子事实验证原祖先归属。

## 验证证据

实施 TDD 覆盖声明副本、1.1MiB 原生 Schema、观察取消／超时、重复提交、组合执行、可信 Scope、原发布漂移、线程归属、关闭重试、unknown effects、嵌套审批及暂停退出竞态。

- 修复前本地相关契约：171 passed in 7.74s；修复后安装包同一组契约增加五项回归。
- 最终实际 wheel，在 /private/tmp 运行包内及旧契约：176 passed in 7.07s。
- 真实 dev30 wheel → dev31 Runtime：十类原审批恢复，原 submit/approval 回执和 Manifest 保持，业务效果各一次。
- 真实 dev31 Facade 接受 → dev30 原核心：相同十类审批恢复保持原回执、Manifest 和单次效果。新入口本身没有改变业务发布协议。
- 134 个基线 SDK 模块与实际 dev30 wheel 完全一致；dev31 修改三个既有模块、新增五个模块。139 个模块在源码／wheel／sdist／安装结果中逐字节相等；私有 workspace、数据库和凭据文件排除。

最终全量回归：2235 passed／44 配置依赖跳过，369.01s，-W error。Ruff、格式、Git 空白检查通过；286 个公开导出在屏蔽 redis/psycopg/qdrant_client/temporalio 后可导入；20 个旧 starter 文件内容摘要保持。服务依赖跳过项没有被计入真实服务／模型／企业验收。两个独立审查问题的一次修复见下。

## 明确拒绝与后续

H2a 为单事件循环内的 Local stateless 子集。接受前拒绝共享 session_id、耐久 Turn／rebind、queue、deadline、handoff 和 Temporal Facade。
进程／事件循环停止后不承诺持续执行；必须使用原代码／组件／数据库显式重连和恢复。
后续 H2b 为持久 Session/Turn 占用与稳定绑定；完整后端入口、H3 自动受管理上下文／摘要／提炼／RAG、H4 环境和 H5 治理按既有清单推进。
完整能力清单保持原方向，没有将可选适配器或测试数量换算成 AgentScope 对齐。

见[实际 API](../../docs/agent-api.md)、[计划](../../docs/superpowers/plans/2026-10-09-local-agent-facade.md)和[剩余能力](../../docs/remaining-work.md)。
未进行付费模型调用、远端提交或发布。

## 独立审查与一次修复

一次 fresh-context read-only 审查：无 Critical/Minor，两个 Important 均通过永久回归复现并修复。

1. 子 Run 的 wait 原来只检查自己的任务错误，但恢复实际由根 Run 托管。批准后原 Provider 缺失时，根 wait 报错而子 wait 超时／无限等待。现在按耐久祖先查找实际根宿主并报告 ExecutionHostFailed；修复原组件后显式 child.resume 可继续原 Run，保持一次效果。
2. 已拥有异步资源的 RuntimeInstance 在创建循环之外首次 submit/close，原 Facade 会先绑定错误循环。现在先复核原资源创建循环，错误调用在接受／生命周期变更前拒绝，原循环仍可正常使用和清理。同步／异步工厂及注入实例保持既有资源责任。

五项新回归：5 failed RED → 5 passed GREEN in 3.17s；无二次审查。

## 本轮取舍与成本

以下对应实施 ledger 的全部 Ruling；不是新增架构方向。

- 沿用户已认可设计继续 inline；不重复审批、切换 worktree 或自动提交。成本：后续范围修订仍需兼容当前增量。
- H2a 先交付 Local stateless 入口，H1 的环境／阶段／Temporal 角色分别依赖 H3–H5。成本：完整 H1/H2 仍未交付。
- 保留旧 RunHandle DTO，在线句柄使用 AgentRun。成本：公开 API 有两个职责明确的句柄类型。
- 不调用付费模型、不写远端、保留本轮私有证据。成本：没有新增智能质量或线上兼容结论。
- 增加只读 parent_run_id，按已有耐久事实恢复原根归属。成本：首期明确只支持 Local。
- 清理重试跳过已完成 drain，清理任务 shield。成本：资源收尾开始后拒绝控制，须完成清理或显式重连。
- Profile Scope 显式传给原 Builder，不从提示词或 Facade options 推导。成本：自定义 Builder 必须遵循已有 Scope 契约。
- SDK 固定后将一次独立审查与安装／全量验证并行执行；不为生成 commit diff 自动提交。成本：后续审查修复需重新完成绿色验证与构建。
- Reviewer set-aside 的 Session/Turn/rebind/FIFO 归 H2b；H2a 拒绝。成本：新入口不提供共享会话。
- Deadline/handoff 明确拒绝。成本：尚无这些业务生命周期控制。
- Temporal Facade／自定义异步权威单独建设。成本：尚不能用本入口覆盖所有后端。
- H3 自动阶段和剩余 H1/H4 角色保持目标。成本：固定声明不等于完整理想 Harness。
- 进程／事件循环退出后只保证已接受意图耐久，持续执行需宿主循环与显式 drain。成本：应用需要管理正确循环与原发布恢复。

- 最终 task-done 核对已执行的全量／安装／升级日志、固定 SDK 摘要与重新构建的包，避免重复运行未变化的绿色全量测试。成本：任何后续 SDK 修改都需重新验证，摘要不匹配将拒绝收尾。

无 deferred Minor；没有将跳过服务测试、旧质量试验或接口预留视作本轮已验证能力。
