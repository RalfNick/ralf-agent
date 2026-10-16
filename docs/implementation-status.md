# Implementation status — 0.1.0.dev120

2026-10-16 P3-2/S2 仍未完成，最新原图原360秒真实验收为 `31b846a` 的1 failed／390.282秒；原四Tool成功、effect adopted、物理停止及资源安全清理不替代两Turn成功。本批已完成完整proof无损传输预算：载荷减少68.4%–71.6%，但完整CPU平均增加9.013%，按原门槛否决，不加Query协议、不复跑服务。产品只补CONTROL未知失败的安全诊断，保持原回执、重试和取消：新增18项、20个相关模块399 passed，独立安装7模块157 passed，默认完整canonical及原／continued保存History离线兼容通过，425产品／862测试无漂移；独立审查无P1／P2，Ruff／格式／空白检查通过。本批没有新增真实服务或模型验收，旧Coding History仍用匹配不可变Worker。其余十二正常／五故障不解锁，P3-3／4／5／A保持原状态。下一批聚焦同步release验证的单次受控计算边界，先证实际调用覆盖、收益和漂移拒绝，不再扩大传输或逐个删除Query；见[整链预算与决策](../architecture/reviews/2026-10-16-coding-session-critical-path.md)。仅本地提交，不推送。

以下为各冻结快照的历史证据；以本段及最新验收记录为当前执行依据。

2026-10-16 当前拓扑归并候选：仅exact Coding4普通JSON完整请求，Coding拓扑复用首次已完整解析的全部叶绑定；公开拓扑、隐藏Agent、原结构／并发、末轮独立全组和Scope验证保留。新增18项通过，完整请求冷包CPU下降32.2%，独立绑定／Runtime基本不变；未据此宣称业务提速。424产品／859测试已冻结，全部Temporal回归3707 passed／589配置依赖skipped，独立安装212 passed及默认canonical／保存History离线兼容通过；原360秒首项本候选正常复验仍1 failed／392.537秒：四Tool最终成功及效果采纳、两root退休、两Turn完整ACK和owned关闭／安全清理均成立，但第二Turn为期限取消而非成功；S2／P3-2保持开放。下一步仅定位最后工具之后的实际未完成步骤，不将完整尾部猜测为observer成本。其他十二正常／五故障未运行。详见[当前验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)；下方为各快照历史证据。

2026-10-16 当前候选：已归并exact Coding4普通JSON输入的同步绑定验证，保留原Scope完整校验、默认／旧协议／自定义输入回退及native逐请求fresh事实；无跨请求缓存。冷包完整绑定链CPU约下降23.7%，完整Runtime基本不变，不外推业务性能。全部Temporal回归3689 passed／589配置依赖skipped，独立安装194 passed，默认完整canonical及默认保存History离线兼容通过；424产品／858测试前后无漂移。唯一原360秒图首项正常复验1 failed／435.464秒；四Tool最终成功且效果全部adopted、两root退休，但整体期限已取消业务，第二Turn缺末end／Advance，owned关闭失败，schema依原Session义务保留。其他十二正常／五故障未运行，S2／P3-2仍开放。详见[本批验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。下方各checkpoint为历史证据，不覆盖本段当前状态。

2026-10-16 最新checkpoint：修复诊断生命周期后，原360秒首项仍1 failed／392.302秒，424产品／857测试无漂移；前三Tool成功、第四child已启动但Tool未调度。两root均退休、Session start/end ACK完整，第一Turn成功／第二Turn取消，owned关闭与安全清理通过，不能判两Turn业务成功。CPU质量首次完整通过（fault0／incomplete0）：含关闭窗口328.620 CPU秒中，Manifest重建64.167秒、composition验证60.179秒、Coding验证28.097秒为互斥成本，大部分发生在关闭前；未覆盖74.179秒。原History离线重放／只读Query计数通过且State不变，单node仅Coding3／composition3，下一步核查成本较高的Registry调用链，不将inclusive相加或继续盲目微调。S2／P3-2未关闭，其余十二正常／五故障未运行，600秒诊断未授权／执行。见[最新验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。下方514.670秒及其他结果保留各自历史范围。

2026-10-16 最新原图CPU v2诊断已终态：1 failed／514.670秒，零错误／跳过，424产品／857测试无漂移，未改变原360秒业务期限。前三Tool及candidate成功，第四Tool在关闭准入后拒绝、无candidate；effects3 adopted＋1 dispatched，两root仅一条退休，assembly关闭失败而Worker退出，schema依原义务保留。CPU采样fault1／incomplete5，全部排名和残差归因不采纳。诊断空stack累计历史线程的缺陷已RED复现并修复，保留64并发和其他限额、补固定首fault原因；四模块76项通过，独立关闭回调联合检查25项通过，未新增服务采样或修改产品。不从该复现反推旧fault唯一来源，下一步须先取得有效关键路径证据，不再按关闭后拒绝猜测源码漂移或叠加微优化。S2／P3-2保持开放，其余十二正常／五故障未运行，600秒诊断未授权／执行。详见[当前验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。以下成本与离线证据保留各自快照范围。

2026-10-16 当前P3-2仍由原360秒图编排验收阻塞。冷包完整Runtime对照已否定helper-guard优化（18.456→19.931ms／次），未进入产品；批量指纹与复用SCV也因未证明足够收益且增加变更检测责任而不实施。原CPU诊断只覆盖约47%的进程CPU，剩余约195.532秒未归因。原匹配Worker已通过199事件保存History离线重放，并在同一ReplayState上完成一次约10.052ms的SDK只读Query，完整State／publication／命令序列不变，0服务／模型；不作实际服务或完整性能验收，异常cProfile耗时撤回。下一步补原Worker关键路径计数覆盖，不继续盲目微调。原其余十二正常／五故障仍待验，独立600秒诊断仍未授权／执行。见[当前结构审查](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md#v21-验证成本结构审查2026-10-16未形成新产品候选)。

2026-10-16 修复既有事件订阅对waiting_input的错误拒绝：同步／异步follow保持等待，真实Local＋SQLite观察断连不改变原Run，Engine重启后按原游标接收完整后续事件和一次input_answered。新增6项，受影响5模块81通过；独立安装38通过，424产品／855测试无漂移，完整默认canonical及默认保存History离线兼容通过。仅现有观察路径兼容修复，没有新增HTTP端点；P3-2保持开放，完整P3-3及后续门槛未验收。见[修复记录](../architecture/reviews/2026-10-16-input-event-observation.md)。

2026-10-16 新增Coding4恢复幂等窄修：原unprepared已采纳但stop_needed排空后，原admitted-stop调用重复相同回执可返回原ACK，不添事件／权限／结算；完整身份与namespace及无原生grant／回执检查保留，首回执、外来／变更证据仍拒绝，unknown不释放。新增22项，受影响20模块402通过，另8个协议模块98通过；独立安装63通过，424产品／855测试核对无漂移，完整默认canonical及默认保存History离线兼容通过。旧Coding History仍需原匹配Worker，不能据旧路径行为保持声称选中Coding指纹相同。原360秒场景仍失败，600秒诊断未授权／执行，S2／P3-2仍开放。见[当前修复记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

2026-10-16 结构审查未形成新产品候选：完整双Runner Runtime少一次外层copy的私有ABBA未显示收益（18.839→19.756ms／次），已放弃；原交接包含必要Context／Model／physical-stop／register／approval，未找到秒级空等可删。原SDK Importer内的纯node identity暖调用约4.9–5.5ms、与host结果相同，不能代替完整Query测量。未重复实际场景、未改产品或期限，S2／P3-2仍开放。独立较长窗口诊断已提出用户澄清，尚未授权／执行，且即使通过也不关闭原360验收门槛。细节见[审查记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

2026-10-16 v21／`e6726c5`正常首项已结束：1 failed／455.001秒，零错误／跳过；424产品及854测试前后无漂移。整体360秒取消第二轮，第二approve180尚未到期。前三Tool成功且candidate已接受，第四实际开始、21.029423秒后为definition_mismatch且无candidate；首seal→正Advance Completed ACK19.594258秒。两root仅一条退休，effects3 adopted＋1 dispatched，assembly关闭未成功，schema按原未退休／Session证据／未采纳写门槛保留；Worker退出不替代关闭。其余十二项正常组合及五项故障未运行，S2／P3-2仍开放。停止同版本重复运行及尾部小修补，下一批复用既有CPU证据审查工具阶段和交接的完整验证成本，不扩大范围或放宽期限。详见[验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

2026-10-16 v21窄候选：仅Coding4 Session observer的后代只读集合合并重复Session验证，原Run／Registry／Start／祖先及逐后代session_proof读取不减；新独立raw七事实与Runtime出口后才返回。三后代真实对照结果及全部非Session Counter相同，Session组15→1；最终23模块368 passed／58.66秒，零失败／错误／跳过，1278产品／测试前后无漂移。独立审查及格式检查通过；独立安装四模块73 passed／20.65秒，默认完整canonical及保存History离线兼容通过，424产品／854测试核对无漂移，Provider0／服务0。随后实际首项未通过，见上方；S2／P3-2仍开放，不从夹具次数推导实际提速。详见[验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

2026-10-16 CPU-only诊断已结束（产品仍为v20／`49d26d8`）：1 failed／453.198秒，零错误／跳过；原整体360秒取消第二Turn。前三Tool成功并有candidate（48.107700／42.299957／44.522015秒），第四Tool20.742248秒为definition_mismatch、无candidate。第一seal至正Advance Completed ACK为21.705067秒；两root仅一条退休、held1，首次close为CloseIncomplete，最终RPCError，schema因未退休root、未确认Session关闭／证据及unadopted write保留。其余十二项正常组合和五项故障未运行，S2／P3-2仍开放。此前正常428.761秒与SDK／RAISE诊断314.926秒保留各自范围，不作跨样本性能比较。

整个Worker计数窗口（含关闭）为370.689625 CPU秒／416.570039墙钟秒；`_current_manifest` 6062次、110.207923 CPU秒，`validate_release` 6147次、inclusive 128.445344 CPU秒，嵌套值不能相加。计数faults0／incomplete0；仅覆盖固定host code，projection未观测为null，不能称CPU为零或据此归因完整关键链。纯Unicode／ASCII分支ABBA的完整Runtime收益仅2–5%，已放弃；广义raw live-pins缺完整等价证明，不实施。随后窄descendant候选的实现与检查见上方v21，实际门槛尚未通过。详见[验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。


2026-10-16 v20源码候选：仅exact Coding4／actual CONTROL／完整固定child的只读observe，已接入封闭Session身份读取；原完整Activity入口、所有Run／Registry／Start／祖先／compact／当前child读取保留，末独立raw Session七事实后才返回。主RED已确认原结果和非Session Counter相同，再由原6组变2组；默认/native逐请求fresh、其他mode、未pin和旧协议保持。新增取消finally清理、逐await拒写端口和完整身份／source pins，私有helper不提供Session权威。采样频率变化已写入实验契约，匹配不可变Worker恢复旧运行。同次135模块回归1986 passed／289 skipped／106.38秒（-Werror），1274产品／测试文件前后相同，独立审阅无P1／P2，Ruff／格式／空白检查通过。安装11模块173 passed／43.01秒，默认完整canonical及原／continued保存History离线重放通过，424产品与850测试副本前后相同、全部导入来自安装。源码本地提交 `49d26d8`；真实首项已结束，1 failed／428.761秒，424产品与850测试前后无漂移。整体360秒取消传入SDK Update；前三Tool成功且原结果已接受，第四业务子Workflow已启动但Tool尚未调度。第一Turn正Completed ACK已取得；第二Turn末observe缺end ACK。三条效果adopted、两业务root退休仍不代Session关闭，schema保留。S2／P3-2未关闭，其余十二项及五项故障未运行。下一批先以既有有界SDK／Worker计时定位实际耗时，不再依夹具计数盲目微调或重跑。


历史诊断checkpoint（2026-10-16，`d9bae41`，产品仍为v19）：唯一原图1 failed／482.320秒，424产品及847测试副本前后无漂移；整体360秒取消，首Turn成功、前三Tool成功，第四Tool返回definition_mismatch、无结果候选。首次close是原任务实际返回CloseIncomplete，非外层等待超时；未知leaf的handler／call-end ACK已齐，但缺原业务结果，effects仍3 adopted＋1 dispatched，仅1／2 root退休，schema正确保留。独立关闭缺陷未证明，停止按关闭报错本身叠加修复。S2／P3-2仍开放，其余十二项正常组合和五项故障未运行。当时拟实施的封闭CONTROL身份读集已在v20实现，实际首项结果以上方及验收记录为准；native逐请求fresh与原360秒门槛保持。详情见验收记录；以下v19首次运行及更早记录保留各自范围。


2026-10-16 v19源码收尾候选：仅已完成原Activity完整验证、child namespace／原始与当前epoch全固定的Coding4 CONTROL只读observe，使用私有验证入口归并冷初始化中的Runtime重建。原SDK形状完整控制链的Runtime full端口76→37；全部原SDK读取Counter、六组Session七事实及返回结果相同。专用入口自身使用真实Runtime固定Manifest完整入／出口，逐await原身份／源码pins不变；权限／原生readset拒绝，错误或取消清除snapshot。缺type／非CONTROL、其他mode／未pin及旧3仍走原类。新增15项纳入同次132模块回归：1956 passed／289 skipped／93.30秒（-Werror），1271产品／测试文件前后相同；独立审阅、Ruff、格式与空白检查通过。安装八模块143 passed／29.94秒、默认完整canonical及原／continued保存History离线重放通过。最新实际为下段v19，S2／P3-2未关闭。

v19实际checkpoint（本地 `4d72895`，原冻结安装）：原图首项1 failed／466.580秒，零错误／跳过，424产品无漂移。第一Turn成功，root start→seal185.594112秒，seal→Session UpdateCompleted正ACK约21.855秒；前三Tool均成功，46.705303／46.799534／44.210528秒。第二Turn第四Tool已启动，整体360秒取消先到，最终runner_outcome_unknown且无结果候选；第二root未seal，不能将三笔native提交当作两Turn成功。其余十二项正常组合及五项故障未运行。

v19两次关闭超时均在原 `_coding_stop_task`，尚未到Session close／Worker shutdown；通用错误文案不能定位Worker故障。四条native资源已物理停止／fence，但一条write仍dispatched、原stop call缺end ACK；仅1／2 root退休，assembly关闭失败，schema按证据门槛保留。fixture的workers_exited仅指其子进程退出，不证明assembly Worker关闭或原调用fence。v18关闭通过属于另一快照，不覆盖本次失败。现有保存堆栈不能区分原stop Update、后置fresh与Parent adoption，本批已补原失败边界的静态await链诊断，四个直接受影响模块37 passed／61配置依赖跳过；产品424文件与v19冻结源码相同。下一步据该诊断定位；不盲目重复全图或放宽期限。

历史验收checkpoint（2026-10-16，v18／本地 `85dce98`，metadata仍dev120）：Coding4 Session封闭整树读取与同次关闭末轮纯physical-pending消解已实现并经独立审阅。131个受影响模块1941 passed／289 skipped／88.74秒（-Werror），1270产品／测试文件前后相同；安装七模块128 passed／22.33秒、零失败／错误／跳过，424产品及846测试副本前后相同、所有导入来自安装。默认完整canonical与原／continued保存History离线重放通过，Provider0／服务0，不代表live continuation；跳过不作实际服务验收。

v18原图首门槛仍1失败／390.395秒、零错误／跳过。第一Turn成功发布，首root start→seal203.202694秒、seal→Session end记录接受21.812938秒。三个Tool均成功并保存候选，耗时45.936381／49.222193／57.774631秒；第四child注册与原360秒取消交错，未成功启动、无第四Tool。owned关闭本轮成功，两root正退休、Session与原树／资源证据通过，schema按原规则安全删除；不能据此宣称内部typed-pending分支实际命中。仍未满足整体期限，其余十二项正常组合及五项故障未运行，S2／P3-2与第三阶段保持开放。下方v17及更早记录保留各自历史范围。

三子树主RED在原v17上为13组重复Session事实；新路径保留每项Run／Registry／Start读取和相同证书，以独立raw SDK七事实及完整出口验证，19项定向检查通过。关闭合法原夹具RED与18项新增检查覆盖晚到停止、资源producer、硬错误／缺ACK／unknown／原资源和子节点消失、旧3保持。实际History不包含Query返回或私有分支遥测，不能把夹具13→1当作实际RPC量或速度改善。下一步仅定位现有执行／交接的剩余耗时，不扩功能、不缓存权限、不提高原80／60／180／360期限。逐快照证据见[验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

当前验收 checkpoint（2026-10-15，v17／本地 `a4cfc38`）：S1 普通 Session 已验收；P3-2 的 S2 Coding Session 仍开放，P3-3／4／5／A 尚未关闭。最终受影响回归959 passed／193 skipped／55.06秒（-Werror），跳过不作实际服务验收。独立安装五模块91 passed／11.39秒、零失败／错误／跳过，424产品及844测试副本前后相同；默认完整canonical及原／continued保存History离线重放通过，Provider0／服务0，不代表live continuation。

v17实际graph-sequential仍1失败／432.08秒，零错误／跳过。第一Turn成功发布，第二Turn第四child已启动，但未批准／未调度Tool便触发原360秒整体期限。前三个Tool均成功（48.236686／43.243227／47.418934秒），第一root成功、第二root在清理取消后以failed退休；两root均正退休、held0，不能代替Session关闭。第二Turn末observer有start无end，原ACK未清；owned关闭先CloseIncomplete，退出Worker后的重试RPCError，schema保留。缺少Registry的Session close回执直接触发保留规则，尚未进入State重建，不将其称为新codec／State缺陷。其余十二项正常组合与五项故障未运行。

本批只归并既有只读验证：Runtime完整检查移到原group边界，固定child的observe省去桥内重复父验证，原生逐请求fresh、首／末完整证据及原80／60／180／360期限保持。实际首root start→seal191.984926秒、两Tool交接33.603793秒、seal→Session ACK24.222412秒；比v16单次样本略短，不能推断因果或稳定性能。当前局部优化不足以关闭整项。下一批核对同一只读树内重复Session身份读取及上游physical close责任，先明确封闭读取／独立出口验证边界，再做必要修复；不新增功能、缓存权限或放宽未知／停止／ACK门槛。逐快照证据见[验收记录](../architecture/reviews/2026-10-15-temporal-deployment-sessions.md)。

执行约束更新（2026-10-15）：按用户指令固定第三阶段范围、优先收尾，当前只执行[冻结清单 P3-1 至 P3-5／P3-A](phase3-support-matrix.md#收尾范围冻结2026-10-15-用户指令)。S1 普通 Session 功能子集已验收，P3-2 的 S2 与所选集成门槛仍待；不新增功能矩阵、适配器或独立重构专项。本条调整开发优先级，不变更以下已验收状态，也不代表第三阶段已完成。

工作区 S1 checkpoint（最终 v6 候选）：显式 `enable_sessions=True`、`deployment_sessions=True` 与部署准入策略已接通普通 Session 的 publication4／Registry4，旧默认选择保持。v6 补齐 closing 期间原 factory 的 evidence ACK 维护通道；每次机械 release 使用 fresh SDK Update ID，原 root／certificate／payload 不变，退休幂等仍由原 Registry History 保证。424 个产品文件在冻结源码、wheel 与安装中一致；v6 默认完整 publication 等值、原／续接 History 离线 replay 通过，新增 Provider 调用为零；live continuation 仍沿 v4 独立证据引用。

实际 SDK 证据分版本保留：v4 默认 60 秒的九种既有普通编排 9 passed、专用 3 秒超时恢复 1 passed、容量场景 1 passed；v6 最小审批／重启链路 2 passed／40.67 秒，全新 Runtime／Client 恢复已 seal 未退休原根及退休回复丢失 1 passed／27.23 秒。v6 债务两项同次 2 passed／84.06 秒、零失败／错误／跳过：每项两次 Turn／物理写入，unknown 及 ACK 债务期间保持 busy／根占位，原实际停止与 ACK 后才退休／发布；owned 关闭未完成时保留 receiver 与资源，按既有契约各两次关闭后排空并关闭一次。既往关闭入口、observer 晚回执、1 秒故障夹具和失败 Update ID 重放记录分类保留，不以复验覆盖失败。

回归出处分开登记：前一冻结 `candidate-full` 完整回归为 12083 passed／805 skipped；v5 受影响 Temporal 为 3175 passed／571 skipped；v6 release 相关 24 模块为 438 passed／90 skipped。这些结果不相加，不宣称当前全量通过，跳过不算实际验收。S1 普通 Session 功能子集关闭，S2 已实现、实际 SDK 门槛仍待通过，Temporal＋PG 集成、P3-2／第三阶段尚未关闭，P3-3／4／5／A 不变。接口与剩余门槛见[固定 Session 计划](superpowers/plans/2026-10-15-temporal-deployment-sessions.md)。

S2 的既往 Agent／sequence 两Turn证据及各候选失败记录均保留在本批验收记录，不拼接为当前十三项矩阵通过。当前状态以上方v17 checkpoint为准。

以下 Dev120 段落描述已提交基线及其当时边界；不覆盖上述 S1／S2 checkpoint 的有限验证结果。

Dev120 已将显式公共 deployment3 接入既定 Temporal Coding Agent／sequence、有界图、Team／Dynamic 与递归组合，和 ordinary2 共用同地址 Registry 容量。原 Run／Parent History 继续拥有审批、native grant、效果与预算；原树闭合和独立 ACK 证明控制退休，unknown、零费用占用与实际 handler 责任保持。子事实通知、紧凑身份／CONTROL 和 fresh-owned publication 减少重复工作；最终完整验证及 SDK 身份门禁保留，稳态只读 read-set 的明确边界见[本批验收](../architecture/reviews/2026-10-15-temporal-deployment-coding.md)，不新增权限缓存或即时 read-auth 撤销能力。

v30 完整离线重新执行全部12651个唯一节点：11847 passed／804 skipped／0 failed／0 errors，430.21秒，无通过复用或未执行项；804跳过不代实际验收。之后4个测试文件修订另有92项定向检查通过，产品416文件未改，不相加为新全量。独立安装416产品字节一致，209个已加载模块全来自安装；dev119默认完整发布、原History重放／续接与新增Provider调用0通过。原安装normal矩阵13项通过／1项失败保留，修订后并行owned-close的独立normal单项1 passed／152.70秒，前后pins、真实故障回执和保留门槛通过；这是两次运行，不是同次14项全绿。测试仅按公开aclose契约允许最多2次恢复调用，原300秒总界／每次80秒保持，不宣称已证明v30的精确根因。原Assembly和Workers结束，unknown Root仍按原占位与恢复资料保留。

历史拓扑、真实Docker及失败记录按对应冻结版本分别保留；结构native peer不新增模型质量或延迟SLO结论。公共SDK Session-coordinator准入仍未实现并保持拒绝，S1设计／私有纯DTO不启用publication4，Coding Session仍为S2必需工作。批次2、第三阶段、完整R01–R26／R13及跨宿主／通用质量门槛未关闭。最终文档与metadata须另行打包记录新出处，不能冒称与v30完整public快照逐字相同。

## Dev119 与此前批次记录（历史范围）

Dev119 已实现普通 Temporal 部署的公共 v2 入口：`TemporalRuntime(admission_policy=...)`、Engine、Profile／JSON／TOML 与同步／异步策略工厂复用原 `DeploymentAdmissionPolicy`。原 Registry 原子保存首个完整请求、Manifest、Activity timeout 和队列；相同 Scope／命令／请求先查原接受记录，再校验新发布，不确定 reserve／start 回复不会换根、换 epoch 或释放占位。原 Run／Parent History 记录真实 Activity 开始／结束及不可逆闭合证书；Registry 自身的 SDK 校验 Activity 核对原树后幂等退休额度。所选普通 Agent、顺序、图、Team、Dynamic 与嵌套范围已完成冻结源码和独立安装验收：每套 46 个受影响模块的 953 项检查、27 项公共 v2 实际服务与 17 项私有 v1 实际服务均零失败／错误／跳过。410 产品文件在源码、wheel 与安装中一致，48 个测试模块固定；原 dev118 默认 Profile／Manifest／orchestration 等值，源码和安装分别重放并续接原 History，新增 Provider 调用为 0。owned 业务、Registry、Worker 与专用服务已关闭，最终出处见[本批验收记录](../architecture/reviews/2026-10-15-temporal-deployment-public.md)。

内部 worker-only v1 保留只占位、不释放的旧语义；公共 Engine 明确拒绝 v1，已有同地址 v1 Registry 不会被替换或自动升级。未选择部署策略的默认发布及原请求／History 兼容已按原版本验证。所选部署模式的 Coding 物理关闭与 SDK Session-coordinator Turns 尚未接入，继续明确拒绝并保留为批次 2 必需项。批次 2、第三阶段与完整 R01–R26 未关闭；本批没有新增模型质量或独立采用结论，仅允许本地提交、不推送远端。见[公共契约](../architecture/specs/temporal-deployment-public-contract.md)与[支持矩阵](phase3-support-matrix.md)。以下 dev 段落保留各自当时的交付范围。

Dev119 另补齐已封存、仍占位根的恢复：Registry 退休 RPC 恢复后，`await engine.drive(run_id)` 核对原信封与 SDK 身份，发送新的精确重复 seal Update 唤醒原 History 的释放重试。证书不变，不复活业务，也不由 Facade 直接释放 Registry；当前终态不代表额度已退休，须查看部署诊断。该 P2 已有真实 RED→目标 GREEN，并纳入最终公共服务矩阵。Parent 取消回执的 `remote_stop_confirmed=False` 要等待实际后代结束；已完成 Action 的 effect ACK 延后沿原 `drive` 恢复，不能把 `reconcile(query=True)` 当作重试 ACK 或业务工具。

本批真实零费用写／ACK 恢复窗口使用测试专用 SQLite 效果证据适配器，其他确定性用例使用默认组件；没有模型、PostgreSQL 或 Docker 调用，不新增 PG 阶段验收或模型质量结论。无 SDK 边界检查最终为 53 passed／68 skipped；最终 sdist 字节／SHA 记录于私有 `final-acceptance.json`，由 root 最后核对；随本地提交交付，不推送远端。

Dev118 将内部所选 Worker 的部署准入接入原 Run／Parent SDK 执行。业务 Activity、选择和子派发前核对原 Registry claim、实际 namespace UUID、原 SDK epoch 和有界原 Parent 祖先；Agent、顺序、图、Team、Dynamic 与嵌套后代共用一个根槽位。所有注册业务 Activity 均受门禁保护，原 handler 请求和 SHA 保持，受管理 Context／limits／completion／Session 写入继续沿原阶段契约。默认发布保持兼容。冻结源码与独立安装各通过 814 项受影响检查、17 项实际 Service；最终出处记录在[本批验收登记](../architecture/reviews/2026-10-14-temporal-deployment-dispatch.md)，不称为本批全量回归或新模型质量验收。

Dev118 当时公共 Temporal Engine／Profile 仍拒绝启用部署策略。不确定启动／重复回执恢复、Coding 物理关闭、Session coordinator 准入、原树／unknown／辅助阶段／真实 handler 闭合证明及安全释放为当时的必需下一交付；当前公共普通 v2 进度以本页 dev119 和其验收记录为准。见[调度契约](../architecture/specs/temporal-deployment-dispatch-contract.md)与[准入指南](deployment-admission.md)。

Dev117 在原 CommandRegistry History 增加部署准入基础：固定完整策略与 namespace、部署隔离地址、Scope 命令身份、原子根限额，以及原根执行 epoch 身份登记。实际服务覆盖并发、容量拒绝无回执、重复命令、队列固定、Worker 重启与 History 重放；这些是登记协议证据，尚未验证业务 Run 的 SDK 绑定。公共 Engine／Profile 继续拒绝部署策略；原 Run／Parent 调度、子孙传播、不确定启动与物理安全释放仍需下一批实现，批次 2 未关闭。见[契约](../architecture/specs/temporal-deployment-admission-contract.md)和[验收登记](../architecture/reviews/2026-10-14-temporal-deployment-admission.md)。

Dev116 补齐[Local 部署根准入](deployment-admission.md)：独立 `DeploymentAdmissionPolicy`、SDK／Profile／JSON／TOML、同步／异步替换及原 Profile 的宿主策略恢复入口。原 Store 固定部署策略并纳入 legacy，根与所有子 Run 共用一份持久槽位；未知、零金额预留、辅助写入、实际线程与原子孙义务均保留。终态验证阶段仅按原证据退休，原提案不清除、不采纳晚到 verdict；公开诊断暴露释放宿主故障。[验收登记](../architecture/reviews/2026-10-14-local-admission.md)区分源码、安装与恢复证据。Temporal 部署准入仍是批次 2 的必需下一交付，不能以单 Run／Runner 限制替代；批次 2 与第三阶段未关闭。

Dev115 在原 Local Run／Action 权威实现持久 Run／审批期限，接通 SDK、Profile／JSON／TOML、绝对 `deadline_at` 与同步／异步替换。时间在原接受／审批事务固定，图、Team、动态与嵌套沿原父级传播；观察超时不取消业务，到期保留实际 handler、未知效果与原预算。源码／安装及恢复证据见[本批登记](../architecture/reviews/2026-10-14-local-deadlines.md)，使用与原版本恢复见[指南](local-execution-policy.md)。当时部署准入未完成；当前 Local 准入与 Temporal 剩余门槛以 dev116 登记为准。

当前开发依据为[第三阶段支持矩阵](phase3-support-matrix.md)。Dev114 接通原 `TemporalExecutionPolicy` 的 SDK／Profile／JSON／TOML 入口和同步／异步替换工厂；内置配置在组件 I/O 前校验，显式错误返回值拒绝并关闭 owned 资源。省略策略保持原默认 Profile 与完整 Manifest 字节；策略与期限仍由原 History 推进。本批恢复、安装及兼容证据见[验收登记](../architecture/reviews/2026-10-14-temporal-policy-profiles.md)。部署容量、HTTP 管理与观察、身份 ACL、保留及框架备份恢复仍是阶段必需后续项，首批不关闭 R21–R24。

第二阶段历史冻结范围见[支持矩阵](phase2-support-matrix.md)。Dev113 顺序／递归 Temporal Coding 已完成所选源码／安装各六场景、36份原History重放和完整回归（10234 passed／704配置依赖跳过）；395产品与独立wheel／安装一致，第二阶段随本地提交冻结。当前进入第三阶段服务化与治理；跨宿主、额外Runner和daemon已发送请求的自动负向恢复为后续范围，unknown义务继续保留。历史各dev段落不覆盖当前矩阵，有限阶段通过不等于完整R01–R26或企业正式可用。

Dev112 增加[原 CREATE 监督与未发送证明](coding-resource-recovery.md)：两层单次 gate、原 broker／CLI 租约、持久结构化回执、冷 query／abort／drain、reap 前进程结束观察和固定源码／导入别名校验。专用 `create_not_dispatched` 经原 Local／Temporal 采纳及实际排空后释放容量，保留原 grant、attempt、未知效果与费用。选定 Temporal 为 native5／binding20、composition6／binding21；旧18／19使用 immutable dev111 Worker，未选定默认字节保持。验收分层见[本批记录](../architecture/reviews/2026-10-14-coding-create-supervision.md)。已发送 create 的 daemon 负向完成、持久队列、公平调度、跨宿主、嵌套／sequence Coding 和复杂真实质量仍开放，完整 R13／第二阶段未关闭。以下各 dev 段落保留当时实现与验收范围。

Dev111 加入[物理 Runner 容量与 create 恢复](coding-resource-recovery.md)：同根容量一、原 invocation 等待、持久原义务、仅查询／验证／停止原 CID，以及所有权 CAS。选定 Temporal 升至18／19；旧16／17恢复需 immutable dev110 Worker，未选定默认发布保持。验收分层见[本批记录](../architecture/reviews/2026-10-14-coding-root-capacity.md)。负向 create 完成证明、CLI监督、持久队列、公平调度、跨宿主与复杂 Coding 质量保持开放，完整 R13／第二阶段未关闭。

Dev110 已验收直接 Agent 成员子集：接通原 Temporal History 内的一层 Agent Team／Dynamic Coding、实际成员 Runner 背压、冻结 child revision、pending-only DAG patch 和完整停止门槛。当前 selected native v3／binding16、composition v4／binding17；未选定默认发布逐字节保持，旧选定 Run 使用匹配不可变 Worker。嵌套、sequence 成员、跨父容量、不确定 create／CID 与复杂真实质量仍开放，完整第二阶段未关闭。真实服务／安装与审查进度见[本批登记](../architecture/reviews/2026-10-14-temporal-coding-orchestration.md)，使用见[编排指南](temporal-coding-orchestration.md)。

Dev109 接通固定 Responses 模型连接、延迟解析的可替换凭证源和 Local／Temporal 显式装配，继续复用原 Action／History 执行权威。dev109 当时选定 Temporal 发布为 native protocol 2／binding 14、静态组合 version 3／binding 15；旧选定发布需要匹配的 immutable Worker。安装包真实 DeepSeek 的三类有限 POSIX Coding 任务各重复三次，通过 9/9 次、78 项独立禁网容器检查；不代表通用 Coding 质量或 AgentScope 对齐。Temporal Team／Dynamic／嵌套 Coding、跨父全局容量、跨宿主和不可确定 create／CID 窗口仍开放，完整 R13／第二阶段未关闭。 见[连接指南](codex-model-connection.md)和[本批验收](../architecture/reviews/2026-10-14-codex-model-connection.md)。

Dev108 已验收有限 Temporal 有界静态 Agent 图 Coding：协议 13／组合版本 2，在原父 History 按有效 Runner 授权调度不同资源并行和共享资源背压；财务已结算但未证明物理结束的原子仍占槽。关闭尝试全部独立原叶、准确核对 PG／History 完整请求并重扫，失败保留资源；停止失败恢复不会重开取消中的业务。Team／Dynamic 的持久选择阶段、跨父全局 Runner 容量、嵌套／直接 Tool、专用认证和真实 Coding 质量仍开放，完整 R13／第二阶段未关闭。 见[并行指南](temporal-parallel-coding.md)和[本批验收](../architecture/reviews/2026-10-14-temporal-parallel-coding.md)。

Dev107 已验收有限 Temporal 串行 Agent 图 Coding：显式 `coding_composition=True` 依赖原 Coding 开关，协议 12 固定原父子请求、namespace UUID 和 SDK epoch；原 History 继续管理调度、审批、结果和预算，PG 只存证据。owned 关闭排空真实 SDK 提交、关闭已有提交准入，并采纳原后代的物理停止；未知效果与整个子 cap 保留。直接 Tool／并行／Team／Dynamic／嵌套 Temporal Coding、跨宿主、专用原生认证和真实 Coding 任务质量仍开放，完整 R01–R26／R13／第二阶段未关闭；dev99 四链路保持冻结。 见[组合指南](temporal-coding-composition.md)和[本批验收](../architecture/reviews/2026-10-14-temporal-coding-composition.md)。

Dev106 已验收原 Temporal Agent／顺序 Workflow 的有限 Coding 委托：显式 `coding_execution=True`、`tools/codex-coding-postgres` 与精确 `runner/registered-tool` 借用接通 SDK／JSON／TOML。所选发布使用 `temporal-3`／binding protocol 11／`coding_execution_protocol=1`；省略选项的默认 Local／Temporal 字节保持。原 History 独占阶段准入、结果与额度，原 PG EffectJournal 同事务记录资源意图及回执，实际 owner／原容器停止证据另行核对；关闭失败保留原资源账本供同循环重试。PG／History 原配置使用精确 readonly file bind，真实保护控制探针通过，原配置内容／inode、原 CID 移除与 History／PG 收尾已验证；此前未保护配置失败保留。复杂 Temporal Coding 仍拒绝，跨宿主、专用原生认证和真实 Coding 任务质量继续开放；固定 process-peer 协议验证不构成真实模型质量。源码全模块回归的旧协议断言已定向修订；独立安装2175项／418配置跳过、实际服务39项零跳过和旧Worker门禁已登记，完整 R01–R26／第二阶段与 dev99 冻结范围保持。见[使用指南](temporal-coding.md)和[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)。

Dev105 将有限 Coding 委托扩展到 Local 图 Agent／直接 Tool 节点、串行／有界并行图、Team／Dynamic 和嵌套成员。复杂发布使用 `local-11`／`local-bindings-19`、`delegated_composition_protocol=1`；根级 Agent／顺序的旧路径和默认未选择工具的字节保持。原子 Run／节点 Action 继续拥有审批、额度和阶段准入；父级取消等待原后代实际停止，unknown 效果与 escrow 不因此清空。并行节点视图核对原 Run／Action／索引／资源，已排除的工具不影响调度，拥有资源关闭仍保留原权威供停止与退出回执。Temporal Coding、专用认证、真实 Coding 任务质量及完整 R01–R26／第二阶段继续开放。见[复杂组合指南](coding-composition.md)和[本批记录](../architecture/reviews/2026-10-14-coding-local-composition.md)，dev99 冻结链路保持。

Dev104 将可选 `runner` 绑定和异步 `tools/codex-coding` 声明接入原 Local 根级 Agent／顺序 Workflow，支持一个 Profile 中多个独立 Runner、精确 `registered-tool` 借用和 owned 关闭重试。显式绑定使用 Descriptor 3／`local-bindings-18`，省略角色保留原 Descriptor 1／2 与默认发布；工具授权交集和原 Run／Action／预算／审批权威保持。具体资源在模型 I/O 前复核物理身份，owned 清理开始前隔离原 Engine，停止或关闭失败保留 Coordinator 和资源账本。图／Team／动态／嵌套与 Temporal Coding 继续拒绝，原生认证和真实 Coding 质量未验收。见[配置指南](coding-profiles.md)和[本批记录](../architecture/reviews/2026-10-14-coding-bindings-and-profiles.md)；dev99 冻结链路不重复评测，完整 R01–R26／G1–G8／第二阶段继续开放。

Dev103 增加[原 Local ToolAction 的 Coding 委托](local-coding-delegation.md)：显式 SDK 注册、一个审批／预留／attempt、原 Run 的一次阶段准入、同连接配置校验、原 Thread／Turn 回执与停止采纳已接通。Docker opt-in 移除原容器并使旧 start argv 失效，宿主工作区与证据保留。仅根级未绑定 Agent／顺序 Workflow；更复杂编排、per-Agent runner、声明工厂和 Temporal 原生委托尚未接入，所选不支持路径在业务 I/O 前拒绝。存储通过公共 DelegatedExecutionStore 能力查询待停止 Run，不依赖 SQLite 私有扫描；默认 kernel／Schema 保留，委托发布显式 local-10／Schema 14。实际环境证据与结构化假服务的业务协议验证分别登记，专用认证／真实模型 Turn 未通过，完整 G1–G8／R13／第二阶段仍开放。最终审查、回归、安装及兼容结果见[本批登记](../architecture/reviews/2026-10-14-local-coding-delegation.md)，dev99 冻结范围保持。

Dev102 新增[保留 Docker Coding 环境与共享 PG 启动证据](codex-coding-environment.md)：原 container ID／generation 冷检查、保留 workspace／状态与实际整容器停止已有有限证据；共享视图借用原 EffectJournal，原 dispatch／启动意图同事务提交，Local／PG 共用纯规则。最终受影响源码 301 项零跳过，含 PG 39 检查／17 实际案例，初始化路由 P1 与全循环取消 P2 由同一审查者实际复验闭环；独立 wheel 安装同 301 项零跳过，实际安装控制／停止／冷重开通过，见[本批登记](../architecture/reviews/2026-10-14-codex-environment-journal.md)。原始 Docker argv 仍可重启已停容器，原 Action／Local／Temporal 准入、旧启动失效与 History 未接入，专用认证／业务 Turn 未执行。R13、完整 G3／G5／G7／G8 和第二阶段仍开放，dev99 保持冻结，不重新评测。

Dev101 固定 Coding 候选配置、只读原生启动校验和 seccomp 资产已实现：真实 App Server 九项控制查询与有限原生命令读写／拒绝／整容器停止探针通过；控制结果保持 execution_admitted=false。独立审查的最终回执后违规请求 P2 已修复。原 Action 委托、专用认证、完整原生 Turn、Local／Temporal 停止采纳仍开放，不标记 R13 或第二阶段完成。见[使用边界](codex-coding-preflight.md)与[验收记录](../architecture/reviews/2026-10-14-codex-coding-preflight.md)。

Dev100 进入第二阶段，新增固定 Codex 0.144.4 协议子集、有界 stdio 通信与独占持久启动证据。启动取消 P1 已由同一独立审查者复验闭环，受影响源码／固定安装各 127 项零跳过；原 351 个产品模块保留。仅基础组件，无完整 Runner 工厂／绑定；真实 Codex、受限工作区和 Temporal 委托取消未验收，R13／第二阶段继续开放。见[实现边界](codex-runner-foundation.md)与[验收记录](../architecture/reviews/2026-10-14-codex-runner-foundation.md)。下列阶段验收与历史记录保留。

Dev99 四条有限 Local 参考链路的固定真实质量线已通过：单 Agent 24/24（复用 dev98 未改的业务／执行／Provider 字节），语义 RAG 24/24，Plan／Team 在关闭 JSON mode 的独立最终配置各 15/15。此前 dev98 与 dev99 JSON mode 的全部失败分别保留，不合并评分。安装后语义 CPU 应用、成员回执反馈、原取消／崩溃恢复与模型资源实释放已有证据；最终源码 8397 passed／617 配置依赖跳过，核心／SDK 安装各 254 项零跳过。四链路的安装／必要生命周期／质量／文档验证通过，随本地提交冻结第一阶段范围；这是阶段参考场景，不代表通用自主规划、完整 H3／M1／R01–R26、Temporal 部署或外部采用完成。见[阶段门槛](delivery-gates.md)与[本批验收](../architecture/reviews/2026-10-13-phase1-business-chains.md)。

Dev98 自动 Facts 索引维护首期子集已验收：来源快照分代、原 Graph ToolAction、准确效果日志和 ready-only Agent 门禁；SDK／JSON／TOML、owned／borrowed 与可编辑 memory-index 模板接通原 Session／Profile 恢复。最终冻结源码 8298 passed／617 配置依赖跳过，两套安装各 163 项零跳过，12 种配置／32 个实际 Turn、六类进程窗口和旧 dev97 的 16 组 Run／Turn 双向兼容通过。349 产品模块一致，四项审查问题由同一审查者闭环。首期仅原生 SQLite／Hash；真实语义／模型质量、远程及 Temporal 维护、后台／增量物理清理／GC、两项 P3 严格输入观察、完整 R01–R26／H3／M1 和外部采用继续开放。 见[使用指南](fact-index-maintenance.md)与[验收记录](../architecture/reviews/2026-10-13-fact-index-maintenance.md)。

Dev97 模型替换与业务组合子集已验收：固定 model-provider core P01–P10／tools P01–P16、可编辑 SQLite 供应方、SDK／JSON／TOML、同步／异步与 owned／borrowed 装配接通 Agent／当前来源 RAG／规则 DAG Plan／Supervisor Team。最终源码 8183 passed／617 配置依赖跳过；独立核心／SDK 各 205 项零跳过，修复后的安装应用共 192 种配置组合通过。六项 P2 经同一审查者闭环；实际原响应、审批效果与遗失响应窗口、旧 dev96 的 16 组 Run／Turn 双向恢复、8 类原生模型方法与默认及 K/S/Facts 字节兼容通过。345 产品模块与安装包保持一致。新返回模型证据以 128 层容器为界，超限保留完成与结算，历史已接收记录保持。未重新验收真实模型、远程服务、Temporal 或独立采用；完整 R01–R26／H3／M1、路由、索引生命周期和质量目标继续开放。 见[使用指南](model-adapter-contracts.md)与[验收记录](../architecture/reviews/2026-10-13-model-adapter-contracts.md)。

Dev96 Facts 存储契约子集已验收：core F01–F10／managed F01–F16，独立 SQLite 替换、SDK／JSON／TOML、同步／异步装配及原提炼／受管理恢复通过。最终源码 7989 passed／617 配置依赖跳过；独立核心／SDK 各 262 项零跳过，每套安装示例完成同一应用 24 种配置组合及实际原工厂恢复。旧 dev95 的 16 组 Run／Turn 双向兼容、80 个已回收子进程、原默认／方法／K/S 字节及 342 模块一致通过。一次独立审查的三项 P2 已由同一审查者闭环，含慢速／最长及空白 namespace、历史计数与审计快照修复。本批没有重新验收真实远程服务、Temporal、模型／语义质量或独立采用；其他角色、索引生命周期、完整 R25／R01–R26／H3／M1 继续开放。 见[验收记录](../architecture/reviews/2026-10-13-facts-adapter-contracts.md)。

Dev95 Session 存储契约子集已验收：core 固定 S01–S10，receipts 固定 S01–S14；独立可编辑 SQLite 替换、同步／异步 SDK／JSON／TOML 装配及原保存恢复通过。最终源码 7727 passed／617 配置依赖跳过；独立核心安装 272 零跳过，SDK 166／1 服务配置跳过，安装示例 13 个实际命令通过。旧 dev94 默认和原 Run／Turn 的 68 个进程兼容验证、338 产品模块一致、隔离／取消及示例地址审查修复通过。本批没有重新验收真实 Temporal 服务、外部远程适配器或模型质量。严格原始非法输入、其他角色 Suite、独立采用与完整 R25／R01–R26／H3／M1 继续开放。见[使用指南](session-adapter-contracts.md)及[本批验收](../architecture/reviews/2026-10-13-session-adapter-contracts.md)。

Dev94 R25 首个知识适配契约子集已验收：固定 K01–K12、安装后 SDK／CLI、独立可编辑 SQLite 参考、JSON／TOML 声明替换与 Agent／RAG／Plan／Team 消费。原方法／Query／生命周期保护保持既有权威；缺 hook 未验证，质量为 null。完整源码 7516 passed／617 配置依赖跳过，独立核心 213／SDK 133 零跳过；原生 Temporal 源码和安装各 12 项／24 Worker 实际等待／12 History 重放，旧93默认及六类原Run双向兼容、333模块一致，五项审查问题闭环。其他角色、完整 R25／R01–R26／H3／M1、真实质量与独立采用保持开放。见[使用指南](adapter-contracts.md)及[本批验收](../architecture/reviews/2026-10-13-knowledge-adapter-contracts.md)。

Dev93 持久用户输入子集已验收：显式 `request_input` 与所选 Planner 共用固定
问题／回复协议，由原 Local Coordinator 或 Temporal History 续接原 Run／Turn。
Agent、图／Team／嵌套成员、flat／DAG Plan 接通 SDK／Profile／CLI 和显式 A2A。
最终源码 7339 passed／617 配置依赖跳过；独立核心 259／SDK 277 零跳过，源码和
安装 Temporal 各 12 项、24 Worker 实际等待、48 条 History 重放。六项审查问题
闭环，327 产品模块与两份安装一致，旧 dev92 默认及六类原 Run 双向兼容。
真实模型质量、独立采用和完整 R01–R26／H3／M1 继续开放。
见[使用指南](user-input.md)和[本批验收](../architecture/reviews/2026-10-13-durable-user-input.md)。

Dev92 R10／H3 父级完成验证子集已验收：显式可替换policy、真实子Run／工具回执、Receipt／Inventory纯gate、受管理模型stage、Plan反馈和Team拒绝沿原Local／Temporal权威实现，提供SDK／Profile和安装后默认参考。最终源码7126 passed／605配置依赖跳过；独立核心522／SDK413零跳过，实际源码及安装Temporal各7项／各23条History重放；旧91默认及六类原Run双向兼容、旧Local／Worker业务I/O前拒绝、321产品模块一致和自有服务退出通过。一次fresh review及同一reviewer修复复验闭环五项Important，包括根Session写响应丢失后的原回执／真实结束证明恢复。原通用推荐版本1／2默认保持；真实模型质量、完整R10／H3／M1／R01–R26及外部采用继续开放。见[使用指南](parent-completion.md)及[本批验收](../architecture/reviews/2026-10-13-parent-completion.md)。

Dev91 显式 Responses 推理续接子集已验收：保留原有序 output／密文／phase 和工具原参数，复用原 ModelContinuation／ModelHistory 与 Local／Temporal 执行权威，接通 SDK／Profile／四类评测 CLI。最终源码6792 passed／598配置依赖跳过（856.08s），独立核心安装494 passed／零跳过，实际源码Temporal5／安装Temporal17通过；311产品模块一致，旧90四类原Run及默认字节兼容。一次审查3个P2与1个CI Minor已修复，另5项公共边界回归通过；自有服务正常退出0并等待。原默认和历史发布不迁移；真实模型质量、完整R05／H3／M1／R01–R26及独立采用继续开放。见[使用指南](responses-reasoning.md)及[本批验收](../architecture/reviews/2026-10-13-responses-reasoning.md)。

Dev90 思考模型适配子集已验收：新增显式 DeepSeekThinkingProvider／deepseek-thinking，复用原 ModelContinuation／完整历史及 Local／Temporal 执行权威，接通 SDK／Profile／四类评测 CLI。保留非思考默认和原 Run；最终源码6519 passed／593配置依赖跳过（993.63s），独立核心安装266 passed／零跳过，实际源码Temporal4／安装Temporal12通过；308产品模块一致，旧89四类原Run和默认字节兼容。唯一审查2个P2已修复；自有服务退出0并等待。真实模型质量、完整 R05／H3／M1／R01–R26及独立采用继续开放。见[接入指南](deepseek-thinking.md)及[本批记录](../architecture/reviews/2026-10-13-deepseek-thinking.md)。

dev89跨Session原生模型历史子集已验收：最终源码6317 passed／589配置跳过（746.39s），独立核心安装243 passed／零跳过，独立安装真实Temporal76及Local/Redis/PostgreSQL50项通过。显式session/frame、每Agent继承/ref/禁用、同步/异步Profile和通用无SQL publication端口已接通；原根成功、准确CAS回执、失败候选排除及真实处理器责任保持。唯一审查4个P2及1个Minor已修复并复核；旧88四类原Run/默认字节兼容、Schema13及实际旧Worker零Activity拒绝通过。外置128轮使用明确128MiB私有服务，原50MiB服务104个已接受Turn后终止的证据保留，Continue-As-New/长期治理不据此完成。完整H3/M1/R01–R26、真实模型质量、独立采用和对等比较继续开放。见[使用指南](model-history.md)与[本批验收](../architecture/reviews/2026-10-13-session-model-history.md)。

Dev88 完整已采纳模型历史子集已验收：最终源码6021 passed／463配置跳过（897.57s），独立核心安装368 passed／8可选SDK跳过，实际Temporal源码和安装各35项通过。新增可替换ModelHistoryPolicy/CompleteModelHistory、Local local6/Temporal joint7显式门槛、原final/签名保存、验证retry单次反馈和完整交互保护。原参数与实际默认值分离；预算不足明确失败，Artifact投影需显式许可，原参考opaque在投影前拒绝。五项Important及真实Worker未获许可读取窗口经RED统一修复；301产品模块字节一致、旧87原Run/默认兼容和三个真实Local进程恢复通过，自有服务已关闭并等待。跨Session Turn原生transcript、DeepSeek thinking/Responses reasoning、真实质量、完整H3/M1/R01–R26及外部采用继续开放。见 [使用指南](model-history.md)与[本批验收](../architecture/reviews/2026-10-13-complete-model-history.md)。

Dev87 模型续接与 Gemini 原生函数子集已验收：最终源码5882 passed／455配置跳过（818.09s），独立核心安装295；实际Temporal源码8新恢复＋17既有场景、安装25均通过，300产品模块一致；旧86默认与同一Run双向回执／完整快照兼容通过。Local原接收／采纳与Temporal joint6两阶段保持各自唯一执行权威，签名原参数与真实默认参数分离；SDK／Profile／中间件和RAG／Plan／Team显式接通。一次独立review的2Important及重新评级的名称范围问题经RED统一修复，自有服务已正常关闭并等待退出。真实Gemini质量、其他推理续接、完整H3／M1／R01–R26及外部采用保持开放。见[模型续接](model-continuation.md)与[本批验收](../architecture/reviews/2026-10-13-model-continuation.md)。

Dev86 端到端任务评测子集已验收：源码5681 passed／447配置跳过（830.34s）、独立核心安装161；源码三次重复RAG24/24、Plan15/15、Team15/15及安装CLI／SDK例子、旧85默认／原Plan回执兼容与298模块一致通过。复用原执行权威，新增最终模型请求可见引用、实际成员／工具回执、独立Embedding计量和观察式恢复；2项Important／1项Minor经有效RED统一修复。离线／MockTransport不构成真实模型质量；完整H3／M1／R01–R26及外部采用保持开放。见[任务评测指南](task-evaluation.md)与[本批验收](../architecture/reviews/2026-10-13-task-evaluation-chains.md)。

Dev85 已验收子集：显式版本2推荐Plan默认使用原DAG结果依赖；完整资源声明替换无需多余Embedding配置，召回替换移除继承的互斥默认。版本1默认保持。业务／规划报告增加重复任务摘要，规划oracle与Provider前置校验、业务未完成Run恢复观察、模型兼容最终输出检查已修复。最终源码5520／447配置跳过、核心安装171、292产品模块一致和旧84原Plan回执兼容通过；独立review的1Important／1Minor均修复。整批验证以[本批记录](../architecture/reviews/2026-10-12-default-chains-evaluation.md)为准；离线回归不构成真实模型质量或完整H3/M1验收。后续段落按各dev批次保留历史证据。

Dev84 Artifact独立绑定子集已验收：memory／SQLite／POSIX JSON默认、custom sync/async、ref/disabled/inherit及宿主namespace选择沿原managed Context和Local／Temporal权威实现。Context与物理存储独立；纯预测完整校验并固定原方法，弱缓存和弱pins不保留历史Context。显式artifact_bindings=True支持无需多余存储的Temporal disabled-only。

最终源码5431 passed／447配置跳过（678.60s），核心104／SDK242安装、真实源码51／安装51（均零跳过）、旧83双向兼容／22原模板／旧Worker零Activity拒绝及291模块一致通过。九类Important经一轮34项有效失败复现统一修复；本任务Temporal PID12900／session19994实际退出0并已等待，用户Docker平台保留。完整R01–R26、远端／binary／GC／cache／治理与真实质量继续开放。 [本批验收](../architecture/reviews/2026-10-12-artifact-bindings.md)。

内容verified／结果succeeded不替代原写者结束证明；写ACK丢失时unknown_remote_execution／nonquiescent可保留。仅joint5/ref未获History grant的read/verify有耐久一次fence后重建；已授予与旧1–4不重试。dev83 M1实际TemporalSandboxCI、M2缺失ServerVersion typed error仍延期。见[指南](artifact-bindings.md)与[例子](artifact-binding-examples.md)。

Dev83 已验收受限原生 SandboxProvider／Docker 默认、原 ToolSource、显式异步声明和每 Agent sandbox ref/disabled 授权交集。Local／Temporal 六类审批重启、已采纳恢复、原生冷接管及真实停止通过。最终源码5280 passed／418配置跳过（763.57s (0:12:43)），核心182／SDK149安装、真实源码32／安装32、旧82双向恢复／22模板／旧Worker零Activity拒绝及287模块一致通过。六项Important统一修复，M1／M2两项Minor延期；自有Temporal实际退出并等待。完整R01–R26、远程沙箱、持久工作区、Artifact传输、外部Runner和真实质量继续开放。见[原生沙箱指南](sandbox.md)。

Dev82 子集已验收：纯可替换 SkillSelector／LexicalSkillSelector、SkillDirectoryRetriever、JSON／可选 SKILL.md 声明，通过原 KnowledgeContext 自动提供被动目录；正文仍走原授权 skill_get，不增加工具权限或执行权威。最终源码5089 passed／386配置跳过（845.08s (0:14:05)），核心155／SDK271安装、真实源码8／安装8、旧81双向恢复／22模板／旧Worker业务I/O前拒绝及281模块一致通过。三项Important经10项有效失败复现统一修复，无新增延期Minor；自有Temporal实际退出并等待。完整R01–R26、语义选择、插件激活、Sandbox／Runner及真实质量仍开放。见[本批记录](../architecture/reviews/2026-10-12-skill-discovery-context.md)。

Dev81 子集已验收：原生写真实生命周期及显式可替换 ToolExecutionPort／tracked owner，原 Temporal History 分别保存独占调用身份、实际结束与效果回执；容量拒绝／RPC失败／观察者取消的通知保持受管理重试。最终源码5021 passed／378配置跳过（758.54s），核心67／SDK232安装、真实源码8／安装8、旧80双向恢复／22模板／旧Worker执行前拒绝及278模块一致通过。三项Important经3项RED→GREEN统一修复，无新延期Minor；原自有服务停止并实际等待退出。完整R01–R26、Sandbox／Runner与质量目标仍开放。 见[本批记录](../architecture/reviews/2026-10-12-native-write-lifetime.md)。

Dev80：纯可替换 Skill 文档解析、可选有界 YAML、固定 SKILL.md 文件目录及 skills-markdown 默认声明子集已验收。最终源码4954 passed／370配置跳过（713.55s），无YAML核心35／SDK359安装、真实源码6／安装6、旧79双向恢复／22模板／272模块一致通过。三项Important经14项RED→GREEN修复，两项Minor延期；原自有服务停止并等待。selector／异步加载／自动Context／Sandbox及完整R01–R26仍开放。见[本批记录](../architecture/reviews/2026-10-12-skill-documents.md)。

Dev79：每Agent Skills的借用原生目录工具、Local／Temporal固定ref/disabled与Profile工厂已验收。最终源码4823 passed／364配置跳过（734.81s），核心55／SDK127安装、真实源码6／安装6、旧78双向恢复／22模板／269模块一致通过。两项Important经10项RED→GREEN修复；真实旧Local／Worker拒绝新角色且新Local继续原Run，自有服务停止并等待。selector／自动目录阶段／标准加载／Sandbox及完整R01–R26继续开放。见[验收记录](../architecture/reviews/2026-10-12-skills-bindings.md)。

Dev78：同步可替换Skills目录、Memory／固定JSON+Markdown File默认和原受管理读工具已验收。最终源码4757 passed／357配置跳过（741.54s），核心142／SDK204安装、真实六类编排及显式Scope默认工厂7项、旧77双向恢复／22模板／268模块一致通过。独立审查四项Important经22项RED→GREEN修复，自有Temporal已停止并等待。专用skills角色、完整YAML／异步加载器／Sandbox及完整R01–R26继续开放。见[验收记录](../architecture/reviews/2026-10-12-skills-catalog.md)。

Dev77：可替换Workspace CAS写入、Memory／POSIX默认、稳定效果键／单根租约与原Source／Local／Temporal恢复子集已验收。最终源码4615 passed／351配置跳过（700.98s），核心安装100／SDK214、真实源码及安装各6项、旧76双向恢复／新协议拒绝／22模板／264模块一致通过；独立审查三项Important经RED→GREEN修复，自有服务已停止并等待。实际Temporal阻塞原生写的取消／关闭／租约窗口为延期证据项，完整R01–R26继续开放。见[验收记录](../architecture/reviews/2026-10-12-workspace-writes.md)。

Dev76 adds per-Agent read-only Workspace bindings in Local and Temporal, fixed original registered-tool intersection and Profile factories. Final source4501 passed/345 configured skips (709.82s), core59/installed160 contracts and required source/installed6 actual Temporal compositions each pass; groups overlap. Actual75↔76 Local/CLI/defaultTemporal/native Session recovery,22 original templates,259 identical product modules and three installed guide examples pass. One Important typed-JSON identity finding is fixed RED→GREEN; invalid live drift error classification remains a deferred Minor. Actual installed75 Worker refuses the new Workspace opt-in before any Activity/model/tool I/O; all owned services and Workers are stopped and waited. Writes, subroot selectors, Skills, Sandbox, Runner and full R01–R26 remain open. [Final evidence](../architecture/reviews/2026-10-11-workspace-bindings.md).

Dev75 adds replaceable read-only WorkspacePort/POSIX/Memory defaults, three original managed tools and async declarations. Final source4431 passed/339 configured skips, core127/installed191 contracts and required source/installed2 actual Temporal FS/Memory cases pass; groups overlap. Actual74 recovery and22 templates,258 product modules and installed examples remain consistent. Eight Important fixes verified; owned service stopped. One C1-control path Minor deferred. Agent.workspace binding, writes, Skills and Sandbox remain open. [Evidence](../architecture/reviews/2026-10-11-workspace-read.md).

Dev74 adds bounded fixedHTTP MCP JSON/POST SSE and async declarations through original ToolSource/authority. Final source4304 passed/337 configured skips, core79/installed320 contracts and required source/installed8 actual Temporal/PG cases pass; groups overlap. Actual73 compatibility,22 original templates and254 product modules remain consistent. Three Important review findings fixed; owned services stopped. Persistent sessions, GET resume, OAuth and full MCP remain open. [Scope/evidence](../architecture/reviews/2026-10-11-mcp-http.md).

Dev73 adds fixedPOST HTTP JSON ToolSource/async declaration and CLI read/plan/approval/write defaults. Final source4225 passed/333 configured skips, core111/installed241 contracts and required source/installed4 actual Temporal＋PG cases pass; groups overlap. Actual72↔73 default Local/Temporal/native-save and old CLI-version1 recovery retain original identities/receipts/effects.250 modules match source/wheel/sdist/installations, owned services stopped. Two Important review findings fixed by8 RED→141 GREEN. [Scope/evidence](../architecture/reviews/2026-10-11-fixed-business-tools.md); full R01–R26 remains open.

Dev72 adds fixed-command JSON CLI ToolSource, actual POSIX process/thread ownership, async tools/cli-json factories and a wheel-contained cli starter. Final source4159 pass/331 configured skips, core45/installed154 contracts, required source/installed2 actual Temporal＋PG cases and original71↔72 compatibility pass.246 product modules match source/wheel/sdist/installations; owned services stopped. Independent review found one Important Unicode-output issue, fixed RED→GREEN; three historical CLI usability/demo minors are addressed in dev73. It is trusted process execution, not a sandbox or DelegatedRunner. [Evidence](../architecture/reviews/2026-10-11-cli-tools.md); full R01–R26 stays open.

Dev71 adds basic Temporal Host startup preflight before namespace RPCs or Client/start-task state: original Engine seconds contract, installed SDK parameter names, primitive/cross-field constraints and all-version build identities. Three Important review fixes preserve caller-code-free strict validation, SDK-valid zeros and nullable identity. Source4114 pass/329 configured skips, installed136 contracts and7 required service cases, minimal98 contracts/38 optional-SDK skips, actual70↔71 compatibility and242 identical modules pass. Owned Temporal is stopped. Rich SDK objects and rare numeric boundaries remain delegated; full R01–R26 stays open. See [dev71 evidence](../architecture/reviews/2026-10-11-temporal-startup-preflight.md).

Dev70 adds explicit multiversion TemporalProfileHost: all-profile preflight, original namespace/Scope/release queues, old Run/Session attachment, explicit default selection, shared actual-work drain and declarable PostgreSQL effect evidence. Original History/Registry/Coordinator retain authority. Final source4060 passed/328 configured skips, frozen original53 services plus Host9 (one offline case), installed62 same-group cases, core/installed contracts and actual69↔70 compatibility pass.241 modules match;4 Important fixes are verified and owned services stopped. Evidence and the deferred startup-options Minor are recorded in [dev70 evidence](../architecture/reviews/2026-10-11-temporal-profile-host.md); full R01–R26/H1–H5/M1 remains open. No live-model or enterprise-quality claim.

Dev69 adds [Temporal Profile assembly](temporal-profiles.md): immutable explicit JSON/TOML catalogs, existing component factories and ten binding roles, async owned cleanup, original remote Session dataset initialization, and a managed Worker that retains actual model/tool/summary/write calls and original end notifications. No Local execution store or new History authority is introduced. Unprofiled manifests/payloads remain compatible. The installed example is offline-first; network execution is explicit. Actual service acceptance covers declared compositions, two Turns/restart/replay, selected Redis/PostgreSQL Sessions and shutdown windows. Five Important review findings are fixed. Final source4021 passed/320 configured skips, source and installed53 actual services each, installed81 new contracts and240 overlapping original contracts/5 skips,235 identical modules, core-only and actual68↔69 compatibility pass. See [dev69 acceptance](../architecture/reviews/2026-10-11-temporal-profile-assembly.md). Owned services are stopped; no live model, push or public release. Full R04/H1/H3/H5/M1 remains open.

Dev68 adds opt-in [Temporal Context read lifetime](temporal-context-read-lifetime.md):
ordinary Context and managed plan/read/verify/finalize handlers, tracked threads
and original end acknowledgements remain owned through timeout/cancellation.
Original Native History requires response and actual end evidence before model
progression or Session release; Parent/Coordinator reuse that quiescence.
Default-off releases and native save-v1 remain unchanged; explicit new reads use
binding protocol2 and old dev67 refuses them before I/O. Actual service cases
cover seven compositions, real Redis/PostgreSQL, mixed automatic memory/RAG/
summary/artifacts and independent Worker exit/restart. Final source3940 passed/306 configured skips (498.96s), installed241 contracts
and39 actual services (303.78s),231 identical modules and core-only paths pass.
Three independently reproduced admission/redispatch races are fixed RED→GREEN.
[Acceptance](../architecture/reviews/2026-10-11-temporal-context-read-lifetime.md)
records the actual old/new compatibility and lifecycle boundaries; this subset
does not complete H3, M1 or R01–R26.
Full Temporal configuration/routing, environment roles, cross-authority leases, live quality
and external adoption remain open.

Dev67 explicitly registers [Temporal Session trees](temporal-session-trees.md): original
Graph/Team/Plan/DAG/nested Parent root reads and aggregate saves, stable private member
addresses, protected source-once snapshots, independent namespace/source selectors and
original History completion gates. Root read/write handlers remain owned through timeout
and cancellation until exact end evidence; root reads are single-attempt. Defaults and
native save-v1 retain their release identity. Final build/full/installed/service gates are
recorded in [dev67 acceptance](../architecture/reviews/2026-10-11-temporal-session-trees.md);
Final source3801 passed/267 configured skips (508.59s), installed198 contracts/41 actual services (455.60s), core-only and226 identical modules pass. This subset does not close full H1/H2/H3/M1 or R01–R26. Temporal Profile assembly,
cross-authority leases, other environment roles, broader read-lifetime governance, live
quality and external adoption remain open.

Dev66 adds explicit [Temporal native/sequence persistent Session saves](temporal-session-data-writes.md): original History intents, admitted CAS writes, exact received receipts, independent adoption/completion, actual-handler ownership and dataset/namespace Session identity. Plain/managed Context use external data once; sequential persistent members must share the same source/namespace, and idle rebind cannot migrate data.
Final source3686 passed/226 configured skips (519.28s); installed150 contracts and25 actual services; source actual65, core-only default/read/save and actual65↔66 defaults/approval/History compatibility pass. Four independent P2 findings plus pre-admission timeout fencing are fixed. Full H1/H2/H3/M1 and R01–R26 remain open; advanced root/member external saves still refuse. Task-owned services have stopped; final221-module/package/docs checks are recorded separately; see [dev66 evidence](../architecture/reviews/2026-10-11-temporal-session-data-writes.md).

dev65 adds opt-in [Temporal scoped Session data reads](temporal-session-data-reads.md): stateless native/sequence host/per-Agent selectors, fixed original resources and bounded Context evidence accepted by original History. Ordinary/managed Context preserve the original snapshot after data changes and Worker restart. PostgreSQL initialize pins actual table schema routing; bridge source methods and nested model Planner preflight are checked.
No external answer saving or cross-Run Conversation is delivered. Selected external data with History Sessions or advanced parents refuses before admission. Full SessionKey/write/completion gates, H1/H2/H3/M1 and R01–R26 remain open. Final3642 passed/204 configured skips, installed140 + separate39 overlapping contracts, actual installed7 plus final source/wheel Temporal4 each, 217 identical modules, core-only/guide and actual64↔65 compatibility pass. See [dev65 evidence](../architecture/reviews/2026-10-11-temporal-session-data-reads.md).

dev64 adds [default exact Session receipts](session-receipts.md): memory/SQLite sync inspection,
thread-safe sync bridge validation and Local independent data recovery. SQLite uses its
existing atomic projection with an additive message lookup index; original data format and
colocated Local route remain. The [Temporal external Session contract](../architecture/specs/temporal-session-data-contract.md)
fixes original Run/Parent completion responsibility, but that managed I/O chain is not delivered.
Final3613 passed/198 skipped,146 installed contracts,214 identical modules, core-only
and actual dev63↔64 default/data/original Session receipt compatibility pass; new independent
default Session refuses old backends before dispatch. See [dev64 evidence](../architecture/reviews/2026-10-11-default-session-receipts.md).
Full H1/H2/H3/M1 and cross-authority Session leases remain open.

dev63 adds [Temporal DecisionPolicy](temporal-decision-policy.md): replaceable pure request/proposal policies and original History evidence acceptance.
Dev62 adds [Temporal completion verification](temporal-completion-verification.md): pure host/per-Agent rules, current-node committed receipts, durable retry/accept and memory gates.
Dev61 adds [Temporal Agent limits](temporal-agent-limits.md): replaceable synchronous policy
proposals, mandatory host/Spec intersection, per-node History adoption, capped Context/model
requests and atomic refusal of over-limit tool batches. Defaults without limits remain unchanged.
See [dev63 acceptance](../architecture/reviews/2026-10-11-temporal-decision-policy.md) and [dev62 acceptance](../architecture/reviews/2026-10-11-temporal-completion-verification.md) and [dev61 limits evidence](../architecture/reviews/2026-10-11-temporal-agent-limits.md); full H1/H3/M1 remain open.

dev60 adds opt-in [Temporal History Sessions](temporal-sessions.md): actual Namespace UUID
identities, durable serial Turns/busy receipts, original Run start intents and idle CAS rebind.
Native/sequence/Graph/Team/Dynamic/nested definitions reuse original Run/Parent Histories;
root and actual descendants must confirm quiescence before conversation commit/release.
Conversation, Knowledge and Facts evidence remain independent. Shared async Session APIs
freeze inputs before awaits, own in-flight RPC completion and detach without business cancel.
Default-off releases remain compatible. External SessionStore routing, other binding roles,
FIFO/input continuation, retention/Continue-As-New and full H2/H3/M1 remain open.
Final3466 passed/146 configured-service skips; actual source Temporal27 plus final entry3,
installed Session15/contracts103,207 identical modules, core-only and actual59↔60 default
compatibility pass. Four reproduced P2 findings are fixed; task-owned services stopped.
Verification is recorded separately in [dev60 acceptance](../architecture/reviews/2026-10-11-temporal-sessions.md).

dev54 adds opt-in [TextTokenizer, token chunks and output reserve](tokenization.md),
dependency-free UTF-8 byte units and optional owned tiktoken vocabulary. Budgeted/managed
factories support explicit byte counters/reserves; custom model tokenizers use SDK injection.
Original character defaults and receipt replay remain. Canonical text tokens exclude vendor
framing/tool schemas and do not prove billing, long-context quality or complete H3.
[Final dev54 evidence](../architecture/reviews/2026-10-10-tokenization.md):
3296 passed/92 configured-service skips,127 installed contracts,192 identical modules,
core-only optional refusal and actual cl100k_base Unicode checks.

dev55 adds opt-in [FileArtifactStore](file-artifacts.md), core-only POSIX JSON payloads
with a bounded SQLite receipt index and explicit JSON/TOML factories. Scope, TTL,
read limits, original references and managed offload protocols remain. Process-loss
publication/replay and composite Local recovery are tested; final evidence is
recorded in [dev55 acceptance](../architecture/reviews/2026-10-11-file-artifacts.md).
Final3343 passed/98 configured-service skips,117 installed contracts and193 identical modules.
Separately, installed file6 and original SQLite6 actual Temporal Worker/History contracts pass
on the verified official CLI1.9.1/Server1.32.0 with SDK1.34.0, including restart and cancellation.
This is same-host resource recovery, not distributed filesystem consistency.
Retention/GC, global disk quota, S3 and distributed filesystem consistency remain open.

dev56 adds explicit [complete-corpus Facts indexing](fact-indexing.md): bounded
memory/SQLite/Redis enumeration, fixed source snapshots, replaceable CAS metadata,
accepted embedding receipts, idempotent vector writes and complete activation.
Default SQLite/Hash assembly remains offline; HTTP embedding and Qdrant are explicit.
Recall hydrates original facts and checks publication/version/value/TTL. Writes require
explicit rebuild. Temporal Facts bindings, repair/GC and actual
semantic quality remain separate gates. Final3397 passed/98 configured skips,74 installed contracts,197 identical modules,
core-only offline indexing and dev55↔56 original receipt compatibility are recorded in
[dev56 acceptance](../architecture/reviews/2026-10-11-fact-indexing.md).

dev57 adds native PostgreSQL fact_snapshot/scan_facts, persistent scoped dataset epochs,
existing writer locks and named server cursors with capped key/value byte projections.
Explicit initialize adds the epoch table while preserving old session/fact interfaces.
Actual isolated PostgreSQL16.15 verifies complete-corpus indexing, reconnect, async
assembly, Agent references, owned close and four process-loss windows. See
[PostgreSQL acceptance](../architecture/reviews/2026-10-11-postgres-fact-indexing.md).
Final3436 passed/68 service-dependent skips,73 installed contracts,198 identical modules,
core-only default indexing, original receipt/starter compatibility and actual dev56↔57
PostgreSQL schema/data/generation upgrade pass. Remote Qdrant composition and Temporal
Facts bindings still require separate evidence.

dev58 adds opt-in [Temporal Facts bindings and bounded recall](temporal-facts.md),
scoped namespace selection, fixed source/client/method identity and replaceable pure
recall planner. Original Context Activities and History accept independent Knowledge,
Facts and recall evidence; managed finalize preserves the original classification.
Default-off releases remain unchanged. Temporal Knowledge selectors, shared Sessions,
other roles and semantic quality remain open; [dev58 acceptance](../architecture/reviews/2026-10-11-temporal-facts.md)
records each verification gate separately. Final3417 passed/119 configured-service skips;
source Temporal12 + original16, installed Temporal12 + contracts94 and200 identical modules pass.

dev59 adds [Temporal scoped Knowledge bindings](temporal-knowledge-bindings.md): host namespace
allowlists, actual selected namespace releases, native composition/method/database/client
pins and pure original-source validation. Global/raw releases remain compatible; scoped
bindings opt into knowledge_protocol=1 in temporal-3. Facts and Knowledge evidence remain
separate; the last source await precedes History dispatch admission. Shared Sessions,
other roles, automatic Temporal Profile assembly and semantic quality remain open.
Final3436 passed/131 configured skips; source Temporal12 + existing28, installed Temporal12,
installed contracts63, core-only and actual dev58↔59 default/raw release compatibility pass.
202 Python modules are identical across source/wheel/sdist/install. Actual PostgreSQL16.15
Activity/source probes pass; no live model quality or cross-machine deployment claim.
Evidence is recorded in [dev59 acceptance](../architecture/reviews/2026-10-11-temporal-knowledge.md).

Target architecture update: [AgentHarness](../architecture/viewpoints/harness-runtime.md)
defines broad Harness/Core roles, per-Agent bindings, Agent/Session facade, managed
context/memory/RAG stages and H1–H5 delivery gates. The [binding contract](../architecture/specs/agent-capability-binding-contract.md)
has delivered [H1a and Local H1b subsets](agent-bindings.md): native Agent/sequence,
Graph, Team, Dynamic and nested members share six scoped selectable roles, stable
declaration paths, fixed parent/child releases and JSON/TOML v2 assembly.
[H1a verification/review](../architecture/reviews/2026-10-08-agent-capability-bindings.md)
records 1902 passing tests, 42 service-dependent skips and installed old/new compatibility.
dev26 [Local H1b verification](../architecture/reviews/2026-10-08-composite-agent-bindings.md)
records 1959 passed/42 configured-service skips and 117 installed contracts;
actual dev25 upgrades retain native/H1a releases and old wheels refuse new composites.
dev27 delivers [Local Session H1c](session-bindings.md): selected sync/async backends,
host-authorized namespaces and durable actual-address admission.
[H1c verification/review](../architecture/reviews/2026-10-08-session-capability-bindings.md)
records 1998 passed/43 service-dependent skips, 155 installed binding contracts,
actual Redis1/PGskip1 and dev26-to-dev27 approval recovery with original releases.
dev28 delivers [Local scoped data H1d](data-bindings.md): Facts/Knowledge host namespace
views, source provenance, actual delegated-client guards and bounded continuation.
[H1d review](../architecture/reviews/2026-10-08-scoped-data-bindings.md) records
2055 passed/44 service skips, 211 installed contracts, actual Redis1/PGskip1 and
dev27 upgrade of nine original approvals. [Fixed DeepSeek trial](live-model-quality-dev28.md)
records business10/16 (repair0/6) and scoped extraction4/4; valid final JSON did
not prove actual repair completion. dev29 adds opt-in pure [Agent completion verification](completion-verification.md), durable receipt correspondence and bounded feedback. Managed async/model verification, PlanVerifier business defaults and broad quality remain open.
[H1e verification/review](../architecture/reviews/2026-10-08-completion-verification.md) records final2113 passed/44 configured-service skips, 250 installed contracts and ten dev28 original approvals recovered. [Fixed single-run DeepSeek trial](live-model-quality-dev29.md) passes eight synthetic business tasks with 17 calls; this does not establish broad task quality or framework parity.
dev30 adds [Local numeric limits H1f](agent-limits.md): pure replaceable policy, mandatory host intersection, pinned per-Agent decision/context/tool-Action caps and atomic over-limit batch refusal. No distributed capacity or currency ceiling is implied.
dev31 delivers [H2a Local stateless Agent API](agent-api.md): immutable AgentHarness,
Runtime-owned Local drive tasks, Agent/AgentRun/RunRef, observation-only wait,
nested control ownership/waking and retryable drain/cancel closing. Full H1/H2
are not complete; remote Sessions, Temporal bindings and automatic
managed stages remain partial. SDK is dev63. The [Facade/Session target contract](../architecture/specs/agent-facade-session-contract.md)
now specifies observation-only waiting, durable busy refusal, Session binding revisions,
and ownership-aware closing. H2a implements the declared Local stateless subset;
remaining shared routing and backend requirements are not changes to legacy
Local/Temporal drive semantics.
[H2a verification/review](../architecture/reviews/2026-10-09-local-agent-facade.md) records final2235 passed/44 configured-service skips, 176 installed contracts, ten actual old/new wheel approval scenarios in both directions, and two reproduced host/lifecycle findings fixed in one TDD pass. No paid-model or full Harness quality claim follows.

dev32 adds [H2b1 colocated Local Sessions](session-api.md): durable native/sequence Turn admission, canonical routes, original binding revisions, stable busy/mismatch receipts and idle CAS rebind. Required result-save/actual-handler/unknown-effect gates retain occupancy. First valid Session atomically activates schema2; older SDKs refuse it. Complete H2b, remote/composite Sessions and Temporal facade remain pending. [H2b1 verification/review](../architecture/reviews/2026-10-09-local-session-turns.md) records final2280 passed/44 configured-service skips, 159 installed contracts, nine schema1 old/new wheel approval scenarios in each direction and actual schema2 refusal/recovery. Three independently reproduced boundary findings were fixed in one TDD pass.

dev33 adds [H2c1 Temporal native/sequence Agent entry](temporal-agent-api.md): shared Agent/AgentRun API and portable RunRef/WaitResult, async reference/attachment, operation-pinned Client/namespace/Scope/release, managed outbound RPC ownership and detach-only client closing. Own observation timers return the last validated snapshot with actual observed_at; query errors propagate. Existing History/commands and Local schema1/schema2 are unchanged. [H2c1 verification/review](../architecture/reviews/2026-10-09-temporal-agent-facade.md) records final2317 passed/47 configured-service skips, 206 installed contracts, actual persisted Service/Worker/History three source and three installed probes, and eleven old/new Local approval cases in each direction. Advanced compositions/bindings/shared Sessions and full H2 remain pending.

dev34 adds H2c2 [registered composite Agent entry](temporal-agent-api.md): Graph/Team/Dynamic/nested definitions, original parent references, bounded pinned discovery of actual child controls and parent outcome_unknown observations. Terminal native approval projection omits unusable controls while preserving action/receipt ledgers. Temporal bindings/shared Sessions and full H2 remain pending. [H2c2 verification/review](../architecture/reviews/2026-10-09-temporal-composite-agent-facade.md) records final2352 passed/56 skipped,231 installed contracts,12 source+12 installed actual-Service probes and actual dev33 original History/Local schema1/schema2 recovery. A compatible v2 patch marker fixes new-parent bookkeeping comparison; legacy histories retain v1.

dev35 adds H2b2 [colocated composite Sessions](session-api.md): Graph/parallel, Team, Dynamic linear-plan/DAG and nested Turns, original member bindings, atomic final conversation/success and bounded descendant occupancy. Successful open/rebind enables monotonic schema3; dev34 readers refuse it before execution. Remote/shared Temporal Sessions, composite root namespaces and full H2 remain pending. [H2b2 evidence](../architecture/reviews/2026-10-09-local-composite-session-turns.md) records actual old/new wheel recovery and final gates.

dev36 adds H2b3 [authorized composite root namespaces](session-api.md): separate borrowed host resource, allowlisted per-open selection, independent original Run admission evidence and canonical parent/member IDs. Configured roots opt into schema4; actual dev35 refuses4. SDK/factory assembly is delivered; Profile declaration, remote Sessions and complete H2 remain pending. [H2b3 review/evidence](../architecture/reviews/2026-10-09-composite-conversation-namespaces.md) records final gates.

dev37 adds root conversation declarations through JSON/TOML Profile components and sync/async Runtime assembly, plus the installed `sessions` starter with original Profile/Turn reconnection and pure status. Previous20 starter trees and absent-component Profile identities remain compatible. [dev37 evidence](../architecture/reviews/2026-10-09-configured-conversation-entry.md) records final2457/56 source,212 installed contracts and44 bidirectional wheel cases. Remote Sessions, Temporal bindings and full H2 remain pending.

The [current remaining-work checklist](remaining-work.md) maps each layer to delivered
subsets, missing capabilities and outstanding acceptance, with H1–H5 priorities.

2026-10-13. Accepted product baseline: dev93; individual accepted subsets and evidence are recorded above. This is the M1 core preview. Full M1 acceptance, enterprise architecture and a production-ready v0.1 release have not been completed. Public interfaces remain experimental. Static Graph Workflow, managed Tool/MCP nodes, bounded parallel execution and explicit async component lifecycle are available. dev14 adds real Redis/PostgreSQL/Qdrant data adapters, bounded plan/execute/verify/replan and local child-Run teams. dev15 adds dynamic DAG/plan patches, nested local workflows, MQ/A2A handoff and an independently History-owned Temporal subset. dev16 adds native async A2A controls, shared PostgreSQL Inbox/Outbox and a packaged local HTTP service with tracked shutdown. dev17 adds History-owned distributed Graph/Team/Dynamic/nesting, fixed RAG snapshots with shared PG/Qdrant ports, per-Run execution policy/timers and an installed Temporal starter; business evaluation remains not_run without model configuration. dev18 adds replaceable UTF-8 parsing/chunking and atomic memory/SQLite/PostgreSQL ingestion receipts plus a user-document starter. dev19 adds explicit float HTTP embeddings, replaceable RRF/rerank and authority-validated parallel Hybrid retrieval with additive assembly and an offline user-document starter. dev20 adds opt-in pure context measurement/complete-group selection/excerpts, actual Harness-request measurement and scoped memory/SQLite artifacts with a seventeenth offline starter. dev21 adds opt-in sourced memory consolidation, managed model summaries, pure custom Temporal context and a bounded real DeepSeek trial. dev22 adds stateless native Responses/JSON/SSE, typed Python tools and an offline-first compatibility suite. dev47 adds explicit semantic/recall/Plan/Team combinations through existing authorities; see [H3 guide](h3-intelligent-combinations.md). Default native local-4/request/Manifest identities and original flat parents remain compatible; new nested/DAG definitions require dev15. Evidence is recorded in [implementation progress](implementation-progress.md).

| Capability | Delivered in this increment | Boundary / next work |
| --- | --- | --- |
| Native Agent | Model/tool loop, fixed AgentSpec, decision limit, common final-output validation and nullable output Schema | One complete response per Action, optionally collected via SSE; provider does not run tools |
| Per-Agent bindings | Dev83 Local/Temporal native, sequence, Graph, Team, dynamic and nested Agents support thirteen selectable roles: provider/decision_policy/context/session/facts/knowledge/tool_set/verifier/limits/stage_policy/workspace/skills/sandbox; fixed paths/releases and host-approved resource selectors. Dev84 adds independent artifacts ref/disabled/inherit and namespace selection through pure managed Context derivation | Dev84 artifact composition, crash/cancellation, old83 Worker refusal, review, full-source, fresh-install and package gates passed; see its batch acceptance record. Only joint Temporal binding5/artifacts1 advertises the new role/selector; legacy releases keep original capabilities. Other selectors, remote governance and full H1/H2 remain open |
| H3 starting combinations | Seven version-1 Profiles; new explicit semantic-knowledge, memory-recall, Plan/Team plus recommended_harness on original Specs/AgentHarness; replaceable pure ReferenceSelector, saved source-bound selection | Semantic profile needs explicit HTTP Embedding/async assembly/indexing; overlap ranks bounded candidates only; default instruction-only members and Schema/CompleteVerifier do not prove task quality. Old three presets retain identity |
| Execution components | Public pure synchronous Harness with NativeHarness default; async ToolExecutor with PythonToolExecutor default; pinned identities and detached/immutable dispatch values | Engine retains governance and authority; arbitrary user Python remains trusted. Explicit native Docker Sandbox is available; external Coding Runner remains pending |
| Runtime assembly | Immutable versioned profiles/catalog, explicit factory registry, strict JSON/TOML, default local builder; original-profile routing, receipt replay before current configuration | Explicit SDK abuild/register_async/owned async cleanup with loop affinity; synchronous ProfiledEngine/CLI do not route async factories. One local instance at a time; original declarations/code/data must remain available; no plugin auto-discovery, hot watcher, code archive or migration |
| Workflow | Legacy sequence and static serial/bounded parallel Agent/Transform/Tool graph; nested sequence/graph/team/dynamic members via managed child Runs | General loops, streaming dataflow and arbitrary async nodes pending; static graph nodes retain existing types |
| Dynamic planning | Flat PlanProposal compatibility plus DAGProposal/DAGNode, default rule/model DAG planners, dependencies/bindings/conditions, durable revisions and CAS pending-node patches; capabilities/limits in PlanningRequest | Finite batch execution; selected durable needs_input/send_input resumes the original planner revision, with owner-only clarifications. More verification domains and broader repeated live quality remain pending |
| Multi-Agent | Sequential/Router/Supervisor, recursive managed definition trees, pinned ancestor releases, isolated Sessions and recursive child-cap settlement; failure/cancel propagation and joined diagnostics | Local defaults plus opt-in Temporal child Workflows; remote communication uses explicit ToolSource/handoff; global capacity and enterprise identities pending |
| Local execution | ExecutionStore v1, CoordinatorLease, SQLite reference authority, asyncio, one POSIX coordinator with fixed path/inode checks, hard-link rejection and real worker-thread ownership | Store/lease ports require atomicity and ownership conformance; no multi-process pool or distributed scheduler |
| Shared Agent entry | Local H2a/H2b1/H2b2 plus Temporal H2c1 native/sequence, H2c2 registered advanced compositions and H2c3 History Session Turns; common Agent/Session/AgentRun/RunRef/WaitResult and async attachment; independently managed Local drives or remote RPCs | Temporal temporal-3 facade accepts the registered binding roles including external Session sources; opt-in History and native/sequence or explicit composite external Turns delivered; other environment roles, direct Tool/Transform graph nodes and non-detach close refused; full H2 and semantic H3 quality pending |
| Message handoff | Structural MessageBus, Inbox/AsyncInbox, Outbox/AsyncOutbox, CommandAdapter; in-memory/SQLite defaults, real Redis Streams dedup/claim/ack; shared PostgreSQL Inbox/Outbox, durable completion before ack | Capacity rejection preserves pending/dedup evidence; retention/compaction, additional broker adapters and failover certification pending |
| A2A | Explicit ASGI native or async-authority service, TaskControlBridge, local owned lifecycle/starter, trusted host authentication, Card and JSON-RPC0.3 polling subset; replaceable A2AClientPort and approval/queryable-write ToolSource | Text/data only; explicit user-input extension discovers original ownerTaskId and resumes the original Task; no SSE/push/gRPC/files or general Task continuation; receipt extension required for message lookup; Temporal composition supports native async controls; definition validation follows the selected execution backend/release |
| Distributed execution | TemporalEngine async facade, independent Workflow/History command/action/credit authority, registered workers, EffectJournal port and PostgreSQL evidence default; actual two-worker kills/replay | Native Agent/sequence default; explicit orchestration_release adds Agent-node Graph/Team/Dynamic/nesting and registered RAG. temporal-3 adds scoped catalog provider/context/knowledge/tool_set/stage_policy/facts, bounded Facts namespace recall and History-managed automatic grounded memory; opt-in History Session Turns delivered; explicit native/sequence saves and Session-tree root/private data delivered; direct Tool/Transform graph nodes, custom Harness and other environment role selection refused; retention/Continue-As-New/global quotas/deployment versions pending |
| Commands | Scoped idempotent submit/approve/reject/cancel/reconcile and local and Temporal DAG patch; original request separate from first resolved release; durable Inbox/Outbox transport receipts | Local commands are sync, Temporal controls async; explicit idempotent send_input delivered; legacy digest migration, auth continuation and local deadlines pending |
| Agent completion | Mandatory Schema acceptance; opt-in pure CompletionVerifier, configurable committed tool receipt/result/argument rules, detached typed task input and durable accept/reject/bounded retry feedback; Local and Temporal per-Agent bindings; Local Profile factories | External Schema references never retrieve; async/model stages and plan-level business oracle remain pending; receipt correspondence does not establish arbitrary external truth |
| Recovery | Independent model response and executor observation receiving stages before DecisionCommit/ResultCommit; adopted decision reuse, stable Actions, unknown-write reconciliation; 10 receiver-window/cancellation regressions pass | Grouped M1 fault report remains; manual reconcile is one command/result transaction; no external exactly-once guarantee |
| Effects | Four declared categories; exact-key reconciler; same tool/args unresolved writes block resubmission | Reconciler returns confirmed result or unknown; richer not-executed/in-progress proof pending |
| Approvals | Persistent pending object, operation digest and explicit local-owner decision | Temporal History-based approval expiry delivered; local expiration, resource-level authorization and enterprise actors pending |
| Budget | Atomic integer execution credits, unknown holds and recursive parent child-cap escrow settled after terminal/quiescent descendant completion | Currency ceilings, global shared accounts and provider billing guarantees pending |
| Memory | Independent sync/async Session/facts ports; SQLite/in-memory and real Redis/PostgreSQL CAS/dedup/logical TTL; paged recall, Session high-water and current-fact validation; opt-in rule/model field selection with source-grounded append-only admission and replay | Semantic revision/retraction and atomic multi-fact admission pending. Legacy/full Session reads and some writes may materialize history; no export/migration/retention, Redis Cluster/failover or full server-version matrix |
| Knowledge / RAG | Scoped in-memory/SQLite/PostgreSQL document authority, CAS/TTL/deletion versions, replaceable text/Markdown parser, opt-in bounded HTML/DOCX body and optional text-PDF parsers and character/paragraph Chunker; atomic document/chunk/term/receipt ingestion, Chinese/English lexical retrieval and provenance validation | knowledge_committed receipt excludes vector readiness; explicit reindex; no advanced connectors, enterprise source ACL/catalog, background indexing or live answer-quality baseline; explicit HTTP Embedding protocol/hybrid/rerank delivered, online semantic compatibility still unverified |
| Vector retrieval | EmbeddingProvider/VectorIndex/VectorRetriever ports; local exact cosine and real Qdrant HTTP adapter; authoritative version/digest hydration; offline HashEmbeddingProvider | Hash embedding is a deterministic token baseline; no hosted semantic embedding default, pgvector, default semantic reranker or cross-service atomic index commit; embedding costs outside execution credits |
| Context | Local native/composite and Temporal managed summaries/reference excerpts/tool offloads with independent receiving/acceptance; replaceable ContextBuilder/MessageCounter/ContextBudgeter/ContextSummarizer, persisted actual snapshot/measurement, exact chars and explicit token estimate, complete tool groups and optional deterministic excerpts; pure RecallPlanner records actual queries; explicit managed model summaries with frozen consumers and registered Temporal custom context | Opt-in TextTokenizer/tiktoken and canonical output reserve delivered; actual model vocabularies, vendor framing, semantic-preservation quality and enterprise source authorization catalog pending |
| Artifacts | ArtifactReference and completed sync/async ports; memory/SQLite and POSIX file JSON stores with Scope, digest, read limits, TTL and namespace capacity; original managed automatic tool offload. Dev84 composes a borrowed selected resource with an independently selected compatible Context and owned declarations | Dev84 documented subset accepted; JSON only, one MiB upper bound. Remote defaults, binary transfer, retention/GC/cache, global disk quota, enterprise IAM and cross-Run/cross-host coordination remain separate work |
| Tools | Trusted functions/callable instances/bound methods/partial, detached descriptors, Schema, fixed manifest/code digest, strict None-return synchronous authorization, executor-owned receipt queries | Captured state belongs in explicit version/config; Async ToolSource/explicit host policy/atomic selected registration; default MCP stdio with tracked worker/process lifetime; typed keyword-function registration with Schema inference, host context injection and pre-authorization default resolution. HTTP/OAuth/persistent MCP, CLI/sandbox and resource leases pending |
| Models | Chat Completions, native Anthropic text/client tools, Gemini text/explicit functions, DeepSeek plain/explicit thinking, stateless Responses and dev91 explicit reasoning continuation; bounded JSON/Schema and complete SSE; original received/adopted histories | Text/client functions only; Responses reasoning subset accepted; required native IDs and supported text/client functions are documented. Live model/account compatibility, media, routing and quality remain open. Borrowed clients stay application-owned; no implicit retries or stored remote conversation |
| Events | Durable per-Run sequence, stable event ID, pagination; opt-in scoped sync/async pull subscriptions, cursor reconnect, SSE encoding and read-only CLI | Retention/compaction, HTTP/WebSocket live transport, model-token authority and OTel pending |
| Evaluation | Offline runtime fixtures, frozen20-case proposal evaluation and eight-case business-task executor; tool ordering/parameters/approval/stop/restart checks and error/usage/latency/private reports | Offline model_quality is null; dev21 small real trial records failures and follow-up scores; no full repeated final-config task/answer/citation baseline or equal-framework superiority result |
| Temporal probe | Independent Agent/sequence and explicit Graph/Team/Dynamic/nesting backends; RAG snapshots, scoped Updates, History replay and actual two-worker failure probes | Full M1 grouped fault/live quality/external onboarding gates remain; unsupported node types, cross-authority data coordination and deployment/remote-stop governance remain |
| External Runner | Not delivered | Codex isolated profile in v0.2; other adapters subject to individual conformance |
| CLI / first use | Twenty-one packaged starters including dag/nested/a2a/temporal/ingest/hybrid/context/memory/model-check/observable; child control hints and remote worker/client CLI; separate planning/business evaluation consoles | Model templates require explicit config; CLI/ProfiledEngine remain synchronous local authorities; local HTTP service owns shutdown; shared remote gateway lifetime remains host-owned |
| Enterprise | Limited protocol/adapter trials only | OIDC, resource ACL, production service/console, retention/migration, failover and operational restore acceptance remain roadmap |

## Immediate next increments

The [dev23 holistic review](../architecture/reviews/2026-10-08-agent-framework-alignment.md)
identified three concrete defects. dev24 fixes duplicate Temporal call IDs,
completed-response evidence loss and all-or-nothing default Session recall.
[Shared acceptance and recall](shared-model-context-contracts.md) documents the
common pure rules and recorded legacy History compatibility. dev25 delivers the
native Agent/sequence six-role H1a binding subset; dev26 extends it to Local
Graph/Team/Dynamic/nested members. dev27 delivers Local Session backends/namespace/address admission. dev28 delivers scoped Facts/Knowledge namespaces and provenance. Temporal delivers six binding roles with Facts/Knowledge namespace selectors; other resource selectors,
remaining Agent/Session APIs, advanced Temporal facade and recommended managed
memory/RAG combinations remain next work; these increments do not complete
AgentScope parity. The [remaining-work audit](remaining-work.md) separates these
gaps from components already delivered.

The [M1 acceptance protocol](m1-acceptance.md) defines real-model tasks, a LangGraph comparison, external developer onboarding and independent Temporal authority. Task fixtures are a specification, not a benchmark. The [getting started](getting-started.md), [recall/RAG](recall-and-rag.md), [execution components](execution-components.md), [recovery](recovery-guide.md), [API](api-reference.md) and [release](releasing.md) guides cover the preview.

The [runtime assembly guide](runtime-assembly.md) documents profile compatibility, explicit factories and public ports. The [static Workflow guide](static-workflows.md) covers graphs; [orchestration](orchestration.md) covers delivered local teams/planning; [remote data](remote-data.md) covers real Redis/PG/Qdrant adapters. The [model guide](model-adapters.md) separates protocols from online evidence. Temporal registered RAG and execution limits are covered by [distributed composition](temporal-composition.md). Global/tenant capacity, streaming dataflow/live event transport, model routing/multimodal, persistent/HTTP MCP and broader distributed orchestration remain separate deliverables.

The [async handoff guide](async-handoff.md) covers native async A2A, shared PostgreSQL receipts and the default local service.

The [general framework capability plan](../architecture/viewpoints/framework-capabilities.md) records the full target. G1 static graphs and parts of G2 Tool/MCP/parallel are delivered. dev14 delivers G3's bounded local planning/team kernel and G4's first real remote adapters; real-model G3 acceptance and G4's full parsing/embedding/context/memory pipeline remain. dev15 delivers G3 DAG/nesting and the first independently History-owned Agent/sequence execution subset; G5 streams/Runners and broader G6 enterprise services follow separately. SDK increments do not close remaining M1 gates by themselves.

1. Extend the verified dev6 component/receiver regressions into grouped M1 fault reports. Both local receiver windows now have real process/cancellation evidence; migrations and complete command outcomes remain.
2. Complete pending input/local deadline/local approval expiry, explicit unknown model retry policy and stronger resource lifecycle handling.
3. Validate real model task completion/tool choice/stopping and context retention against a fixed scenario set; retain the offline regression suite separately.
4. Extend the delivered Recall/Session indexes to efficient final append, indexed Run/unknown-effect queries and capacity limits separate from budgets. Cancelled but still active calls must retain capacity until completion.
5. Extend the delivered independently History-owned Temporal subset using the same approval/cancel/unknown-effect contracts; retain explicit refusal of unsupported orchestration and require actual service tests for each new capability.
6. Deliver the general SDK increments against the existing approval/budget/recovery contracts, with starters and adapter conformance per capability. Add the first external Runner and broaden the delivered Temporal subset through their own authority/resource gates; keep M1 acceptance and feature support distinct.

## Interpretation of guarantees

Scope is provided by the trusted host, not authenticated by an enterprise identity service. Python handlers can access the host environment and must be trusted. Provider/tool version and explicit configuration identity belong to the integrator; changing hidden handler dependencies without updating the manifest is outside this preview's compatibility guarantee.

Unknown business effects remain recorded even if cancellation/other failure ends the Run. A different Run ID is not a safe recovery mechanism. The unresolved-write guard compares tool name and normalized JSON arguments within the owner scope; resource aliases or equivalent arguments require future business identity normalization and can already be constrained by host policy.

File-backed coordinator locking currently supports Linux/macOS. The original context limit counts JSON characters; an opt-in counter adds a message budget, whose UTF-8 token estimate is not exact model usage. The budget limits synthetic execution credits, not actual currency. The demo is deterministic scripted execution, not an AI intelligence benchmark.

## Review disposition

The initial review fixed crash/cancel effect loss, scheduled cancellation overrides and empty/refused/incomplete model response success. The second review verified the complete implementation and extension paths, fixed late result/cancellation races, pinned historical settlements, mutable configuration and backend identity, and introduced storage/lease/context/async memory ports. Custom SDK profiles are now resumable through the CLI factory. See the [review report](../architecture/reviews/2026-10-05-runtime-extensibility.md) and [extension guide](extending.md) for evidence, ownership, capability limits and the remaining architectural work.

The third review reproduced seven gaps left by the 141-test baseline: unsafe database aliases, ignored async authorization, configuration-dependent submit identity, empty custom-provider decisions, post-append backend changes, retained completed tasks/locks, and invalid expiry values. dev3 closes those boundaries and adds regressions, including encoded empty text and generator authorization. See the [reliability disposition and gates](../architecture/reviews/2026-10-05-reliability-boundaries.md). The extracted final-output validator is a first pure boundary, not a completed Harness or ToolExecutor implementation.

The fourth review reproduced context-manager policy bypasses, cancelled Tasks hiding running executor threads, and Store close failures releasing ownership too early. dev4 enforces the sole None-return authorization contract, tracks actual framework-managed tool/reconciler/memory threads independently of Tasks, and keeps failed-close Engines quiesced under their lease. See the [authorization/shutdown disposition](../architecture/reviews/2026-10-05-authorization-shutdown.md). This lifecycle work does not implement capacity limits, sandbox termination, separate receipt persistence or Temporal authority.

dev6 adds public Harness/ToolExecutor boundaries and separates durable receiving from adoption. A saved response is proposed/adopted without repeating the Provider call; a saved tool observation is committed without repeating the handler/query. Received evidence may settle after cancellation, while proposals/follow-up scheduling and terminal reopening remain forbidden. Model credits settle on receiving the complete response, tool credits on ResultCommit; missing usage remains unknown. Manual owner reconcile uses its existing atomic command/result transaction. The 10 real-process/cancellation receiver tests pass; see [execution components](execution-components.md). This closes these local implementation windows without completing grouped M1 reporting, live-model, Temporal or external-adoption gates.

Independent dev6 review additionally fixed actual Provider source changes hidden by registry replacement, pre-call refusals incorrectly becoming unknown effects, and rejected retries obscuring earlier unknown attempts. Undispatched attempts release only their own reservations; historical unknown effects remain blocked/reconcilable and settlement targets the real dispatched attempt. The [review disposition](../architecture/reviews/2026-10-06-execution-components.md) records evidence and compatibility.

dev7 adds bounded Recall and local RAG. Independent review found and fixed facts changing while knowledge awaits and sources expiring during later asynchronous validation. New/unknown model dispatch reuses the original references and snapshot, validates current facts/knowledge, and preserves historical unknown reservations if refused. Already-received responses are adopted without new source reads or Provider calls. Validation is conservative over all retrieved candidates, and multiple authorities do not provide a cross-backend atomic snapshot.

dev8 adds public structural ports and versioned assembly. Independent review fixed invalid-return cleanup, retained close retry, control receipt replay during another profile's execution and optional diagnostics. Default SQLite reads enforce the original command Scope/payload before returning receipts; changing defaults or losing an old profile does not prevent replay. Installed-wheel history and resource ownership evidence are recorded in the [review](../architecture/reviews/2026-10-06-runtime-assembly.md).

dev9 adds implemented model protocols and complete SSE collection. Independent review fixed empty JSON deltas, error-frame handling, malformed response normalization and lossy native/opaque history. Shared preflight and response capabilities cannot authorize tools; the existing Engine adoption/effect protocol remains authoritative. Default identity/installed dev8 compatibility, fixture coverage and unavailable online evidence are recorded in the [model review](../architecture/reviews/2026-10-06-model-adapters.md).

Monetary budgets, enterprise authorization, sandbox isolation, full Temporal feature parity and live-model quality still require implementation and validation. dev8 retains default dev6/dev7 local-4 compatibility, adding identities only for explicitly enabled Recall/Knowledge/planner/profile. Catalog routing resolves retained original declarations and adapters; it does not migrate Runs. dev3–dev5 local-3 continuation requires the original runtime. SQLite Schema v1 and dev3 caller request digests remain unchanged; old receipts do not grant new-kernel continuation. dev1/dev2 submit replay needs the original version. Automatic Run/command migration is unsupported.

The [managed tools guide](managed-tools.md) distinguishes borrowed source/transport lifetimes, one-shot POSIX process ownership, explicit host effects, reserved idempotency fields and Tool plan v2. Existing v1 plans retain their representation; no automatic migration or general sandbox is provided.

The [parallel Workflow guide](parallel-workflows.md) documents v3 graph node isolation within one Run. Default serial identities remain unchanged. dev14 teams/plans separately use linked child Runs; both remain local execution.

The [framework parity review](../architecture/reviews/2026-10-06-framework-parity.md) records the dev12 comparison and contract repairs. Subsequent dev14 additions are recorded in the [data/orchestration review](../architecture/reviews/2026-10-07-data-orchestration.md); no cross-framework benchmark or superiority claim is established.

The [async assembly guide](async-assembly.md) documents dev13 lifecycle support and its SDK/CLI boundary; the original synchronous authority contracts and default identities remain.

The dev15 guides describe [DAG/nesting](dynamic-dag.md), [MQ/A2A](remote-handoff.md), [Temporal](temporal-execution.md) and [proposal evaluation](planning-evaluation.md). Runtime/transport evidence does not establish real model quality or full M1 acceptance.


The [dev16 handoff review](../architecture/reviews/2026-10-07-async-handoff.md) records async controls, shared PostgreSQL receipts, local service shutdown, initialization/callable drift fixes, actual services and installed compatibility evidence.

Dev17: [distributed composition](temporal-composition.md) and [business evaluation](business-evaluation.md) separate delivered execution behavior from enterprise and live-model quality acceptance. A queryable effect receipt does not prove a lost remote handler stopped; parent escrow remains held until actual quiescence is proven.

The [document ingestion guide](document-ingestion.md) describes dev18 D1: independently replaceable parsing/chunking, atomic knowledge receipts and the fifteenth installed starter. The [intelligent data pipeline design](../architecture/viewpoints/intelligent-data-pipeline.md) separates this delivery from pending D2 semantic/hybrid retrieval, D3 context/memory and D4 live quality.

Dev18 evidence: [document ingestion review](../architecture/reviews/2026-10-07-document-ingestion.md) records atomic knowledge receipts, fixed extension boundaries, actual services/process loss, compatible installed upgrades and one independent review. Semantic AI quality and remaining D2–D4 are separate gates.

Dev19 D2: [hybrid retrieval](hybrid-retrieval.md) documents explicit HTTP embeddings, rank/ID proposal ports, frozen and repeatedly source-validated candidates, structured branch lifetime, strict/degrade semantics and new factory names. Offline defaults remain; semantic/task quality and D3/D4 require their own evidence.

The [dev19 review](../architecture/reviews/2026-10-07-hybrid-retrieval.md) records the verified extension boundaries, four independent fixes, real transport/data combination and installed compatibility evidence.

Dev20 D3a: [context/artifacts](context-artifacts.md) and [review](../architecture/reviews/2026-10-07-context-artifacts.md) record pure context defaults, explicit large-result storage and compatible installed recovery. Automatic fact extraction, managed model summaries, semantic quality and enterprise/Temporal context acceptance remain pending.

Dev21: [managed memory](managed-memory.md), [Temporal context](temporal-custom-context.md) and [real trial](live-model-quality.md). Rule/model selectors, append-only sourced observations, durable managed summaries, pure frozen consumers and native JSON-object mode are available. Defaults retain original identities; automatic in-Run compression, semantic revision/retraction and full final-config model acceptance remain pending. Final evidence appears in [review](../architecture/reviews/2026-10-08-managed-memory.md).

Dev22 begins [ordered alignment](agentscope-alignment.md): [typed tools/native Responses](sdk-model-tools.md), native formatting/semantic SSE and bounded managed compatibility checks. The default no-provider console is not_run; offline fixtures and online protocol checks keep model_quality=null. Full AgentScope parity, sandbox/interactivity and online Responses compatibility remain pending.

Dev23 adds opt-in synchronous invocation middleware/default logging profiles and
scoped resumable committed-event observation. [Guide](middleware-and-events.md).
Default authority/releases remain; input continuation, Workspace/Sandbox and
AgentScope parity require subsequent increments.


dev38 adds H2b4a [remote native/sequence durable Turns](session-api.md#远程持久会话dev38h2b4a): existing Redis/PostgreSQL Session adapters expose bounded atomic exact-message receipts. The original Local authority journals required save intent, dispatch and receipt; lost acknowledgements pause and explicit recovery reuses adopted output without repeating business effects. Terminal recovery queries only and preserves cancelled/failed state. Stable remote SessionRef, independent admission metadata, conservative Scope/address refusal and transactional opt-in schema5 are delivered. Composite root remote data, cross-authority leases, Temporal shared Sessions, FIFO/input/deadline and full H2 remain pending. Actual-service and installed/upgrade evidence is recorded in the dev38 review; absent PostgreSQL configuration is not a delivery-quality claim.


dev39 delivers H2b4b [remote composite root conversations](session-api.md#远程复合根会话dev39h2b4b): Graph/parallel/direct-transform, Team, Dynamic Plan/DAG and nested Local Turns fix an explicit receipt-backed root resource independently of members. The original authority persists the final proposal, corresponding workflow/orchestration marker, required save and receipt; recovery completes the save directly without repeated planning, verification or child/business execution. Async Profile session-resource assembly reuses existing backend factories and owned lifecycle. Native↔composite idle rebind preserves one remote address. New capability atomically enables semantic schema6; old38 refuses it, previous schema1–5 remain supported. Cross-authority leases, Temporal binding/shared Sessions, FIFO/input/deadline, automatic Harness stages and complete H2 remain unfulfilled.


dev40 delivers the first Local H3a [managed rule-memory stage](managed-memory-stages.md) for native Agents and sequences. It is opt-in, separately host-granted, grounded and charged against Run execution credits. Original authority persists source/proposal/CAS intent/receipt evidence; unknown writes retain credits and explicit terminal recovery only inspects exact facts. Auxiliary failure does not replay business work or change terminal success. BindingCatalog supports stage_policy inherit/ref/disabled; JSON/TOML sourced-memory and sourced-memory-async reuse existing backend/client factories. Semantic7 activation is atomic with first enabled admission; dev39 readers refuse it. Default-off releases remain unchanged. Advanced/Temporal automatic stages, automatic model extraction, background jobs and semantic memory revision remain undelivered.


dev41 delivers H3b1 [managed context preparation](managed-context-stages.md) for opt-in Local native Agents/sequences. Pure per-Agent context bindings plan complete omitted same-Run groups; the original Engine owns rule/model summaries, fixed source/reference snapshots, independent intent/response/projection evidence and original-budget accounting. Invalid responses use a fixed fallback; dispatched unknown calls retain credits without retries. Terminal adoption is evidence-only, reference versions are revalidated before business disclosure, and real task/thread ownership is preserved. JSON/TOML managed-summary factories reuse host providers and pure counter/budgeter ports. Semantic8 activates on first enabled admission; old dev40 refuses8 while default identities/schemas1–7 remain compatible. Automatic Session/RAG compression, advanced/Temporal stages, model extraction and full H3 remain open; no new real-model quality claim.


dev42 adds H3a2 [automatic model-selected memory](managed-model-memory-stages.md), opt-in for Local native/sequence. Original memory_stages persist tool-free selection intent/response/keys and independent credits, before existing grounded CAS writes. Empty selection is valid; invalid/unknown selection writes nothing and never falls back to all fields. Actual provider/target/policy pinning, cancellation and evidence-only terminal settlement preserve the original authority. stage_policy and JSON/TOML sourced-memory(-async) factories reuse existing ports. Semantic9 first admission is atomic; dev41 refuses9; rule/default identities and schemas1–8 remain. Free-form/advanced/Temporal stages and full H3/quality remain open.

## dev43 H3 recommended data context

Versioned Local Basic / Local Knowledge / Managed Memory Profiles now compose the existing ports. Opt-in ManagedDataContext adds deterministic Session/knowledge/fact excerpts, existing managed history summaries, and artifact-backed large tool context projections with original-Run intent/read-back/receipt recovery. Default SQLite artifact factories are owned; SDK targets are borrowed; registry sync/async replacements are supported. Native Local Agents/sequences only, semantic Schema10; original default releases and schemas1–9 remain supported. Raw execution evidence is retained. Semantic reference summaries, remote artifact adapters/GC, advanced/Temporal automatic stages, final-config model quality and full H3 acceptance remain open. See [guide](recommended-harness.md).

## dev44 H3 composite and Temporal managed context

[Local advanced and Temporal context](composite-temporal-context.md) reuse the original pure policies, provider/artifact ports and execution authorities. Local graph/parallel/Team/dynamic/nested actual Agent decisions now support compression/offload; node frame journals and scoped summary reservations remain in the original Run. Optional semantic Schema11 rejects older readers. Temporal explicitly registers temporal-2 and separates pure plan, artifact read/write/verification, single-attempt summary response and final snapshot in History; source validation follows artifact awaits before model disclosure. Original temporal-1/default releases remain. Unknown summaries hold credits and remote uncertainty; late receipts settle after cancellation. Native/advanced real Worker kill/restart and parent/child History replay are tested. Automatic memory writes remain Local native/sequence only; Temporal per-Agent binding/shared Sessions, semantic reference quality, remote artifact defaults/GC, payload/storage governance and full H3 remain open.

Original History atomically admits managed external dispatch after preparatory reads; accepted cancellation blocks unadmitted calls. Previously granted operations retain late evidence. Unknown artifact execution remains nonquiescent after a receipt or successful later tool, holding the parent's child allowance. Knowledge adapters use the public references/validation contract; missing parallel execution frames fail against surviving original Action evidence.

## dev45 Local composite automatic memory

[Composite memory stages](composite-memory-stages.md) reuse rule/model-selected grounded policies and original CAS source/intent/receipt protocols for Local graph/parallel/Team/dynamic/nested actual Agents. Schema12 is optional and atomic; native/sequence identities and activation stay unchanged. Parallel workflow_node scopes source/fact keys, journals and budgets in original Run projections. Pure observations stay I/O-free; explicit closed-root resume recovers original terminal children under existing drive locks, never new selector/CAS dispatch, then settles parent escrow only with evidence. Versioned managed-memory defaults and per-Agent target bindings compose through existing sync/async factories. Temporal writes, semantic revision and full H3 quality remain pending.

## dev46 Temporal automatic memory and scoped Agent bindings

Explicit temporal-3 releases support versioned provider/context/knowledge/tool_set/stage_policy choices through original AgentDefinition/BoundDefinition paths, including actual native/sequence/graph/Team/dynamic/nested Agents. History owns source/selector/adoption/read/CAS/verification phases and independent credits. Exact fact inspection v1 required; no selector/CAS retry after dispatch. Explicit root drive recovers original uncertain child evidence without implicit query I/O. Found facts do not prove timed-out remote execution stopped; parent allowance remains held.

Legacy temporal-1/2 retained. Other Temporal binding roles, resource selectors, shared Sessions, semantic memory quality and full H3 remain pending. See [usage and boundaries](temporal-memory-bindings.md) and [acceptance](../architecture/reviews/2026-10-10-temporal-memory-bindings.md).

Dev47: [H3 intelligent combinations](h3-intelligent-combinations.md) add explicit semantic HTTP Hybrid, relevant bounded Facts/complete Session selection and Plan/Team starting definitions through original AgentHarness/authorities. Original version-1 presets/ManagedDataContext remain compatible. Final 2972 passed/92 optional-service skips; installed75, six dev46↔47 original approval/context/Manifest recoveries and eight process-exit windows. Independent review fixes seven reproduced failures; current capability contradictions corrected. No live quality or new remote-service certification. See [acceptance/rulings](../architecture/reviews/2026-10-10-h3-intelligent-combinations.md).

Dev48 adds [explicit HTTP reranking](http-reranking.md) through the existing AsyncReranker/Hybrid source authority, owned async factories and semantic Profile option. Old pure ranks/preset declarations remain. Preparation may repeat paid retrieval after interruption; rerank fees and live quality are not covered by execution credits.

Dev48 final: 3019 passed/92 optional-environment skips; installed103 contracts, 12 dev47↔48 default approval recoveries and two semantic identity-only recoveries with exact Profile/Context/Manifest equality. Old wheel rejects the new adapter before opening the database. Independent review's two real HTTPX transport/stream close failures reproduced RED→GREEN; no deferred minors. Wheel/sdist, Ruff/format/whitespace pass. See [acceptance and decisions](../architecture/reviews/2026-10-10-h3-http-reranking.md). No live rerank/answer-quality or renewed remote-service claim.

Dev49 adds [Query transform and semantic Facts recall](query-and-semantic-recall.md): replaceable sync/async transform, deterministic aliases, existing source validation, bounded original Facts semantic ranking, task-text planner and ordered reference selector. Explicit semantic-memory async Profile owns a separately versioned managed embedding lifetime; old seven Profiles/classes remain. Actual model-response process recovery, scoped Graph Facts and Temporal Query Knowledge replay have evidence. Semantic Facts is Local only; no corpus-wide index, live quality, fee ceiling or renewed remote-service certification.

Dev49 final: 3105 passed/92 optional-environment skips; installed86 new contracts, 12 dev48↔49 original approval recoveries and two semantic Knowledge identity-only recoveries preserve exact Profile/Context/fresh Manifest. All186 packaged Python modules match source. Three Important query-source expiry/resource/mutation findings reproduced RED→GREEN; no deferred minors. Build, static checks and local documentation links pass. See [acceptance and full decisions](../architecture/reviews/2026-10-10-query-semantic-recall.md).


Dev50 adds opt-in [model query transformation](model-query-transform.md): borrowed completed async ModelProvider, bounded strict tool-free proposals, named-provider JSON/TOML assembly and scoped Knowledge/Facts preflight. Original eight Profiles and absent-option identities remain; Local accepted Action and Temporal Knowledge snapshot recovery reuse original evidence. Preparation can repeat before acceptance; no model quality, fee ceiling or Temporal Facts claim.


Dev51 adds [pure HTML ingestion](html-ingestion.md): opt-in HtmlDocumentParser and installed ingest template, UTF-8 text extraction with bounded structure and original source/atomic receipt recovery. Text defaults remain unchanged. No browser/CSS/URL fetching; PDF/Office/connectors and full H3 remain open.

Dev52 adds [pure DOCX body ingestion](docx-ingestion.md): canonical UTF-8 WordprocessingML paragraphs/table text, bounded ZIP/XML validation and installed ingest template. Existing text/HTML pipelines and committed receipts remain compatible. Word layout, inherited styles, images, headers/notes and other Office/PDF formats remain outside this adapter; full H3/M1 is open.

Dev53 adds [optional text PDF ingestion](pdf-ingestion.md): lazy pypdf 6.20+ below 7, strict unencrypted page-order text, scoped library limits and installed ingest template. No core dependency or original Text/HTML/DOCX default changes. OCR/layout/real PDF compatibility corpus, global host isolation and full H3/M1 remain open.
