# dev69 Temporal Profile 装配验收

基线 ddb6dbb/dev68；工作区候选 0.1.0.dev69；完整目标 R01–R26 仍 ACTIVE。
独立 review 的5项 Important 已完成一次统一修复；冻结源码、安装／真实服务与旧新兼容门槛已通过。仅交付本记录子集，不关闭完整 R04/H1/H3/H5/M1。

## 已验证子集

- 纯 Profile／Catalog、JSON／TOML、默认关闭开关、冲突拒绝、十类绑定、资源装配、取消／失败重试与真实线程保持；Task2 131项通过（2.52s），后续增量需最终冻结回归。
- 真实独立双 Worker：native／sequence／graph／team／plan／dag／nested，各两 Turn、重启、模型次数、原 History replay，7项通过（91.42s）。
- 真实 Redis／PostgreSQL 配置工厂及 Agent 私有 Session selector，原停止证据和 replay，2项通过（17.31s）。
- 真实 SDK 模型／摘要／同步工具／Session 写入关闭窗口，4项通过（7.57s）；原 Worker 保持可处理通知直至实际结束，之后释放资源。
- SDK hosting Task 致命取消入口保护复现1RED后73项相关GREEN（1.68s）；嵌套 SQLite backend 配置归一化1RED后21项GREEN（1.06s）。
- Team 选择缺 Scope、远程 Session 数据集未初始化均由实际服务 RED 证实后修复；没有修改未配置 Profile 的历史请求形状。

离线 Provider／合成工具不是线上智能质量证据。自有服务仅 localhost17269、Redis17369、
PG16.15 0700 Unix56369／UTF8隔离数据库；Temporal CLI1.9.1/server1.32.0。
独立 Worker 和所有服务最终需要关闭并实际等待。

## 最终验收

- Python3.12 冻结源码：**4021 passed／320 配置依赖 skipped，482.94s**。跳过不计为通过，未在本机运行完整Python3.11/3.13矩阵。
- 冻结源码真实 Temporal／Redis／PostgreSQL：**53 passed／428.47s**；独立安装 wheel 同组：**53 passed／448.26s**，无跳过。包含历史39项与本批14项。
- 新增 Profile／装配／Worker／生命周期便携契约：源码**81 passed／2.73s**，安装包**81 passed／3.58s**。安装扩展原契约**240 passed／5配置跳过，10.83s**，与81项重叠，不能相加。
- 最小依赖安装、缺SDK明确拒绝、图树两Turn及旧native保存/召回通过；安装便携测试**75 passed／6缺可选SDK skipped，2.56s**。此前SDK测试未声明可选依赖1RED已修正，SDK存在时81项仍全部通过。此变更只增加测试的可选依赖保护，发生在全量回归后；产品235模块冻结不变，按需重跑SDK存在／缺失环境契约。
- 源码／sdist／wheel／两个实际安装环境：**235个SDK模块哈希完全一致**，Metadata及导入版本均0.1.0.dev69；无源码路径泄漏。
- 真实 dev68→dev69→dev68：Local审批／原Session／类型化回执／默认Profile／21种starter，Temporal原审批与native save-v1 Session／Turn／History replay均通过，工具各只调用一次。新Profile能力未声称可在旧68执行。
- 安装离线配置模块和隔离namespace内真实图两Turn示例成功。最初复用源码示例的Scope／command_id、却换数据路径／队列导致原命令History无人处理；已只读确认该队列无业务Run，取消并等待该测试进程，在独立namespace重新验收。这个失败没有算通过；完整多版本队列路由继续待交付。
- Ruff、603文件格式、Git空白与本地文档链接检查通过。CI补默认无SDK安装路径、显式Redis、实际Profile契约；45分钟job上限覆盖扩大的测试组。GitHub CI未执行，本机验证不代替其跨版本矩阵。45分钟上限是新增取舍：误判会让未来失败job最多占用45分钟。
- 本批自有Temporal17269／Redis17369／PGUnix56369及所有测试Worker已停止并实际等待；`stopped`存在。服务数据／日志与修复记录保留在任务临时目录，不提交运行状态或凭据。
- 未调用真实模型、未推送、未公开发布。本地提交在全部文件与最终重建检查后进行。

## 独立 review 与统一修复

唯一独立只读 reviewer 检查 ddb6dbb 至完整工作区（含未跟踪文件），独立运行
75项契约测试通过／4.02s。没有 Critical 或 Minor；5项 Important 全部按实际影响接受。
没有启动第二位 reviewer。统一修复的6项复现全部先失败（1.58s），修复后26项通过／1.18s，
相关182项通过／4.80s，另64项配置／Local 回归通过／3.17s；最终4021项全量通过。

| 问题 | 修复与证据 |
| --- | --- |
| 构建取消关闭仍有桥接线程的资源（P1） | 工厂 Task 与显式线程独立持有；未排空返回可重试 cleanup，停止后才关闭资源 |
| 并发 cleanup 重试丢失资源（P1） | 明确拒绝同时关闭；保留同一实际资源关闭 Task 和原资源栈 |
| SDK 致命 Worker 错误被吞（P2） | 先建立 SDK 实际停止，保留原取消上下文；owned 清理完成后传出原致命异常 |
| indexed-memory 隐式 SQLite 路径缺失（P2） | 默认／嵌套 source 接收 Temporal data_path；不用假的 Local ExecutionStore |
| 无效配置／缺查询 Provider 先做 I/O（P2） | 内置纯校验与宿主／绑定 query provider 预检在任何工厂构建前执行 |

新增精确回归见 `tests/test_temporal_assembly_review.py`。脚本错误（测试路径名称、
macOS /var 与 /private/var 别名、沙箱 socket 绑定）不计为产品可靠性发现。

## 边界与决定

- 连续执行既有架构，不重复方案确认菜单；若理解有误，需根据用户修正调整实现。
- Temporal sourced-memory Stage 要求明确 Memory target，因为 Local 默认依赖执行 Store；迁移声明需补目标。
- 单 Assembly 固定客户端对象／队列；创建 Engine 后禁止资源移交，关闭同时关闭其 Engine 入口。
  多客户端／队列需独立 Assembly 或执行前移交。
- 数据端口仍以 Scope／原固定证据为边界；SQLite 保持线程亲和，线程安全同步数据需显式桥接。
- 关闭不是业务全部完成、全局停机或任意外部效果停止的证明。正常关闭先等待业务空闲；
  后续准入停止可能需要其他版本 Worker 恢复。阶段 wait_timeout 不是全操作总 deadline。
- 完整 R04/H1/H3/H5/M1、多版本路由、环境角色、EffectJournal 声明工厂、容量／保留、
  企业 IAM、真实质量与外部采用继续开放。

独立 review 的全部六项未评范围也已作明确决定：

1. 私下创建的未登记后台工作不纳入支持；明确桥接已托管。误用会让工作超出资源所有权，适配器需显式登记／等待。
2. 关闭仍按阶段超时，自定义资源 close 不设总时限。需要严格总 deadline 的应用需自行限制观察并保留重试责任。
3. 不自动取消所有业务或证明部署／外部效果停止；原 History 保留这些权威。未完成业务可能需要兼容 Worker 与外部核验。
4. detach 后由高级宿主接管执行和清理；误用会在受管理保证之外提前释放资源。
5. 多版本路由、环境角色、EffectJournal 工厂、跨权威租约与企业治理继续待交付；不能把本批配置视为完整企业支持。
6. 真实智能质量与完整 R01–R26 验收未证明；离线脚本不能支持 AgentScope 对齐或优于它的结论。

另外，工作区而非已提交范围的 review 依赖最后源码／包快照校验；Task3 在 executor 完成全部最终门槛后才交付。连续执行既有用户授权的计划、显式 Stage target、
固定客户端／队列这些既定取舍保留，误判分别需按用户修正、补迁移目标或拆分 Assembly。
