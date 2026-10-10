# dev56 全库事实索引验收

基线 ce32d6a/dev55。用户授权持续执行与本地提交，不推送。最终源码／安装／兼容与独立审查验证已结束；提交 SHA 以 Git 为准。

## 实现与设计对齐

新增 FactScanner/AsyncFactScanner、FactIndexMetadataStore/AsyncFactIndexMetadataStore；IndexedMemoryStore 组合既有 Embedding/VectorIndex 与独立 CAS Catalog。原始 Facts 为权威，索引只保存派生引用，不增加 Run 状态机。
默认 memory/SQLite 枚举、SQLite/Hash 配置，Redis native scan 与可选 HTTP/Qdrant；JSON/TOML独立角色支持自定义同步／异步工厂。SDK borrowed，工厂 ledger owned。
每页 scan→accepted embedding→幂等 vector→page commit；完整结束才active。严格来源快照、TTL和原值回读；已采纳模型响应沿原执行契约。

## 故障与独立审查

真实os._exit四个窗口：embedding响应保存、vector提交但ACK丢失、page checkpoint、active提交。恢复保持2次batch、最终4个vector，ACK丢失允许稳定ID upsert重复。
独立review两项P2已RED→GREEN：Qdrant物理identity忽略使集合切换误用旧ready；SQLite只截断value导致大key越预算。现在固定declared identity并限制key/value原始SQL读取。
其他复现覆盖async/lazy catalog返回、伪ready cursor／损坏phase、source实际SQL资源替换、active写入期间源变更、总记录超限、原FactsView分页来源。

## 验证记录

- 完整回归：3397 passed／98 skipped，596.44s；跳过项保持其实际环境依赖，不算服务验收。
- Ruff、format、Git whitespace 通过；wheel/sdist 构建成功。
- 安装 dev56 wheel 后74项 Scanner／Index／配置／旧装配契约通过；进程恢复测试子进程以实际安装包目录导入。
- 源码、wheel、sdist、installed 的197个Python模块字节一致。
- 独立Python3.12 core venv仅RALF与12个核心依赖，无redis/psycopg/temporalio/tiktoken/pypdf；离线配置索引、Agent事实引用、关闭重开和原Run回执通过。
- 实际dev55→dev56→dev55三次运行保持原默认budgeted/managed-summary/managed-data身份、Run/Manifest和SQLite产物引用；21 starter逐文件字节保持。旧55在创建Run数据库前拒绝新indexed-recall-async声明。

真实本地Redis相关37项通过；新增扫描覆盖大整数／Unicode／expired、游标与源变化、270条全库索引及client+SQLite向量重开。
Qdrant新组合使用HTTP fixture，不能代替真实服务。本批次未调用真实模型。
任务验收日志保留在 /private/tmp/ralf-agent-dev56-zujg6n38；完整回归22663已exit0结束，所有Redis服务由fixture停止。

## 未完成范围

查询为全库排序top256候选分页，不代表所有匹配已枚举。source写后须显式rebuild；未提供自动索引、损坏修复或旧namespace GC。
PostgreSQL native扫描、Temporal Facts绑定、自由合成／信念修订／遗忘、全局配额／导出迁移及真实Embedding/业务质量仍待验收。默认Hash不证明语义质量。
本批次不关闭整个R15/R17/H3/M1；下一批继续能力清单主链路。
