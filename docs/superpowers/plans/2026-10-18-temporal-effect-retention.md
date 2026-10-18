# P3-4 PostgreSQL 重复效果副本清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在原Temporal完整封存和PG数据绑定之下，有界清理冗余效果副本，保留全部原执行与恢复事实。

**Architecture:** `TemporalEngine.compact_effect_evidence`是显式SDK维护入口，复用原Scope、namespace UUID、原epoch、原Runtime发布和完整封存树校验，只读原History，不新发业务命令／grant／seal／退休。原PostgresEffectJournal只删除与已采纳主回执字节完全相同且摘要正确的重复evidence；原主效果、不同来源／不同结果／冲突证据全部保留。

**Tech Stack:** 现有Temporal SDK、PostgresEffectJournal／_PostgresAdapter、psycopg；无新后端或调度器。

**Spec:** [冻结P3-4](../../phase3-support-matrix.md#固定剩余清单)及[已验收远程身份／审计](../../../architecture/reviews/2026-10-18-temporal-scope-audit.md)。用户已允许独立推进P3-4并保留全部门槛，持续自主执行，不再请求例行实施批准。

## Global Constraints

- 只本地提交，不推送；基础SDK／dev99／dev113冻结，S2原失败及P3-5／A原依赖保持。
- 不删主效果result、History、Registry／命令、业务库、资源启动／停止证明；不以测试schema删除冒充产品保留。
- 不新增后台清理、统一purger、身份平台、控制总线、后端或编排组合。
- 逻辑副本释放不是完整Run遗忘、隐私擦除或磁盘立即缩小；进度／删除字节不是业务效果回执。

## Review Focus

- 终态／ready单独为真、缺原seal、活动／unknown／实际未停止、父树未完成时，不允许SQL删除。
- namespace UUID、原epoch、Scope、Runtime发布或PG连接／表绑定在await间漂移时拒绝，删除事务回滚。
- 只删除已采纳主行对应的相同result／source／digest副本；保留冲突、不同来源、坏摘要以及其他Run／Scope。
- 原SDK的begin／observation／重复ACK／命令重提在清理后仍返回原结果、绝不重新派发。
- search_path变更、并发晚到相同ACK、响应丢失／重启和分批游标不能导致唯一证据丢失或无界扫描返回。

### Task 1: PG绑定与严格副本删除

**Files:** Modify `src/ralf_agent/temporal_journal.py`; create targeted real PostgreSQL tests.

**Interfaces:** `_PostgresAdapter._initialize(..., tables=("ralf_temporal_effects", "ralf_temporal_effect_evidence"))`固定原实际表schema；私有journal操作接受原Scope／run_id、1–1000条上限、可空`after_effect_key`和框架内同步复核，返回扫描／删除记录数、删除payload字节与后续位置。不是新增公共EffectJournal必需端口。review修复另增加私有原namespace异步复核，在当前Action提交前执行，不是公共可配置授权端口。

- [x] 先写并运行RED：副本删除、主行／冲突保留、同key其他Scope／Run隔离、未知／未采纳／坏摘要不删、search_path漂移、事务中断／晚到ACK。
- [x] 复用原target advisory transaction lock；锁内重读主行，校验state=adopted且`digest(json.loads(result)) == adopted_result_digest`，仅删scope／effect_key／result／source／`digest([source,result])`全等的副本。每个Action事务独立原子；主表零修改。
- [x] 原始真实PG复验通过，拒绝未初始化／未固定原数据集；不引入SQL模拟器代替数据库验收。

### Task 2: 原Temporal权威准入与SDK入口

**Files:** Create `src/ralf_agent/temporal_retention.py`; modify `src/ralf_agent/temporal.py`; create boundary and selected actual Temporal／PG tests.

**Interfaces:** `TemporalEngine.compact_effect_evidence(run_id, *, runtime, limit=100, after_effect_key=None) -> dict`复用原Worker Runtime及其PG journal。结果包含所选Run／原epoch／根封存摘要、扫描／删除量和下页位置，不产生新的业务回执权威。

- [x] 写RED：无权／活动／ready但无完整seal／子树未结束／组件漂移时无SQL删除；合法封存后原观察、重复业务控制与一次写入保持。
- [x] 沿原status授权、SDK Describe／`execution._proof`、只读`_ancestry`与`release._tree(seal=False)`核对原完整根树；必须使用既有seal且无新Update／Signal。不能仅看终态或Registry退休。
- [x] 固定Scoped Engine／Client／namespace、Runtime发布、原journal／连接／schema绑定；await后与SQL提交前复核，真实物理停止／效果采纳／额度退休保持各自证据。
- [x] 公有普通Agent／顺序所选既有场景实际验证：清理前后、重复／冷恢复、unknown与活动树保留；不新增拓扑压力专项，不以单场景外推全部组合。

### Task 3: 安装、兼容与P3-4收口核对

**Files:** Existing capability／usage／acceptance documents and isolated wheel artifacts.

- [x] 源码与隔离安装受影响检查、固定字节及原默认兼容；实际服务同包验收，一次独立review及必要修复。
- [x] 重跑受产品变化影响的原52项授权交集／2项远程身份审计；未受影响基础与历史证据按其精确版本复用。
- [x] 对照原P3-4全部门槛核对证据，缺项保持开放；P3-5／A不自动解锁。完成后本地提交，不推送。

Pre-flight: Task 2 consumes Task 1的原journal事务与表绑定；Task 3只采纳同一最终制品证据。旧初始化、用户自定义journal或未选择发布没有完整证据时明确拒绝，不把拒绝本身算作必需链路交付。

验收：[最终记录](../../../architecture/reviews/2026-10-18-temporal-effect-retention.md)。源码／安装各234 passed／22配置skipped，最终wheel实际服务24 passed／零跳过，442产品一致；原默认材料及两条默认History兼容。review唯一P2经有效RED→GREEN、实际SQL窗口回滚修复。每Action独立事务、整页部分提交明确记录；不声称跨系统原子提交。P3-4按原冻结最小范围收口，S2原失败、4项基线夹具失败、P3-5／A与长期未交付保持。
