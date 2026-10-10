# dev65 Temporal 固定 Session 数据读取验收

基线：1b02e72 / dev64；日期：2026-10-11；只做本地提交，不推送。

当前批次实现固定资源和有界读依赖。host／每 Agent session inherit/ref/disabled、宿主 namespace、原始方法／实际客户端／物理来源、RecallQuery 固定，原 Run/node 私有地址读取沿 Context/managed Context 的原 History 采纳；Conversation／Session data／Facts／Knowledge 分开。已接受快照在数据变化和 Worker 重启后保留。

这不是完整外置 Session：无自动答案保存、跨 Turn 地址、持久 SessionKey 映射或高级根/成员保存门禁。显式 History Session 与选中来源的高级组合（含嵌套模型 Planner）接受前拒绝。完整 H1/H2/H3/M1、R01–R26 和实际质量目标保持开放。

## 审查闭环

独立只读审查发现三个 P2，均有 RED→GREEN：

- 线程桥接底层 read_page 缺失和方法替换：新增两个失败用例，再固定底层原对象／三个方法，禁止 legacy full-read fallback。
- 模型 Planner 未纳入高级范围：直接／嵌套两个失败用例，再递归检查实际受管理 Planner。
- 真实 PG schema 切换采纳其他数据：隔离 PostgreSQL 两 schema 红测，再固定 initialize 解析的实际表名，普通 SQL 与 named Facts cursor 都限定 schema，Session physical 包含路由。旧的 Facts physical 格式保持；原事实端口回归通过；旧 Facts／Knowledge 发布跨 schema 恢复身份仍是单独待验收门槛。

复核原三个问题均闭环，独立单元28/28通过；相关真实数据96项通过。无遗留 P1/P2，未以 mock 数据库替代服务证据。

## 分开记录的验证

- 最终源码及仓库外 wheel 各实际 Temporal4项：native／sequence × 普通／managed Context。native 在原 Context 已接受但模型命令尚未调度时通过 SDK 测试拦截器暂停 Worker并kill，sequence 在A模型完成／B读取前kill；后端数据改变后继续使用原A快照，原读／模型计数保持且 History replay 通过。
- 仓库外安装 wheel：140项固定读、Facts／Knowledge、managed Context 与默认会话恢复契约通过；最终旧绑定错误分类相关39项另行重验通过（包含与140重叠的用例，不计作179个独立案例）。
- 仓库外实际服务7项：上述 Temporal4、Redis1、PostgreSQL2（含 schema 路由）通过。
- fresh core-only：无 redis／psycopg／temporalio／tiktoken／pypdf，默认离线索引、原回执、scoped Session read 与原 Context/model 采纳通过。
- actual dev64→65→64→65 wheel：默认 Run/Manifest、原 SQLite Artifact、21 starter、typed Session 回执保持；原同库 Session 审批及重复控制回执只有一次测试工具效果。
- actual Temporal dev64→65→64：原默认审批恢复／重复回执／History replay 及一次工具调用通过；旧 Worker 对新 host Session read 发布在模型/工具 I/O前拒绝 definition_mismatch。

最终冻结回归：**3642 passed／204 skipped，620.69s，44944 exit0**。跳过项为未配置真实服务或其他可选配置，不视为通过；本批服务另行运行。Ruff、格式和 Git 空白检查通过。217个产品模块在源码／wheel／sdist／target／实际wheel及core安装中完全一致，最终能力文档和制品元数据同步核验。Temporal两项自有Service48054/74178、PG96105均正常exit0，停止标记确认，所有测试Worker在finally结束。


## 执行记录与限制

首轮服务测试业务完成但 replay 遇到 SDK late import，移动纯状态模块到初始导入后四项重跑通过。加强窗口的首版停在已经启动的 Model Activity，源码/安装各2失败2通过：框架正确将未知模型结果置为 failed/outcome_unknown。改为真正模型调度前的 Workflow fault injection 后各4通过，未放宽未知模型重试契约。先前两次相关测试命令引用了不存在的文件，均 exit4/no tests；纠正后96项才算证据。初次未冻结版本的全量主动中断 exit2，不算通过；首个冻结全量 exit1：3641 passed/204 skipped，仅旧拒绝列表仍把 session 归为unsupported；修正为未注册版本 definition_mismatch，相关契约重验后最终完整重跑。

未调用真实模型／未重跑 Qdrant／未做外部首用验收；本批不证明模型质量、跨权威租约或开源对等能力达标。内存实例只支持同生命周期；PG 必须显式 initialize，SQLite 为同宿主同线程资源。自定义源必须实现 native bounded read_page、精确 receipt v1 与 JSON physical identity。

临时根：/private/tmp/ralf-agent-dev65-ou97wkxz，指针 /private/tmp/ralf-agent-dev65-current。下一批继续原保存意图／CAS／精确 receipt／完成门禁，持久根和成员地址与完整会话协议，不缩小全部能力目标。
