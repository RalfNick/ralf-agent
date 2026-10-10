# Temporal scoped Session reads implementation plan

> REQUIRED SUB-SKILL: superpowers:executing-plans. Existing nonmain workspace and continuous user authorization; only local commits, no push.

**Goal:** 实施完整 Temporal 外置 Session 数据契约的固定资源与原 History 有界读采纳依赖，接通每 Agent Session 选择和既有 Context/managed 阶段；后续原保存门禁/Parent完成仍按全目标推进，不以读能力关闭外置Session。

**Architecture:** 原 Context Activity读固定Session数据；原Run History接受与重放独立Session read evidence，Knowledge/Facts分类保持。Worker保存原client/method/physical pins，数据端口不是执行权威。外置写和SessionKey物理路由必须在后续端到端协议才开放，当前只允许stateless原Run私有地址的读绑定，显式SessionTurn/高级子树须拒绝未经实现的组合。

**Spec:** architecture/specs/temporal-session-data-contract.md；binding contract；existing Temporal context/facts patterns.

## Rulings / boundaries

- 本批接通 native/sequence stateless 私有Run读，不开放外置持久Session。原 History Session仍默认History，任何外置store绑定+SessionTurn组合接受前拒绝，防止缺写门禁/物理租约。
- 每 Agent session inherit/ref/disabled，并固定host范围与namespace；disabled不改变Context其他来源。静态seq成员可独立私有Run路径读，不伪称持久会话串行Turn路由。
- 高级Parent全Data子树先拒绝，直到member稳定跨Turn路径与根保存门禁实施；原9roles/高级组合不变。
- bounded read_page/maxitems/maxchars/scanlimit，cleanSnapshot与actualaddress/revision/pins; defaultmemory/SQLite及nativeRedis/PG sync/async可替换。

### Task 1: scoped fixed Session read registration

Files: new temporal_session_data.py/pure state helper; Runtime/bindings additions; tests.
- RED missing role/registration, unsafealiases/mixedlazy results/physicaldrift/namespace escape; GREEN fixedworker registration, exactmethods/policy/actualdatabase/client.
- Scope/namespace/actualsessionaddress固定；boundedsnapshot capturesoriginalrevision/messages andreceipt; nofullhistoryread fallback.

### Task 2: original Context/managed/History adoption

Files: activities/state/managed context integration; tests.
- Native/sequence perAgent inherit/ref/disabled usesprivateRun/nodeaddress; original acceptedmodelcontext replay, sourceclassification, missing/corruptsnapshot refusals.
- ExplicitSessionTurn/Parent withselectedexternal resource acceptsnone andperforms0data/model/tool I/O untilwrite/fulladdress contracts delivered.
- ActualTemporalWorker read/evidence/replay andsource/nativeadapters tests; existingdefaults/managedKnowledge/Facts remain.

### Task 3: release acceptance

Onefreshcontextread-only finalreview via skills; prove findings RED→GREEN. Full/installed/core/build/olddefault/historyreceiptcompat, docs actual capabilities/limits/nextfullwrite. Versiondev65 localcommit only. WholeR01–R26active.


## 本批实现验收

Tasks 1–3 的读取依赖、Context/managed原证据、审查/真实服务/安装/回归门槛已实现；完整外置保存与持久Session仍按原目标继续。最终证据见[dev65验收](../../../architecture/reviews/2026-10-11-temporal-session-data-reads.md)，不以本计划子集替代全部能力目标。
