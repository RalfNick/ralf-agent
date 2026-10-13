# dev105：原 Local Coding 的图与父子编排

本批交付有限 Local 复杂组合：图 Agent／直接 Tool 节点、串行／有界并行图、
Team／Dynamic 与嵌套成员。每种组合复用原 Run／Action 或原子 Run，不建立新的
原生调度权威。dev99 四条参考链路继续冻结；本批不关闭完整 R01–R26、R13、
Coding G1–G8、第二阶段、Temporal Coding 或真实模型质量。

## 交付边界

- 仅从实际选择的 step／member 发布聚合 Coding 工具，冲突身份拒绝；工具绑定仍
  是宿主权限的交集。显式复杂发布使用 local-11／local-bindings-19 与 composition
  protocol 1。根级 Agent／顺序的 local-10／bindings-18、Descriptor 1／2／3 原字节
  保留；无 Coding 的原默认发布不增加标记。
- 图的并行 NodeEngine 是原 Run 的内部视图。Store／原动作节点索引、请求／release／
  definition digest、实际工具 Registry 与线程跟踪器固定到原父权威，不能借 frame 0
  另造请求。结果采纳只更新该原 Action，其他并行分支的意图和回执保持。
- 并行图根据有效授予工具对应的实际 Runner 对象安排单操作所有权；同资源节点先
  等候，不提前追加 attempt，不停止原拥有者。不同资源允许受原并发上限控制的重叠。
  不扩大 WorkflowScheduler 的 slots 契约。Team／Dynamic 仍由原策略安排并发，使用
  同一 Runner 的成员应串行安排或显式选择独立资源。
- 原后代树验证 parent／call／reservation／release 关系；父级的 escrow 不替代叶子
  Action 自身预留。父取消、兄弟失败及冷恢复沿已记录 child ID 停止原资源。
  实际停止、Run 终态和效果／预算结算独立：unknown 和 held escrow 不因 fence 清空。
- owned 关闭保持原 Coordinator／Store 与资源账本；隔离期间仅接收既有停止及退出
  回执。关闭失败／观察者取消后重试同一 handle，不开放新 submit／drive／阶段 grant。

## 并行开发与审查闭环

三个切片分别实现选定发布／绑定、原父子停止、节点投影；root 统一原权威接口、
版本、物理身份检查和集成。作者及 root 保存实际 RED→GREEN：旧拓扑拒绝、缺少
直接 Tool grant、冲突发布、错误节点身份、清理隔离、兄弟实际 worker 未退出、
原 parent escrow 被替换等。历史六个拒绝用例改为支持路径和零业务 I/O 断言；缺少
显式 Runner 的 bound Agent 及 Temporal 拒绝保持。

阻断问题已在同一审查上下文闭环：

1. 资源占用过滤读取 raw Agent tools，可能用已被 tool_set 排除的 Runner 阻塞普通
   节点。有效工具／composition 标记过滤通过作者 RED→GREEN；独立普通图探针在
   排除的 Runner busy=1 时立即成功，零原生调用。
2. 停止树错误限制第九个叶子 Run。原契约允许八个编排父级委托最终非编排叶子；
   两个有效失败复现后，仅允许合法叶子深度九，禁止继续形成第九编排父级、深度十
   或环。取消及 owned 关闭的八层祖先原身份验证通过，不改变原 max_depth 准入。
3. **P2：owned 并行关闭无法继续原停止恢复。** 关闭隔离先于 wait_for_threads；其
   quiescence 登记使用公共 _authorized，导致每次关闭都在停止前拒绝。root 用窄
   _original_run 退出／读取许可修复，公共业务与原生 grant 继续关闭。独立实际
   subprocess peer 的 Team→Team→parallel Graph 验证：第一次真实 stop 故障保留
   四项 ledger、两个日志和 Coordinator；消除原故障后，同循环重试关闭成功。

独立审查最初 111 passed；最后修复相关五模块 49 passed。实际 SQLite／子进程 peer
串行直接图及绑定并行图通过，原动作节点索引 1／2、原 Run release、一次 attempt、
每资源一次 Thread／Turn 和结果采纳均保持。四种真正不同 PID 的 producer／consumer
冷取消（Team、Dynamic、两种嵌套）保留原请求及未知 Turn 回执，消除原 stop 故障后
仅停止原容器，原模型调用数不增加，unknown 与 held escrow 保持。
这些是协议与生命周期证据，peer 和 Docker CLI 是确定性夹具，不是实际模型或真实
Docker 环境验收。

保留的非产品失败：首个私有探针在自行关闭 journal 后检查 release，得到正确物理
拒绝；首个冷探针在相同 PID 中保留原环境 owner lease，第二个对象正确地不能接管。
正式证据改用真正 producer 退出／consumer 新进程，未手动释放 lease 制造冷恢复。
P2 关闭失败为真实产品问题，其失败和独立复验分别登记，不与这两类夹具失败混同。

## 最终验证登记

私有阶段证据：`/private/tmp/ralf-agent-dev105-root`。
独立审查：`/private/tmp/ralf-agent-dev105-independent-review.md`；
实际协议探针：`/private/tmp/ralf-agent-dev105-review`。

| 检查 | 最终证据 |
| --- | --- |
| 完整冻结源码 | 8944 passed／634 配置依赖跳过，全部565模块；原生超时敏感255项先静止环境执行，其余包构建串行／隔离分片并行，全部退出0，Source／Test输入哈希不变 |
| 固定 wheel 安装 | checkout外900 passed／零跳过，116.56秒；只复制测试／工具／JSON，不复制产品Python；SDK／metadata均dev105 |
| 实际前版兼容 | 源码与固定安装各44个同数据库阶段通过；普通schema1和根绑定protocol18／schema14双向原发布字节保持；旧dev104在零Provider／native／Action采纳前拒绝8类新queued组合；新版恢复相同原Run |
| 文档默认与替换 | SDK／JSON／TOML配置身份一致；安装后绑定Agent、sequence、Graph、Team、Dynamic、nested成功；直接Tool图原审批目标2项、零attempt，可取消。离线Provider不证明Coding业务质量 |
| 制品一致性 | 367模块源码／wheel／安装一致；旧355模块保持、9旧模块改变、3新模块；原生Runner／环境／协议／日志与3份JSON保持。最终sdist核对全部产品、测试及本批文档 |
| 静态与审查 | Ruff、1008文件格式、Git空白通过；同一审查者闭环P2关闭阻断及有效工具过滤／合法最深叶子，独立原生协议及真进程冷恢复结果分别保留 |

固定 wheel SHA-256：`42356244e3e54e8bbe5e5dfc97442ba8d2728d09ccb803dbe4c08777f6fa1e75`。
本批完整回归无失败；开发RED、旧断言过渡失败、审查产品P2及两类私有夹具失败均保留，
未追改为通过。两轮私有兼容矩阵每个启动argv、退出和输出均保留；没有启动错误。


配置跳过不作为实际服务通过。原生 Runner／环境／固定协议／启动日志与三份 JSON
保持 dev104 字节；明确复用 dev103 的有限实际控制／停止／旧 start argv 失效证据。
本批不重新调用真实模型、不读取宿主认证、不启动真实 Docker／PG／Temporal 服务。

## 下一门槛

Local 的有限复杂准入／恢复已补齐，完整旧 Worker、跨宿主资源归属与公共组合部署
仍需逐项验收。下一批沿原 Temporal History 接入阶段／控制 grant 和共享 PG 启动
证据，保留唯一 Workflow 权威与明确拒绝边界；随后独立处理专用原生认证和重复
Coding 任务质量。不能用类型检查、控制读回或协议夹具替代这些证据。

使用说明：[复杂组合](../../docs/coding-composition.md)、
[配置与所有权](../../docs/coding-profiles.md)、
[完整门槛](../specs/delegated-coding-action-contract.md)。
