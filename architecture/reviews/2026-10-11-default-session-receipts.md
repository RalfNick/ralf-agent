# dev64 默认 Session 精确回执与外置责任审查

基线9a1b067/dev63；本批仅本地提交，不推送。日期2026-10-11。

## 已实现范围

默认 InMemoryMemory/SQLiteMemory 增加同步 SessionReceiptBackend v1，精确 Scope、实际地址、
原 message_id、当前 revision、原提交 revision 与完整消息。结果 finite JSON/detached；缺失明确 None。
ThreadedMemoryAdapter 暴露同一 async 契约，拒绝混合 async 后端、惰性结果和读取期间同名后端替换。
SQLite 添加原始字符串 ID 投影和独立源写失效标记，复用原消息投影按 seq 核验；旧原数据格式与同库 Local 路由保持。
非字符串旧 ID 不被 TEXT 亲和性转成合法字符串回执。旧写者清理原索引 dirty 标记也不能清掉新 ID 索引失效。

Local 独立默认数据使用既有远程 Session admission/save 权威，不新增状态机。
默认内存/SQLite 的七类 Graph/parallel/Team/Plan/DAG/nested/transform 根保存与 borrowed 关闭可运行；
原生 Agent 和 Team 的真实进程写前/提交后退出，经原审批与业务效果恢复，不重跑模型或已确认业务操作。

完整 Temporal 外置读/写/每 Agent Session 绑定尚未实现。本批补齐前置 SPI 并固定
[完整责任规格](../specs/temporal-session-data-contract.md)：原 Run/Parent 数据门禁、根/成员地址、原接受读快照、
写意图/准确回执/未知核验、namespace 物理资源身份、生命周期及旧协议门槛。
不关闭 R01/R02/R14、H1/H2/H3、R26/M1；不把共享数据后端当作跨权威执行租约。

## 测试与独立审查

初始默认回执25RED→91GREEN；线程桥接26GREEN后两个边界2RED→94GREEN。
新默认复合/同库路由15通过；独立进程四个窗口通过。
只读独立审查发现一个P2：旧整数ID1被TEXT索引认作字符串1。三个原类型/既有clean/旧写者clean用例
RED后增加独立ID投影与失效触发器，相关最终50通过，扩大默认/原会话回归122通过。
原无receipt后端的旧拒绝夹具现在显式设置 session_receipt_version=None；保留接受前拒绝/借用生命周期检查。
首轮全量在修复期间主动中断，717passed/5failed/2skipped，exit2，不计成功证据。
旧负向断言失败造成的未关闭租约警告随夹具修正消失；初始worker脚手架Scope/CommandReceipt序列化错误
已修正，不视为产品行为或成功证据。Markdown格式发现两篇既有示例与新示例不匹配，已统一格式。

安装包在源码目录外的146项通过；独立core-only新环境的typed SQLite/reopen、内存/threaded回执、
既有离线Facts索引/Agent原Run恢复及原样指南可运行，且可选SDK均不存在。
实际wheel63→64→63→64的默认Run/Manifest/Artifact/21starter与原ID类型数据保持；
原同库Session审批在新版完成一次效果，旧版重复审批/提交保持原回执，模型总计2次。
新独立默认SQLite Session在旧dev63的派发前明确拒绝，模型仍1次/业务0次。
安装首轮受/dev cache warning影响exit1，不计通过；最终禁用cacheprovider的5234已exit0（146/11.04s）。
最终全量22252已exit0：**3613 passed、198 skipped（563.98s）**。跳过项包括未配置的真实服务，不计验收通过。
Ruff、格式与Git空白检查通过；源/wheel/sdist/install共214个Python模块最终字节一致。
最终归档包含本页、默认回执指南、完整Temporal外置目标规格、能力队列/清单/架构与实施计划。

## 限制与下一步

内存扫描已持有ID，非跨重启耐久后端；SQLite dirty/旧索引首次核验需重建，clean精确核验不解析整个历史。
单条消息不提供无限大小保证；SQLite 留在创建线程。Resource/客户端按 owned/borrowed 原责任关闭。
本批没有创建真实 Temporal/PG 服务，也未调用模型。既有Redis/PG回执保持原实现，真实数据库新组合与
Temporal外置全链路分别验收。下一批实施完整原History Session数据阶段，随后继续清单其余能力。

任务目录 `/private/tmp/ralf-agent-dev64-hk711mpa` 保留日志/兼容脚本/core验证；full-verified.log与实际terminal exit0一致。
自有完整回归进程30716已结束；没有本批托管中的Temporal/PG服务，fixture子进程随测试正常结束。仅本地提交，未推送。
