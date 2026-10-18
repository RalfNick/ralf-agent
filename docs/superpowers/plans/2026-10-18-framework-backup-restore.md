# P3-5 所选框架备份恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans；独立Local与远程验收可以按用户授权并行。用步骤复验，不新增备份平台。

**Goal:** 安装后实际恢复所选SQLite／Temporal／PG的原数据、版本、身份和业务回执，验证升级失败可诊断并回退。

**Architecture:** 复用原SDK恢复、数据库原生backup／dump／restore及不可变Worker；停止准入、排空实际调用后生成有限备份集，在原服务停止后恢复到空数据目录。恢复不建立新执行权威、不改历史、不清未知或额度。默认能力已有接口足够时交付可执行runbook及安装后测试，不新增通用备份封装。

**Tech Stack:** SQLite backup API、既有PostgreSQL16原生工具、持久Temporal dev server、当前不可变442产品wheel；Python3.12／macOS ARM POSIX。

**Spec:** [冻结P3-5](../../phase3-support-matrix.md#固定剩余清单)、[恢复职责](../../../architecture/design.md#124-备份恢复)、[现有本地步骤](../../recovery-guide.md#默认本地项目的手工备份演练)。2026-10-18用户明确批准“允许独立推进P3-5，保留全部门槛”，仅调整顺序，S2原失败与P3-A不变；不重复请求例行批准。

## Global Constraints

- 基础SDK、dev99／dev113冻结，复用已验收442产品wheel；仅发现可复现交付阻塞才最小修复。
- 只本地提交，不push。无新后端／编排／Runner／身份平台／通用迁移器／跨宿主灾备。
- 原路径／namespace UUID／epoch／Scope／release／policy／业务effect_key必须保留；备份不提供第二个同时运行的部署。
- 副本导出、原进程退出和History重放不单独充当完整恢复；必须先隔离原权威，再从备份数据运行原业务。
- 未确认效果或实际停止时保留未知义务；不能删锁、改History、清quota或靠新Run绕过旧写。
- 只清理本批成功自有资源；失败资料、旧失败容器／卷／数据库保留。凭据不输出或提交。

## Review Focus

- 源仍活跃／实际handler未退出时不能通过拷文件形成可激活备份；runbook明确停止新请求及实际排空责任。
- 恢复点之前的审批／命令与unknown效果不能重置；相同effect_key的外部业务仍只写一次。
- 备份后已发生的外部效果不得被旧业务快照覆盖或凭丢失的本地回执重做。
- 错误版本／配置不得写原Run；升级拒绝后的原不可变工厂／Worker回退可实际恢复。
- pg_dump成功不等于跨系统一致性；完整Temporal数据、PG效果、应用／资源、凭据与原身份必须逐项有归属。

### Task 1: Local原两库备份恢复与回退

**Files:** `tests/test_local_backup_restore.py`；`docs/framework-backup-restore.md`。

**Interfaces:** 使用原`create_demo_engine`、`SQLiteStore`／Coordinator、SQLite backup API与原CLI。测试只读备份清单及原Action回执，不提供公共新端口。

- [x] 固定三个原窗口：等待审批、真实业务提交后进程退出／unknown、错误Provider版本。实际从backup API快照恢复到原空路径，旧目录保留，原库身份不变。
- [x] 恢复后重取原提交／审批，使用原effect_key核验一次业务效果；备份后的外部业务数据不回滚，不能把旧业务副本替换实际事实。
- [x] 错误配置尝试恢复明确失败、原库不变；回退原工厂成功，已接受命令与效果保持。若已有契约通过，不为测试数写无用产品代码。
- [x] 原步骤提取为可复制操作说明；安装后用同一测试输入验证，证据按原版本归属。

### Task 2: 实际Temporal／PG数据恢复与原Worker

**Files:** `tests/test_temporal_backup_restore_service.py`及必要的测试专用helper；相同runbook。

**Interfaces:** 已选公有普通Agent、原DeploymentAdmissionPolicy／PostgresEffectJournal／ToolExecutionOwner，真实持久dev server及新自有PG16容器。`RALF_TEST_BACKUP_OWNED_SERVICES=1`显式启用，缺配置默认跳过。

- [x] 暂停原准入并排空真实调用，在原审批及unknown窗口保存完整Temporal SQLite与PG原生dump、原namespace／epoch／Scope／发布／policy／业务身份清单。
- [x] 停止原服务并留档，从备份恢复空数据目录／数据库，新Client与匹配Worker接原Run；不能仅重启原未丢失数据库或只导出History。
- [x] 原审批、重复控制、unknown／held保留、查询／核验恢复、业务一次写入、最终完整seal／原History重放／根退休及owned关闭验证。失败资料保留。
- [x] 实际拒绝不匹配版本／发布，回退原不可变配置后恢复；明确dev-server验证不外推生产Temporal集群物理备份。

### Task 3: 同包证据及范围收口

**Files:** 状态／能力清单、阶段矩阵、恢复runbook、验收记录。

- [x] 复用原wheel校验全部442产品；源码与隔离安装运行受影响Local检查，相同安装包实际远程验收。无需无理由重复全suite／模型质量。
- [x] 一次集成review；重要发现有效RED→最小修复→相关复验。工具或数据目录失败保留，不偷偷更换验收条件。
- [x] 逐项核对原P3-5，未完成保持开放；S2原360秒和全部原门槛不变，P3-A不自动解锁。完成后仅本地提交。

Pre-flight：Task1与Task2使用同一原wheel但独立数据，不共享恢复状态；Task3只归并已验证原制品证据。SQLite演练不能替代远程恢复，Temporal dev server不能外推生产跨库原子备份。

验收：[最终有限记录](../../../architecture/reviews/2026-10-18-framework-backup-restore.md)。原442产品wheel不变，Local源码／隔离安装各3 passed零跳过，原同包真实Temporal／PG两次备份恢复1 passed零跳过（JUnit17.635秒）；928 Python＋2 JSON输入固定。一次独立review的owner／ACL与私有权限要求已落实；ACL默认规范化、重放漏namespace的两次夹具失败和停止的失败资源均保留。P3-5最小范围收口，S2原360秒、4项既有夹具失败和P3-A原依赖保持。无产品改动／新wheel／真实模型或全suite复跑。
