# Dev94：安装后知识适配契约套件验收

本批基于 `d6e703c`，验收 R25 的首个 `knowledge-retriever` v1 子集。
完整 R01–R26、R25、H3、M1、真实模型／语义质量和独立采用仍开放。
见[使用指南](../../docs/adapter-contracts.md)、[设计](../../docs/superpowers/specs/2026-10-13-adapter-contract-suite-design.md)及[实施计划](../../docs/superpowers/plans/2026-10-13-adapter-contract-suite.md)。

## 交付边界

- 公共 `AdapterContractSuite`、不可变有限报告和固定 K01–K12；无 Fixture 不做 I/O，返回 `not_run`，缺必需 hook 标为 `not_verified`。
- 显式离线的独立 SQLite Source／结构化 Retriever；可编辑安装模板，SDK／JSON／TOML、同步／异步、owned／borrowed，以及 Agent／RAG／Plan／Team 原消费者。
- 原 `KnowledgeContext` 方法固定与 Query 原参数／类型守卫。三个公开方法源码及 Query 的构造／repr／asdict 保持；没有新 Run、Session、租约或 History 执行权威。
- 原操作真正结束后才清理；release／close 失败保留同一个调用、owner、workspace，在原事件循环重试，不重新跑用例或重复成功关闭。
- 实际独立进程验证原 `model_dispatched` 和 `model_response_recorded` 窗口；退出后删除来源，不重新 seed、检索或模型调用，原 Run／Action／attempt／command／Session Turn／预算保持。

Suite 验证固定行为和本地参考组合，不是任意适配器证书。确定性词法／Source-copying Provider 的 `semantic_quality` 和 `model_quality` 为 null。原生 Temporal 检查不推广为任意外部适配器的分布式验收。

## 审查与修复

同一个 fresh reviewer 独立复现并复核五项 Important；最终无遗留 Critical／Important。

| 发现 | 最终行为与证据 |
| --- | --- |
| 假挂起仍通过 TTL 检查 | 正常来源正向控制；观察自有调用启动及原 coroutine 真实挂起，变更后仍未结束 |
| 同路径物理数据库被替换 | 原 FD／device／inode 固定，读与 await 前后拒绝替换／删除重建；关闭原 FD，不修改替换库 |
| 当前更新版本未作正向校验 | 新版本 raw／Context 验证返回成功后，才删除并拒绝同一原块／引用 |
| release 失败提前关闭活跃资源 | 原任务／释放回调进入原 cleanup closure；同 loop 重试和重复观察取消均等待真实结束 |
| prepare／初始装配失败遗失 FD | 未返回 Session 的工厂自己回滚；audit SQL 失败仍关闭 FD；只观察的工厂不创建 Source，激活后立即交原 BuildContext |

最终 reviewer 聚焦八个新测试模块：177 passed／36.22s，实际 exit0；31 个候选文件摘要在审查前后相同。有效 RED／GREEN、原失败和修复前发现均保留。可信 Python 任意反射、未测操作系统及对抗文件系统竞争不在该证据范围。

## 实际验证

以下分组有重叠，不能相加作为独立测试总数。

| 门槛 | 结果 |
| --- | --- |
| 完整源码，warnings 作为错误 | 7516 passed／617 配置依赖 skipped，1156.85s，实际 exit0 |
| 独立核心 wheel | 213 passed／零跳过，21.53s；七类可选服务／媒体模块未安装 |
| 独立 SDK wheel | 133 passed／零跳过，4.05s |
| 安装后 CLI／完整可编辑应用 | 无配置、显式 offline、init／check／seed／四类消费者，九条命令均实际 exit0 |
| 原生产 Temporal 源码 | 12 passed／93.49s；24 Worker 实际等待退出、12 History 重放 |
| 原生产 Temporal 安装后 | 12 passed／114.66s；24 Worker 实际等待退出、12 History 重放 |
| 旧 dev93／新 dev94 | 六类原 Run 回执／记录／预算双向一致；默认及 selected Knowledge Context／Registration／Query／来源／Local／Temporal 发布身份一致 |
| 原默认组合 | 六调用方请求、四 Local、两 Temporal 和十六推荐 Profile 完全一致 |
| 包与冻结代码 | 333 产品模块、573 测试模块保持冻结；源码／wheel／sdist／两份安装产品模块一致 |
| 自有服务清理 | session54974、父 PID82370／子 PID82447 正常关闭，实际 exit0 并等待，原 PID 均不存在 |

首次真实 Temporal 门槛暴露旧测试 Worker 未转发 `dispatch_guard`／`on_end`：7 failed／148.61s，原测试进程有序中断 exit2、实际 Worker 已等待。只修复测试覆写签名与转发后完成上述真实门槛；原生产方法和失败证据保留。第一次服务启动错误的相对 Python 路径 exit127 也保留，没有算为运行成功。

最终静态、文档、包 provenance 和本地 Git 状态由根执行并记录。私有证据目录：
`/private/tmp/ralf-agent-dev94-_52fik84`；独立审查报告：`evidence/reviewer/final-review.md`。
本批不使用凭据、不调用真实模型、不推送远端、不发布 PyPI／GitHub Release。

## 保持开放

其他数据／模型／工具角色契约、真实服务拓扑矩阵、外部作者首用与升级兼容矩阵继续推进。Session 消息、Facts、Knowledge、Vector、Artifact 的数据权威与 Local／Temporal 执行权威保持分离；不把一个套件子集折算为整个框架完成。
