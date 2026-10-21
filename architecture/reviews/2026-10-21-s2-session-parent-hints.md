# S2 Session 根通知路由与观察取消边界续修

2026-10-21，承接[dev14正式16/18](2026-10-21-s2-coordinator-queries.md)。本批继续处理递归第二Turn ready80、关闭不完整及并行Session.status的SDK CANCELLED。Activity90／ready80／Runner60／审批180／正常与冷交接整链600／其他故障300／first-close60／cleanup40保持，不扩功能或更换执行权威。

## 诊断与排除

旧dev14独立SDK Query诊断有8,585次Query，其中status 2,584次；两个root分别1,252次／204秒跨度及1,022次／171秒跨度，测试观察间隔50ms。累计await存在重叠，不能当CPU或串行耗时。

为区分观测负载，在独立私有测试副本仅将`_eventually`休眠改为250ms，并记录超时状态；产品、全部期限、谓词与场景断言保持。递归仍第二Turn80秒超时并关闭不完整，失败schema `deployment_coding_5be63dc87b994c399a26a7ef5f22375f`保留；并行通过，第二Turn Session空闲观察22.932秒，所有观察deadline均未到，未复现SDK CANCELLED。这两个诊断不作为正式验收，不把降频当作修复；源码测试观察频率保持原值。两次自有服务均已停止，零停止错误，旧资源未动。私有根：`/private/tmp/ralf-s2-observation-load-20261021`。

递归原History两Turn有64个Control Activity，55个observe中33个只读到running且无pending，另5个queued。该分布支持继续检查提示调度成本，不能据此删除独立来源校验。未实施新的进度合并、定时器或授权缓存。

## 确定的错误通知路由

Session4业务根的实际SDK父级是Session Coordinator，原`_notify_deployment_parent`仅检查父级存在且同namespace，就发送`deployment_child_wake`。Coordinator唯一Signal handler是`wake`，不接收该通用组合提示；真实Session通知由独立`_notify_deployment_session`维护。原递归失败的Coordinator History含35个`deployment_child_wake`和1个`wake`。

dev15在原实际epoch检查后，以新的History patch marker识别Session4、lineage空的根，精确核对Coordinator父namespace／ID／epoch，停止错误通用路由。只清理该路由的pending／error／retry／attempts，防止旧失败提示留下无效的一秒重试；`_session_deployment_pending`／sent等真实Session债务保持。后代lineage非空和旧marker False保留原行为。该修复不改变校验、预算、审批、效果或退休权威。

初始路由测试夹具漏选Coding协议，其失败不是有效RED，记录保留。补齐原selected配置并加入选中断言后，同一13项在原dev14隔离安装上7失败／6通过；修复源码相关5模块82通过／零跳过，包含13项路由、14项取消、原child wake／Session end／close order回归。父三字段漂移、两种根、后代、旧marker及遗留重试恢复均覆盖。独立静态复审未发现新增阻塞，不替代实际History和服务验证。

## 取消异常边界

确定性SDK-shaped复现：RPC接收到调用方`CancelledError`后映射为RPC CANCELLED，导致外层`asyncio.timeout`已到期却仍抛RPCError。原代码12项4失败／8通过；修复仅在原Task的取消计数相对RPC前增加、且原SDK状态为CANCELLED时恢复`CancelledError`。不调用uncancel、不增加重试或Task，不改变成功UUID或来源校验。无新增取消、旧遗留取消计数、其他RPC状态均保留原异常。最终14项通过，包含“新增取消但非CANCELLED”的负向覆盖。

这没有证明原正式并行失败同因：旧快照没有取消增量，新的并行诊断未复现；递归关闭Task快照cancelling=0也不满足本修复条件。不能将此异常边界修复称为ready80／关闭或原并行根因已解决。

## 验证与收口条件

更广源码回归84模块1,416通过／27配置跳过，127.30秒；另14项namespace取消测试通过，两组有重叠不相加为独立覆盖数。最终格式整理后固定唯一私有`0.1.0a2.dev15`，wheel SHA `0e59f2274a3d8f33bf8339b541dafefea4e1f343a9a665f2d8670db41b2cb457`；442产品／957测试输入文件，源码／wheel／隔离安装逐文件一致。私有根`/private/tmp/ralf-s2-coordinator-candidate15-20261021`。

原50ms观察输入的递归独立诊断1通过／零跳过，JUnit429.974秒；两轮写入／两根退休、Session空闲／Assembly关闭、Worker退出及正证明schema清理通过。Coordinator原History仅两次`wake`，错误`deployment_child_wake`为零；自有Temporal／PostgreSQL已停止并清理，零停止错误，旧资源未动。该诊断不计入正式18项，也不凭一次通过声明ready80或关闭问题全面解决。

原默认材料逐字节保持（去尾LF SHA仍`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`），两份旧默认History与两starter各一次业务写入通过。额外按原始字节回放dev14递归History：两旧业务根、四组合后代、两叶子共八份通过，原History解码确认没有新增patch ID。旧Coordinator单份失败；以原dev14安装独立对照也在相同History event 8报NondeterminismError，两次日志及原History保留。SDK Replayer固定使用`replay-None`队列，原History／accepted队列一致但与该回放队列不同，而Session初始化精确校验队列；本轮不修改该既有回放限制、不放宽地址校验，不将九份回放报全绿，也不声称新Worker可接续旧selected发布。

随后仍须同包原输入首项通过并停止自有服务，再运行剩余17项；全部原失败保留。S2／P3-2／第三阶段在门槛未满足前继续开放；完成后仅本地提交，单次跳过钩子，不推送或公开发布。

## dev15正式首项失败与最小续修

原输入正式首项1失败／零跳过，JUnit506.024秒，驱动停止，剩余17项与完整离线回归未启动。第二Turn第四个Tool在部署验证的namespace读取阶段发生SDK CANCELLED，History scheduled至failed约0.1695秒；新调用方取消计数增量分支未命中，不是Activity90或整链600超时。此前第二Turn已通过ready80，累计三写入；主操作最终在审批等待180秒失败，收尾first-close60／cleanup40失败并CloseIncomplete。原schema `deployment_coding_437537d643bd47f383e51875b4127b5b`、History、失败数据库及停止容器保留；自有Temporal／PG停止，零停止错误，旧资源未动。

原Tool尚未派发claim，停止State仍以完整proof／Scope／原请求／Runner登记独立stop invocation，并合法返回`original_invocation_id=None`。消费端错误地只接受非空str，后续stop反复被格式校验拒绝。dev16仅将该字段接受域改为精确None或原非空精确str；不改变State或物理停止规则，不据None释放容量／采纳效果。原State→Workflow→Signal／Query往返覆盖未claim／已claim、重复观察、错误字段／类型和stop无业务grant；旧严格消费者RED为1失败／9通过。

namespace只读恢复策略：固定原namespace／service／RPC及函数体绑定，每次I/O前后复核；无新增调用方取消的CANCELLED最多重读一次，尝试间sleep(0)允许取消；非CANCELLED一次、第二次失败保持第二个原异常，调用方取消优先传播。没有重试工具、控制命令或Update，不缓存UUID或校验结论、不重置期限、不增加Task。原读取RED（修正body测试夹具后）7失败／3通过，包含一次恢复、有界次数、漂移及尝试间取消；另补第二次成功后漂移拒绝。独立静态复核未见该只读边界的安全阻塞，仍不能称原SDK CANCELLED服务根因已解释，也不能凭None回执修复声明未claim停止已完整恢复。将重新固定唯一制品后按原门槛验收。

## dev16固定制品与最终回归

补充构造边界RED1失败后，将请求构造移出RPCError捕获范围，避免本地构造异常被误作传输重试。最终五模块64通过；源码136模块2,370通过／29配置跳过，174.76秒；隔离安装相同选择2,370通过／29配置跳过，181.98秒，356个实际加载产品模块均来自固定SITE。此前源码构造整理前2,369通过／29跳过结果独立保留，两组不相加。最终新增两文件25项在原不可变dev15安装12失败／13通过，确认旧产品仍复现缺陷；原无效夹具及所有RED日志保留。

唯一私有`0.1.0a2.dev16` wheel SHA `89c42fcfef5a68938ce3430f15a70f7831480ee62cd2ba5c70e239c1180cbd52`，442产品／959测试输入，源码／wheel／隔离安装逐文件一致。私有根`/private/tmp/ralf-s2-coordinator-candidate16-20261021`。默认材料保持原精确字节及SHA，两份旧默认History、八份旧业务根／后代History、两starter各一次写入通过；既有Coordinator回放限制按前节保留，不称可接续旧selected发布。

原输入正式首项1通过／零跳过，JUnit425.457秒；四次业务写入、两根退休／Session空闲、Assembly关闭／Worker退出／正证明schema清理通过。自有Temporal／PG已停止并清理、零停止错误，随后才启动同包剩余17项；全通过后运行完整离线回归。旧dev14正式16/18、dev15独立递归通过及正式首项失败各自保留，不跨包拼成绩。当前S2／P3-2／第三阶段保持开放；不推送或公开发布。

## 入口待递送取消与dev17续修

补充审查的单协程SDK-shaped探针确认新增P2：入口已有未递送的Task取消时，原dev15抛RPCError／一次读取，dev16因计数基线已含该取消而重读并成功／两次读取。这不是原实际SDK CANCELLED服务根因；却是本批读取恢复引入的取消回归，不能仅因正式并行已通过而放行。原固定包／测试输入不改，探针原件位于`/private/tmp/ralf-namespace-pending-cancel-review-20261021`（脚本及JSON）。

最小修复仅在入口公开`task.cancelling()>0`时、记录计数基线前`await asyncio.sleep(0)`。待递送取消直接抛CancelledError，不进入SDK；已处理旧取消仍保留正计数但可继续只读恢复。原RPC前绑定检查仍在该新增await之后，namespace／service／RPC／函数体漂移均拒绝，未使用Task私有字段、未调用uncancel、不增加Task或改变期限。新增7项RED6失败／1通过；修复后与原五模块合计71通过，待递送取消零RPC、旧取消可恢复、checkpoint四漂移零RPC均覆盖。

dev16原矩阵继续取证，但候选已被入口取消修复替代；完整离线回归启动前增加候选替代guard（原计划脚本另存、原SHA记录），返回125并明确`run=False/test_child_started=False`，不把未运行说成通过或测试失败。最终dev17须先完成自身回归／安装与兼容，再按原同包首项→剩余17项→完整离线回归验收，不能使用dev16成绩替代。S2／P3-2／第三阶段继续开放，全部原失败及未知义务保留。


## dev16正式矩阵结论与dev17最小续修

同包首项通过并停止自有服务后，剩余17项15通过／2失败／零跳过（JUnit2987.21秒），正式合计16/18。并行Session.status本轮通过，未再次出现SDK CANCELLED；不能据此宣称原传输取消根因已解释。递归正常与冷交接均为第二Turn ready80失败，随后Session／Assembly关闭未完整确认。递归schema `deployment_coding_f65440db8a85404b9103bb101d0d3105`、冷交接schema `deployment_coding_e9b9ba651f47413f80482d9cb6696fbb`及hard-kill原精确预期schema均保留，自有Temporal／PG已停止、零停止错误，停止容器与失败数据保留、旧资源未动。完整离线回归未解锁，未运行。

递归第二root逐层register为4.864／8.475／15.702秒，叶部署准入11.762秒；末次Model结束于root开始后78.391秒。ready80由submit返回后计时，不能将80减该root相对时间当作准确余量。History同时显示父级连续读取相同子修订；这构成检查重复CONTROL的依据，不把所有耗时归因于同一原因。原件位于`/private/tmp/ralf-s2-coordinator-candidate16-20261021/remaining-matrix`。

不采用指纹批次guard：微型库存探针显示约27.32% CPU下降，但不能证明跨批次helper globals无回调，且没有完整CONTROL收益证据。handle复用／describe与Query并发同样未采用，不跳过原工厂、地址及端口校验。

dev17仅在原diagnostics Query的精确内部请求下，同步返回当前diagnostics、完整physical proof和原先已ACK的父通知token；不调用Query内patched、不重算token，不增加公开能力。原祖先、端口、Session、namespace和前后release校验保持；消费端完整验证并实际采纳同次Query的proof，避免旧child覆盖。载体缺失沿用旧路径、显式空／坏载体拒绝，compact往返校验精确hex64。

父级仅当观察期间恰好新增一次hint、其token与原Query的已ACK token相等、且独立forced计数未变化时合并重复读取。cancel／deadline／patch／重复drive强制的新读取、多hint及旧History均保留原generation规则。审查发现的“T2后重放旧T”窗口已先用两项RED复现，再增加单次增量条件；没有新增token缓存、状态权威或期限。旧History由新patch marker保持原分支。新增测试同时覆盖原子proof采纳、坏载体、Query身份、不改History及force穿插；最终制品与服务结果待下方实际补录，当前仍不宣称S2完成。


## dev17唯一制品与复验

唯一私有wheel `0.1.0a2.dev17`，SHA256 `631f95a0a47d344d041a140cb1995c89981155ca37eeb416606b28e8c770f228`；442产品／961测试输入，源码、wheel、隔离安装产品逐字节一致。受影响138模块：源码2,413通过／29配置跳过（181.58秒），同包隔离安装2,413通过／29配置跳过（179.70秒），356个已加载产品模块均来自所选source／SITE。默认材料精确字节与既有SHA不变，2份默认History、8份旧业务History、2条starter各一次写入通过；既有Coordinator离线回放限制仍单列，不声称任意旧Worker续跑已验收。

独立递归诊断1通过／400.95秒：两轮写入、两根退休、Session空闲、Assembly关闭、Worker退出及正证明schema清理通过；自有Temporal／PG停止并清理，零停止错误，旧资源未动。5份原History实际出现`ralf-observed-parent-hint-v1` marker，确认新分支执行；这不是正式18项成绩，单次跨运行时差不作为稳定性能改进百分比。

随后同包原输入正式首项1通过／428.52秒，四次写入、两根退休、Session／Assembly关闭与Worker退出通过；本轮自有服务停止并清理、零停止错误后，才开始同包剩余17项。私有根`/private/tmp/ralf-s2-coordinator-candidate17-20261021`；全部期限保持，当前剩余矩阵进行中，完整离线回归待全部18项通过后解锁。旧dev14／15／16失败、独立诊断和当前正式结果各自保留。


## dev17正式矩阵结论与dev18候选

正式首项通过并停止本批自有服务后，同包剩余17项16通过／1失败，正式合计17/18；并行Session.status、冷交接及四故障通过。递归第二Turn仍ready80超时，Session／Assembly未完整关闭；schema `deployment_coding_57221670b231447ab466c82294ac6bab`、原History与数据库保留。自有Temporal／PG均已停止、零停止错误，失败容器保留、旧资源未动。完整离线回归未解锁，未运行；不以独立递归通过覆盖正式失败。

第二递归叶子在root相对42.131秒启动，准入42.681–52.742秒，和父级42.679–52.580秒首个queued观察并行。两次Context与Model后，末Model在76.769秒结束，审批经过三层新读取才在92.955秒到根。上述root相对时间不等于ready80起算点，不能据此计算精确超时量。无界延后首读等待hint方案已否决：初始化失败、准入重试和永久通知失败均可能没有hint，不能新增无限等待。

候选dev18保留原初次dirty读取及所有force，仅在selected4新patch、精确queued、仅初始提交命令、通知债务为空、业务／物理账本及恢复待办全空时省略初始queued提示。跳过不写notified、不制造ACK、不清dirty；首次真实动作后原通知恢复，物理账本变化仍会通知。无新增timer、期限、公开能力或执行权威。测试初版漏选Coding协议，42失败／2通过属无效夹具，原日志保留；修正并断言selected后，原不可变dev17有效RED1失败／43通过，新候选相关151项通过。源码、安装、恢复及正式服务结果另行补录，当前不宣称ready80已修复。


## dev18冻结与首项结果

唯一私有`0.1.0a2.dev18` wheel SHA256 `4305fc0b334f8ddf633929bf59d395511c8d3e50678ce6ced6ef5278ff5e98be`，442产品／962测试输入；源码、wheel、隔离安装产品字节一致。139模块源码2,457通过／29配置跳过（182.83秒），同包安装2,457通过／29配置跳过（185.72秒），356个实际产品模块均来自所选source／SITE。原源码沙箱轮9失败／1错误保留：8处Unix socket绑定拒绝、Redis Unix绑定拒绝，另一次延后收集的未关闭socket告警；允许本机测试自有socket后重跑同一输入，不改产品／测试或屏蔽警告。私有驱动旧目录引用在冻结和服务启动前已纠正，等待驱动停止记录保留，未覆盖任何旧包。

默认材料精确字节保持，2份默认History、8份原dev14业务History、两starter各一次写入通过。递归独立诊断1通过／420.801秒，两轮ready80／写入、两根退休／Session空闲、Assembly关闭、Worker退出及正证明清理通过；6份原History出现`ralf-empty-queued-parent-hint-v1`，确认新分支执行，不将单次跨运行波动当稳定提速比例。自有Temporal／PG停止并移除、零停止错误，旧资源未动。

同包原输入正式首项1通过／417.988秒，四次写入、两根退休与完整关闭通过；自有服务停止并移除、零停止错误后，才启动同包剩余17项。当前矩阵进行中，尚未解锁完整离线回归，不以独立诊断通过替代正式18项。私有根`/private/tmp/ralf-s2-coordinator-candidate18-20261021`，原失败、全部期限及未确认义务保持。


## dev18正式矩阵与并行尾部续查

同包剩余17项最终16通过／1失败／零跳过，JUnit3172.696秒，连同首项正式17/18。递归正常项通过／432.046秒：第二Turn ready80、两次写入、两根退休、Session／Assembly完整关闭通过；冷交接及四项故障通过。自有Temporal／PG停止、零停止错误；并行失败schema与硬崩溃精确预期保留按原规则保存，停止容器和原History／数据库保留，旧资源未动。完整离线回归未解锁，未运行。

唯一失败是并行图（490.539秒）：四次业务写入后，一个第二轮叶子Tool返回`tool_error/dispatched=True`，缺最终`final_thread_read`和`result_candidate`，主操作审批180秒失败，关闭未完整。该叶原History在13:20:48.171939采纳native completed、13:20:52.709249采纳真实stop、13:20:55.223478记录runner_outcome_unknown；EffectJournal保持dispatched／result=None，其余三项adopted。根后续两次成功observe到该叶waiting_reconciliation／unknown=1，因此证据不支持丢提示，不能用四次写入确认结果。

目前也不能仅凭Tool scheduled至completed约63.263秒判定Runner60：正常Timeout应转换成RalfError的runner_outcome_unknown，而外层tool_error表明逃出的异常为非RalfError，仍可能有后续错误覆盖。当前仅准备同一dev18产品的独立私有诊断，扩展现有有界异常位置钩子记录RAISE／PY_UNWIND的类型／位置／task取消计数／RPC状态，并把thread/read加入原native收发元数据白名单。完整SDK计时不启用，不记录异常消息、参数或结果，不改产品、任何期限或正式输入。原私有诊断脚本漏计thread/read的审查P2已修正；正式失败保持，诊断结果不能替代18项验收。


独立并行尾部诊断使用同一dev18产品、私有单文件观测overlay及原期限，1通过；四次thread/read均实际received／responded，未复现目标非Ralf异常，已停止并清理自有服务。该结果不覆盖正式失败、不定性Runner60或SDK CANCELLED根因。当前以逐字节相同的dev18产品／962测试输入，在独立新根`/private/tmp/ralf-s2-coordinator-candidate18-recheck-20261021`重验完整首项→17项；不修改product或测试函数，仅在测试外安装有界4,096条RAISE／PY_UNWIND类型／位置／task取消／RPC状态观察器，不含消息／参数／结果，也不改业务输入、故障注入、任何期限或断言。新首项通过并完整停止本批服务后才运行17项，不拼合先前成绩，原失败及数据库保持。

## 同包复验期间的宿主睡眠取证

上述复验首项1通过／422.089秒并停止、移除本批服务后运行17项。顺序场景出现ready80超时；只读电源日志确认2026-10-21本地22:26:34合盖睡眠，以及22:28:02–22:36:15等维护睡眠，与该场景窗口重合。原始失败、History和数据库保留，不因环境事件改为通过。睡眠会中断本机Temporal／Docker，当前证据尚不足以将该场景全部异常定性为产品或环境单一原因。

原dev18并行失败的21:16–21:24窗口没有匹配睡眠，不能将两次失败合并归因。当前同包复验的并行场景通过，仍不覆盖原正式失败。全部17项继续完成取证，未通过不解锁完整离线回归。

使用者已明确确认后续保持开盖接电并继续完整复验。下一轮独立根`/private/tmp/ralf-s2-coordinator-candidate18-awake-20261021`保持同一wheel、442产品、962测试和辅助输入字节，重新执行首项→停止服务→17项→全部通过后完整离线回归。仅在自有验证进程存活期间使用`caffeinate -i`防止空闲系统睡眠，不更改全局电源设置、不覆盖合盖睡眠。已有失败和验收期限不变，不混合跨轮成绩。

## 同包带观测复验结论与纯修订通知回声

上述dev18复验最终首项1通过、17项14通过／3失败，合计15/18。顺序第二Turn ready80失败与睡眠重合；递归第二Turn ready80失败和冷交接初始ready80失败发生在后续无匹配睡眠窗口，不能归因于合盖。顺序、递归的取消后Session／Assembly关闭和Worker退出均通过，正证明允许清理；冷交接仍CloseIncomplete，schema `deployment_coding_3d090ed656f84a7ba99d260435541a4e`及原数据库保留，hard-kill精确预期schema另行保留。自有Temporal／PG停止、零停止错误，失败容器保留，旧资源未动；完整离线回归未解锁。

当前17项全局RAISE／PY_UNWIND观察存在回调成本，但没有定量证据能把数十秒差异归于它。其失败保留，不与原无观察器17/18或独立并行诊断拼分。准备的dev18-awake目录尚未启动：在确认新产品问题后保存未运行理由，不再用旧包重复碰运气；后续修复制品将重新完成自身资格检查和首项→17项。

递归第二root的逐层register为6.251／8.937／16.158秒，叶准入60.530–73.655秒、Context73.945–81.363、Model81.740–87.264、第二Context87.784–92.052（均root相对秒，非ready80准确起算点）。只读审查确认：根相邻多次完整compact observe仅ACK、snapshot.state_revision、physical_proof.revision／proof_digest变化，预算、业务快照、workflow资源标志及物理状态不变；两套原采纳各增加revision，继续向祖先发提示，造成实质通知回声，不是force、失败fallback或丢提示。

候选dev19仅在完整原pin／proof／State.observe采纳之后识别这类变化。把本次完整观察的顶层snapshot.state_revision替换为旧值，按原观察公式重算digest，必须等于旧digest，保留完整子预算、native与input数据；再比较父全部State事实及自身物理账本，仅定点排除本边来源修订／摘要和父revision／事件日志，并要求新增日志只有该子Run的原两类采纳事件。非终态、无stop／seal／retirement且新patch允许时，实际增量记入既有通知counter。原公共revision、最新proof、全部事件、ACK／dirty／force和终止路径保持，不增加观察缓存或执行权威。

测试初版复用已封存树且漏scope，4失败为无效夹具；纠正并断言selected4后，有效RED1失败／3通过（`notification-red.log`）。首版整份State用JSON detached复制遇policy对象不可序列化，4失败后改为deepcopy；只读复核同时指出提取纯观察公式会改变旧Pure库存、新helper未登记，已在冻结前撤回提取。最终原`TemporalParentState.observe`逐字节不变，比较内联到原已登记Worker函数，其嵌套代码替换有登记回归保护；旧dev18 Manifest的17组／129个pure callable精确一致且校验通过，不外推任意旧Worker续跑。

新增20项通知测试通过，包括两种观察投影、完整子预算与预留变化、父恢复／新事实／物理owner、终止、旧marker、同修订矛盾、重复采纳不消耗ACK／dirty、业务数据中同名revision／digest及嵌套代码登记。此前相关131项通过；最终源码、隔离安装、旧History及正式矩阵另行补录，不以单测宣布S2通过。正式性能复验不启用全局异常观察器，所有原期限、原失败和未知义务保留。

## dev19冻结、资格检查及正式首项

唯一私有wheel `0.1.0a2.dev19`，SHA256 `58f12c5f0cf406aa2d8c2ef37ff22219a6836dd0885cd9de4650b46fd5acbb0e`，442产品／963测试输入，源码、wheel、隔离安装产品逐字节一致。受影响140模块：源码2,477通过／29配置跳过（193.319秒）、同包隔离安装2,477通过／29配置跳过（187.277秒）。原默认材料精确字节及SHA保持，两份默认History、八份原dev14业务History和两starter各一次业务写入通过；原Coordinator离线回放限制及“回放不等于任意旧Worker续跑”边界不变。

当前资格及服务驱动在自有进程存活期间使用`caffeinate -i`，不更改全局电源设置；正式测试未启用全局异常观察器，不改变任何原测试函数、故障注入、期限或断言。原同包首项1通过／408.608秒：四次业务写入、两根退休、Session／Assembly关闭和Worker退出均通过，自有Temporal／PG停止并移除、零停止错误、旧资源未动后，才开始剩余17项。私有根`/private/tmp/ralf-s2-coordinator-candidate19-20261021`；当前矩阵进行中，完整离线回归仍须全18项通过后解锁，全部旧失败各自保留。

## dev19正式服务矩阵结果（跨至2026-10-22）

同包剩余17项全部通过、零失败／错误／跳过；连同首项为18/18。并行图360.466秒、递归397.212秒、冷交接343.590秒；这是各自JUnit含收尾耗时，不把它们误称为ready80耗时或稳定提速百分比。递归两轮ready80、业务写入、根退休、Session空闲、Assembly／Worker关闭及正证明清理全部通过；4份原History实际包含`ralf-source-revision-notification-v1`，确认通知修复路径执行。冷交接完成原丢回执恢复、后续取消与关闭，四项ACK／硬崩溃故障也通过。

本批自有Temporal／PG均已停止、零停止错误、旧资源未动。剩余一份schema精确属于hard-kill原预期保留，停止容器和数据库保存；零意外保留，不把预期未知义务说成物理完成或删除。先前dev18并行未知结果、带观测三失败及更早各候选失败均不覆盖。服务驱动确认全部18项通过后才启动同包无筛选全量离线回归；当前全量与后续新旧History重放待完成，最终验收另行补录。

## 最终核对与交付边界（2026-10-22）

同一dev19无筛选隔离安装全量回归13,991通过／891按原条件跳过，零失败／错误，JUnit2,092.668秒。实际加载模块来源检查、442产品／963测试及辅助输入前后摘要校验均通过。当前工作区、冻结project、wheel及SITE的产品／测试字节一致；没有以源码、安装或不同包的通过项拼接正式18项成绩。

停止正式服务后，额外顺序重放原dev17八份、原dev18八份和当前正式dev19八份业务History，24/24通过，零真实服务／模型调用；加上资格阶段原dev14八份，共32份不同业务History通过。当前dev19的原marker重放也通过；默认两份History单列通过。旧Coordinator离线回放在原包也失败的既有队列身份限制继续保留，历史selected发布仍要求匹配不可变Worker，本批没有承诺任意旧Worker续跑。

全量Ruff、1,406个Python文件格式和Git空白检查通过；四份本批文档最终392个本地链接目标检查通过（冻结证据副本中的前次检查为390个）。最终只读复核发现支持矩阵仍将历史S1标为当前并称批次2未关闭，已更正当前状态并保留历史成绩与原失败。自有资格／服务／全量驱动的本地时间窗口为2026-10-21 23:45:42至2026-10-22 01:21:13，未匹配到系统Sleep／Wake事件。临时空闲睡眠保护随进程退出，全局电源配置未改；用户开盖接电授权及原受睡眠影响的失败分别保留。

本地受限证据副本在`dist/s2-session-parent-hints-20261021-dev19`，721个清单项，`SHA256SUMS`的SHA256为`93de13ff01fe376071e0f9ca56c189f4b50b68a98355ab39ae7bd62ef72e7057`。受保护数据9,917份仅登记摘要，原History／数据库留在各原私有根及停止容器；连接私密文件与原始数据库不复制，已登记测试密码从副本中排除。所有早期失败与独立诊断仍按原候选保留，不将原件或安全副本说成公开制品。

**P3-2/S2所选技术门槛已通过。** 并行Session.status、递归第二Turn ready80与完整关闭、冷交接和全部五故障在同一包通过；预算、原动作身份、未知效果、真实停止及唯一执行权威保持。P3-1／3／4／5及原P3-A未受影响的验收仍按原制品出处复用，本批补齐最后S2阻塞与当前完整回归、安装、约定兼容及文档；依冻结规则8，以本轮本地提交作为第三阶段冻结交付点，不继续扩充长期清单。

原dev18并行叶子的非Ralf未知异常本轮未再现，异常来源仍未确定；本轮通过不能覆盖该失败或证明一般传输稳定性。上述门槛验证的是可信单宿主、所选Python3.12／macOS ARM64、Temporal／PG与有限原生协议端的行为；未追加真实Codex模型、通用模型质量、所有平台／历史发布或生产HA验收。R01–R26长期目标、外部采用和公开发行边界保持。本轮只进行一次跳过钩子的本地提交，持久hook配置不改，不推送或公开发布。
