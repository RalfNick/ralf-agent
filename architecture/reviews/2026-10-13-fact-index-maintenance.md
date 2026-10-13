# 自动 Facts 索引维护：实现与验收记录

dev98 自动 Facts 索引维护的首期本地子集已验收。
基线是已本地提交的 dev97 `3ecc7e9`。本批新增原 Graph／Session 下的
有界索引刷新、来源快照分代、准确效果回执及 SQLite／Hash 默认组合。
不新增执行权威；原 `IndexedMemoryStore` 实现与身份保持不变。

## 实现边界

- GenerationIndexedMemoryStore 按固定 Scope／namespace 选择来源，使用
  来源快照分代的 build／active 键，复用原扫描、嵌入、写向量和检查点算法。
- FactIndexMaintenanceToolSource 使用原 ToolExecutionOwner、ToolPolicy、
  InvocationContext 和 Run／Action／Attempt；独立 CAS 日志保存原意图与准确回执。
- 刷新 Graph 节点只有 ready 通过输出 Schema，之后执行 reader Agent。
  同一物理 Facts 后端提供独立的写入与索引读取端口；原记忆阶段负责写入核验。
- SDK、JSON／TOML 与 memory-index 模板使用原 abuild；观察走原
  ProfiledEngine，异步应用恢复解析原 Profile 并重连原 Session／Run。

ready／partial 是实际索引状态的回执；source_changed 是明确的固定来源变化。
普通 CAS／预算错误仍保留 pending 意图，不伪造 partial。已保存的历史效果回执
可核验原 Action，但不能代替 reader 对当前 Facts 的来源校验。

## 验收证据

三个独立作者分别维护来源分代、受管理工具和默认组合；共享导出、装配、版本、
文档与验收由主任务集成。本批新增 115 项测试：生成索引 31、工具 25、
原进程恢复 6、工厂／模板 50、公共集成 3。单测不替代安装和业务质量证据。

| 验证范围 | 实际结果 |
| --- | --- |
| 完整冻结源码 | 8915 个不同用例，8298 passed／617 配置依赖跳过；零失败／错误 |
| 独立核心／SDK 安装 | 各 163 项适用契约及集成测试，零跳过；均从 site-packages 导入 |
| 已安装默认应用 | SDK／JSON／TOML × owned／borrowed，两套安装共 12 种配置；24 个主应用 Turn，加 8 个指南 Turn；30 个 CLI 子进程全部退出并回收 |
| 已安装原进程恢复 | 六类窗口 × 两套安装，12 个实际 Run／Session；36 个 Worker 及 2 个来源探针全部等待、回收 |
| dev97↔dev98 | 16 组原 Run／Turn 双向恢复；核心 72 个进程含先行基线，SDK 原默认／Session／Facts／K/S 4 组比较再用 8 个进程；全部回收 |
| 静态与产物 | Ruff／格式／Git 空白检查通过；349 个产品模块保持源码、wheel、sdist 与两套安装字节一致；原 fact_index.py 与旧版本安装未改写 |

完整源码按四个互不重复的测试分片运行。首次沙箱结果为 8192 passed／615 skipped，
另 108 项均因测试本地 HTTP／Redis socket 被禁止而失败。仅这些用例在允许自有
socket 的环境复验：106 passed、2 项正确要求真实 PostgreSQL／Qdrant 配置而跳过。
最终统计按 JUnit 用例身份合并，源码与测试全程冻结；重复验证不计新增用例。
首次重试控制器误要求零跳过，原断言失败记录保留；独立 XML 合并证明上述统计。
安装验证首次误选两项仅用于源码构建的 fixture，保留失败记录后纠正选择；
完整源码仍覆盖它们，实际安装 CLI／应用矩阵另行执行。未修改公共测试来规避失败。

提交前缓存区检查覆盖新增文件，清理了模板 README 的一处行末空白。最终产品重新
构建，两套安装测试与应用矩阵再次通过；生成应用仅 README 少一个行末空格，其余
九个文件字节不变。最终源码重新执行四个完整分片，8297 passed／617 skipped，
一项既有 CLI 子孙进程测试在 killpg 时出现 OS PermissionError；同一冻结源码单独
复验 1 passed，按用例身份合并为上表结果。进程只读检查没有存活的该测试子孙进程。
首次失败保留，没有修改 CLI 实现，也不将一次复验推断为已修复稳定业务缺陷；
R13 的完整停止／故障治理仍开放。源码及测试的最终字节全程固定。

六类窗口区分规范化嵌入返回、向量写入、页检查点、active 发布、独立效果回执
以及原 ToolAction 回执。前四类显式恢复保留旧 unknown hold，并单独预留新的
Attempt；后两类采纳准确完成回执，未新增索引效果。纯观察从不派发。
嵌入已返回但未持久化的窗口允许再次计算，不能宣称不发生第二次计算。

应用验证检查原 Session 绑定、原 Profile 恢复、重复命令不增长效果、显式 seed
幂等、当前 Fact／版本／值进入实际模型请求，以及结算额度和资源排空。
六类恢复窗口检查原 Run／Action／Attempt／效果键／Turn、命令回执、保留额度、
来源与向量／元数据证据；只读观察没有派发。故障恢复后实际处理器和额外任务为零，
三个原生数据连接关闭。这里的模型是明确披露的离线 fixture，quality 为 null。

## 独立审查与修复

一次全批独立 review 发现两项 P1 和两项 P2，均由同一审查者复核闭环：

- 关闭必须保留原始 Source、真实执行 Owner 及原关闭方法；外层／嵌套 Owner、
  SDK Source 指针和关闭方法替换均明确拒绝。await 前后检查，恢复原绑定后
  同循环重试，真实 handler 退出之前不关闭数据库。
- 固定端口改用对象身份比较，拒绝供应方 equality 隐藏的原生 Catalog 方法接收者
  替换。复现中的 equality 调用、原与外来元数据写入均为零；旧合法身份保持。
- generation-only 来源读取采纳边界覆盖 scan／validate／inspect 期间的原生写入，
  保存准确 source_changed；普通 CAS、预算和来源未变的非法返回仍保留 pending。
- 模板增加显式 Session ID；指南切换 owned／borrowed 使用不同 Session。
  同模式 SDK／JSON／TOML 继续原绑定，默认跨模式仍按原契约拒绝。

首轮关闭复核还复现 SDK 的 source.aclose 替换漏洞，已补三项 RED→GREEN 与
原方法固定，最终独立实际处理器探针及 9 项聚焦生命周期测试通过。
另一组聚焦复核为 26 passed。P3 描述文字漂移和布尔 journal schema_version
严格输入校验留在后续 R25；本批不宣称这些观察导致伪造效果。

私有原始证据保留于本任务临时目录 `ralf-agent-dev98-lefqes9k`：
`evidence/source-final-acceptance.json`、`evidence/installed-tests-final.json`、
`installed-index-app/combined-final-receipt.json`、`installed-recovery/actual-02/receipt.json`、
`compat/repaired-final-compatibility.json`、`evidence/sdk-compatibility-final.json`、
`reviewer/closure.md` 及最终产物字节／文档记录。它们为实际本地证据，未作为公共
可下载报告或服务认证发布；公开测试与指南可复现所述首期边界。

## 仍开放的能力

只验收首期 SQLite／Hash 的有界默认链路；真实语义质量、远程联合索引、
Temporal 维护、后台作业、增量删除物理清理、历史代保留／GC 和完整
R01–R26／H3／M1 继续开放。回归覆盖已有自有本地 Redis／HTTP fixture；
没有重新验收 PostgreSQL、Qdrant、Temporal 服务或真实模型／外部采用。
本批只本地提交，不推送远端，也不作公开包索引或 Release 发布声明。

设计及执行步骤见[契约](../../docs/superpowers/specs/2026-10-13-fact-index-maintenance-design.md)
和[计划](../../docs/superpowers/plans/2026-10-13-fact-index-maintenance.md)。
