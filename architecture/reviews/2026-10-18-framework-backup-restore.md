# P3-5：所选原数据备份恢复与版本回退验收

2026-10-18用户明确允许独立推进原P3-5，保留全部原失败及验收门槛。
本批复用既有SDK和数据库原生命令，新增可执行恢复测试与[操作说明](../../docs/framework-backup-restore.md)，
没有新增产品代码、备份平台、迁移器、后端或编排。仅本地提交，不推送。

## 原门槛与实际证明

| 原P3-5要求 | 实际证据 |
| --- | --- |
| 安装后备份并恢复SQLite／Temporal／PG原数据 | 默认oncall两库直接执行原文档backup API代码；原执行目录留档，在原空路径放回备份。真实Temporal先实际停服务，再完整复制离线持久目录；PG原生dump全测试库，恢复到新空stage1／stage2数据库和新Temporal目录，原库／目录不作目标 |
| 原版本Worker、业务身份与效果证据 | 原不可变442产品SDK／Worker，namespace UUID、Run epoch、Scope、队列、policy、发布和effect_key一致；状态／events／PG主效果／evidence／业务与owner／非默认ACL逐项相同 |
| 活动与unknown义务安全保留 | 待审批恢复后仍待原审批；真实业务提交后丢响应，第二次恢复仍waiting_reconciliation、Action outcome_unknown、原根held=1；业务只写一次，原核验与采纳后才seal／退休为0 |
| 升级失败可诊断并有原版本回退 | Local错误Provider版本使原Run drive以definition_mismatch拒绝，原库不变；恢复原工厂后原审批完成。远程错误发布在Worker构造及原Run drive均拒绝，原History／PG／业务状态不变，回到原发布与一根policy后继续原任务 |
| 原命令／回执与恢复 | 冷SDK重复submit／approve／reconcile返回原回执，原Action与effect_key未换；正常History及Registry实际重放，原Owner实际结束、根退休与关闭分别取证 |

验收范围是默认Local应用与所选普通公有Agent的上述部署数据恢复／发布回退，
不是全部编排／数据角色组合、自动Schema迁移／降级或生产Temporal集群灾备。
没有通过删除锁、改History、清quota或重新运行未知写来制造成功。

## 制品、输入与结果

产品保持`2de0dbd`的442文件（439 Python＋3 JSON）不变，复用原已安装wheel：
`dist/p3-temporal-retention-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `1f8efacb14afffb187e6fe71a64ab73e4b1f688267637e124d90e1210f026e06`。
本批没有重建wheel、升级协议、重跑模型或重新建设已冻结基础交付。
产品前后哈希一致，原默认及History兼容按其原精确制品证据复用。

| 检查 | 最终实际结果／原始证据 |
| --- | --- |
| Local源码 | **3 passed／零失败、错误、跳过**，`/private/tmp/p35-local-source-20261018.xml`，JUnit 12.818秒 |
| 相同测试输入、隔离已安装wheel | **3 passed／零失败、错误、跳过**，`/private/tmp/ralf-p35-local-backup-install-20261018/installed.xml`，JUnit 12.529秒；原文档备份代码及输入固定 |
| 同一wheel真实Temporal／PG | **1 passed／零失败、错误、跳过**，`/private/tmp/ralf-p35-backup-remote-v3-20261018/actual.xml`，JUnit 17.635秒；一个完整三阶段场景、两次从备份恢复 |
| 产品／完整测试副本 | 442产品一致；远程928 Python＋2 JSON共930测试输入与源码／运行副本相同，`products.json`／`inputs.json`／`verification.json`／`final-audit.json` |
| 原备份及身份 | case目录`approval-backup`／`unknown-backup`的完整Temporal数据、PG dump、`backup.json`及逐文件SHA；`original-identity.json`、两份原状态、两份restore记录及upgrade-refusal |
| 原结束与关闭 | stage0／1／2分别有真实deployment／tool calls排空、Worker停止、Engine／Journal／业务连接关闭记录；最终原Run／Registry History及restore-result、owned-service-cleanup |

默认未启用新自有服务的测试按配置跳过，原始skip记录保留，不算真实服务通过。
源码／安装Local与远程服务分别记录，不拼成同次完整suite。
全量Ruff、1,376文件格式与Git空白检查通过；没有无理由重复全量回归。

## 故障窗口与安全边界

Local实际应用由独立子进程运行。审批快照恢复到原路径后回读原Run／命令；
另一子进程持有Coordinator时文档备份拒绝，原库不变，失败空备份目录保留。
业务真实提交后`os._exit(77)`，备份保留原executing attempt和额度，恢复由原drive
归一化／查询原effect_key；没有在backup步骤把未知改成完成。恢复执行库时保留当前业务库，
备份后新增的另一条业务事实仍存在，原Action只保留一条派发意图、原业务效果没有重复。

远程使用普通持久Temporal dev server，固定原CLI SHA256
`33c298d41f6eefebf01a28a3511f444480e939e21d3518cb0c12a4abad467c4b`，无time-skipping。
本批新PG16容器／独占volume包含原效果schema和独立business schema；三阶段使用三个数据库。
每次先停止Worker并验证实际调用已排空、关闭连接，再停Temporal、备份整目录与全PG库。
原PG停止后才恢复下一阶段；旧服务不与恢复目标同时驱动业务。owner及非默认ACL完整恢复，
不使用no-owner／no-privileges绕开身份。目录0700、数据及清单0600，凭据单独私有文件不入提交。

该测试业务在备份／恢复窗口内受控停写，不能外推支持真实外部业务回滚。
外部系统备份后可能已接受新效果，应保持其当前事实，按原effect_key核验；
缺足够证据或查询／幂等能力时必须隔离并人工处理。相关资源／凭据／版本清单见操作说明。
本机持久服务证明不等于生产Temporal SQL／Cassandra／跨节点灾备过程已验收。

## 审查、失败与收口

一次独立集成review未发现新增产品P1/P2，要求保留PG owner／ACL及私有备份权限，已落实。
首轮远程1 failed／11.178秒：显式授予owner默认权被PG正确规范为NULL，夹具错误要求原始
非空ACL字节；改为仅撤销owner CREATE／TRUNCATE形成非默认ACL，保留原完整对照。
第二轮1 failed／15.837秒：两次恢复／原效果采纳与退休已完成，夹具History replay漏传
原namespace而报不确定性；补原namespace后最终通过，重放门槛没有删除。
两个失败目录`/private/tmp/ralf-p35-backup-remote[-v2]-20261018/`、各自停止的容器／volume
和原数据均保留不动。最终v3仅在全部原证明、三个Worker关闭后移除本批成功容器／volume，
备份与Temporal目录继续留档，Docker Desktop继续运行。原有其他资源未触碰。

Local最初两轮分别因猜错原attempt状态及把RunEvent当dict而失败，各2通过／1失败，
修正为原executing状态与公开事件属性后最终3项通过；无产品修复。所有原日志保留。
证据汇总脚本曾将pytest的current符号链接重复计为第二个case，改为只计实际目录后核对，
不影响原服务结果。最初4项既有Temporal输入夹具失败仍保留，不据本批算通过。

**P3-5按上述冻结最小范围收口。** 不自动解锁P3-A，S2原360秒失败与全部原门槛不变。
下一项是原P3-A整体候选的准入核对／完整回归、安装及约定兼容，阶段完成仍要求处理原依赖；
不把本批或三个已关闭子门槛当成第三阶段、M1或R01–R26全部完成。
