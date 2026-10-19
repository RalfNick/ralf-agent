# dev122：项目审查修复与有限验收

日期：2026-10-19。基线为 `d4ab9e1`／dev121，本记录对应其后的 dev122 工作区候选，不把基线提交冒充修复后的源码快照。

## 范围与修复

按用户授权修复上轮完整审查确认的四项 P2、两项 P3，复用现有能力，不新增执行后端、编排、数据适配器或依赖。

| 问题 | 修复及行为证据 |
| --- | --- |
| Local 审批真值转换 | 原执行权威在接受命令前严格要求 bool。七类非法值通过直接 Engine／Facade 均被拒绝，不留冲突回执、不执行写入；同一 command_id 随后可接受合法决定。原 bool 拒绝／批准及重复回执保持 |
| 默认 wait 隐藏失败宿主 | 已提交终态仍可观察；非终态暂停／控制结果返回前检查原根和子级宿主故障。新测试注入短暂事务故障，恢复存储后 Agent／Team 默认等待仍报告故障，显式 resume 后原审批到期且写入为零 |
| scoped 语义召回漏结果 | 可选结构化 `recall_mode="window"` 保留完整 scan_limit 和多条排名结果；普通 cursor 路径保持。来源信息纳入字符预算，拒绝外来 Scope、模式漂移、超限或不符合窗口契约的分页结果 |
| Embedding 异步 callable | VectorRetriever 复用公共异步 callable 判断；内存／SQLite 索引均完成实际索引、查询和来源验证 |
| A2A 错误字节上限 | 不能容纳于响应预算的请求 ID 在 RPC 派发前拒绝；错误回退也限制字节数。ASCII／UTF-8 长 ID 无 Inbox／Run 接受，普通 ID 在结果超限错误中保持 |
| 独立 CI job 目录 | 两项 Local 安装门禁使用本 job 已复制的 artifact-contracts/tests。新增已有 P3-4 Scope／审计／PG 安全清理测试的源码与安装后门禁，复用原 Temporal／PG 环境 |

## 组合、恢复与兼容

- 新的 scoped 语义测试明确返回第二条相关事实和多条排名结果，来源撤回后验证拒绝；结构化窗口后端不要求继承 SemanticMemoryStore。
- 独立 SQLite Facts 和 Local 执行库完成审批暂停→关闭执行权威→重新打开→原 command 回读→批准→成功；原模型动作的记忆引用保持，恢复暂停时不重新 Embedding，业务写入一次。
- Temporal 仅执行离线原状态机的 Context 采纳／状态恢复测试：原 scoped 语义快照保留，Embedding 一次。这不等于实际 Service／History 重放或新的分布式资格。
- 非默认 window 模式加入 Facts 资源发布身份；旧游标资源身份保持。已接受的旧 scoped 语义任务应保留原匹配环境，不静默重绑或迁移。包版本升级不追溯撤销既有错误审批。
- `recall_mode` 是现有召回语义的可选声明，不引入新的模型阶段、后台索引或执行权威。添加 provenance 后过大的结果省略并计入 skipped，不补发查询、不生成窗口分页游标。

## 验证记录

- 审批 RED：14 failed／2 passed；宿主等待 RED：2 failed；语义绑定 RED：4 failed／1 passed；Embedding／长 ID RED：4 failed／1 passed。失败分别对应原始缺陷，随后修复。
- 最终受影响源码：34 模块 **592 passed，零失败／错误／跳过**，53.79 秒；JUnit：`/private/tmp/ralf-dev122-source.xml`。
- 本机假 Embedding HTTP 的组合测试：首次批次因沙箱禁止 socket bind 出现 1 failed／81 passed；允许仅本机 loopback 后，该模块 **2 passed**。保留环境失败，不外推真实模型质量。
- checkout 外独立 wheel 安装：12 个定向模块 **223 passed，零失败／错误／跳过**，18.50 秒；包含本批修复、旧数据分页、基础组件与连续教程。
- 原安装 starter 的正常审批／进程崩溃恢复分别通过，各业务写入一次。包元数据、运行时和 CLI 版本均为 `0.1.0.dev122`；pip check 通过，442 产品文件与源码一致。
- 安装测试与示例取自本批构建的源码包，运行目录不含 src/，清空 PYTHONPATH；依赖复用本机已安装库，无下载、模型或外部服务调用。最终源码包另核对测试、示例与产品输入一致。
- CI 全新临时布局核对 190 个 pytest 文件路径。修正后的两项 Local 安装门禁另用隔离 wheel 实际执行：部署准入 **197 passed**（34.81 秒）、持久期限 **187 passed**（39.58 秒），均零失败／错误／跳过；各自精确结果保存在制品 `verification/ci-local-*.xml`。这两次运行与上面的223项部分重叠，分别记录，不相加为独立覆盖数。
- 独立只读审查未发现 P1／P2／P3；其定向回归 29 passed、旧 cursor／legacy 回归 4 passed。Ruff、1,381 文件格式及 Git 空白检查通过。

## 制品与未验收范围

推荐制品位于 `dist/basic-sdk-dev122/`，与 dev121 及所有 dev120 历史目录分开。wheel SHA256：`6c077b6ba585594b3c2a0a4c700ee7470a98f896fbb49219e72ae95b24ce0387`。最终 sdist、源码输入清单、各项安装与 CI 记录的精确校验见 `delivery.json` 和 `SHA256SUMS`；文件校验只用于制品定位，不是函数指纹专项。

本批没有运行全量套件、真实模型、真实 Temporal／PostgreSQL 服务、函数指纹 qualification、S2 或旧 History 兼容专项；新增 CI 接线不作为真实服务通过证据。原 S2 失败、剩余矩阵和阶段未完成状态全部保留。备份辅助脚本的宿主路径限制继续登记，不扩展为新迁移平台。

仅本地工作区与本地制品，无提交、推送或公开发布。
