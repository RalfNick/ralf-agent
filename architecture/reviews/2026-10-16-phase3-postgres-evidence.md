# 第三阶段 PostgreSQL 证据核对

日期：2026-10-16。只核对已有实现、测试入口和已终态工件，不启动服务、不修改运行时，不重开已后置的性能专项。当前状态仍以[唯一摘要](../../docs/implementation-status.md#当前交付摘要)为准。

## 哪些证据可以复用

| 链路 | 已有依据 | 不覆盖的范围 |
| --- | --- | --- |
| P3-1 Temporal 策略＋PG | dev114 的[原策略验收](2026-10-14-temporal-policy-profiles.md)按原范围冻结；现有 `test_temporal_policy_profiles_service.py` 通过声明式 postgres EffectJournal 验证期限与审批等行为 | 不自动证明后续 deployment Session 协议 |
| P3-2 普通 Session S1 | 原[普通 Session 验收](2026-10-15-temporal-deployment-sessions.md)已通过；普通双 Turn 和冷恢复测试使用默认 journal，债务测试使用专用 SQLite 证据适配器 | 不能把 S1 通过当作完整 Temporal＋PG 集成通过 |
| P3-2 Coding Session S2 | `coding_system` 已使用真实 `PostgresEffectJournal`、`codex-coding-postgres` 工具和 PG Runner／资源日志；原 360 秒失败和 600 秒诊断均留下真实 PG 表快照 | 当前版本全部所选拓扑、故障与原期限仍未验收；并非缺一个数据库适配器 |
| HTTP＋Temporal＋PG Inbox | `test_a2a_temporal.py` 已有双 HTTP 进程去重、提交后回执前进程死亡的测试设施，使用 PostgresInbox 与原 Temporal Run | Inbox 回执、效果日志及部署准入是不同职责；这些测试不能替代 P3-2 Session 或 P3-3 整体验收 |

## 本次实际核对

复核两个既有终态快照，而非运行新的场景：

| 原快照 | 原 pytest 结果 | 本次重新核对的原输入 | PG 关联与关闭证据 |
| --- | --- | --- | --- |
| `ec0ebe4` 原 scenario360 | 1 failed，386.753 秒含收尾；没有两 Turn 完整成功结果 | 34 项原输入当前 SHA 与原 before／after 清单相同 | 四张 PG 表各 4 行，同一组 Scope／effect_key；4 effect adopted、4 resource 的 stopped／fenced／transport_closed 为真且无 pending stop；2 root 退休、0 retained，原关闭／清理允许 |
| 同包独立 scenario600 诊断 | 1 passed，456.329 秒含收尾；诊断专用，不满足原 360 门槛 | 43 项原输入当前 SHA 与原 before／after 清单相同 | 同样四张表各 4 行且键集一致；原业务结果有两 Turn、4 次提交效果、两 seal 与 held0；原资源停止及关闭证据为正 |

四张表为 `ralf_temporal_effects`、`ralf_temporal_effect_evidence`、`ralf_temporal_runner_effects`、`ralf_temporal_coding_resources`。本次检查表快照的键关联与上述状态，不重新执行旧版 SDK 证明校验，不从采纳状态推导任意外部操作恰好一次。

两个摘要分别校验为 `3b3e26d540b545f648c7d371a85ed3da9eccc57fb2cc0bdf3c26d3665e991377`、`b63c60765d390880214577e3e065c5e9dfdd2307eb8c35a8ddd68f1223afc135`。含两个输入清单与摘要共 81 项原文件读取前后哈希不变。旧包结果不覆盖后续 Runtime release 重入修复；当前 425 产品文件与基础交付相同，未新增真实服务或模型证据。

本次审计目录：`/private/tmp/ralf-agent-pg-evidence-audit-20261016/`，含 `result.json`、原输入哈希与四份测试源码哈希；结果 SHA256 为 `6e413612bbe3ad97eec7bfcbda78e1a8f8f204127dad61e318f1a7bef4799e02`。不读取或输出服务凭据，不修改原工件。

## 剩余矩阵与执行入口

仓库原测试成功收集 **18 项**，仅 collection，不执行或计作通过：

- 正常 13 项：agent／sequence、顺序／并行图、三类 Team、flat／DAG／model 动态编排、checked-team、team-sequence、recursive，沿用原 SDK／JSON／TOML 选择。
- 故障 5 项：审批时冷交接＋退休回执丢失＋下一 Turn 取消；effect ACK、native-stop ACK、deployment-end ACK 三种原义务保留；CONTROL 硬杀后的原 Turn／未知调用保留。

原入口为 `test_temporal_session_deployment_coding_service.py`、`test_temporal_session_coding_recovery_service.py` 与 `test_temporal_session_coding_crash_service.py`。服务配置仍只使用原 `RALF_TEST_TEMPORAL_ADDRESS`、`RALF_TEST_POSTGRES_DSN` 等宿主配置；沿用原匹配 Worker、Scope／资源身份和清理保护，不添加新配置或服务。

当前首项仍是 `graph-sequential-sdk` 的原 360 秒门槛。它通过前，其他十二正常／五故障不解锁；失败及 600 秒诊断不拼接为当前完整矩阵。产品有变更后需要按原范围补验，不能用本次 collection 或哈希核对代替安装后真实服务验收。

## 处置与后续

本次关闭阶段门槛 0 项；没有证明数据库缺陷，也没有理由新增适配器或重建 PG 链路。继续后置 S2 性能专项，禁止无新依据复跑或微调。

原冻结计划同时要求 P3-2 关闭后进入 P3-3。已向用户明确提出开发顺序调整：允许先实现可独立的 P3-3 提交／查询／审批／取消／核验恢复及持久 HTTP 事件游标，保留原执行权威和全部阶段验收门槛。**尚待用户选择，不据此启动后续功能或将 P3-2 标为完成。** 若保持原顺序，则等待用户恢复性能专项；不继续用重复证据核对延长交付。
