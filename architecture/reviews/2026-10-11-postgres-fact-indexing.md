# dev57 PostgreSQL 全库事实索引验收

基线cb9a824/dev56，用户授权持续开发与仅本地提交，不push。最终完整／安装／版本与实际数据库升级门槛已通过；提交SHA以Git为准。

## 实现与设计

新增PostgresMemory fact_snapshot/scan_facts，复用FactScanner、既有writer/advisory事务锁、IndexedMemoryStore和CAS Catalog。
显式initialize只新增ralf_memory_fact_scan_epochs，原Session/Facts接口和数据不重建。source每Scope/namespace固定epoch/generation。
named server cursor itersize=1，SQL分别截断key/value原始UTF8 bytes；预算拒绝先于JSON解码，避免普通libpq整页缓冲。
SDK borrowed、async配置 ledger owned；远程CI明确纳入Redis/PG全库索引测试。

## 真实服务与恢复证据

本机Docker daemon不可用，替代方案在任务临时目录从PostgreSQL官方16.15源码编译，不改系统安装或用户数据库。
官方来源：https://www.postgresql.org/ftp/source/v16.15/ 。25181309字节，SHA256 c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed。
仅任务0700 Unix socket，无TCP；psycopg[binary]3.3.6/Python3.12。
初始四个真实服务测试RED缺失native端口；实现后相关60 passed。
四个os._exit窗口覆盖accepted embedding/vector ACK丢失/page commit/active commit；batch2、query1、最终vector4；ACK丢失可upsert3，其他upsert2。
实际270条索引、连接／SQLite vector重开、Unicode／大整数／expired、字节续接、config Agent引用及owned关闭通过。
PG新旧存储／摄取／消息与PG/Redis进程回归52 passed／1 Qdrant组合依赖跳过。
独立只读review未发现P1/P2，实际验证取消释放named cursor／事务／advisory锁，阻塞writer继续，正常／预算失败后连接可复用；其自有数据和连接已清理。

## 最终门槛

首轮完整启用PG得到2 failed／3434 passed／68 skipped（618.18s）：test_data_binding_remote和test_session_binding_remote按旧2元组解包新3元组夹具；修复后Session Catalog还需匹配该夹具Scope。测试统一使用隔离Scope并正确清理，四个远程绑定定向回归通过；CI补入这两项，避免主job长期skip掩盖测试腐化。
这不是修正生产授权规则。随后一轮刚启动的旧夹具回归被Ctrl-C中断，session99904已exit130、对应日志lsof无持有进程；不将其视为成功。最终完整24107已exit0，full-suite-verified.log记录3436 passed／68 skipped（653.58s），子进程PID5885；未发现剩余失败。
安装包69＋最终远程绑定4共73项、198模块一致、独立core venv、原默认Run/Manifest/SQLite产物及21 starter兼容通过。
独立新PG数据库用实际56→57→56五步：old schema／新增epoch表／旧写者使新游标与索引失效／原事实版本保持，全部通过。
Ruff／format／Git whitespace与wheel/sdist构建通过。完整真实PG范围内所有可运行测试通过；68跳过为Temporal/Qdrant等实际服务条件，不能替代其验收。本批次未调用真实模型。
服务55632已发送任务stop、runner exit0与stopped=0确认正常关闭；临时目录保留官方PG源码/binary/日志供下一批复用，无运行中PG服务。
任务目录 /private/tmp/ralf-agent-dev57-xjhrw5oj。

## 未完成范围

Temporal Facts绑定、PG/Qdrant真实联合索引、自动增量／修复／GC／信念修订和真实语义质量仍待验收。默认Hash不证明语义质量。
同样遵循dev56 top256召回窗口，FactScanner才是全库枚举。本批次不关闭整个R15/R17/H3/M1。
