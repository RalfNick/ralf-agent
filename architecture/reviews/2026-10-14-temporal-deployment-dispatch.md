# dev118：原 SDK 执行与部署准入绑定

本批于 2026-10-14 开始，2026-10-15 收口；从 dev117 本地提交 `6b54475` 继续[第三阶段批次 2](../../docs/phase3-support-matrix.md)。它接通内部 Worker 的业务执行门禁，不交付公共部署准入或安全释放。[协议](../specs/temporal-deployment-dispatch-contract.md)规定原 Registry、Run／Parent History 和 SDK 实际身份的关系。

## 实现与审查结果

所选 Worker 在首个业务 Activity、Parent selection、子 Run 启动前验证完整策略、原请求／Manifest、实际 namespace UUID、SDK 原始／当前 epoch 和 Registry 原绑定。所有业务 Activities 包括上下文、记忆、Session 保存、预算、采纳及恢复均经过同一门禁。子孙继承原根槽位，逐级匹配原 Parent 记录、实际 SDK parent 关系和固定 child epoch，不增加根额度。注册的自身准入 Activity 才可豁免业务包装；外部同名函数不可豁免。原机械 Activity owner 包装仍在最外层。

业务 request 保持原摘要：选定 Worker 使用 `{scope, _deployment_activity_request}` carrier 验证实际 History，再将原 inner request 交给原 Activity。默认路径没有 carrier 或新增 Manifest 字段。Parent 先记录原子调用意图再投影部署证据，投影失败回滚新记录。非法初始化证据由原 SDK-owned run 明确失败，避免构造器异常留下未等待的 SDK coroutine。

独立审查找到两项实际缺陷并修复：先投影再记录会使真实 graph 子调用失败；在冻结的阶段 request 后追加 SDK 字段会破坏 limits／completion／context／Session 摘要。实际 graph 初次复现为 1 failed／2 passed；恢复旧 header 注入会使四个受管理阶段回归失败。新增七项行为测试验证 Parent 意图／回滚、团队选择和上述四个真实阶段。最初真实 Agent Activity 还发现模型 payload 缺 Scope；carrier 统一携带 Scope 并保留原 payload。非法 SDK 初始化的严格警告失败通过原 run 的失败路径解决，没有抑制警告。

可选依赖模拟另发现两组测试没有声明 Temporal SDK 前提，最小复现为 2 failed；补充模块 fixture 后，无 SDK 模拟为 57 passed／89 skipped。这是测试依赖边界验证，不是另一套最小 wheel 安装。产品和实际 Service 用例未变，复用了原有效服务证据；更新后的受影响源码／安装再次验证。

默认物理停止夹具绕过 `__init__`，初次宽回归为 813 passed／1 failed；检查初始化失败字段改为兼容缺省读取后，最终受影响检查通过。服务夹具另有 Python tuple／JSON list 比较，以及第二轮检索词与种子文档不匹配，均修正夹具并保留早期报告，不登记为产品缺陷。服务测试与实现并行到达，没有把全部服务用例宣称为实现前 RED。

## 冻结验证范围

| 验证 | 最终结果 |
| --- | --- |
| 受影响源码 | 36 个模块，814 passed；零失败、错误、跳过；严格警告，27.58 秒 |
| 仓库外独立安装 | 同一 814 passed；零失败、错误、跳过；严格警告，27.79 秒 |
| 实际 Temporal 源码服务 | 17 passed；零失败、警告、跳过；65.83 秒 |
| 实际 Temporal 安装服务 | 同一 17 passed；零失败、警告、跳过；67.13 秒 |
| 产品字节固定 | 406 个产品文件在源码、wheel 和独立安装中一致；固定测试文件未变化 |
| wheel SHA256 | `6042a1d9569e7b70289340c5a73851ffb8c0827d6130543a07da0fdde7e530d4` |
| 默认发布 | 不可变 dev117 的完整默认 Profile／Manifest／orchestration 与当前 canonical JSON 相等 |
| 原默认业务 History | 原 dev117 原生 Agent 成功；新 Worker 重放并续接，原回执／结果相等，新增 Provider 调用为 0 |
| 实验性发布 | 原 dev117 Coding publication 由匹配旧安装接受；当前 composition／native source 门禁拒绝，仍需匹配原 Worker |

17 项实际服务覆盖九种定义（Agent、顺序、图顺序／并行、Team Sequential／Router／Supervisor、动态 DAG、嵌套 Parent），审批重启、Provider 未结束时取消、每 Agent RAG／受管理数据，以及五种没有合法原准入证据的启动拒绝。数据场景验证 namespaces 与原阶段协议，不证明语义检索质量。每套服务重放 25 份成功业务 History；五种拒绝启动核对 SDK 失败事件，不伪造其重放成绩。

源码与安装共 60 个实际业务执行关闭、34 个测试 Registry 终止，所选 Worker 全部退出。原默认兼容 Run／Registry 也按原测试身份终止。Registry 终止是测试清理，不是产品槽位释放。最终专用服务没有运行中的 Workflow，控制进程已退出，专用端口 56950／56959 已关闭；私有数据库保留不代表框架备份／恢复能力完成。

私有证据目录为 `/private/tmp/ralf-agent-dev118-root`：源码／安装 JUnit、无 SDK RED／GREEN、原 History、观察和清理、默认兼容、固定文件与 package provenance、早期失败及最终服务关闭记录。独立安装从自身 site-packages 导入产品；借用本地依赖库而非重新下载依赖。服务子进程只继承最小环境与专用地址，不继承模型密钥。本批没有调用模型、PG、远端 CI，也没有重跑完整阶段回归。Ruff、格式、空白检查和最终构建另行核验；CI 新增相应源码／安装入口不表示远端已执行。

## 必需后续能力

公共 `TemporalEngine`／Profile 对所选部署模式仍明确拒绝。内部 Worker 支持普通编排、非 Coding 每 Agent 数据／上下文与 Session 写入；选定 Coding 的物理关闭和 SDK Session-coordinator Turns 尚未接入，明确拒绝。它们保留为批次 2 必需项。

下一交付必须完成公共装配及不确定启动／重复提交的原回执恢复，然后整合 Coding 与 Session coordinator 原权威。原树终态、零金额预留、未知效果、辅助写入、实际 handler 和物理停止义务都闭合后，才可以实现幂等安全释放。失败继续占位并提供原恢复证据，不能用 TTL 或强制驱逐消除未知工作。

本批内部依赖完成不关闭批次 2、第三阶段或 R01–R26；后续还有托管观察／控制、身份 ACL、保留与框架恢复。公共与恢复／释放接入预计仍需多个独立批次，工作量高于本内部门禁。仅本地提交，不推送远端。
