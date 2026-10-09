# dev32 — Colocated durable Local Sessions / H2b1

日期：2026-10-09；Git 基线：da55f97（dev30）；实施范围：本轮开始前捕获的 dev31 SDK → 当前未提交 dev32。保留原 dev31 增量与本轮私有验证记录。
完整 H1/H2、理想 Harness、AgentScope 对齐和企业验收均未完成。

## 实际架构与范围

- SessionKey 固定可信 Scope、规范存储资源、namespace 和会话 ID；SessionRef 固定原 Runtime 协调 locator、绑定修订和定义摘要。
- AgentSession 为 borrowed 应用入口；关闭仅分离入口，执行托管与资源生命周期复用 H2a Runtime。Session 查询、历史分页和 attach 不创建模型调用、业务派发或新状态机。
- SessionAdmissionStore 为可替换的可选端口，v1 ExecutionStore 不变。默认 SQLiteSessionAdmission 与原 Run/command 使用相同连接、事务和 Coordinator；变更完成态、读取数据类型、后端身份及实际保存证据受公共边界验证。
- 首次 Turn 复用原接受规则，一次事务保存命令回执、Run、Turn、序号和占用。重复命令先找原回执，不重新解析当前默认。busy/mismatch 持久拒绝不创建额外 Run/Turn。
- native Agent／顺序 Workflow 及其既有绑定可用；每步骤须选择同库、同地址的 SQLite Session。拒绝独立数据库、远程资源、混合 namespace 和 Graph/Team/Dynamic 会话，原无状态组合继续可用。
- 审批、非终态、真实线程／handler、unknown 写效果和必需最终 Session 保存共同决定占用。观察只读取证据；下一次显式 admission/rebind 原子推进 owner。失败但未成功提交结果无需伪造最终消息。
- idle CAS rebind 保留历史声明与回执，原 Run 使用原发布。旧 revision 可查历史、重放原命令；新输入需当前 revision。资源／namespace 变化需要显式新会话。
- 规范实际地址防止别名注册及 raw submit 绕过，空闲会话仍保留路由。首个有效 Session 原子启用 schema2；旧 SDK 在派发前拒绝，普通无状态数据库继续 schema1。

schema2 是明确的单向兼容边界，无自动降级。自定义 admission 适配器仍需满足真实原子性与完成证据，返回 None 本身不能证明一个故意违约的适配器已经写入。

## 验证

TDD 覆盖严格 DTO、CAS／分页／Scope、激活与 Turn 接受回滚、实际地址别名、原绑定漂移、重复回执、审批重启、线程取消／unknown 核验、结果保存确认、borrowed 关闭、可替换 admission 和不支持组合的准入拒绝。

- Task1 114 passed；Task2 最终149 passed；另有审查修复10项，全部观察到 RED→GREEN。
- 修复后全量：**2280 passed／44 skipped，375.83s，-W error**。跳过项依赖配置服务，不算本轮真实 PostgreSQL/Qdrant/Temporal 或模型验收。
- 实际 dev32 wheel 在 /private/tmp 执行 H2a、Session、绑定与编排契约：**159 passed，6.05s**。
- 实际 dev31 → dev32 及 dev32 → dev31 wheel：各九类 schema1 原审批恢复（原生、1.1MiB Schema、顺序、绑定、并行图、团队、动态、DAG、嵌套），原 submit/control 回执、Manifest 保持，业务写入各一次。
- schema2：新 wheel 暂停审批后关闭；旧 wheel 在派发前拒绝且 Run 行不变；新 wheel 原 SessionRef/RunRef 重连，重复审批回执一致，占用释放，Turn 仍为1，业务数据库确实只有一次效果。
- 捕获的139个 dev31 SDK 模块与实际旧 wheel 一致；144个 dev32模块在源码／wheel／sdist／安装结果逐字节相等。基本依赖与 extras 保持；私有 workspace、数据库及凭据文件不进入包。
- 屏蔽 redis/psycopg/qdrant_client/temporalio 后实际包294个公开导出可用；二十种 starter 的生成文件摘要与旧 wheel 相同。Ruff、格式、Git 空白及本轮文档链接检查通过。

无付费模型调用、远端写入或公开发布；上述试验使用明确的离线 Provider 与真实本地业务数据库，不构成智能任务质量或对等框架比较。

## 一次独立审查与修复

fresh-context reviewer：三项 Important，无 Critical/Minor；保留其行为分级，一次 TDD 修复，无再次审查。

1. 自定义同步 admission 方法可能返回 contextmanager 等惰性对象；原来状态可被当成已保存。公共 ValidatedSessionAdmission 现在要求 mutation 为 None、confirmation 为 bool、read 为有限具体 JSON，并拒绝惰性／非法返回。`test_lazy_admission_results_refuse_before_durable_acceptance` 八种入口验证不进入对象、不丢原子性。
2. 已成功解析但变化的 manifest 原来抛异常而无拒绝回执，恢复组件后相同命令可能接受。现在持久化 binding mismatch，恢复后仍返回原拒绝；新 ID 才可尝试。`test_resolved_manifest_drift_rejects_durably_after_component_is_restored` 覆盖。
3. 同一执行数据库改 Runtime locator 后可能 open/attach 原 Session、生成错误 RunRef。协调摘要现含原 locator，open/attach 在可用句柄前验证，原 locator 仍可恢复和重放。`test_incompatible_locator_refuses_session_attach_and_open_without_losing_original` 覆盖。

合计10 failed RED → 10 passed GREEN in0.73s；修复后全量2280 passed／44 skipped。

## 全部实施取舍与成本

以下按 ledger 顺序记录全部 Ruling，包括 reviewer set-aside；无 deferred Minor。

1. 沿已批准路线 inline，不重复确认／自动提交／切换 worktree，保留 dev31 dirty。成本：用源快照而非新 commit 标定增量。
2. H2b1 限同库 SQLite native/sequence，schema2 显式启用使旧 SDK 不能绕过。成本：启用后不能降级；完整 H2b 与远程／复合会话待交付。
3. 可选端口增加 legacy_owner，原 authority 逻辑不直接查询 SQL。成本：自定义 admission 必须实现这个恢复查询。
4. busy 根据 Run／保存／效果证据及实际托管只读判定，owner 在下一次显式命令推进。成本：存储中的最新 owner 可继续指向已完成且可续接的 Turn。
5. 一次独立审查以捕获的 dev31→dev32 为范围，安装／兼容验证并行。成本：后续修复必须重新完成冻结 SDK 的全量及安装验证。
6. Reviewer set-aside 的跨独立／远程 admission 后置，同库实现只保护规范执行权威。成本：远程共享会话须有独立目录／协调协议。
7. Reviewer set-aside 的复合会话、FIFO、deadline、input、handoff 与 Temporal 后置并明确拒绝。成本：H2b 尚未完整。
8. Reviewer set-aside 的召回／AgentScope 质量不属于本轮运行协议，无收费调用。成本：没有新的质量或对齐结论。
9. Reviewer set-aside 的 package／installed／full 门槛由实施者独立执行并核对。成本：源码审查本身不足以证明交付。
10. Reviewer set-aside 的故意违约适配器不能从 None 验证真实写入；检测惰性／非法返回并要求适配验收。成本：宿主仍信任自定义适配器遵守事务契约。
11. 最终 task-done 核对本轮实际全量／安装／兼容日志与固定 SDK／重新构建包，不重复运行未变化的绿色全量。成本：任何后续 SDK 变化都会使摘要不匹配，必须重新验证。
12. 保留未提交源码及本轮私有证据，不进入自动分支整合／发布／清理。成本：最终提交与发布仍为独立步骤。

使用见[Session API](../../docs/session-api.md)，交付步骤见[计划](../../docs/superpowers/plans/2026-10-09-local-session-turns.md)，完整缺口见[剩余清单](../../docs/remaining-work.md)。H2b 的远程／复合会话与 Temporal Facade、H3 受管理默认链路继续沿原架构推进。
