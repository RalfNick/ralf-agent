# P3-4：所选 Temporal／PostgreSQL 双身份与审计验收

本批仅补原P3-4所选普通Agent远程身份／审计证据，无产品改动、无新后端／平台／编排。
源码仍为`247e6d4`的440产品文件，使用已验收wheel：
`dist/p3-local-retention-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `068b90130f25dd9a7a3ada5ec7e55d2c5f3cae6831231a938f6eb3622c149111`。
完整P3-4仍缺PG完成数据的安全保留产品入口；S2原失败、P3-5／A及全部门槛保持。

## 原路径与实际场景

继续使用原`public_system`、`TemporalEngine`、原Worker／Registry／队列、
`PostgresEffectJournal`及`ToolExecutionOwner`。宿主将两个有效测试Bearer映射到
两个Scope，两个Facade共享同Client、队列、发布、Inbox；没有新权限平台或任务权威。
原Workflow查询／命令均先检查Scope，A2A控制仍先读原授权状态。

容量保持1：Bob先正常完成并退休，Alice随后进入真实审批或“业务已写入、响应丢失”窗口。
每场景验证：

1. 两位有效调用者各自提交／查询；相同messageId在各Scope映射到不同原任务。
2. Bob读取Alice原Task、事件、持原cursor读取，以及取消／审批／核验／恢复共7次均401。
   原Task status、全部事件和PG效果／evidence／业务写入前后逐字相同。
3. 两个独立HTTP宿主先后运行；重启后原message映射与原控制回执可重取，
   Alice沿原审批／人工核验与机械恢复完成，每个原effect的业务calls始终1。
4. 默认`ServiceAudit`使用固定测试key跨宿主关联：Scope refs不同，原Task／命令refs一致，
   secret、Bearer、原Scope／Task／Action／digest不入审计，failures和dropped均0。
5. 清理前检查根占用为0、完整原seal与原epoch History重放；随后才关闭宿主、Worker与
   自有测试Workflow／Registry，并删除成功场景schema。测试终止Workflow不是退休证明。

## 原始证据

证据目录：`/private/tmp/ralf-p34-remote-service-20261018/`。

| 范围 | 实际结果 |
| --- | --- |
| 隔离安装真实HTTP／Temporal／PG | **2 passed／零失败、错误、跳过，JUnit 28.494秒**；`service-tests.xml`，approval与unknown-write两个场景 |
| 既有资源授权交集安装回归 | `test_workspace_bindings.py`与`test_data_binding_resources.py`：**52 passed／零跳过**；`/private/tmp/p3-4-resource-intersections-20261018.xml`，JUnit 0.859秒 |
| 产品与输入固定 | 440产品在源码／wheel／安装一致；922个Python测试输入与真实运行副本前后哈希相同；`verification.json`、`test-inputs.json` |
| 场景与关闭 | 每个case的`scope-http-result.json`、`scope-host-closed-*.json`、原seal／History及`cleanup.json`；共4个HTTP宿主，各两个Facade和Inbox已关闭 |
| 基础服务 | 现有CLI哈希固定，真实普通Temporal dev server、独立持久SQLite，无time-skipping；既有PG16镜像新建自有容器 |
| 安全清理 | 两schema均经成功证明后删除，剩余自有schema为空；Temporal关闭，PG停止，仅成功本批容器／卷删除，旧失败容器／卷及数据库未改；`result.json`、`shutdown.json` |

独立审查未发现本有限验收的P1/P2，特别确认退休证明先于测试终止与删除。
受影响Ruff、格式和Git空白检查通过。没有重跑完整suite、真实模型或新质量评测。
上批4项既有Temporal输入夹具失败仍保留未通过；本批不覆盖这些输入场景。

## 范围与下一步

本批证明测试宿主认证适配下的普通Agent所选路径，不证明通用认证平台、所有编排／资源
组合、并发多租户调度、强制耐久合规审计或PG安全保留。默认内存sink仍可能在崩溃时丢记录。
原SDK／CLI／Local基础交付和dev99／dev113冻结范围不重开。

下一步仅补原P3-4的PG保留：沿原完整封存树和固定数据集，清理与已采纳主回执完全相同
的冗余副本。主效果result、冲突证据、命令幂等、History与物理资源证明不得删除；
不按TTL／终态／测试schema删除推断安全，不新增统一purger或后台平台。
仅本地提交，不推送远端。
