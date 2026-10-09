# Agent Facade、Session与关闭契约 — 目标v1

日期：2026-10-08；状态：H2实施前的行为规格，尚未实现；审查基线：dev24；dev25 H1a不改变本契约的未交付状态。
本文与[AgentHarness设计](../viewpoints/harness-runtime.md)、
[能力绑定](agent-capability-binding-contract.md)、[Run命令](run-command-contract.md)、
[Action恢复](action-recovery-contract.md)共同约束统一入口。
新命名与参数是目标接口，不能当作当前SDK API直接调用。

## 1. 对象和职责

| 对象 | 责任 | 权威与所有权 |
| --- | --- | --- |
| Agent | 应用入口，使用固定AgentHarness与Runtime发起/观察Run | 自建Runtime时owned；显式共享Runtime时borrowed |
| AgentHarness | 每Agent的循环策略、能力组合与受管理阶段 | 通过ExecutionAuthority执行，不自行存储Run状态 |
| Runtime | 组件装配、资源拥有/借用、任务托管和关闭 | 复用RuntimeBuilder/RuntimeInstance；不再引入一个调度状态机 |
| RunTaskSupervisor | 持有本地drive Task、接收异常、恢复启动已接受Run | 只管理进程任务；步骤选择/命令/预算仍在执行权威 |
| SessionAdmission | 串行Turn的身份、序号和占用约束 | 同一执行后端的耐久权威记录；不是Session记忆数据或Facade内存锁 |
| RunHandle/RunRef | 在线控制入口/可序列化重连接定位 | 活句柄依赖开放Runtime或显式Reader；Ref不带客户端或凭据 |

RuntimeKernel保持公共协议和纯规则定位，逐步提取。它不是第二个Runtime实例、
Supervisor或存储服务。现有Harness/NativeHarness继续保持纯prepare/propose兼容。

## 2. run、submit与wait

submit先完成持久接受，返回RunHandle/RunRef；随后Runtime托管执行。
接受与启动之间的崩溃窗口必须能依据Run意图恢复，不能依赖请求函数finally来启动。
run等价于submit加wait；等待结束不决定业务是否继续。

wait默认在完成、失败、取消或需要人工介入时返回；可以显式选择等待终态。
wait只读取已提交事实/事件，不能提交drive、取消或新的模型/工具动作。
执行先由submit/resume/control唤醒权威并交给宿主托管。查询旧Run也不隐式恢复执行。

等待结果包含RunRef、事实snapshot/版本、wait_reason和observed_at。
wait_reason为state_reached或observation_timeout。后者是观察结果，
不新增业务timed_out终态，不覆盖已有结果/错误。
调用方取消wait传播CancelledError；业务Run保持原状态，并释放本次观察资源。

可靠调用显式提供command_id。便利入口生成ID时，必须在发送前产生可追溯的
SubmissionRef并由Runtime记录；接受回执不明时，按原ID查询，不能生成新ID重提。
调用方取消或HTTP错误发生在接受期间，不证明Run不存在或已取消。
wait_timeout、等待目标和close策略不进入submit的请求身份；deadline_at、
输入/定义/显式绑定/Session选择等业务声明进入身份。原命令先查历史回执，
解析后的资源/默认组件只在首次接受时固定，不能因配置变化重新计算旧请求身份。

## 3. 等待、截止时间和取消的独立语义

| 事件 | 观察行为 | 业务行为 |
| --- | --- | --- |
| wait_timeout到期 | 返回原Run当前snapshot，wait_reason=observation_timeout | 不提交取消；Runtime/Workers继续托管 |
| caller取消await wait/run的等待阶段 | 取消本次观察，传播CancelledError | 已接受Run不取消，不删除回执/待审批 |
| HTTP/SSE断连、关闭事件迭代器 | 结束当前订阅与传输 | 不隐式提交业务取消；可凭游标/RunRef重连 |
| deadline_at到期 | 可观察到耐久deadline_exceeded原因 | 权威按固定deadline政策停止新派发并进入取消路径 |
| 显式cancel(command_id) | 返回持久取消回执 | 权威应用取消并传播到约定子Run/执行器 |
| 关闭Agent/Runtime | 按第7节的所有权与策略执行 | 关闭不自动等于cancel |

wait_timeout为本次观察时长；deadline_at为业务绝对UTC截止时间，
在接受时固定并纳入请求身份；close_timeout为资源收尾时限。三者不能互相代用。
参数必须为有限合法值。截止计时使用执行权威时间/记录，不能取模型文本中的时间。

deadline默认未设置；后端不支持持久业务计时则在提交前拒绝deadline_at。
到期的取消原因与用户取消分别记录，但仍遵循现有Run终态/竞争规则：
先提交成功则到期不能覆盖成功；先应用取消则晚到结果只补证据而不改成成功。
deadline或cancel不证明业务回滚、供应商停止或线程退出；未知效果仍核验。

cancel显式目标为Run，并有可信Scope、稳定command_id及约定的子Run范围。
普通事件订阅/超时处理中不得调用cancel。拒绝/批准/核验也必须走原命令契约。

## 4. Local与Temporal执行托管

Local：Runtime在自己的事件循环内持有RunTaskSupervisor，独立于请求/等待Task，
强引用真实drive任务并观察异常；wait不直接await可取消的engine.drive，
也不能使用wait_for(engine.drive)模拟等待超时。
Supervisor按执行权威接受记录唤醒drive；重启依据持久Run/Action恢复，
不是根据内存Task列表推断业务完成或重建Action。

Temporal：客户端Facade提交/查询/观察；服务器Workers/Workflow继续推进。
断连或客户端观察Task取消不删除服务器Workflow。Worker/服务的关闭是另外的宿主操作。
客户端Runtime只管理自己创建的传输/观察资源，不能关闭借用的Workers/SDK Client。

进程/事件循环真的退出时，Local不承诺持续推进；未完成Run保持耐久，
由具备原发布/Scope的后继Runtime恢复。观测超时不能释放Coordinator或执行线程归属。
不存在执行宿主时，诊断区分business_state与execution_host_status，
不能将“尚未恢复执行”伪装成业务成功/取消。

当前LocalEngine.drive的caller取消会提交取消、Temporal.drive等待超时返回snapshot；
这些legacy行为保持兼容。统一Facade是新增版本边界，H2必须实现托管和纯观察，
不能直接包一层现有drive就宣称等价。

## 5. Session身份、绑定与串行Turn

SessionKey由可信Scope(workspace, principal)、规范Session资源身份、
namespace及session_id组成。资源身份标识实际存储资源而非仅适配器名称：
同文本ID在不同数据库/namespace不是同一会话，同实际资源的别名不能取得两份占用。
资源身份独立于适配器实现版本/backend_id：升级客户端不能生成另一份会话占用。
由可信宿主注册并验证稳定资源标识及地址映射；不允许调用方任意声称同一资源，
无法安全确认别名关系的组合明确拒绝，不承诺仅凭DNS/连接字符串消除所有别名。

SessionRoute固定SessionKey及SessionCoordinationRef。一个Session只由指定执行后端
协调写Turn；另一后端不能独立写同一SessionKey来绕过占用。
跨后端切换必须显式迁移/分支，不能按同session_id静默当作同一连续会话。
Route映射在可信会话目录耐久登记，首次创建使用唯一键/CAS；其他Runtime必须验证
原CoordinationRef，不能各在自己的执行库为同一SessionKey重新登记一份占用。
此目录只路由，Turn/Run仍由指定权威推进；不具备安全登记/访问能力的后端组合拒绝。

Session保持binding_revision与固定会话/Agent绑定引用；当前Run始终使用原Release。
同一等待审批/输入/核验对象的续接路由回原Run，不能使用新默认版本开替代Run。
默认配置更新不会自动升级已打开Session；新Session/无既有Session约束的新Run可解析新默认。
空闲Session可显式rebind，携带expected_binding_revision并由权威CAS记录新修订，
仅作用于以后Turn。存储资源/namespace变化是新SessionKey，需要显式迁移或分支，
不是一次rebind。旧历史、来源和审批不被重写。
把不同Agent配置接入已有Session但未匹配/明确rebind时，返回session_binding_mismatch。

推荐初始策略为reject_if_busy，不是内存排队：
- 前一Turn运行、等待审批/输入/核验，或虽终态但未真正静默/必要会话写未确认，
  新用户输入返回SessionBusy及原RunRef，不创建第二个可执行Run。
- 明确approve/reject/send_input/reconcile/cancel针对原等待对象，不算新Turn；
  普通文字不能被猜测为同意审批。
- 用户要并行需显式新Session/分支。新Session也不能绕过全局未知业务写阻断。
- Session控制可以持久停放，关闭/重启Runtime不清掉占用关系。
- 只有前一Turn终态、实际执行已静默、必需保存已确认且相关未知写核验责任解除，
  权威才释放占用。到期租约/Facade对象消失不表示这些条件成立。
  必需保存指按该Turn结果契约要求的写入：已派发而回执未明需先核验；
  在会话写意图产生前已经失败的Run，不要求凭空补写成功消息才能释放。

TurnAdmission记录turn_id、单调turn_seq、command_id/input_digest、SessionKey、
binding_revision、RunRef与占用关系。seq由权威分配，同命令重放返回原Turn。
新Facade的忙碌拒绝有稳定拒绝回执；同命令重放仍拒绝，重新尝试用新command_id。
这是新入口协议，不改变旧raw submit异常/请求编码。

Local由其事务存储原子接受Turn/占用/Run意图。
Temporal由该后端的Session协调Workflow记录Admission/占用/Run-start意图，
Run Workflow仍独占业务Action/审批/预算/终态；协调Workflow不运行模型或业务工具。
跨Workflow开始不是共同事务：先固定Turn/RunID/启动意图，再幂等启动，
崩溃恢复查询原回执并补启动/关联，不能释放一个仍可能已启动的占用。
Session数据在远程存储时，必需append使用固定message_id/CAS/去重回执，
在权威确认保存前不能释放占用；不虚构跨库事务。

## 6. 后续持久排队能力

H2首期queue模式明确拒绝queue_not_supported，不把MQ投递或内存列表当Turn队列。
后续独立版本可提供queue，只有真实能力/恢复案例通过才启用：

- 接受时固定Turn、序号、输入、绑定修订/Release及原请求身份。
- 只在前序Turn达到释放条件后按FIFO开始，审批/核验续接优先作用于原Turn。
- 去重、顺序、占用、容量、取消尚未开始Turn、业务deadline与恢复均耐久。
- 排队不预执行模型/业务工具；执行预算/队列容量分别控制。
- Session rebind不追改已排队Turn；旧绑定不可用时明确保留/拒绝，不换最新版本。

共享SessionStore读写协议不等于具备此能力，后端通过细粒度能力描述声明。
内存任务索引、Broker消费锁、短TTL锁都不能成为Turn顺序唯一记录。

## 7. Facade关闭与资源所有权

| 入口来源 | Agent退出时 | 谁负责执行与共享资源 |
| --- | --- | --- |
| 独立Agent自建Runtime | 关闭自身订阅并调用owned Runtime的关闭策略 | owned Runtime托管运行及其创建资源 |
| runtime.create_agent/显式注入Runtime | 关闭这个Agent入口/订阅；不关闭借用Runtime或取消Run | 外层Runtime继续托管所有共享Engine/池 |
| 远程Service/Temporal客户端入口 | 关闭owned传输/观察，不关闭借用服务/Workers | 外部执行宿主保持其运行责任 |
| 显式Reader/attach的控制入口 | 关闭自己拥有的Reader/Client，不改变Run | 原ExecutionAuthority保留事实 |

远程客户端只拥有传输时，默认close是关闭观察/传输的detach，
已被服务器接受的Run继续由Workers托管；不要求等远端Run终态或停止借用Workers。
下述drain约束适用于实际拥有执行托管责任的Runtime。共享Agent的观察取消与owned
Agent上下文退出触发的宿主drain是两个独立操作，不能在wait内部隐式关闭宿主。

注入资源默认为borrowed；显式own才由对应Runtime逆序关闭。
多个Agent共享同一池/Engine，只有拥有它的Runtime可关闭一次；
借用Agent结束不能使其他Agent或其已接受Run失败。

默认owned Runtime close_policy=drain：
1. 阻止新接受，保持观察/取消/核验和关闭重试可用。
2. 托管的已接受Run推进到终态或稳定人工等待点；不无限等待人类批准/核验。
3. 等待在途实际handler/线程/子工作结束，接收并保存已知证据；
   需要核验的Run耐久保留，不能凭Task结束证明远端停止。
4. 等待审批/输入/核验且本地执行静默时，可以关闭宿主而保留原Run/Session占用，
   返回可重连接RunRef；这是parked，业务Run没有被取消。
5. Engine/store关闭成功后逆序关闭owned组件并释放归属。
   暂存回执/关闭失败不能释放Coordinator后允许旧对象再执行。
   若执行与存储已成功关闭而剩余客户端关闭失败，保持Engine不可执行并报告/重试
   剩余资源关闭；不为只读客户端失败重新取得执行租约。必要归属保留针对尚未静默
   的执行或尚未完成的存储收尾，不把所有关闭异常当成永久占用。

close_timeout推荐默认30秒，可显式配置；超时返回/抛出CloseIncomplete并提供关闭报告，
不转成成功关闭，也不改用cancel。Runtime保持quiescing/失败重试状态及必要资源/租约，
报告仍运行/待核验的RunRef，调用方重试close或明确选择取消/获支持的移交。
取消close的等待也不能丢掉收尾任务或放开真实handler归属。
上下文body已有异常时保留原异常，并附加关闭报告/异常说明；不得静默吞掉关闭失败。

可选close_policy=cancel：对Runtime明确管理的Run提交稳定取消命令，保留晚到证据，
等待真实退出后才释放资源；这不是close的隐含默认行为。
可选handoff只在后继宿主及原发布可验证、执行归属可安全交接的后端启用。
当前Local未认证此能力，必须拒绝；Temporal客户端存在外部Workers也须按声明的
责任确认后detach，不等于证明业务停止。不得先关资源再尝试移交在途工作。

无论drain/cancel/handoff，required Session保存和未知效果证据不能丢弃；
Remote stop、Run终态、预算未知占用和本地资源静默分别报告。

## 8. 关闭后的句柄

Agent关闭但借用Runtime仍开放：RunHandle可通过该Runtime继续status/wait/control，
前提是当前身份仍有权限；已关闭Agent本身不能接受新输入。
Runtime已关闭：关联活句柄不能偷偷重开Engine/Client/读取新默认，
操作返回runtime_closed；最后缓存snapshot只能作为带时间的历史观察展示。

RunRef保存authority_locator、run_id、release_digest及Session定位，不带秘密。
使用开放Runtime.attach(ref)或显式RunReader重新连接，重新验证Scope/资源访问；
查询和控制原Run遵循原Release与命令身份，缺失旧组件不回退最新实现。
持久审批/核验可在后继Runtime中继续；Session占用由原事实决定。

## 9. H2验收矩阵

| 场景 | 必须证明的结果 |
| --- | --- |
| 两后端wait超时/取消、HTTP断连、关闭订阅 | Run未取消、无额外工具派发；受托管执行继续；可重连 |
| 接受前后caller取消/回执丢失 | 原command_id定位唯一Run/Turn，不重提新身份 |
| 显式cancel与成功/deadline竞争 | 同公共终态规则；晚到回执保留，无重复业务写 |
| Local观察取消后关闭/事件循环退出 | Supervisor不被观察取消；真实线程未退出不能释放租约 |
| 同Session等待审批/输入/核验时新输入 | 稳定busy回执、无新可执行Run；明确续接仍作用于原等待 |
| 多进程/跨重启Session竞争与别名 | 一个占用、单调Turn、原绑定；不以锁TTL删除事实 |
| 相同文本SessionID跨Scope/资源/namespace | 正确分离；同实际资源别名不会形成双占用 |
| idle rebind与历史续接/显式分支 | CAS修订只影响以后Turn，旧审批/源快照保持 |
| 新Facade Session排队请求 | 首期明确拒绝；能力实现后验证耐久FIFO而非内存队列 |
| 独立/共享Agent上下文退出 | borrowed不关闭池/Engine；owned drain保留等待对象/RunRef |
| close超时、重复close、close被取消或存储失败 | CloseIncomplete可诊断/重试，必要租约保留，旧对象不重开执行 |
| 关闭后RunHandle/Reader/attach | live依赖明确、Ref可重连，查询不自动驱动/换Release |
| 实际旧wheel与History | legacy drive/提交/编码保持；新Facade版本契约独立验收 |

这些是设计验收要求，本轮没有执行上述新Facade行为测试或宣称H2已实现。
