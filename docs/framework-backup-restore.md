# 所选部署的备份、恢复与版本回退

本说明落实P3-5的操作责任，使用原SDK及数据库原生命令。它不创建备份服务、第二套
Run状态机或通用迁移器。当前实际验收状态以[唯一摘要](implementation-status.md#当前交付摘要)
为准；备份文件、History导出和进程重启各自都不能单独证明恢复完成。

## 先列清原部署

备份集需要关联下列原事实。只保存版本字符串不足以定位相同代码，应保留原wheel及其
SHA256、应用源码／配置和所选Worker制品。凭据用安全渠道保管，清单只记录引用，不抄密钥。

| 内容 | 必须保留的身份／数据 | 原负责方 |
| --- | --- | --- |
| 执行与审批 | Local执行库／命令／额度；或完整Temporal持久数据、namespace名称及UUID、Run epoch、Task Queue、Registry、原发布与策略 | 原执行权威与数据库运维 |
| 效果与未知 | 原PG EffectJournal主行与evidence；原Action／attempt／effect_key、审批／核验回执及实际停止证明 | 原SDK／效果日志 |
| 业务事实 | 原下游资源及效果查询／幂等记录，恢复点之后是否仍有新效果 | 业务系统所有者 |
| 记忆与知识 | 实际选择的Session／Facts／Knowledge／SourceCatalog、索引版本／来源、Artifact／Workspace内容与物理身份 | 各数据后端所有者 |
| 执行环境 | 原Runner根目录／锁／义务／locator、原镜像与代码、停止回执及未结束资源的现状 | 原环境／Runner所有者 |
| 服务交接 | 实际部署使用的Inbox／Outbox／HTTP事件前缀及命令身份；认证映射与授权配置 | 宿主与原消息存储 |

未使用的组件不额外创建，已有业务也不迁入新库。如果这些内容分属不同系统，必须列清
每个恢复点及停写顺序；PG dump不是跨系统事务快照。清理副本的入口也不提供备份或恢复权限。

## 停写与取得备份

1. 停止接收新任务、审批、输入及业务控制，停止其他可触发工具／模型／记忆写入的宿主。
   断开HTTP连接或取消等待者不会停止业务。
2. 退出Worker／drive并独立等待实际handler、线程、环境／Runner调用停止；保留原结束证明。
   若关闭返回`CloseIncomplete`，不能将其写成关闭成功。无法排空的外部资源继续保持未知，
   原环境／义务目录保留，不能删除锁或通过清额度制造可恢复状态。
3. 活动Run可以仍等待审批或核验，原状态、期限、占位与未知额度全部进入备份。
   不为备份取消原业务或把所有Run改成终态。
4. 在仍被隔离、不会有后台业务写入的恢复点保存数据库与相关资源。备份目录0700，数据
   及清单0600。目标必须是新目录／新文件，失败或未完成的备份留档，禁止激活。
5. 检查每个数据库完整性、全部文件哈希、原制品与身份，记录完成清单，保留原源数据。
   校验成功也不代表可以同时启动两个副本；激活前必须确认原执行者及原服务已隔离。

默认离线oncall的Local两库可直接执行[既有Python步骤](recovery-guide.md#默认本地项目的手工备份演练)。
它持有原Coordinator并使用SQLite backup API，包含WAL中已提交内容。另一个Engine仍持有
Coordinator时拒绝；目标目录已创建但没有完整两库的失败集不可用于恢复。
原执行库同时保存该默认应用的Session／Facts，测试业务效果在独立`business.sqlite`。
换用外部记忆或知识组件后须按上表扩充实际备份清单，不能继续声称只有两个文件。

对于已选PostgreSQL，使用其原生一致性导出与实际恢复，保留原schema、角色／权限、资源身份。
例如在已配置、受保护的libpq service配置下（不在命令行写密码）：

```bash
PGSERVICE=ralf_original pg_dump --format=custom --file=private-backup/effects.dump
pg_restore --list private-backup/effects.dump
```

`--list`只检查归档可解析，不是恢复演练。相关业务库若可控且已停写，可在同一备份窗口
导出；真实外部业务仍以自身当前事实为准。角色／凭据、共享集群全局对象不包含在单库dump中，
需要原运维另行保管。不要以跳过角色／权限恢复隐藏身份差异。

Temporal必须备份完整服务持久数据及其原配置／namespace身份，不能只保存`fetch_history()`。
本机持久dev server的有限演练在实际服务进程退出后备份整个离线数据目录，统一保留可能的
SQLite WAL／SHM；不能从活动数据库混拷几份文件。生产Temporal SQL／Cassandra集群的
运维备份、跨节点恢复点和归档服务需由对应服务运维执行，本机演练不证明这些生产过程。

## 恢复到隔离目标

先确认原Worker、宿主与服务已停止／隔离，保留整个旧数据目录和失败材料；不要直接
覆盖原目录。Local恢复须回到原绝对路径，新空目录中放入备份，不能混入旧WAL／SHM、
硬链接或另一个仍持有的Coordinator锁；原数据留在独立归档目录，不启动第二个副本。

PG恢复使用新空数据库，原schema／backend_id与角色保持；显式检查目标后才执行：

```bash
# ralf_restored必须指向已确认的新空数据库，原部署已停止；不是原活动库。
pg_restore --exit-on-error --single-transaction --dbname="service=ralf_restored" private-backup/effects.dump
```

恢复失败时该目标保持隔离，原库与备份不变，先诊断再重新创建新的空目标；不向失败半成品
继续运行业务。不同网络地址不等于不同逻辑资源，恢复部署仍要沿原namespace UUID、epoch、
Scope、policy、Task Queue、原发布及效果键续接；不能重新注册同名新namespace冒充原历史。

恢复完整Temporal数据后先连接新Client，校验namespace UUID与原Run epoch；使用匹配不可变
Worker／SDK／工厂，并在开放业务之前检查原投影、命令回执、效果日志、外部业务及资源义务。
改变backend_id、源码、Provider、Tool版本、Scope或受选发布不是恢复手段。
若外部效果或实际停止证据仍未知，保留unknown与原占位，通过原查询／核验／机械恢复处理。
禁止直接删PG效果、改History、清Registry额度或另起Run绕过同一写效果。

**外部业务不能随旧快照回滚。** 如果备份后又发生效果，不用旧业务备份覆盖现有记录。
先使用原effect_key核对当前业务事实，再由原协议恢复。恢复点缺少足够派发／回执证据、
下游又不支持查询／幂等时，不能安全自动重试，保持隔离并人工处理。示例服务的effect_key
去重不保证任意真实接口恰好一次执行。

## 版本升级失败与回退

升级前保留可运行的原wheel、应用／配置、数据库备份和Worker映射。先在隔离数据副本上
核对选定发布与Schema，原Worker仍是未完成Run的恢复入口；不让新旧Worker在同一Task Queue
上竞争不兼容的实验History。

不兼容配置应得到`definition_mismatch`等明确诊断，且原业务数据／命令不被改写。
撤下错误候选后，使用原不可变工厂／Worker及原配置重新连接原数据，检查原回执再恢复。
失败回退不能删除原已接受命令、重置审批／期限／预算或恢复旧业务事实。Schema已经被升级
且不可向后读取时，不直接将旧Worker连到改写库；先隔离失败目标，在已验证的数据副本恢复
原版本并核对外部恢复点，保留失败库供诊断。当前不提供通用Schema自动降级器。

验收至少应看到：从真实备份恢复的新数据位置、原身份一致、待审批／unknown仍保留、
重复提交与控制返回原回执、业务未重复、原效果采纳、实际停止、完整seal、额度退休和正常关闭。
错误候选被拒绝后回到原版本可续跑，才能称此所选组合的回退已验证。

## 可重复验证与证据边界

仓库中的`tests/test_local_backup_restore.py`直接运行上述Local文档代码，使用独立应用进程。
`tests/test_temporal_backup_restore_service.py`显式启用时创建本批自有真实服务，原库留档，
将完整Temporal备份及PG dump恢复到空目标；默认配置缺失时跳过，不能算通过。
真实演练前应使用隔离、可丢弃的项目和数据库，不对已有失败容器／业务数据运行破坏性命令。

```bash
python -m pytest -q tests/test_local_backup_restore.py
RALF_TEST_BACKUP_OWNED_SERVICES=1 python -m pytest -q tests/test_temporal_backup_restore_service.py
```

第二条需要本机Docker Desktop、既有PG16镜像、psycopg／Temporal SDK及冻结的Temporal CLI。
测试专用helper的`CLI`／`CLI_SHA`固定本次所选宿主制品及路径，不自动下载新版本；其他环境
应先准备匹配制品并单独登记输入／服务证据，不把本机安装结果外推为跨平台验证。

成功测试资源先有原效果／停止／退休证据才清理；失败的新资源停止但保留。安装包、输入、
数据库备份、identity／History与关闭结果按精确版本登记。测试使用结构化Provider，无真实模型
调用，数据库恢复也不证明任务质量、生产HA、跨宿主灾备或全部Runner／数据组合恢复。

当前有限验收和原失败资料见[逐项记录](../architecture/reviews/2026-10-18-framework-backup-restore.md)。
