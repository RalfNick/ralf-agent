# 部署 Session 集成与收尾验证

当前仍未关闭原360秒S2门槛。ec0ebe4已获授权的600秒独立诊断两Turn完整成功、退休及清理通过，但不代替原验收；详见[整链记录](2026-10-16-coding-session-critical-path.md)。另本批修复[根Runtime注册回调重入](2026-10-16-temporal-release-reentrancy.md)：相关628项、独立安装171项及默认离线兼容通过，未将旧包真实诊断当作新修复服务证据。以下按快照保留历史记录，不覆盖当前结论。

## Activity 根命令定向查询（2026-10-16，实际仍超时）

2026-10-16 P3-2/S2 仍未完成：本批 actual Model／Context 的 Coding4／binding23 根命令定向查询已实现，保留完整 fresh ancestry、原 Registry 握手与实时准入，缺失／不匹配提示回退。新增21项通过，独立审查无P1／P2；全部270个Temporal模块3759 passed／589配置依赖skipped，独立安装14模块291 passed，默认完整canonical及保存History离线兼容通过，425产品／861测试无漂移。一次原图原360秒实际验收仍1 failed／390.282秒：四Tool均ok、效果adopted且物理停止；首Turn成功，第二Turn最终为failed／released，未产生完整业务验收结果。两root退休、两Turn完整正ACK、owned关闭与安全清理通过，不能替代业务成功。不据此宣称性能改善，本批不追加复跑或查询级微调；其余十二正常／五故障及P3-3／4／5／A仍待原定门槛。下一批先基于既有证据形成关键路径和传输预算，再决定成组修复；仅本地提交，不推送。

核心 RED：MODEL／CONTEXT 两项在原代码仍各有一次 `coding_composition_candidates` 查询。新路径保留完整原 `_ancestry` 的 Query／Describe 顺序，提示只取现有原 Activity context 的 command；必须匹配 raw client、原 carrier、当前 Activity Run／epoch／namespace、fresh original／root 的 Scope／请求／Manifest，以及 `root_run_id(deployment, Scope, command)` 的确定性地址。随后新建原 Registry 代理，执行完整 SDK 握手、`coding_composition_admission` 与原准入／namespace／关闭检查。不使用 context 的 admitted 值，不保留跨调用缓存。

默认、旧 publication、Tool／CONTROL、无 actual Activity 或上下文不匹配均保留原扫描。定向查询仅验证目标 root 的原 Registry intent；不再顺便检查同 Scope 无关候选损坏、全局候选数上限或绕过正常 Registry 派生地址约束伪造的重复项。这是显式实验协议的查询范围调整，不能声称任意损坏状态下与全量扫描等价；原 Worker／History 仍按不可变匹配版本恢复。

本批实现验证已完成：新增21项 `-Werror` 通过；全部270个Temporal模块3759 passed／589配置依赖skipped、零失败／错误，222.762秒进程窗口（pytest自身219.33秒）。425产品／861测试冻结，无源码漂移。独立安装14模块291 passed／39.472秒、零失败／错误／跳过，源码／sdist／wheel／site425文件一致，861测试副本前后不变；默认完整Profile／Manifest／编排canonical及原／continued保存History离线重放通过，模型／服务调用0。独立只读审查无P1／P2，Ruff／格式／空白检查通过。这些不代替原场景业务验收。

私有证据：`/private/tmp/ralf-agent-dev121-root/activity-root-release/result.json`；冻结清单SHA256 `649dc6b404e97f3095049da8f6a13af13523fc261b1813c9d07fccfcc81fb27d`。独立安装摘要 `/private/tmp/ralf-agent-dev121-session-sdk/default-compat-s2-activity-root-routing/final-summary.json`，SHA256 `001c971bbf04f4c06dc0b54289b71ef0e70b69c04735c17662eb5a57a0077cd1`。原始单项由同一独立安装包执行并已终态exit1；原Tool80／Runner60／approve180／scenario360／first-close60／cleanup40秒保持，无诊断flags，其他十二正常／五故障未启动。

原实际单项1 failed／0 errors／0 skipped，JUnit390.282秒（含原关闭）；根进程session22047已确认exit1，425产品／861测试及安装导入无漂移。原scenario360在 `approve → status → _view → SDK Query` 取消，非approve180超时。四Tool分别38.067292／36.221950／41.038917／39.338817秒，均SDK Completed、ok:true，有原candidate和采纳摘要，四effect adopted、四physical stop且无pending stop。两root accepted／retired均2，retained0；两Turn各6start／6end且全部原Completed ACK为正，首Advance succeeded／released，第二failed／released。assembly关闭和Worker退出成功，schemaRetained=false、deletionAllowed=true、保留原因空；未手动清理，无完整 `session-coding-result.json`。第二Turn第四Tool23:38:54.215060Z完成；后Context23:38:56.680737→59.777864Z、3.097127秒成功。末Model23:39:00.020130→03.189868Z、3.169738秒，返回validation_error／dispatched:false。独立History顺序为Registry Coding close正Completed e196在23:39:01.846962Z（close_requested:true），末leaf原parent-stop取消e215在02.311035Z，`admit_context_dispatch` 正Completed e221在03.002468Z明确allowed:false，然后Model拒绝，graph root cancel e474在05.990082Z。原guard在allowed:false抛ValidationError，与该未派发结果一致；这是原360超时后关闭拒绝的证据，不构成独立模型故障。root最终child_run_failed／failed来自该末leaf，不表示第二Turn成功。末两次CONTROL observe分别4.950611／4.925859秒、均ok，不据此宣称分支命中或性能收益。脱敏tail摘要 `/private/tmp/ralf-agent-dev121-session-sdk/activity-root-normal-terminal-evidence/tail-summary.json` SHA256 `a4d97f4dd5ed9a2dbc69d491683ec18857f867a7b61b84d864c41ecb8979c57e`。

原图本批没有证明性能收益或门槛关闭。只读终态提取34输入文件哈希前后相同，摘要 `/private/tmp/ralf-agent-dev121-session-sdk/activity-root-normal-terminal-evidence/summary.json` SHA256 `4c5081b0560e5db2ad88141509e1e7a5378b86a35f0b9925ce8e7e7c21beee4a`；输入表SHA256 `74d82895d5b93f27615067f95fcff410c8156bc2ba2d1d79f863d65d377968b0`。本批不再启动服务或连续微调。下一步先统一关键路径／请求传输预算：现有日志存在约0.6–0.9MB重复载荷警告，但警告本身不能证明网络、序列化或重建各自耗时；将其与既有Manifest／composition／Coding成本证据关联后再选成组修复，不扩大支持矩阵、不更改期限，也不预设改进。

以下保存前批证据，不覆盖本批结果。

## Model／Context 完整入口归并（2026-10-16，原场景仍超时）

当前唯一集成阻塞仍是 P3-2/S2 的原 `graph-sequential-sdk` 两 Turn 在 360 秒内完成；不重开已成功的工具执行和取消清理。原 c4 History 中，末 Context 的 5.129344 秒里，Activity 开始至实际 call-start 正 Completed 已占 1.916502 秒；末 Model 的 5.300220 秒里，该前置区间为 3.251893 秒。它们来自同一运行的 SDK 时间界限，不是函数 CPU、纯网络时间或两个可相加的独占成本。Model 在 close／cancel 交错之后返回 `dispatched:false`，不因此认定模型或独立校验缺陷。

完整调用链与离线单次 Runtime 校验不同：universal `validate_activity` 在深度一、已固定 child epoch 的路径读取子节点、父节点、父节点刷新，各自执行独立 Session 七事实验证，共三组。Context 本体另有前后两个 composition tree guard；正常 Model 则有入口和 dispatch guard。本次失败 Model 不保证走满后者。`selected_runtime` 只构造浅拷贝的选择视图，没有重建 Runner 或连接池。实际 History 未记录 Query 耗时，不能从静态调用次数分摊上述秒数；原 normal 运行也没有 SDK spans。12 项输入哈希核对不变，私有证据 `c4-context-model-wrapper-reading/summary.json`，SHA256 `3c5e651ba310e4047b247740274973198f6f15ebbac7e9dc9912b01a52f2c414`。

此前逐字符正则候选已撤回：四个冷进程 ABBA 完整 Runtime CPU 18.4020→17.4833ms，仅下降 4.9924%，未达到预先约定的 10%；完整请求和独立绑定链分别约 0.27%／1.10%。完整结果和拒绝行为一致，但没有据此进入真实服务复验。产品恢复 c4 原字节，候选和失败决策仅保留私有目录；不把 32 项候选检查当作当前产品新增能力。同线程同步 Runtime profile 仅用于离线成本定位，不能外推真实 Worker 或解释完整尾部。

下一最小候选限定在 actual Model／Context 的 Coding4 universal 入口：复用既有 node 的纯关联，保留 Run／Registry／Start／namespace、父初读与刷新及 held-root 读取；组内节点是不可采纳 proposal，末端新建独立 raw Session verifier 完整读取七事实，身份和 Runtime／source／ports 全部通过后才返回 proof。缺祖先 pin 必须丢弃本组并从 raw client 走原完整路径，不在 proposal 上 pin 或发 Update。原生 Tool／permission、其他 Activity、后续 tree guards 与 call ledger 保持原路径。该窄采样边界须先 RED→GREEN、恢复与漂移检查及审查，安装／兼容和原场景真实复验未通过前不称交付；不再为小函数微调重跑服务，也不修改原期限。

上述候选已完成源码与离线检查，真实单项仍未通过：新增私有 Activity reader 纳入 publication4 的完整文件库存。首个祖先读缺 pin 才回原路径；父刷新缺／错 pin 继续拒绝。入口即固定独立 SCV 及其完整依赖，逐 await 固定原 checker、代理实例／service／已创建 handle 与 raw SDK 端口，避免末构造 SCV 重建变更后的基线。轻 checker 不调用完整 `_policy`；完整 Runtime 保留在组入口／出口及原节点读取边界。审查发现的代理实例端口替换 P2 已修，复核未发现其他 P1／P2。

原核心 RED 为 Model／Context 两项实际入口形状分别观察三组而非一组 Session 验证；修正后 proof、原非 Session 读取 Counter／顺序和输入保持，完整 Session 验证三组变一组。新增31项覆盖 carrier／Scope、默认与旧路径、初始缺 pin、父刷新、原 Session／Runtime／source／端口漂移、取消后 fresh 重试及重复调用无跨请求复用。代理实例端口三项首次运行已在修复后通过，没有补造其 RED。首次扩大回归保留1 failed／536 passed／21 skipped：旧 CONTROL info 缺 `activity_type` 时门禁误抛 AttributeError；改为回原路径并补缺字段检查，相关两模块39 passed／16.02秒。修正版全部269个 Temporal 模块同次3738 passed／589 skipped／206.65秒，零失败／错误；skip 不作为服务证据。Ruff、格式和 Git 空白检查通过。

冻结 `activity-read-release-v2/snapshot`：1761项目文件／425产品／860测试，source及tests的1285项与工作区核对无漂移。新模块SHA256 `ee40c1db35a160503fe9a1dcf082f6e2a96d83291070f10cc6d0c215c79f62dd`，测试SHA256 `50937817a7dec157a7191c63f431ccf099022859512ce23e163725c738ea9545`。独立安装13模块270 passed／31.010秒，零失败／错误／跳过，425项 source／sdist／wheel／site逐字相同，860测试副本前后相同。完整默认 Profile／Manifest／orchestration canonical 仍为 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原及 continued 默认保存History离线重放通过，Provider／服务0；不代表 live continuation 或旧 Coding History 兼容。wheel SHA256 `10e18433f4c9a33562d4a2a53bec40b123ba569e7bce74a261de3e33b3da1657`，sdist SHA256 `5ac4eabefc140f357415fde1da5df455e1f513931503766f24bb24d8cc1802fb`，安装证据 `default-compat-s2-activity-reads-v2/final-summary.json` SHA256 `558f3ae6af9d43c8b3ae02ad8263cd3cdf6e3b885692d6241b77686d88c9a3c7`。旧修正前安装269 passed单独保留，不作为本候选证据。

唯一原 `graph-sequential-sdk` 正常复验已终态exit1：1 failed／391.197秒（testcase390.683秒），零错误／跳过，425产品／860测试无漂移；原body在approve.sleep处被scenario360取消。四Tool均SDKCompleted成功，耗时38.144950／35.503391／38.842755／37.731461秒，均有SQL candidate、adopted效果及正physical-stop证据。两root均退休（accepted2／retired2／retained0），两Turn各有6组start／end和全部Completed正ACK；首Advance为succeeded，次Advance为cancelled，均released:true。owned assembly关闭和Worker退出成功，原门槛允许安全删除schema，reasons为空；没有两Turn全部成功的业务结果文件。34项原输入哈希不变，证据 `activity-read-v2-normal-terminal-evidence/summary.json` SHA256 `cb0f9c7e6e720f91b84855d6398251095422b3fd54fc079b3ebf72691c745291`。

本次尾部比前次走到了更后步骤，但不因此宣称稳定提速：最后Model于UTC23:12:10.714434开始、15.688740正完成；Registry coding-close在15.890912 Accepted／15.890928正Completed。parent observe在17.013192见child=succeeded，join登记17.117455开始、21.075810返回definition_mismatch；root取消在20.577200正Completed。join登记开始已在原关闭正记录之后，返回又晚于root取消，不能把该拒绝当作独立验证缺陷。原Advance的最终children也确认a／b succeeded而join cancelled且started:false，无join SDK Start。body-error文件mtime14.917037仅为异常后的代理，不冒充精确取消时点。尾部证据 `tail-summary.json` SHA256 `248f7feac4b2377d7d648ee245559db15b66a60de7a9561ba7673b02c3649c1e`。

正常runner SHA256 `b032ec38edac086f45570de901a5f88d3375e048697493494b1a7d63901da34e`，完整审计 SHA256 `e312e51e9822c39959760d6888ced142b4f228be0c906ef59304b1b8bb01f554`。原80／60／180／360／60／40秒与空诊断flags保持，其他十二正常／五故障未解锁，600秒诊断未执行。S2／P3-2及第三阶段仍开放；当前候选只证明只读协议与减少重复读取的契约行为，没有解决实际期限，也未证明端到端改善。下一步只定位剩余原编排交接与SDK验证的累计开销，不重开成功的工具／关闭，不围绕整体取消后的拒绝继续补丁，也不重复运行同一正常版本。

同一History的入口界限另存 `entry-boundaries.json`（SHA256 `ed560e57230b69c699cbb69bbb21f84c6dbc7550fffee6311d489c83d491e59a`）：末Context ActivityStarted→call-start正Completed为1.709857秒，末Model为2.004045秒；前次c4为1.916502／3.251893秒。只有两个独立实际样本且没有分支marker，不能据此直接证明新分支命中、稳定收益或CPU归因；更不能用这两个局部区间关闭原360秒验收。

## 请求内拓扑绑定复用（2026-10-16，原场景仍超时）

原360秒正常首项仍由本地`90da97c`的435.464秒失败记录定义；本批只处理该P3-2阻塞，不增加范围或改期限。同一`validate_request`原来在初始步骤、Coding拓扑及末尾三处重复整组绑定验证。现仅exact Coding4、普通JSON完整request／manifest、非空显式绑定且已遍历全部实际Agent路径时，拓扑阶段复用首次已经完成的叶绑定解析；未显式绑定的叶也已用原默认descriptor检查。私有`_topology_definitions`只拆出原并发／递归结构检查，隐藏planner／completion Agent继续逐一验证；公开`validate_topology`保持独立完整入口，末尾原完整`validate_bindings`／`effective_step`及构造器Scope检查保留。无bindings、旧协议、自定义容器／共享引用及扫描回退沿原路径。原native逐请求fresh SDK、效果／预算／停止ACK和执行权威均未改。

这是实验Coding路径内部采样次数调整，不是缓存、跨请求证明或新增skip参数。新helper进入原pure源码库存；旧selected History仍用原匹配不可变Worker。先观察主RED：三Agent完整请求27次描述校验而非预期18；修复后18，公开拓扑仍9。新增18项已通过，覆盖graph／Team／Dynamic／嵌套、legacy／custom回退、并发与Runner拒绝、缺路径、source库存／现场替换、隐藏Coding planner、拓扑后tool_set变化被末轮独立拒绝，以及无绑定仍经公开拓扑入口。初次补充的嵌套测试误用仅接收AgentSpec的GraphNode，且漏列AuthorizationDenied预期；均为测试构造修正，产品未因此变更。独立源码审查无P1／P2。进一步提前协议验证／复用Session投影需要额外错误顺序、helper现场身份及隐藏Agent责任论证，本批未实施，不叠加猜测优化。

冻结`topology-pass-release/snapshot`：1759项目文件／424产品／859测试，audit SHA256 `82b87ed53f1800608256116f0f4b9ac6fbf8b9e2e5820f553326e51ce1e165d2`。相对90da97c仅修改`temporal_state.py`和`temporal_coding_composition_protocol.py`两个产品文件。全部268个Temporal模块同次回归3707 passed／589 skipped／197.494秒，零失败／错误；589配置依赖跳过不作服务验收。新wheel独立安装后10模块212 passed／8.268秒，零失败／错误／跳过；source／sdist／wheel／site的424产品及859测试副本前后相等，导入均来自独立site。完整默认Profile／Manifest／编排canonical保持原SHA256 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原及continued默认保存History离线重放通过，Provider／服务0，不代表live continuation或旧Coding History兼容。wheel SHA256 `ec20719abd6ac9e73671354d924d9d7b1b410dcddd8737aab0cc49fbbb10426b`，sdist SHA256 `bb209fb01a7af6bdda63e312e06a8d544132a7c04d234121dddd13338325d784`，安装汇总SHA256 `0a0c19d168f30f4b66d40fa929dddfb330c66c2592ca2a206e817b05832f6eae`。

预先固定完整`validate_request`为主指标（不少于10% CPU收益），采用真实双Runner工厂、PG view夹具与BindingCatalog、原三Agent图请求；A为90da97c匹配不可变包，B为本冻结候选，各自冷导入并建立自己的原发布／pins。四进程ABBA每块每操作10次；各冷进程内先预热后计时，测量的是隔离包的warm完整调用，不代表首次调用。无服务／模型／native。完整请求CPU均值A75.58105→B51.2205ms，下降32.231%；绑定控制14.9012→14.88545ms、Runtime控制19.7961→19.0087ms，均视为基本不变，不外推端到端或吞吐。测量外计数为descriptor27→18、Coding／composition协议各36→24，独立绑定链仍各6；profile恢复、原输入canonical及产品／物理pins前后不变。完整material的24处差异均闭合于声明的四函数／两source及其派生摘要，无整块屏蔽implementation；Scope、缺Runner、坏协议／并发与source替换拒绝一致。证据 `request-validation-cold-abba-90da97c/summary.json` SHA256 `c3ed085651d3c92b3fdd4fcdaa814e08902550ad3b074a963efd140fd37fd8be`。

唯一原`graph-sequential-sdk`正常首项已终态exit1：1 failed／392.537秒（testcase392.005秒），零错误／跳过，424产品／859测试前后无漂移，diagnostic marker为空。所有80／60／180／360／60／40秒期限保持；原body仍为scenario360在approve.sleep处取消，不是审批180或Tool80。四Tool均原SDKCompleted成功，分别37.523601／35.478805／39.143722／38.319134秒，有SQL result_candidate、adopted效果和正physical-stop证据；第四Tool完成于22:24:06.176838Z。最后一个工具成功也不代表第二root完整业务成功，不将尾部耗时猜测为纯observer成本。

本次两root均正退休（accepted2／retired2／retained0），effects4 adopted。两Turn均有6组start／end及6＋6个Completed正ACK；第一Advance在22:21:24.797403Z正完成、root_state=succeeded，第二在22:24:41.515726Z正完成但root_state=cancelled。没有最终两Turn业务结果文件。owned assembly关闭成功、Worker退出，schema通过原证据门槛安全删除，reasons为空；取消Run的责任清理成立，原两Turn业务成功门槛仍失败。不把不同运行的435.464→392.537秒当稳定业务加速。34项原输入前后哈希一致，终态证据 `topology-pass-normal-terminal-evidence/summary.json` SHA256 `a764f42b5403660e8fc28b6abbf3450644a38c74f184dfa2278c36a00dda987f`。

同一原History的最小尾部核对已明确下一边界：第四Tool22:24:06.176838成功后，evidence于08.373096完成，tool_execution_ended有07.345095正ACK；Context于08.670270开始、13.799614正完成，随后Model于13.994179开始、19.294399返回validation_error／dispatched:false。initial-body-error文件mtime16.597481仅异常后的文件代理；原Registry coding-close在17.246233 Accepted，child取消在18.097343 Completed，root取消在21.454645 Completed。四个CONTROL observe分别于10.908622／14.782179／19.235595／22.829394成功完成，前三见running、末见cancelled；第二root只启动a／b，没有join子Run。故到取消时child最终Model仍在途，业务尾部不只是Session观察等待；该Model回执在close／cancel交错之后，不能据此认定独立验证缺陷或模型质量问题。12个原输入哈希不变，无服务／重放／新采样；证据 `topology-pass-tail-evidence/summary.json` SHA256 `f8c2469d8947787ad0d5312a8a9b374ea6d18984f35877d065a1fb8eab36e78c`。上述时间均为UTC22:24分内，除明确mtime代理外都是原SDK事件；不从中推断函数CPU或删除成功observe／join。

正常runner SHA256 `63526f367d44a77c67058b1234d860355f4610c9544b696129a65028fda74147`，audit SHA256 `54b3a363ab1713a6f0efa2bf47aac4c25a9161bc08e531f4ef7b0fcfffa8ad77`。其余十二正常／五故障未解锁，S2／P3-2继续开放；独立600秒诊断仍未授权／执行。下一步复用本次原History确定第四Tool之后实际未完成的业务／控制步骤，再针对必要完整校验成本提出候选；不重开成功的工具与安全关闭、不盲目重跑当前包或继续扩大绑定归并范围。

## 同步绑定验证归并（2026-10-16，原场景复验仍失败）

本批只修复 P3-2 原360秒首项的已证实成本来源，不新增能力、拓扑或期限。在 exact Coding4 的普通JSON输入中，`validate_bindings` 每个descriptor先独立执行原完整含Scope验证，再把该返回值交给内部纯投影，避免公开投影重复完整验证。公开 `effective_manifest` 仍独立完整验证，并可显式接收Scope。默认／旧3、自定义容器、共享引用／环、非有限数和超过有界资格扫描的输入均走原路径；扫描限制只决定回退，不新增公开输入限制。原 `selected_session_data`、原生请求逐次fresh SDK事实、效果／预算和停止ACK不变，没有跨请求缓存或新的验证权威。新增两个纯函数均纳入composition源码库存。

这是实验Coding路径的重复source／alias采样次数调整，不能声称所有采样次数不变或旧selected指纹相同。旧Coding History继续用原匹配不可变Worker恢复。主RED先观察单Agent三次验证而非预期两次，修复后native22／composition23均为两次；三Agent完整链由9次变6次。补充测试覆盖Scope优先拒绝、默认／旧协议／自定义容器回退、坏协议和source库存、公开独立验证、输入隔离及扫描边界。没有调整Runner Scope的既有授权职责。

冻结快照 `binding-pass-release/snapshot`：1758项目文件／424产品／858测试，inventory SHA256 `e5b02b7abaa4d32d0d694b56db242fae909f52d3e2aef3cdb6acba8119d6465f`。9个受影响模块源码194 passed／7.021秒；全部267个Temporal模块3689 passed／589 skipped／190.070秒，零失败／错误。589配置依赖跳过不作为真实服务验收。独立新wheel安装后同9模块194 passed／6.212秒，零失败／错误／跳过；424产品在source／sdist／wheel／site一致，858测试副本及前后审计不变，导入均来自安装。完整默认Profile／Manifest／编排canonical仍为 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原及continued默认保存History离线重放通过，Provider／服务0，不代表live continuation。wheel SHA256 `81e0ccbe8be5c3be36502eda4d9557fbb5bd41c89126324670674b35ad76697c`。独立源码审查无P1／P2。

一次四个冷进程ABBA使用相同物理配置的真实双Runner工厂、完整Coding4／composition23发布与原三Agent请求，无服务／模型／native调用。完整绑定验证CPU均值A19.4461→B14.83585ms，下降23.7078%；完整Runtime验证仅约0.55%变化，不称为改善。完整结果差异24处，全部由声明的五个函数／source摘要变化解释，没有整块屏蔽implementation；原完整Scope、坏协议和source拒绝一致。该测量只证明同步完整绑定链的CPU收益，不代表业务墙钟或框架整体提速。证据 `binding-validation-cold-abba/summary.json` 及 `independent-result-review.json`（SHA256 `e41e8248583759562b257e97738bd66c90b088d73d62545375b784ea467c41c7`）。

唯一原 `graph-sequential-sdk` 正常验收已终态exit1：1 failed／435.464秒（testcase435.006秒），零错误／跳过。Tool80／Runner60／审批180／场景360／首次关闭60／清理40保持，diagnostic flags及marker均为空；424产品／858测试前后无漂移。原body在approve→status→SDK query处由360秒scenario取消，不是Tool80或审批180到期。四个Tool最终均成功（40.451683／39.821789／40.538817／49.333893秒），各有result_candidate、adopted效果和正physical-stop证据；第四Tool到21:59:59.818411Z才完成，不能把关闭期间才取得的结果当原业务窗口内成功。

两root均正退休（accepted2／retired2／retained0），但第一Turn才有succeeded Advance的Completed正ACK。Session第一Turn6组start／end及正ACK完整，第二Turn6个start／5个end，缺末end及Advance；没有最终两Turn业务结果文件。首次close为CloseIncomplete，最终close为RPCError；Worker已退出而assembly_close_succeeded=false，schema依scoped_session_close_unconfirmed／session_evidence_invalid（EvidenceMismatch）保留。四笔效果已采纳和root退休都不能代替Session责任解除；未强制退休或清理，也未据本次关闭报错推定独立缺陷。36项原输入前后哈希一致，业务证据 `binding-pass-normal-terminal-evidence/summary.json` SHA256 `17e8957aac55c056e39c7426581e61319b9667d2661d471d467be4217e18da5a`。

本批归并有完整同步绑定CPU收益，仍不足以关闭原360秒两Turn及Session收尾门槛；不由不同产品／采样运行推断稳定端到端改善。其余十二正常／五故障未运行，S2／P3-2不关闭，独立600秒诊断仍未授权／执行。下一批只针对既有有效CPU证据中的完整Manifest／协议重复构造边界，先证明职责、现场source及Scope拒绝保持，再决定有实质完整链路收益的最小候选；不继续同版本盲目复跑或提高期限。正常runner SHA256 `f63bbed87316474fcbf6f94e5f1e0aa02b10963d213e15a362ee63ef2dfb3c85`，其audit SHA256 `21361791726216d1236d19d96a01731214855ae0fdc80044a1bcd48c1963aa60`。

## 修复后 CPU v2 首项（2026-10-16，有效计数，业务仍未通过）

仅修复诊断生命周期，产品仍与`9ebb6f9`的独立安装逐字相同。新冻结`cpu-v2-lifecycle-fixed-prepared`含424产品／857测试，audit SHA256 `802804adb2a75a687da5fe9d7fcc55ebe2d51a44cca5db60bf28b89649239319`；相对上一采样只有诊断helper和测试两文件变化，runner仅换全新输出目录。原单项`graph-sequential-sdk`及80／60／180／360／60／40秒期限不变，未执行其他组合、模型或600秒诊断。

唯一实际诊断已终态exit1：1 failed／392.302秒（testcase391.623秒），零错误／跳过，424产品及857测试无漂移。原body仍在approve.sleep被360秒scenario取消。三个Tool分别41.510／48.470／59.019秒成功，均有candidate、adopted效果和停止证据；第四child已启动Context／Model，**尚未调度Tool**，不能沿用上一样本的第四Tool definition_mismatch。两root均正退休；Session两Turn各6组start／end及Completed正ACK，Advance分别为succeeded和cancelled，原assembly关闭成功、Worker退出、schema按证据安全删除。正关闭证明成功Turn与取消Turn责任已清，不是两Turn业务成功。34项原输入前后哈希不变；业务证据`cpu-v2-lifecycle-terminal-evidence/summary.json` SHA256 `6cfa442b67409efaf41427e00f9966b46c164ed2c7a42080e721e12a40b98ea6`。

本次唯一CPU记录通过质量门禁：fault0／incomplete0／first_fault_reason=null，321统计行和635时间桶完整对账，无重叠窗口。含关闭的进程CPU328.620秒、墙钟382.218秒；选中目标exclusive254.441秒，未覆盖74.179秒，不能为未观测部分猜测归因。互斥前三为Runtime._current_manifest64.167秒／5313次、composition.validate_protocol60.179秒／57082次、coding.validate_protocol28.097秒／45971次。Coding的inclusive87.600秒已包含composition，不相加。RunnerJournal._json标签是共享严格JSON验证，不等于全部来自journal。

精确Registry closeCoding Accepted为21:16:20.376506Z；initial-body-error文件mtime21:16:19.514991Z仅作代理，不当精确取消点。10秒同步返回桶中，关闭前完整桶0–34的selected-exclusive233.361秒，跨界桶35为5.900秒单列，关闭后完整桶为15.180秒；最大观测单call wall0.275秒。前完整桶主要为composition57.266秒、Manifest56.767秒、Coding26.715秒，说明重成本已发生在关闭前；分桶不是精确critical-path或可回收预算。证据`cpu-v2-lifecycle-fixed-terminal-analysis/phase-evidence.json` SHA256 `ee4e1308ad4753187e67d3b30942be316b03cd47e0831dfd77a4f59947e5c127`。不同运行的392.302与514.670秒不推导稳定性能改善。

随后仅一次零服务离线调用边检查：本次匹配的424产品和首个成功child原199事件History，经原runner／restrictions重放，在原ReplayState的合成只读Query中仅计两个验证函数及最多两层caller、512键，不采集参数／locals或函数耗时。Query正响应、State／publication／命令序列／原business completion及History全部不变，计数fault0／overflow0，原线程profile恢复、Replay成功，子进程exit0。该node Query触发Coding3次（经_selected两次、_require一次）、composition3次；不能把单node结果外推Registry的377次Query及64.484秒inclusive成本。证据`cpu-v2-query-call-edges/summary.json` SHA256 `686efa0f5694c099c77c4754ec88e96bfb12b0afc96b1403f3c73b85bf2b12b1`。下一步只读核查原Registry Query的完整调用来源及同一同步栈重复验证，不再猜JSON或追加小缓存。warm native permission归并9→2虽然理论可保留fresh读取，但每Tool触发次数有限，未据此实施新协议。

Registry调用边随后完成一次：复用本次原211事件History及匹配安装，在原ReplayState发一次原view Query，Replay／Query成功、profile恢复、fault0／overflow0，424产品与History不变，完整Registry存储字段1,393,641B、publication／命令序列／原completion前后相同。容器快照对所有dict／list／tuple／set作递归类型标签，9组类型碰撞反例通过，避免set与用户dict同形而误认State未变。最终原State已无held root，选择一条原正退休root，不能外推为历史377个Query的状态分布或业务关键路径成本。

本次单Query触发Coding60次、composition61次；其中Coding48次来自`reject_runner_descriptor→coding_enabled`、9次来自`validate_runner_tools→coding_enabled`，剩余3次来自完整Manifest／deployment入口，所有composition调用均保留各自父调用计数。它证明绑定层的重复完整协议检查是明确的下一审查点；未据此删除检查、缓存allowed、提前解析动态alias或承诺收益。Registry原始事实及退休分支继续完整验证；下一批优先在一次同步绑定验证内明确公开边界与内部已验证数据的职责，先以RED及源码边界审查证明替代路径，再进行完整链路成本对照。证据`cpu-v2-registry-query-call-edges/summary.json` SHA256 `2cf8b56afbb427321bc52d7d25fee47c8c35f93b1cc2935973854c6a108f39b7`。该离线Query没有SDK服务／模型／Client，也不构造新State或补写History事件。

S2／P3-2仍开放，原其余十二正常／五故障未运行。原360秒验收没有通过；本批诊断及正关闭不关闭阶段，也不授权600秒窗口。

## CPU v2 关键路径诊断（2026-10-16，实际首项失败，采样无效）

仅修改测试遥测，产品仍为`9ebb6f9`，不新增能力或调整原80／60／180／360及关闭期限。原CPU默认v1保持；显式CPU＋variants开关或原测试目录marker才启用v2，peer在子进程环境过滤前固定选择。固定18个同步目标补入直接`dto._intent`、origin、Runner／journal／protocol校验；只将位置与完整CodeType结构相等的新code对象记为遥测副本，不作为原模块、源码或授权证明。首次START立即配对，外来代码只禁用自己的该事件；不用全局restart，不采集参数／结果／异常内容。

收集有256code／64线程／128栈／2048统计行及时间桶行／1MiB输出边界，只清自己的监控slot／local事件及callback。限额、负值、未结束或不自洽使采样无效；输出超限则无记录，缺文件不能当零CPU。10秒桶按同步返回时归属，保留最大跨桶调用wall及Unix起点，帮助区分业务与关闭窗口，不能当精确关键路径。桶原点误用单call起点的RED已复现并改为整个window；原业务RuntimeError／CancelledError同对象保留，超输出上限也不吞异常。

新增16项，四受影响模块同次75 passed／3.08秒（-Werror），零失败／错误／跳过；Ruff／格式／空白通过，产品源码无修改。核心首次copy／改body或位置拒收、多线程／nested异常、外国tool的DISABLE保持、部分注册失败／cap清理、双context、env过滤后marker及桶总数对账均覆盖。独立源码审查无P1／P2，桶补充由上述RED复验。预先在原v21不可变安装、原199事件ReplayState的单次只读SDK Query验证了新Sandbox node副本正计数、fault0／incomplete0／timing_valid及完整State不变；该较早helper快照SHA为`a90d36ad8dbf1315792debcd7e8ec80cf1e3604b4cf8741634dc4b890e81e65a`，不冒称包含随后补入的桶字段。该次证据`v21-query-cpu-v2-offline/summary.json` SHA256 `38fe1caa59e5f2ee9f296cb12601be4b603415177f8da5525f4239adfb0097ce`，服务／模型／Client0。

最终冻结`cpu-v2-final-prepared`含424产品／857完整测试，frozen audit SHA256 `f34c7bf139195c079f171faf97cbbd0faeda58d8fbb2124b342374e02d401a77`，helper SHA256 `8888dde7affea2ee3ffdd6f52c81271b0bf103ec3a51336a4ecd6298b35fc005`。原产品source／独立site／wheel逐字等值，直接复用已安装产品，无新build。唯一`graph-sequential-sdk`实际CPU诊断已终态：1 failed／514.670秒，零错误／跳过；424产品和857测试前后无漂移。原业务360秒取消发生在approve.sleep，关闭时间另计；永久diagnostic-only，无remaining入口，不能据本次关闭原360秒门槛。

本次CPU记录`timing_valid=false`、fault1／incomplete5，观测64个线程身份和7个代码副本。已完成行与时间桶即使对账相同也不能覆盖采样质量失败；全部函数排名及残差归因不采纳。记录只包含通用fault计数，不能从64个线程反推实际触发分支。CPU质量证据`cpu-v2-terminal-analysis/final-evidence.json` SHA256 `aeab3bc2efde0940e20607f31ea1a21d494b9cc7e376b5eb2b8ec229c8eacbfa`，保留失败原件；先修复可复现的诊断生命周期问题，不盲目复跑同一夹具。

业务证据与CPU质量分开：前三Tool分别43.217／42.755／46.954秒成功，均有原candidate、adopted效果及停止证据；第四Tool14.245秒返回definition_mismatch、无candidate，资源为unprepared。accepted2／retired1／retained1，effects3 adopted＋1 dispatched；Worker退出而assembly关闭失败，schema因原退休／Session证据／未采纳写义务保留。37项原输入前后相同，业务证据`cpu-v2-terminal-evidence/summary.json` SHA256 `214bdeba9297a83daae7bf77a40463177025cd2c1904f41d6a1c44f149fd7105`。其余十二正常／五故障仍未运行，600秒诊断未授权／执行。

后续只读因果核对将第四Tool收窄到原关闭准入分支：Registry的closeCoding在20:55:03.700827Z完成；原child在20:55:04.225365Z的自动cancel ID，按原Workflow ID／epoch重算与唯一`grant_allowed=False`分支完全相同；20:55:05.919499Z才返回definition_mismatch。无原prepare grant接受，资源prepare_granted=false／prepared=null，Parent-stop取消发生在其后。因而不按独立源码／epoch漂移缺陷修改产品，也不放宽关闭后拒绝。History缺原Python trace及Query回包，最终异常仍可能来自该分支finally重验或显式closed抛出，不能断言某个Registry／node字段的实际返回。两路只读审阅一致，六项输入哈希不变；证据`cpu-v2-fourth-tool-boundary/summary.json` SHA256 `d1459f459a58e31d657713e857e4dcaec07dfd810f4833b88c67274d25b9e769`。主阻塞仍是关闭前两Turn超过360秒。

诊断自身已完成最小修复：旧`stacks`保留结束线程的空列表，确定性顺序65个逻辑线程（同时仅一个活动调用）会错误耗尽64额度。RED复现后，仅在最后一帧返回时删除空stack；保留64并发／2048历史统计行和其他原限额，新增固定首fault枚举，不记录异常内容。仅替换诊断模块的threading代理，未改真实threading模块。RED两项失败→定向通过；最终四模块76 passed／5.42秒（-Werror），零失败／错误／跳过，Ruff／格式／空白通过，产品源码未修改。该复现证明诊断缺陷，不反推旧实际fault的唯一来源；旧采样仍无效，不补算排名或声称原360秒已通过。本批未启动新的服务采样。

## 已采纳未准备回执的恢复幂等修复（2026-10-16，源码候选）

复用 v21 已终态资料，不重跑服务。第四 Tool 所在 Scope 的 Registry close 在18:57:22.223170先接受，原 owner 回执18:57:32.328305接受，原`ralf-deployment-coding-close:*`取消18:57:34.638707接受，Tool随后以definition_mismatch返回。原History没有native phase grant；首次unprepared回执148有Completed149正ACK，第二次同证据回执183的Completed184则为authorization_denied，不能把两次Accepted都当成功。PG同一effect／Run／Action／namespace_binding已有prepare_granted=false、pending_stop=false，但业务effect仍dispatched。该正物理证据不等于业务无效果结算，现有契约与纯状态测试明确保留unknown。私有只读证据`v21-fourth-tool-causal-audit/result.json` SHA256 `f1732dfb1a64a1a255057df818114831e40e9f4d691e44ff235b9d14222416e7`，四个输入前后哈希一致；内层异常未持久化，不能仅凭History断言每个拒绝条件。

最小纯History复现确认独立P2：首次原unprepared已采纳并完成停止观察后，新的原admitted-stop恢复调用在journal I/O期间遇到stop_needed被推进为false，相同完整回执被误拒。RED为2 failed／14 passed；候选仅在exact Coding4允许完整canonical相同的已存unprepared返回原ACK，不写状态、不添事件。完整原proof、stop身份、无grants／无prepared-stop-thread-turn、原namespace/request/runner/dispatch/generation仍全部检查；首回执、不同证据、bool／number混淆、矛盾native状态及外来身份拒绝，unknown预算不变。未选择与publication3保留原拒绝。新增22项覆盖活状态／独立深拷贝恢复、身份及矛盾证据；深拷贝不是SDK History恢复验收。

20模块402 passed／16.11秒，另8个协议模块98 passed／4.83秒，均-Werror、零失败／错误／跳过，分别登记不冒称同次全量。首次受限运行392 passed／10 failed，其中8项本地Unix socket bind被沙箱拒绝，2项为其未关闭socket的后续告警；原报告保留，允许测试专用socket后同组402项通过。独立只读审查未发现新增P1／P2，格式及静态检查通过。本修复改变Coding executable inventory，旧Coding History继续用匹配的原不可变Worker，不声称Coding发布字节等值。

独立构建／安装两模块63 passed／2.209秒，零失败／错误／跳过；424产品在source／sdist／wheel／site前后一致、855测试副本无漂移，所有产品导入来自新安装。完整默认Profile／Manifest／orchestration canonical等值，原及continued默认保存History离线重放通过，Provider0／服务0，未运行live continuation或旧Coding History。证据`receipt-recovery-check/final-summary.json`；wheel SHA256 `15abbd357f6be56b4b89421d4d45ae803380b57cb61d0c85416b0076e5954b4e`，sdist SHA256 `b78c947a49cc8d8fadd85328059c525d073be649cd845a66b74e898bcd54d603`。本登记在构建后同步，不声称当前全部文档与构建快照相同。

完整Registry快照的唯一修正setup测量已完成：host／原Sandbox／私有passthrough CPU中位7.540／10.443／6.608ms，全部9次812B结果canonical相同、State与query不变。仅fixture JSON测量，无实际SDK Query／activation或State恢复，不证明passthrough安全或整体性能收益；未修改产品沙箱配置。未再叠加性能微调。原360秒验收仍失败，独立600秒诊断仍未授权／执行；该幂等修复不消解未知业务效果，也不关闭S2／P3-2或解锁其余十二项正常组合和五项故障。

## v21 验证成本结构审查（2026-10-16，未形成新产品候选）

新的成本边界核对：原v20含关闭的Worker窗口中，固定目标exclusive CPU依次为`_current_manifest`110.207923秒、`dto.validate_intent`23.730883秒、`validate_release`自身16.483636秒、`SessionControlValidation._check`14.183679秒、`CodingValidation._check`10.391366秒、observer0.160222秒，共175.157709秒；进程其余195.531916秒未覆盖，不能归因给JSON或当作可回收业务时间。原v21实际211,063B intent的离线纯验证约13.53–15.95ms，origin约9.93–9.96ms，0服务／模型／SDK client；证据`v21-pure-validation-cost/result.json` SHA256 `9de846d2bb4a1f0f184fe0ae6bb19599516dc86070fbebc2f9cc1adaea63f2e2`。1849次DTO观测包含关闭，不能等同SCV构造次数或业务关键路径。

本批不采纳两种新缓存设计：固定inventory批量指纹若提前解析目标，会漏处理中途alias替换；只在出口拒绝helper漂移，也不能消除已污染的共享LRU。复用SCV对象虽能保留逐次SDK读取，但需要新的驻留实例／方法及DTO传递依赖保护，现有证据不支持足够关键路径收益。CREATE三次构造仍各含alias及原源码读取；composition末轮126项也有独立live descriptor采样，不能因正常夹具无业务回调就删除。源码保持原实现，不再叠加这些微优化；下一步使用匹配不可变Worker与保存原History做有界离线重放定位，Queries与服务时间不在重放覆盖内。

原v21不可变安装已完成一条实际Coding child保存片段的原版SDK离线重放：199事件、1,177,109B，重放阶段CPU0.991171秒／wall2.211143秒，子进程exit0。原History SHA256 `a9c1b6b536137b77d88e569a43788cd69aa71e80b47352073f068f5fcec253f5`及424产品文件前后不变，原runner／restrictions不改，服务0／模型0／未创建Client。末事件为WorkflowTaskCompleted；业务Tool成功与result_candidate已有原记录，但这不是WorkflowExecutionCompleted，也不证明资源退休或owned close。实时Query、Activity实现及服务等待不在重放范围，不能据单child结果分配整个195.532秒残差。带cProfile的第二次重放同样成功，但统计存在负耗时及self大于cumulative，全部profile函数耗时结论撤回；每activation新建Profile且同线程开关，现有记录不足以确认原因，未猜测换timer重跑。原版重放的独立计时与哈希审计不受影响。证据`v21-child-replay-offline/summary.json` SHA256 `98960840df3b6a7c114763503666f538cae887e6bbb8b9a54d1f257c34cf1e22`，另保留`profile-quality-rejected.json`。下一步先论证如何对原重放State采样只读Query，不以新State夹具、缺失事件补造或新服务场景替代。

上述Query诊断随后在同一原ReplayState完成：薄delegate在eviction前送一次独立query-only activation，经原Sandbox／SDK只读handler，既不把响应送给Core也不更改输入History，随后原样转发eviction。正响应665B，CPU10.051708ms／wall10.051333ms；60字段／332,885B完整State、publication、SDK命令序列和原business completion均前后相同，原424产品与History哈希不变，Replay成功且eviction命令0，子进程exit0，服务／模型／Client均0。首个探针误将421个py与含3个json的424项库存比较，setup失败／Query0；仅修正该计数后在全新目录执行一次，原失败保留。证据`v21-query-activation-offline-fixed-setup/summary.json` SHA256 `9af607dc1c966af465904792d8317321fbf3caeb46c56140253460c088b4cc83`。这是离线合成观察，并非历史实时Query回放、实际服务延迟或完整性能门槛；单child的单次结果不能解释整个未观测CPU。下一批只补原Worker的关键路径计数覆盖（含Sandbox代码副本和直接DTO验证），先验证诊断自身质量，再决定必要的原360秒采样；不继续追加缓存或放宽期限。

后续冷包对照已排除helper-guard候选：A／B分别首次导入并构造各自真实原pin，使用同一物理夹具，未热替换或绕过依赖保护。四个独立进程ABBA、每块30次完整双Runner Runtime校验，A为18.423233／18.488433ms，B为20.103867／19.758900ms；合并18.455833→19.931383ms，候选约慢8%，因此放弃。135项原算法指纹与全部选定现场调用Counter相同；完整声明的差异逐路径核对为两项改动函数及其派生源码／声明摘要，未整块屏蔽implementation。无服务／模型／native调用，源快照及夹具前后无漂移。证据`cache-guard-cold-review/summary.json` SHA256 `eb4ade240f79bca351638ac60550f2249306220cbc585707f17ae100cff2dbf1`；公共产品未采用该候选，未采用的测试草稿已移至私有证据目录。此测量不代表实际360秒样本或稳定生产性能结论；停止该优化分支。

后续唯一helper-guard私有原型在完整Runtime测量前被原Runner dependency pin拒绝：临时替换executable_digest代码与原固定依赖不符。未修改或绕过pin，临时代码已恢复，未进入ABBA；六个小等价case不是完整Manifest等价或收益证明，未实施该优化，也不外推原360门槛。证据`cache-guard-review/failure-summary.json`；无服务／模型／native或公共修改。原始性能阻塞仍开放，独立600诊断仍未授权／执行。

复用已结束的正常原图History和独立安装，未重复实际场景、未改产品或测试期限。此次不是v22候选，`e6726c5`仍是产品基线，S2／P3-2及第三阶段继续开放。

- **完整Runtime构造。** 每次双Runner验证调用check_runner_binding4次、runner_registration2次、implementation_identity4次、inspect.getsource28次、handler.check14次、runner.identity18次、executable_digest1009次。这些包含真实getter、方法和源码复核，不能把累计时间全部算作可删除工作。唯一私有候选只省ToolRegistry.manifests末次外层copy，保留全部现场读取；完整Runtime ABBA为18.8391→19.7560ms／次，120份Manifest canonical及全部采样调用Counter相同。没有显示收益，且未知自定义deepcopy仍需fallback等价证明，因此未实施。纯测CPU3.3064秒，0服务／模型／native；临时方法已恢复，产品无变化。证据 `runtime-copy-review-v21/result.json`。
- **原交接工作。** 两窗口31.565852／43.275841秒，按互不重叠边界分为旧Tool结束→父正physical-stop采纳10.560971／16.740411秒、该采纳→下一register完成6.636540／7.148317秒、register完成→新Tool开始14.368341／19.387113秒。第二轮还含两次原CONTEXT Activity，分别5.229330／4.132518秒；不是可直接跳过的空闲。窗口TimerStarted均0，Signal ACK最大37.697ms，WorkflowTask排队最大17.398ms。Parent observe与子Activity存在重叠，不能全部累加成可回收串行时间；跳过旧queued/running观察可能丢失唯一waiting_approval唤醒，未采纳。证据 `v21-handoff-review/summary.json` SHA256 `f9264be68b2bd119f6c7774fdbd8d16031e9aab66624164b81babf4df243af1f`。
- **沙箱纯函数覆盖。** 对本次真实原child的完整proof／Start／父physical-stop输入，在原SDK Importer与原restrictions中执行node_identity_digest，未改passthrough或任何验证器。host暖调用4.388–4.936ms，Sandbox暖调用4.915–5.481ms，完整输出相同、cache guards均正常；纯测CPU50.428ms。未观察到该纯函数的数量级放大；这不覆盖完整node(State)、Registry Query、activation或传输，不能拿5ms解释SDK调用总耗时。证据 `v21-node-sandbox-offline/result.json` SHA256 `dc374b0574ab257f64000c8130c94d3fd598e9dba89dffc4594f9f57cdc61db2`。另一个完整Registry fixture的host测量为7.283–8.871ms；其Sandbox setup在原CREATE别名校验处被拒，未运行Sandbox Query，未据此得出比值或绕过校验。
- **准入入口边界。** validate_activity的默认ancestry可能发child-pin Update，不能直接称为只读。仅完整admitted且原父边epoch已固定的子集可另行论证封闭读取，bind／pin／call-start更新必须保持在外；本图常见深度1入口只预计减少一组，root CONTROL无此收益。没有完整链路收益证据，本轮不增加该collector，也不引入raw-pins第二验证器。

为区分“整体测试取消导致第四Tool／close失败”和独立功能缺陷，已向用户询问是否允许一次独立较长窗口诊断，**尚未获得答复，未执行**。已准备可审查的私有dry-run：同一冻结产品及原854测试不改，额外独立测试文件的AST仅将场景看门狗360→600；Tool80／Runner60／approve180及关闭规则保持，单跑原graph-sequential-sdk，显式标记diagnostic-only，不能打开其余矩阵或关闭原360门槛。默认不执行，不读取服务配置；仅明确授权后才允许`--execute`。用户若要求保持所有场景360，则放弃该诊断，继续按原门槛开发；不把未答复当作授权。

## v21 正常原图首项（2026-10-16，`e6726c5`，未通过）

复验原冻结 `frozen-candidate121-s2-descendants-v21-final`／独立安装包，未开启CPU、SDK计时或RAISE。唯一首项为1 failed／455.001秒（testcase454.553秒），零错误／跳过；424产品、wheel及854测试在运行前后无漂移。初始body为CancelledError，原栈为scenario:76→approve:386→sleep:665，原整体wait_for360到期；第二root开始至其后cleanup cancel仅132.230586秒，第二轮approve180尚未到期。其余十二项正常组合及五项故障未运行，S2／P3-2与第三阶段继续开放。

前三个Tool均成功且原result_candidate已接受，实际Activity分别47.483732／42.913477／45.864810秒。第四Tool确已调度和开始，21.029423秒后返回definition_mismatch，无candidate；不能沿用旧样本“第四Tool未启动”的结论。三笔native写与结果采纳分记。首root为succeeded seal，seal至正Session Advance Completed ACK为19.594258秒；两轮各首Tool完成至下一Tool开始间隔31.565852／43.275841秒。它们是本样本时序，不证明夹具15→1对应实际RPC数，也不与不同运行推断稳定性能收益。

原effects为3 adopted＋1 dispatched，accepted roots2／retired1／retained1。首次close为CloseIncomplete／close_incomplete，最终cleanup为RPCError；Worker进程已退出而assembly_close_succeeded为false，schema保留。删除门槛明确为root_retirement_unconfirmed、scoped_session_close_unconfirmed、session_evidence_invalid（EvidenceMismatch）、unadopted_write，不能以进程退出或首轮ACK清除第二root义务。未认定额外关闭缺陷，也未强制退休或删除数据。

私有脱敏事实 `v21-final-terminal-evidence/terminal-evidence.json` SHA256 `f96d232685b305cce7889fe91d632505f3e902918c715a022d74f045b9bcdae2`，保留输入History摘要。新增helper的源码绑定还经独立复核：原SCV与factory registration固定完整source_bindings，不能由新reader重新baseline洗掉原绑定；CodingValidation不调用该后代helper，显式ports列表不对称未形成绕过，本轮不据此补代码或复跑。

本轮不再重跑同产品或叠加尾部小优化。后代读取归并尚不足以关闭门槛；下一批复用已有CPU证据，审查原工具阶段及跨步骤交接的完整验证成本，先证明候选保留原契约且对完整链路有实质收益，再复验固定首项。不新增功能、第二验证权威、跨请求事实缓存或权限缓存，不提高80／60／180／360及关闭期限。

## v21 后代只读集合候选（2026-10-16，实际验收待定）

仅在 Coding4／binding22或23 的 Session observer 已确认原证书及 Registry 正退休后，将后半后代读取纳入新的独立封闭集合。复用既有 reader 的 node／ancestry 关联，保留 LIFO、未启动过滤、固定 epoch、重复／4096 上限、每条祖先边第二次父读以及原逐后代 `session_proof` Query。中间结果不可采纳，独立 raw SDK Session 七事实、完整身份及 Runtime／source 出口通过后才返回 detached 列表。外层业务身份、Registry epoch、末 Session 验证与 State／end ACK 不变；ordinary／旧3、所有 native 请求沿原路径。

主 RED 在旧循环先证明完整结果及全部非 Session SDK Counter 等值，再由重复 Session history15而非1失败；候选减少为1组，不能据此推导实际 RPC 或墙钟收益。新增14项覆盖祖先第二次父读、错误 epoch／重复／原 root、完整 Registry intent／origin、末 reset／namespace、fake outer、方法 source 替换、异常／取消排空与新调用重读、ordinary 拒绝。最终23模块同次368 passed／58.66秒（-Werror），零失败／错误／跳过；1278个产品／测试文件前后相同。独立只读审查无 P1／P2 阻塞，Ruff／格式／空白检查通过。

最终源码快照 `frozen-candidate121-s2-descendants-v21-final` 含1753公共／424产品／854测试，inventory SHA256 `c198e945efc47d30e07c2e508ce96debaa4a9635ae285d146093f86468cd4c44`；本验收登记在冻结后同步。独立安装四模块73 passed／20.65秒，零失败／错误／跳过；424产品在source／sdist／wheel／安装间一致，854测试副本及安装前后无漂移，所有导入来自独立安装。默认完整Profile／Manifest／编排canonical等值，原及continued保存History离线重放通过，Provider0／服务0，不代表live continuation。wheel SHA256 `2baceefd8305ce66d17cac0b2935592392bc6009705653d60d3328465a93c4c4`。随后v21正常首项455.001秒失败，见上方；本批未重跑相同v20诊断或放宽期限。首项原图、其余十二项正常组合及五项故障门槛仍未通过／未运行，S2／P3-2继续开放。

## v20 CPU-only实际诊断（2026-10-16，未通过）

`installed-s2-v20-cpu-diagnostic-sdk` 唯一首项1 failed／453.198秒，零错误／跳过；原整体360秒取消第二Turn，不能归为另一个approve180到期。前三Tool成功并有原candidate，耗时48.107700／42.299957／44.522015秒；第四Tool20.742248秒返回definition_mismatch，无candidate。第一root seal至Session正Advance UpdateCompleted ACK为21.705067秒；不是只取得Accepted。其余十二项正常组合和五项故障未运行，S2／P3-2保持开放。下方正常428.761秒与SDK／RAISE314.926秒是独立样本，不能比较为稳定性能变化。

首次close为CloseIncomplete（original_coding_close），最终cleanup为RPCError；accepted2／retired1／retained1，effects为3 adopted＋1 dispatched。原删除门槛列出root_retirement_unconfirmed、scoped_session_close_unconfirmed、session_evidence_invalid（EvidenceMismatch）及unadopted_write，schema保留。首Turn正ACK不消解第二Turn或原写的剩余义务；不把其他样本的缺ACK细节直接套入本次，也不据关闭汇总错误认定独立产品缺陷。

CPU聚合覆盖整个Worker及关闭：370.689625 CPU秒／416.570039墙钟秒；`_current_manifest` 6062次、110.207923 CPU秒，`validate_release` 6147次、inclusive 128.445344 CPU秒。嵌套inclusive值不能相加，也不能全部算作approve或Tool窗口。faults0／incomplete0；固定host code之外的Sandbox重导入未覆盖，projection为未观测null，不是零CPU。证据为私有 `v20-cpu-diagnostic/final-cpu-summary.json` 与 `terminal-evidence.json`；CPU-only没有同时启用SDK span或RAISE。

下一步仍只针对既定阻塞：纯Unicode／ASCII分支ABBA在完整Runtime中仅2–5%收益，已放弃；广义raw live-pins没有完整差异等价证明，不实施。随后实施的窄descendant集合候选见上方v21记录，其实际收益仍待原门槛验证；不缓存SDK事实、权限或跨请求结果，不放宽期限，也不据本轮CPU计数宣称任何候选收益。

## v20 SDK／RAISE历史计时诊断（产品仍为`49d26d8`）

本批仅在私有runner显式启用既有SDK计时与RAISE异常定位，复用原冻结v20、原安装产品与测试；没有改变Tool80／Runner60／approve180／整体360或关闭预算。唯一首项诊断已结束：1 failed／314.926秒，零错误／跳过，424产品与850测试副本前后无漂移。**诊断不是正常验收，不能与下方428.761秒正常样本推导速度改善或退化。** 本次初始错误明确为首Turn的approve180 TimeoutError；仅一个业务root、两个Tool成功并有原candidate（69.037／68.056秒），最终root cancelled seal，无正Session Advance ACK，schema保留。没有第二Turn／第三、第四Tool。

6441条SDK span完整配对、无pending；约309.676秒可见窗口中，span墙钟并集247.279秒。各组和并行span不能累加，也不等于纯网络时间。两个native进程收到initialize至返回turn/start分别22.124／23.229秒，期间各有547个重叠SDK span，并集18.672／19.639秒；peer自身逐方法响应为毫秒级。Worker loop lag中位25.34ms／p95 143.68ms；一次只读进程快照中，运行260秒、累计CPU164.49秒（包含诊断与并行Activity）。这些证据把定位重点移至本地完整校验／Workflow纯投影及SDK等待的组合，不能据此归因某个独占阶段。

现有SDK计时的边界必须保留：Session selector有1083个Query未标出kind；History读取、converter decode和原assembly raw-client关闭RPC未逐项计时；异步子Task常丢失runner调用栈。独立源码审阅确认通用Activity wrapper不会绕过exact observation分支，但额外执行原完整准入与实际call ledger；根Parent完整Worker路径静态至少三组Session事实，直接transport夹具只有两组。不能从夹具6→2外推完整Worker读取数。

异常定位把首次close直接抛出点收窄至composition `_close_subtree:938`，之后由原close汇总、bridge再包装，非外层等待超时。sealed后原Coding receipt／child-stop的非精确重复被既有不可逆门禁拒绝；日志不含原evidence内容，不据此猜字段差异、放宽sealed门禁或认定新关闭缺陷。后续cleanup RPCError与首次close分开记录。

另做零服务离线CPU测量：保存的211493字节真实Session请求，100次 `_check(full=False)` 每次约0.665ms，其中digest约0.635ms，source bindings约0.012ms；这不是实际关键链占比。双Runner完整Runtime参考模板无profile 30次共0.601秒，带cProfile三次0.149秒，主要累积在完整manifest重建；模板不是原实际Profile，不把单次样本换算为优化收益。**不再盲目减少轻校验次数。** 下一必要诊断仅针对固定同步Runtime／Session校验与compact投影代码，采用测试专用、显式启用的有界CPU聚合，不替换产品方法、不读取载荷、不新增SDK或改变权限。仅该定位缺口及受影响检查属于本批；正常首门槛、其余十二项及五项故障仍未通过／未运行。

CPU诊断夹具本地检查已完成：独立helper固定八个host code对象，采用严格id身份（不把结构相等的Sandbox code副本当原对象）；只对这些code启用START／RETURN，global UNWIND首先按固定身份过滤。64线程／128层边界、异常／丢失／fault计数、每线程CPU与墙钟及整个process窗口数字均有界；exclusive只扣除选中目标之间的嵌套，不是全callee self time。原code／产品method不替换；默认关闭、Python无monitoring时不回退trace，槽位归属和外部工具不接管，失败不覆盖业务返回或异常。已修复disabled setup异常遮蔽与结构相等副本UNWIND误入的RED，未修改产品。五个受影响模块同次95 passed／4.43秒（-Werror），零失败／错误／跳过；1277产品／测试文件前后相同，424产品仍与v20相同，独立审查无P1／P2。CPU-only实际聚合结果已在上方单列；保持原场景与期限，诊断不解锁其余矩阵。

该CPU-only诊断夹具冻结为 `frozen-candidate121-s2-v20-cpu-diagnostic`：1752公共／424产品／853测试，inventory SHA256 `02e1536c56817ebfc37b95ff9789c02780daa4075acd8461616ee8b8745228a9`。产品与原v20相同，复用原已安装wheel；私有runner仅bootstrap，显式白名单只加CPUflag、不继承模型配置。该次实际已结束，结果见上方；本段文档在冻结后同步，不声称公共文档仍逐字相同。

## v20 正常首项结果（2026-10-16，`49d26d8`，未通过）

唯一原图首项 `installed-s2-closed-observation-v20-sdk` 已结束：1 failed／428.761秒，零错误／跳过；424产品与850测试副本前后无漂移。初始 `WorkflowUpdateRPCTimeoutOrCancelledError` 是整体360秒取消传入SDK Update，不能归为独立RPC超时或approve180到期。第二root启动至随后cleanup cancel不足122秒。其余十二项正常组合与五项故障未运行，S2／P3-2保持开放。

前三Tool均成功且原result_candidate已接受，Activity各耗时46.739／48.432／44.631秒。第四个业务子Workflow已启动，但无Tool调度／开始／结果候选，不能称第四Tool已执行。第一root成功seal到Session正Advance Completed ACK为21.733秒；正ACK为Session History e213，不以e212 Accepted代替。

关闭仍未完成。首次close由原bridge任务返回CloseIncomplete，不是外层等待超时；内层具体原因仍未保存，不能证明独立关闭缺陷。三条native资源均有原停止／fence／退休／transport closed证据，三条效果均adopted，业务root为accepted2／retired2；但Session第二Turn仍6个call_start／5个call_end，末observe缺end ACK、无正Advance，且没有Registry Session close Accepted。根退休不消解Session义务，schema继续保留；fixture子进程退出不代表assembly关闭成功。

两root全部observe自首次起均携原SDK child epoch，冻结Workflow路径在mark_started前已固定完整child身份；不能把耗时归因于末observe才pin。History未保存父proof Query回包或私有分支遥测，因此仍不能实证优化分支命中，夹具Session读取6→2不等于实际RPC减少或性能改善。下一批先使用既有有界SDK／Worker计时诊断区分实际读取、校验和事件循环等待，再决定最小修复；诊断与正常验收分开。不继续同产品盲跑、不追加功能、不放宽原期限或ACK要求。

## v20 封闭CONTROL身份读集（源码及安装检查）

本批直接针对P3-2原360秒两Turn门槛，不修饰未知效果或放宽关闭要求。原真实控制链主RED先确认pack结果、所有非Session SDK Counter和Update0相同，随后Session history6不等于2失败。实现后原完整Activity入口保留；共享私有 `_read_session_node` 只复用原Run/Registry/Start纯关联，默认 `_proof` 不变。封闭集合首次从实际原节点取得完整intent／origin，并与已验证入口的root／namespace／manifest／Session origin固定；后代节点不要求业务lineage为空。

私有bootstrap和fresh保留全部原组件／配置／节点／当前描述读取；末parent reading仍取完整实际事实。所有collection SDK调用走固定只读端口，对每次await（包括异常、取消和逐History项）执行原captured checker及source／handle／service／converter／Activity／request pins。完整canonical Session身份为不可变str并由原读取端口实例固定，既不缓存SDK回包也不提供权限。末独立new raw SCV完整七事实与该身份相等、原出口通过后才pack。finally调用原captured discard，在成功／错误／取消时清除整个集合和snapshot；已捕获旧端口不再可用。默认、独立未open validator、native逐请求fresh、permission、其他mode／未pin／旧3保持原路径。

本批修订了明确的实验采样语义：完整CONTROL调用首末采样替代中间重复组，允许原Scope只读在漂移被末验发现前继续，但不允许使用结果，也不承诺逐读立即撤销。独立verifier与原类／方法、helper及端口闭包都在source pins内；历史publication4仍须匹配不可变Worker，不自动迁移保留的未知运行。

定向真实SDK形状检查覆盖原结果／Counter、原Session epoch／first／original／namespace漂移、完整Registry身份变更、source／SCV类或validate替换、假outer.validate、取消无pack及清snapshot、后代与缺祖先pin拒写。端口实例被lookalike替换的新增RED已复现并补固定实例检查。最终同次135模块回归1986 passed／289 skipped／106.38秒（-Werror），1274产品／测试前后相同。289跳过不作服务验收；首轮沙箱Unix socket限制及未闭合集合误用新getter均记录在失败日志，后者仅在所选分支使用新私有端口后原22项通过，最终在已授权本地隔离Redis／Unix socket环境复验完整受影响集合。独立源码审阅无P1／P2，Ruff／格式／空白检查通过。安装兼容通过，实际首项失败如上，不据夹具计数宣称实际360秒已通过。


冻结 `frozen-candidate121-s2-closed-observation-v20`：1749公共／424产品／850测试，inventory SHA256 `adbf5b0ad530cff2059fa2e6249b269c930d0dda136da7c3ba62d88b02382ce8`。wheel仍为dev120，SHA256 `6be9f55dc9e0a66df8f717475c1745973915c37611650c539dfefc6ddecd2bf4`。独立安装11模块173 passed／43.01秒，零失败／错误／跳过，424源码／wheel／site与850测试副本前后相同，所有导入来自安装。默认完整canonical仍为 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`；原／continued保存History离线重放通过，Provider0／服务0，不代live continuation。首次安装套件Unix socket沙箱失败单独保留，按既有IPC授权在相同集合／断言完整复验通过；所有build／test子进程退出后才可运行一次原图。验收后文档单独同步，不声称当前公共文档与冻结字节相同。

## v19 历史诊断结论（`d9bae41`；产品仍为v19）

本轮仅增加原关闭失败边界诊断，复用原v19 wheel及已安装产品；冻结1746个公共文件，inventory SHA256 `f89cfde08be85f82551eb81175e69d183da90bc9152d5167eb2a6a64450cc53f`。唯一原图运行 `installed-s2-close-diagnostics-v19-sdk` 为1 failed／482.320秒，零错误／跳过，424产品与847测试副本前后audit相同。产品未优化，不将本次样本与上一轮比较为性能改善。其余十二项正常组合和五项故障未运行，S2／P3-2保持开放。

主错误仍是原360秒scenario取消approve.sleep，非approve180超时。第一root17:01:57.185010Z→17:05:00.885200Z成功seal；携带正Advance的UpdateAccepted e200为17:05:22.382063Z，原UpdateCompleted正ACK e201为17:05:22.382079Z，seal后21.496879秒；原Activity203和消费WFT206随后结束。前三Tool均成功并有原result_candidate。第四Tool17:07:34.476059Z实际开始、17:07:49.346967Z结束，14.870908秒、ok:false／definition_mismatch，原回执只有owner／error，尚无prepared／thread／turn／result_candidate；本轮不能标为runner_outcome_unknown或业务成功。第二root在保存窗口内无seal。

新增诊断改变了下一步判断：首次close原trace是 `_bounded_task` 正在await原task，随后bridge.close:649自身抛出结构化 `CloseIncomplete({deployment_coding:[{phase:original_coding_close,code:close_incomplete}]})`；不是 `_bounded_task:723` 的外层TimeoutError翻译。原任务done后被既有drain清除，因此快照中没有活跃coding_stop_task。并行release Activity的query堆栈不能当作它的等待因果；跨shield的静态帧同样不提供任务关联。bridge保留code但丢失内层report仍是诊断限制，不据此猜测具体内部错误。

本次四条native资源均已有封闭证据（三条正stop、一条正unprepared），effects为3 adopted＋1 dispatched且无原结果evidence／adopted digest。未知leaf原四对call_start／call_end、handler结束ACK均完整，本轮不声称它仍缺原end ACK；实际效果未确认仍独立阻止退休。最终assembly关闭失败，cleanup重试RPCError，accepted2／retired1／retained1，Session关闭证据不足，schema保留；fixture子进程退出不替代assembly关闭或原调用fence。**保留行为有依据，独立关闭缺陷尚未证明。** 不为追逐不同关闭窗口反复运行服务或放宽unknown要求。

下一修复只针对原360秒完整两Turn门槛。只读架构复核允许研究“单次exact Coding4 CONTROL observe封闭Session身份读集”：原完整Activity入口不变，中间保留所有原Run／Registry／Start／祖先／当前child读取与固定完整身份关联，最终独立raw SDK七事实和全部原出口通过后才返回。此候选尚未实现，当前保留每组七事实的契约仍有效；不能只删除校验或声称采样语义完全相同，不能影响native逐请求fresh、权限及写操作。先完成狭义设计、反例和独立审查，再实现和复验；不启动第二次同产品诊断。

## v19 CONTROL 只读冷验证候选（2026-10-16，安装通过／实际首项失败）

源码本地提交 `4d72895`，metadata仍dev120；冻结1746个公共文件，inventory SHA256为 `a5717970302584b7aedb31d90c8027349f8a6f15dc5a3b0044d41ad6d8e452da`。安装后八模块143 passed／29.94秒、零失败／错误／跳过，424产品文件源码／wheel／site及847测试副本前后相同，所有导入来自安装目录。wheel SHA256为 `5913d9a324413dbea7ffcbc5a54691a758883e57630b44d35130e2700d5e42ff`。默认完整canonical仍为 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原／continued保存History离线重放通过，Provider0／服务0，不代live continuation。所有离线进程退出后只运行一次原图首门槛，结果1 failed／466.580秒，零错误／跳过，424产品和测试副本前后无漂移；验收文档后续另行同步，不称与冻结公共文档逐字相同。

v18剩余阻塞的离线定位分开记录：原native22工厂的单个只读方法，在单／双Runner SDK形状fixture分别约69.82／107.83毫秒process CPU，4次Runtime full、2组完整Session七事实、27次SDK事实读取；实际composition23深度1与更大Manifest不同，不能外推实际45–58秒Tool耗时。原完整双Runner Runtime的3次full带cProfile约0.155秒，实际保存Session的intent／command查询各30次CPU均低于0.1秒，也不支持单靠JSON／复制解释整体期限。未据此修改权限、缓存或数据库。

原CONTROL真实验证／proof／SCV链、只替换SDK传输边界的冷observe中，完整Runtime端口76次：原Activity gate8、ctor4、pre-body46（其中bootstrap31）、composition body2、post-parent proof／policy6、出口validator9、最终Runtime1。SDK形状fixture的Runtime端口只作等值检查，不能把其耗时当作真实组件重建CPU。原约33.108秒工具交接含两个observe、register与后续child启动／审批；第三Tool完成后20.373秒含三次observe，分别处于context／model收尾及最终成功状态，不能删除这些合法阶段。

修复仅在原完整Activity证明后、exact Coding4、固定child namespace／first／current epoch及实际 `ralf.temporal.control.v1` 时选择私有 `_ObservationValidation`。复用原bootstrap／fresh所有SDK读取与纯关联，专用入口自身直接完整Runtime固定Manifest入／出口，中间执行原local/source/claim/port/request pins；不使用调用者的假validate作完整出口。base与派生类／方法固定，委托前锚定base class和原checker code，权限与原生readset入口拒绝，任何错误／取消清snapshot／digest。原末轮parent proof、child describe、Activity／namespace／Runtime保持；缺type／非CONTROL、未pin、其他mode及旧3沿原类。该边界不宣称所有cold bootstrap仍逐await重建Runtime，也没有通用skip开关、mode token或permission缓存。

有效主RED的全部SDK Counter和返回结果已先通过，仅full76不小于76失败；修复后full37，所有原SDK Counter、六组Session事实和原pack结果相同。15项新增检查涵盖Runtime出口、source／base class／checker替换、Activity／client漂移、取消清snapshot、unexpected Update、普通public validate／permission完整检查、未pin与非CONTROL回退。独立源码审阅通过。同次132模块回归1956 passed／289 skipped／93.30秒（-Werror），1271产品／测试文件前后相同，Ruff／格式／空白检查通过。安装已通过，原图实际首项失败，S2／P3-2保持开放；以下按快照记录失败，不拼接为通过。

实际主错误为scenario→approve→sleep的CancelledError，由原整体360秒取消触发，非approve180超时。首root16:43:31.505343Z→16:46:37.099455Z成功seal，185.594112秒；两Tool46.705303／46.799534秒成功，交接29.795237秒。Session携带正Advance的UpdateAccepted为e200，真正UpdateCompleted正ACK为e201 16:46:58.954866Z，seal后21.855411秒；Activity203与消费WFT206随后完成。第二root16:47:12.534714Z开始，第三Tool44.210528秒成功；第四Tool16:49:07.866628Z实际启动，root取消16:49:24.046948Z先到，最终46.581249秒完成、ok:false／runner_outcome_unknown，没有thread／turn／result_candidate。第三→第四Tool交接41.747054秒，第二root保存窗口内未seal。三笔native提交不代替完整业务成功。

37个CONTROL scheduled均匹配原owned call-start的实际activity_name `ralf.temporal.control.v1`，0缺失；保存History没有构造器、Query返回或Runtime计数，不能宣称专用分支实际命中或实际76→37。首root较v18单样本更快，不能推断稳定性能或归因；seal→ACK仍约21.86秒。

两次关闭超时（原60秒、cleanup40秒）均由 `_drain_execution` 等待同一 `_coding_stop_task` 的 `_bounded_task` 产生。通用“Original Worker startup or shutdown remains owned”文案不能证明Worker shutdown失败；此时Session close和 `_finish_worker` 尚未执行。保存的顶层pending为bridge.close、Runner._retire及SCV.read，无法确定嵌套SDK操作。四native资源均pending_stop:false、stopped／fenced／retired／transport_closed:true，但effects为3 adopted＋1 dispatched；第四leaf原handler结束ACK已存在，随后ralf_coding_stop的call_start在保存窗口没有call_end ACK。physical正证据不能清除原effect／mechanical／end义务。cleanup为assembly_close_succeeded:false、accepted2／retired1／retained1、schema_retained:true，拒绝原因root_retirement_unconfirmed／scoped_session_close_unconfirmed／session_evidence_invalid／unadopted_write；workers_exited:true只覆盖fixture子进程poll，不证明assembly shutdown或原调用fence。不删除资源，不推断typed-pending回归。

本轮后续仅改fixture诊断：首次close异常、Worker退出前，对原coding／Session stop task优先保存最多16层内建coroutine／generator静态await帧，总任务上限32；只含basename／function／line，不读取locals、任务名或载荷，不恢复／取消原任务或查询SDK。现有控制流审阅未证实自等待环；不得在未定位SDK等待点前继续叠加性能修复。该诊断不改424产品文件、默认发布、原80／60／180／360及关闭60／40秒期限，不作为新的实际验收。 首次缺嵌套帧／缺边界快照均先复现RED，修复后四个直接受影响模块37 passed／61 skipped／4.80秒（-Werror）；61项实际服务条件未配置而跳过，不计验收。独立审阅无P1／P2，Ruff、格式与空白检查通过；424产品逐文件SHA与原v19冻结安装源码相同。本批未再次调用实际服务或模型，也未删除保留资源。

## v18 收尾候选（2026-10-16，实际首项仍超时／关闭通过）

两项修复针对P3-2原图期限与owned close阻塞。三子树读取使用真实Session／Parent／Run State、原admission／closure／seal与原SDK形状：原v17完整树有13组Session七事实，新封闭读取为1组，所有Run／Registry／Start读取Counter和返回证书逐项相同；独立raw verifier不可被outer validate替代。19项覆盖成员intent／origin、终末Start／epoch、源码／类替换、缺seal／pin、取消及普通4双轮保持。通用proof和sealing未引入skip，原生每请求fresh保持。

关闭主用例对合法原夹具／HEAD源码复验RED，早期pure physical pending即使在同次末扫后root／child均正停止仍失败。修复仅在exact Coding4／binding23延后这类本模块标记，保留全部hard错误；原最终resource／ancestor adoption后只读fresh整树与原资源正验证，缺child／resource、变epoch、unknown／未停／缺ACK仍拒绝。18项新检查通过，新增只读helper纳入原Worker指纹；不新增cancel／drive／Update、attempt或期限。该RED不证明v17实际CloseIncomplete的唯一来源。

独立实现与夹具审阅无阻塞。同一候选131个受影响模块1941 passed／289 skipped／88.74秒（-Werror），1270个产品／测试文件前后相同；跳过不作实际服务验收。Ruff、格式与空白检查通过。源码本地提交 `85dce98`；冻结1745个公共文件，inventory SHA256为 `b7e190ff8b89c80ece6f74cdd11701c2c302c7c246952ebb36ba583f697eafbe`。424产品文件在源码／wheel／安装中相同，846测试副本前后相同；安装七模块128 passed／22.33秒、零失败／错误／跳过，所有导入来自安装目录。wheel SHA256为 `b9664d07a1b0596af5b75b4ebb2b7ff3d9a6fc15178843d3110fc61651232a1f`，metadata仍dev120。

默认完整Profile／identity／Manifest／orchestration canonical仍为 `9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原／continued保存History离线重放通过，Provider0／服务0，不代live continuation。

实际 `installed-s2-closed-tree-v18-sdk` 首门槛1失败／390.395秒、零错误／跳过，424产品／846测试冻结副本前后相同、所有导入来自安装。primary／initial均为scenario76→approve370→sleep665的CancelledError，发生于原360秒整体取消，不是approve内部180秒超时。首root于16:05:03.871527Z开始、16:08:27.074221Z成功seal，耗时203.202694秒；第一／第二Tool分别45.936381／49.222193秒，均有原stop、result_candidate及成功结果，交接33.108373秒。携带正Advance的call_end Update于16:08:48.887159Z接受，seal→end接受21.812938秒，正ACK、原Activity及WFT消费随后完成。

第二root于16:09:04.113051Z开始，第三Tool16:09:37.711754Z→16:10:35.486385Z，57.774631秒成功；原stop与候选均在完成前记录。原root直到16:10:55.859508Z观察到该child成功；第四child的register16:10:55.940365Z→16:11:00.105125Z与整体取消交错并返回definition_mismatch，没有第四child Started或Tool调度。第二root16:10:58.966034Z记录cancel，16:11:03.073819Z以cancelled seal。最终三笔native业务提交不代替完整两Turn成功。与v17单次样本相比首root慢11.217768秒、seal→end接受短2.409474秒；不作因果、RPC数或稳定性能结论，SDK History未记录Query返回及reader私有分支命中。

本轮owned关闭成功：`assembly_close_succeeded:true`、`close_error:null`、`workers_exited:true`，原accepted2／retired2／retained0，Session关闭与原树／资源清理证据成立，deletion_allowed:true、reasons空、evidence_errors空，schema_retained:false。该实际证据关闭本轮cleanup错误，不能证明typed-pending内部条件实际命中或旧v17资源已获删除授权。旧快照恢复资源继续保留。原80／60／180／360期限、native逐请求fresh和全部停止／ACK门槛保持；其余十二项正常组合及五项故障未运行。S2、P3-2与第三阶段仍开放，下一步仅定位原执行／交接的累计耗时。验收后文档单独同步，不冒称与冻结1745个公共文件逐字相同。

Session retention History离线逐command／begin_call／end_call／recover_deployment_result重建及原ACK逐项匹配：两Turn各6 start／6 end，最终busy:false、active_run:null、pending_calls0、unpublished_turns0，两entry均published。首Turn发布succeeded，第二Turn发布cancelled，不能当作两次业务成功。e204／e389为携带正Advance的call_end UpdateAccepted，e205 16:08:48.887177Z／e390 16:11:14.963162Z才是原UpdateCompleted正ACK（recorded:true／body_stopped:true）；seal→完整ACK为21.812956秒。两root原closure ready:true／reasons空，call ledger分别20／10项，未停及缺end／fence均0；保存资源3项均pending_stop:false、stopped／fenced／transport_closed／retired:true，3 effects已adopted。此分析只读本轮保存证据，未新增服务请求或对旧资源执行删除。

日期：2026-10-15。按 [P3-2 固定计划](../../docs/superpowers/plans/2026-10-15-temporal-deployment-sessions.md)收尾，仅本地开发与提交，不推送。S1 普通 Session 功能子集已在 `4fdd5ae`、`8e33b9a` 记录；本批继续接通既定 Coding Session，不引入新编排、适配器或执行权威。

## 当前结论

当前以顶部v19为准：S1普通Session功能子集已验收；S2首图仍因整体360秒未完成两Turn，第四Tool为unknown，Coding close未排空、第二root未退休、schema保留。其余十二项正常组合与五项故障未运行，P3-2及第三阶段开放。下方v17及更早结果为历史证据，不覆盖当前状态，不把单次耗时差异归因于特定优化。

v17 `frozen-candidate121-s2-read-groups`：1743文件／424产品，inventory `0ebe1405a0340979d46c8b77c037466989939502de8b94fa17255a118218186e`，wheel SHA256 `8dba36a020238553d6037c51ee56dae1cb3fd1db32eff2692e6543b1495f774f`。独立安装五模块91 passed／11.39秒（-Werror、零失败／错误／跳过），424产品及844测试副本前后一致，导入来自安装。默认完整canonical与原值相等，原／continued保存History离线Replay通过，Provider0／服务0，不代表live continuation。

v17实际首项1 failed／432.076秒、零错误／跳过，424产品和测试前后无漂移。首root15:18:24.611015→15:21:36.595941成功seal，191.984926秒；前两Tool48.236686／43.243227秒，交接33.603793秒。Session正encoded ACK15:22:00.818353（seal后24.222412秒），Activity15:22:01.054201完成，WFT15:22:01.227124消费；第二Turn15:22:09.054接受，第二root15:22:16.019173启动。第三Tool15:22:48.883619→15:23:36.302553，47.418934秒，三个Tool均ok:true与原candidate／stop。第四child15:23:59.712372实际启动，但没有批准或Tool调度；primary15:24:13.253为scenario360取消approve.sleep。第二root收到cancel后15:24:36.053584以failed seal，15:24:43.666正退休。与v16比较仅为两个单次运行，不构成性能因果或稳定SLO证据。保存carrier和最终child_execution符合直读分支条件，SDK History没有Query回包或分支marker，不称为直接命中计数。

Session首Turn6对start／end；第二Turn6start／5end，末observer start ACK15:24:44.466961后无end／Advance。11个完成Activity的原return与对应end语义digest全匹配；首Turn编码语义2448126B与原digest匹配。初始owned close报CloseIncomplete，报告phase=original_coding_close；生命周期在Session关闭前重抛，Registry没有close_deployment_sessions Update。retention helper的require(records)直接EvidenceMismatch，未进入session_evidence／State reducer，所以不能称为新State／codec拒绝。Worker退出后重试Registry配置查询RPCError；唯一Session body诊断为FAILED_PRECONDITION，位置树读取／原祖先proof中的readonly query。cleanup为assembly_close_succeeded:false、workers_exited:true、accepted2／retired2／held0、deletion_allowed:false，reasons为scoped_session_close_unconfirmed与session_evidence_invalid，schema保留。没有证据证明本批local-pin检查造成State缺陷，也没有证据排除其上游耗时影响；Session债务必须保留。

v16 `frozen-candidate121-s2-session-boundaries`：1742文件／424产品，inventory `52eb0156c67ba0003ceff9abcb2374bf4fe1b49122c8a913253c11fe41872fd8`，wheel SHA256 `ff04c96f17364d7561cd82b2cf5c55400010fa1f68248280f7f6a2034ccf4b5e`。独立安装四模块79 passed／9.40秒、-Werror，424产品及843测试副本前后相同，导入均来自安装。默认完整canonical与原值相等，原／continued保存History离线Replay通过，Provider0／服务0，不代表live continuation。

v16实际图首门槛1 failed／386.44秒、零错误／跳过；424产品和测试前后无漂移。首Turn applied14:48:02.870至正Advance／ACK14:51:59.534，第二Turn14:52:06.930已接受，证明第一Turn已发布并解除占用。三个Tool分别49.570947／43.645311／47.214290秒，均ok:true与原candidate／stop证据。首root14:48:08.588990开始、14:51:28.054560成功seal，耗时199.465570秒；两Tool交接35.248867秒。第二root14:52:14.249630开始，首Tool成功后仍需三次观察（6.599615／6.500831／5.028370秒），第二child register14:53:54.901560开始；14:53:59.594842整体取消先到，注册以definition_mismatch返回，第四Tool未运行。主堆栈为scenario360取消approve.sleep，不是内部180秒TimeoutError；原80／60／180／360期限均未改。

原Session每Turn各6对call_start／call_end，12个Activity返回与原ACK语义digest全部相符。成功Turn的编码wire786224B／语义2450877B，cleanup取消Turn编码wire379873B／语义1194007B；两者均正Advance／released:true，第二Turn为cancelled，不能算两Turn业务成功。原runner cleanup为assembly_close_succeeded:true、workers_exited:true、accepted_roots:2、retired_roots:2、retained_roots:0、deletion_allowed:true、reasons:[]、schema_retained:false、unexpected_retention:false。清理器实际修复成立，原v15失败资源不受影响；该结果不能关闭完整正常矩阵或五项故障门槛。下一批只处理已定位的交接／观察累计耗时，不调大期限或扩展能力。


v15 `frozen-candidate121-s2-observe-readset`：1741文件／424产品，inventory `b2c29e53608e5f09a6e1eff78ec79fd8a43b9c25dddae9d662102bb7ddbfaf51`，wheel SHA256 `e4675aa292556f4d4c6ffcde6587be4a6768ae84ea27230fda4ac6b72302e7e0`。独立安装两模块32 passed／3.04秒，-Werror；424产品与842测试副本前后无漂移，导入均来自安装。默认完整canonical与原值一致，原／continued保存History离线Replayer通过，Provider0／服务0，不代表live continuation。
v15实际graph-sequential 1 failed／278.43秒、零错误／跳过。两个Tool分别55.064416秒／51.206474秒，原join成功读回晚于超时诊断文件，root最终succeeded并正退休。cleanup记录assembly_close_succeeded:true、workers_exited:true、retired_roots:1、retained_roots:0；schema仍保留且deletion_allowed:false，唯一拒绝原因session_evidence_invalid／KeyError。原Session有6次call_start／6次call_end，无未结束调用。最后observe的语义body2447868字节，编码Update body785015字节，Activity完整wire786068字节；两处解码digest均为 `823b7f408f91774bd0c3f327ae17063198d953f27c2f4aaf3c814e722c91e70f`，与原end.body_result_digest相符。实际编码门槛已有正向证据，但整图／两Turn与删除门槛未过，不删除原schema。
清理器缺陷已复现：State.end_call先验证／解码，随后测试读取器仍以原封套访问body['ok']。修复只在State完整校验后用相同Manifest解码；完整History重建及篡改／缺ACK／未退休保留两模块36 passed／10.63秒（-Werror），未接服务或删除资源。warm重复完整Runtime校验另有十模块179 passed／8.08秒。上述源码检查不代替新冻结候选的安装／实际图复验。

修复后的同一清理器还对v15原保存的203-event Session History完成全部离线重建：原Registry接受／退休、调用ACK、Advance、receipt及最终pending_calls／unpublished_turns为零均通过。没有实时SDK查询或删除schema，原失败cleanup记录保留；该结果证明读取器能处理原实际证据，不单独授权当前资源删除。

当前源码的有限聚合分两层。warm Coding callback仅在原完整binding／submission Manifest与外层固定配置相同时，将内层重复Runtime重建交回既有两次独立外层完整检查；cold／public／permission保持原full，七项SDK事实及逐await pins保留。只读Session observer仅对exact Coding4、binding22／23启用组内读取：每次SDK await前后仍完整本地pins与Runtime检查，组内不再每项重复七事实；原proof／closure／tree／descendant组出口、最终出口、独立origin verifier及owned body／end ACK的完整七事实检查保持。普通4／默认wrapper仍逐项完整validate；选项严格bool且固定原选值，原资源与wrapper源方法进入既有pins，无Update端口、权限缓存或新状态机。真实_observe的主RED逐read10→11次完整校验，修复后native／composition正Advance及ordinary对照通过；追加选值漂移拒绝后四模块同次86 passed／4.87秒。最终受影响Session／Coding回归同次860 passed／193 skipped／53.01秒（-Werror），193项配置依赖跳过不作为真实服务验收。独立审查、Ruff／格式／空白检查通过；此为v16实际运行前的源码记录；最终两Turn仍整体超时，结果以上方v16 checkpoint为准，原逐原生请求fresh及全部期限未改。

## 实现边界

v17关闭候选另行核对：原close末段继续对root子节点采纳正stop，最后一项15:24:48.922，随后15:24:49.076报CloseIncomplete。较晚的15:25:19 PG捕获中三resource均pending_stop:false且stopped／fenced／transport_closed:true，三个effect已adopted；这是较晚快照，不能倒推49.076时每项都已正闭合。源码 `_close_subtree` 保留早先pending、`composition.close` 累计早先obligations后在末轮资源／祖先adoption之后仍据旧列表拒绝，构成需要定向TDD的候选；bridge把内层report压成单code，现有实际证据不能唯一确定命中分支。下一批必须以原fresh完整身份与真实闭合证据区分已消解pending和仍有效错误，不靠退休额度或放宽证据“修复”关闭。

v17源码收尾只针对v16累计期限。按原三child正观察路径静态推导，wrapped SDK读至少159次，v16逐读前后造成至少318次额外完整Runtime重建；该下界不是实测RPC总数或性能。现exact Coding4 aggregate transport每读保留source／client／service／converter／Activity／request pins，使用full=False，完整Runtime复核留在既有group及最终出口；独立origin七事实与其full、owned body和end ACK均保持。普通4/default逐读原full不变，最后descendant session_proof与后续组／最终出口共同保护，不提前返回Advance。主RED native／composition每SDK额外重建2次→修复后0次；17项测试验证真实_observe在Runtime漂移时仍于完整出口拒绝，并覆盖逐读源码／请求／端口／Activity及逐History项漂移。

同批compact observe仅在exact Coding4、原child非空固定epoch和完整namespace／first／current child_execution匹配时，保留原first Activity proof与完整Coding validator，直接调用原composition.control＋既有拒写client；省去中间重复桥验证。末current parent proof、child describe、validator、Activity／namespace／Runtime及pack完全保留；missing pin／其他mode／旧3仍走桥。实际生产reader和proof的SDK形状夹具RED父Activity验证2次→1次，结果与原桥exact相等；9项含出口Runtime／namespace／父子身份／原pin／源码漂移及冷写拒绝，底层Update0。静态每合格observe至少省16项重复SDK读取，不把该下界换算成秒数。两项产品合并经独立审查，最终受影响回归同次959 passed／193 skipped／55.06秒（-Werror）；跳过不作为实际服务验收，Ruff／格式／空白检查通过。此为v17运行前的源码证据；随后安装／离线兼容通过，实际两Turn仍整体超时、关闭未完成，结果以上方v17 checkpoint为准。原80／60／180／360期限与native逐请求fresh保持。

- 显式 Session＋部署准入＋Coding 使用 publication4／Registry4，旧默认选择保持。同地址不兼容 Registry 拒绝，不换地址规避容量。
- native6／binding22、composition7／binding23 请求与库存形状保持。实际 SDK parent 是原 Session coordinator，业务 lineage 不把它计作业务父节点或根额度。
- 原 intent、首次信封、Scope、namespace、原始／首个／当前 epoch 关联真实 SDK 证据。Registry 管准入和退休，原 Run／Parent History 管业务、预算和效果，Session History 管串行 Turn 与发布。
- owned 关闭先完成 Coding 物理收尾、Session 排空、原调用及退休，再退出 Worker。未知效果、缺 ACK 或 CONTROL 进程死亡不因终态而清除。
- 测试资源清理只读原 SDK History，复用原 Session 状态规则验证调用结束、正退休及关闭证据；缺证据保留原资源。

## 分快照证据

| 检查 | 结果与限制 |
| --- | --- |
| 首轮受影响 Temporal 回归 | `s2-first`：3226 passed／584 skipped，138.59秒；232模块，冻结源文件前后不变，未启真实服务或模型 |
| 配置与 Registry | 170 passed；所选组合、原 Coding admission 索引及普通4隔离 |
| 生命周期与 bridge | 124 passed；原 stop、scoped close、真实配置版本及 owned 接收责任 |
| ancestry／compact | 220 passed；旁置 origin、真实 SDK parent、Registry 配置与业务 lineage |
| 第一轮安装 Agent | 1 failed，Session 激活延迟导入纯 Coding inventory，未进入业务执行；失败与原 History 保留 |
| 沙箱修复 | 初始加载预载纯 inventory；native6／22、composition7／23 激活 RED→GREEN，98项定向通过，未扩大 sandbox 权限 |
| 第二轮安装 Agent | `s2-sandbox`：1 failed／222.51秒；原工具进入 waiting_reconciliation，保留未知效果、占位和恢复数据；其余十二种组合未启动 |
| 计时复现 | 同一安装产品及现有脱敏计时夹具复现握手期限问题，部分 preflight 已回应、未提交业务 Turn；不作正常验收 |
| 原生相邻校验修复 | publication3 专用优化遗漏 Coding4，造成重复 fresh；RED→14项通过，相关本机进程回归217项通过，普通4仍隔离 |
| 只读集合校验修复 | 完整组件检查放在 SDK 读取集合入口／出口；逐 await 原 pins、全部7次事实读取保留；此快照读取顺序不变。43项通过，模拟组件漂移均阻止返回授权 |
| 离线 CPU 测量 | 完整 native factory、零延迟 SDK 形状读取：174.82→39.60毫秒，约4.42倍；不代表端到端延迟或线上吞吐 |
| 退休与发布补齐 | Coding4 的 release closure、Parent CONTROL 和 Session Advance 仍有普通／旧3分流遗漏，已分别补齐；定向153、51、94项分别通过。v3／v4实际失败均保留，v4已正退休但未发布，不能据此当作完整Turn通过 |
| v4 受影响回归 | 3272 passed／589 skipped，137.97秒；239模块。后续v5只改Session Advance，因此不冒称v5全量 |
| v5 安装相关回归 | 589 passed／241 skipped，37.35秒；63模块、340已加载模块来自独立安装路径，424产品文件前后一致 |
| v5 实际 Agent | 1 passed／215.995秒，零失败／错误／跳过；两Turn、两次业务写入、四次原生提交，审批／重复命令、原父身份、退休和会话发布通过。清理证据成立，测试schema已安全删除 |
| v5 默认兼容 | 完整默认Profile／identity／Manifest／orchestration与原快照相等；保存的原／continued History重放通过，Provider0／服务调用0，未重跑live continuation |
| v5 组合矩阵 | 两个隔离进程各首项失败：顺序工具80秒超时；Dynamic-flat 的完整 Session origin 被旧 metadata1 子调用校验拒绝。各自后五项未运行，不能称十二项已完成 |
| 子调用身份修复 | 完整 metadata2 复用原纯 Session origin 校验，业务 lineage、Scope、namespace、原父身份保持；RED→GREEN，117项定向通过，Parent sandbox 激活无延迟导入 |
| Coding4 只读并发 | 首批四项独立 SDK 读取并发，全部七项事实、Start／queue 校验、最终 CURRENT describe→namespace 与完整入口／出口保持。失败和取消等待读取全部结束；13项定向、120项相关回归分别通过，双人审阅无阻塞，不提高原期限或缓存权限 |
| v6 受影响回归 | 3313 passed／589 skipped，137.25秒；242个Temporal测试文件。全部1729个冻结文件前后哈希一致，未启外部服务或模型，skip不作服务验收 |
| v6 实际 Agent | 1 passed／184.12秒，零失败／错误／跳过；两Turn及原身份／效果／退休／发布断言通过。424个产品文件前后一致，340已加载模块来自独立安装；其余矩阵首两项失败，后续十项未运行 |
| v6 组合矩阵 | 两进程各首项失败：sequence-json 363.42秒、dynamic-flat-toml 510.42秒，后续十项未运行。原生业务提交分别4／2次，但后一个动作缺最终结果候选；原Activity完成返回tool_error，无ActivityTimedOut。关闭失败及原未知效果／schema保留，不计完整Turn通过 |
| v6 隔离计时复现 | 相同安装产品，sequence单项281.95秒失败。测试native响应毫秒级，重复SDK校验在请求之间占用较多时间。第二个native执行的首个SDK读取至取消相隔60.0069秒，吻合原Runner60秒期限，取消发生在原adopt的fresh校验内；此证据属于该计时复现，不反推其他运行的具体异常。诊断不作正常验收，未修改产品期限或放宽授权 |
| 同步 selector 复制定位 | 原真实167KB intent：selector重复6次完整复制，command／intent查询各8次；每同步方法复用一次隔离快照后分别1／2／2次，CPU中位约4.64→1.03、5.95→1.65、6.04→1.53毫秒。此为局部CPU测量，不等于服务延迟或完整链路通过；全部字段校验、隔离语义及SDK读取保持 |
| v7 安装验收 | 原失败sequence-json优先复验：1 passed／306.23秒，零失败／错误／跳过。两Turn、四次业务写、原结果采纳、退休／会话发布和安全清理通过；424产品文件前后一致、340已加载安装模块来源已核验；原80／60秒期限不变。其余矩阵Agent单项通过；graph-sequential失败、dynamic-flat失败，后续九项未运行 |
| v7 图失败定位 | first child原Tool在80.004秒发生真实SDK超时；thread／turn／terminal观察已记录，原final-read／candidate缺失、effect仍dispatched，后续approve180秒是下游等待失败。未知效果与schema保留 |
| v7 动态失败定位 | 两Turn的Tool均成功、两effect已adopted、两root已退休；第二次首次Session observer持久返回session_control_failed且ACK完整，未发布。原身份显式重试得到正Advance／发布并安全清理；不是native预算／2MiB拒绝。底层异常未保存，继续定向诊断 |
| v7 observer 诊断尝试 | 相同安装产品的单项脱敏PY_UNWIND探针505.07秒失败，停在approve，未取得目标observer底层异常；不作正常验收，不据此判新根因 |
| 原启动握手优化 | 仅selected Coding4在initialize／initialized后并发固定8项独立只读请求，每请求保留原fresh校验；全部成功后才校验完整profile／进入业务，失败／取消先排空。RED→265项相关检查通过，原3／普通4／Local仍串行；实际性能与组合待验 |
| observer可诊断性 | 原错误返回与ACK不变，增加有界脱敏异常类型／RPC状态／静态位置日志；不记录消息、参数、locals、payload。71项相关检查通过，日志handler失败不改变原业务／ACK，实际异常仍待捕获 |
| v8 安装首门槛 | `installed-s2-preflight-sdk`：graph-sequential 1 failed／369.12秒，零错误／跳过；其余十二项未运行。424产品文件前后一致、340已加载模块来自独立安装；失败与原恢复资料保留 |
| v8 图失败定位 | 原Tool发生80.002秒真实SDK Activity超时，turn receipt距执行开始77.20秒；无terminal observation／result candidate，effect仍dispatched、根额度保留。prepared→thread grant为21.686秒，未显示相较v7加速，不能据此宣称并发握手改善实际性能 |
| v8 安装定向与离线兼容 | 安装后两个新增测试模块14 passed／1.87秒，-Werror。默认发布canonical SHA256为`9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，与原快照相等；原／continued History离线重放通过，Provider0／服务0，不代表live continuation或组合验收 |
| v9 最小origin合并 | 仅删除`CodingValidation._fresh`首轮重复origin校验两行，保留bootstrap、集合末尾完整七项事实及实际Query／Update／SQL／native I/O双边验证，无缓存。RED为3 failed／5 passed；相关检查93 passed／4.24秒，另一次独立复核84 passed／5.04秒，不相加为全量或服务通过 |
| v9 安装首门槛 | graph-sequential 1 failed／365.94秒；其余十二项未运行，故障场景未执行。424产品文件前后无漂移、340已加载安装模块来源已核验；原Tool在80.002156秒真实SDK Activity超时，terminal observation为75.92秒，无result candidate，effect仍dispatched、额度及恢复资料保留。局部时间变化不代表完整链路通过 |
| v9 observer日志 | 脱敏日志捕获`RPCError／CANCELLED`，位置为`control.operation:113`：begin之后、body之前的第二次validate，经verification早期gather进入_namespace。此为独立observer读取失败证据，不是主Tool超时的已证根因，也不是成功Advance采用失败 |
| v9 安装定向与离线兼容 | 安装检查22 passed／2.57秒，-Werror；默认canonical等值，原／continued History离线重放通过，Provider0／服务0。各项与真实首门槛失败分别记录，不称v9已验收 |
| v9 受影响回归 | 245个Temporal模块：3355 passed／589 skipped／2 failed，143.94秒，冻结产品源码前后不变。两项失败为相邻native测试保留了旧的内部origin次数预期；测试修订为明确断言bootstrap加实际Query前后验证，并与新origin测试同次22 passed／3.33秒。产品未因此改动，不将两次运行拼为一次完整绿色回归；589跳过不作实际服务验收 |
| v7 安装相关回归与兼容 | 八模块155 passed／6.52秒，-Werror、零跳过；完整默认发布相等，原／continued History离线重放通过，Provider0／服务0 |
| v6 默认兼容 | 完整默认Profile／identity／Manifest／orchestration等值、原／continued保存History重放通过；Provider0／服务0，无live continuation |
| 测试清理与诊断 | retention32项、Worker异常保留32项分别通过，交叉审阅无阻塞；body与close原异常均保留 |

## 候选与剩余门槛

v14 `frozen-candidate121-s2-control-body-codec`冻结于本地`91a7837`：1740文件／424产品，inventory `583fdcbed44e21f1ed9e669189d4ab36099e1717da3be78c289e8de8cf5d5150`，wheel SHA256 `0b96f87e073fb400da065b5eedb38cee2d76e23b33b734d4be8f5953db03a316`。独立安装新增两模块37 passed／6.70秒（-Werror、零失败／错误／跳过）；source／wheel／site及841份测试副本前后字节一致，默认完整canonical仍为`9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原／continued保存History离线Replayer通过，Provider0／服务0，不代表live continuation。

v14实际graph-sequential仍1 failed／308.83秒，零错误／跳过，424产品及测试前后无漂移、339已加载模块来自独立安装。主异常是approve辅助等待180秒超时，两个Tool分别53.223301秒／60.000258秒完成且`ok:true`，均有原result_candidate／stop收据。父release Activity约29.17秒后返回`deployment_release_failed`，原root退休未确认。owned关闭先CloseIncomplete，Worker退出后重试为RPCError／Timeout expired；最终cleanup为schema_retained、deletion_allowed:false，保留pending Registry Update、未确认退休／Session关闭及原证据，不能称清理完成。其余十二项正常组合与五项故障未运行。

v14保存的Session History只有5次call_start／5次call_end：两register原body分别212144／212496字节，其余三observe为160字节的pending结果；最后end在13:45:42.742924 UTC，之后为wake Signals，没有大结果observe完成。全部保存History编码标记为0，无PAYLOADS_TOO_LARGE；故本次没有命中编码正向路径，不能据错误未复现关闭2MiB实际服务门槛。源码及安装codec证据继续有效，服务证据仍待。

主流程结构定位来自独立的v13原History：首次批准13:14:58.178至父观察最终子成功13:18:00.169共181.991秒，两Tool合计127.831465秒，中间交接40.901435秒。父12次observe累计83.750秒，部分与Tool重叠，不与Tool耗时直接相加。源码下界为每observe三轮fresh至少39项事实、四轮完整root proof至少52项，合计至少91次SDK事实读取；12次至少1092项，不含其余bootstrap、physical及namespace读取。Query不入History，这不是实测RPC总数。下一项将固定child epoch的Coding4 observe中相邻的只读describe与完整校验归为一组；前置execute.validate_activity、bridge前完整bootstrap／fresh、末轮校验及其他模式保持。审阅未发现该重排跨过grant／Update，但仍须RED→GREEN和安装实际验证，不据此预判主超时已解决。

该有限重排已实现：仅exact整数版本4、observe及原SDK proof中的固定child epoch，将describe前的一次validator.validate移至其后的既有完整校验集合，三轮变两轮；constructor固定资源／源码／Activity／请求及完整Runtime检查保持。最前execute.validate_activity仍完整完成才发只读describe，DTO核对后必须完成bootstrap＋fresh才进入bridge，末轮不变；register／cancel／recover、epochNone及旧3路径保持。真实CodingValidation（非伪造validator返回）的主RED为3轮及旧顺序，修复后相关六模块同次115 passed／6.97秒，-Werror、零失败／错误／跳过；含during-describe Runtime／namespace／父子epoch及SDK端口漂移在bridge前拒绝和其他模式／旧3对照。独立源码审查、Ruff、格式与空白检查通过；该增量尚未冻结安装或运行实际门槛，不从读取预算减少推导真实延迟或关闭成功。下一批只复验原图首门槛，单次服务检查此前约5分钟；通过后才运行剩余十二项及五项故障，缺陷修复耗时不作确定承诺。

当前有界修复只针对v13取消后另行暴露的2MiB恢复传输限制：exact Coding4且原body大于512KiB时，将canonical JSON经zlib/base64编码到exact版本信封，整个信封至多1MiB，解压至多原8MiB加1字节探测；尺寸、摘要、canonical、EOF及尾随数据全部校验，禁止无界flush或截断。结束确认Update与Activity返回两处均使用该编码；State先解码再按原digest及完整语义校验记账，Workflow先解码再校验ACK并处理结果。原Update ID、semantic digest、冷恢复body和ACK保持；普通4及小结果保持raw，旧raw仍接收。新增四个codec源码绑定沿原factory／validation前后检查，await中替换会被拒绝。新wire需匹配不可变Worker，不能宣称旧Worker可直接热接续新编码。

这项修复的主RED分别为codec API缺失、合法大Advance的end_call／Workflow尚未解码，以及codec源码替换未被原pins拒绝。最终相关八模块同次191 passed／10.79秒，`-Werror`、零失败／错误／跳过；覆盖原合法2,097,693字节body（合法submission仍小于1MiB）、重复ACK、冷状态恢复、Scope／摘要篡改不改账本、两处wire输出及SDK sandbox runtime激活。代码审查与Ruff／格式／空白检查通过。本轮不启动新的服务矩阵，安装及真实服务payload复验仍待；该源码结果不证明解决180秒审批等待或owned关闭。P3-2／S2保持开放，原十三项正常矩阵及五项故障门槛不删减。

后续性能修复仅针对 P3-2 的原期限阻塞。v9 的计时诊断与正常验收分开：首次探针因 Python 的非局部 monitoring event 配置错误在业务前失败，未取得 CPU 证据；修正并完成离线探针检查后，固定图诊断仍失败（396.11秒），不能计为通过。有效的首 owner 至次 owner 前采样窗口为84.722秒，不冒称完整 Activity 边界：目标函数 exclusive CPU 合计28.291秒，其中 Manifest 重建15.893秒、Runner root检查6.158秒；原生九项回应合计0.092879秒。SDK交叠区间66.226秒与CPU重叠，不相加；原函数pins均未变，探针错误为0。

已完成两项最小修复并待冻结实际复验：plain Runner 连续调用同一 root 检查时合并一次，Connected 的不同 override 与 base 保持独立；Session 校验仅在两份 intent 的 canonical digest 相同时共享本次快照，每次仍重算完整 wire hash，不同 canonical 的数值键输入保留原双快照校验。原七项 SDK 事实、逐 await pins、独立 Runtime 检查和期限均保持。定向证据分别为 registration RED 4失败／2通过→6通过、相关218通过；snapshot RED 9失败／7通过→相关137通过、最终16通过；最终两项及相邻边界同次63通过／4.99秒。各次检查不拼为当前全量，不代表实际图场景已通过。

v10 `frozen-candidate121-s2-root-snapshot` 已完成冻结与安装：1735文件／424产品，inventory `6ad18433fd38dd6170f08fc11089a5e838eb35737e45f519aec015578b923451`。源码／wheel／site 字节一致，安装定向30通过／3.86秒，默认完整canonical及原／continued History离线重放通过，Provider0／服务0。实际 graph-sequential 仍为1失败／364.31秒，但失败阶段已改变：两个原Tool分别71.409541秒、76.865328秒正常完成，均返回`ok: true`并采纳原result candidate，没有原80秒Activity超时。首次Turn的approve辅助等待在180秒处超时并发出原取消，第二Tool随后完成；第二Turn未执行，不能算完整图或Session验收。后续关闭也未完成，缺少最终cleanup报告，不声明资源清理或恢复已通过。源码／wheel／site／测试前后无漂移，340个已加载模块来自安装。

v11 候选仅合并显式 Coding4 callback 内重复的完整发布校验：外层固定 Manifest 入口／出口独立检查、bootstrap、公开 validate／permission、SessionControlValidation 的全部七项 SDK 事实及完整检查保持，资源／源码／请求／Activity pins 仍逐边界核对。主回归使用真实 Session verifier，warm callback 重建次数 RED 为11次、修复后5次；不是缓存 SDK 事实或权限。相关五模块75通过／3.58秒；加入边界回归后的同次六模块91通过／4.89秒，Ruff／格式／空白检查通过。独立审查无阻塞。实际首门槛结果另列，未通过不进入其余组合与五项故障门槛，不以局部计数代替验收。

v11 `frozen-candidate121-s2-aggregate-readset`：1736文件／424产品，inventory `a285a49afd978230142244e4f949447b21e529b88d1d83c7ae1e37eecc281efb`。源码／wheel／site一致；安装后四模块46通过／3.54秒，零失败／错误／跳过；默认完整 canonical 与原值相等，原及 continued 保存 History 离线重放通过，Provider0／服务0，不代表 live continuation。产品与837份测试副本前后无漂移，导入均来自独立安装。

v11 实际 graph-sequential：1失败／333.35秒，零错误／跳过；其余十二项及五项故障未运行。424产品／原测试前后无漂移，340已加载模块来自安装。只读原 History 核对两个 Tool 分别56.530649秒、57.576230秒完成，均有`ok:true`与原result candidate；第一 Tool完成到第二 Tool开始间隔41.476033秒。第二 child 的实际结束证明完成后开始 plain join 注册，随后180秒审批辅助等待失败并触发清理取消；join 注册结果为definition_mismatch。Root最后seal为cancelled，Registry释放该完整cancelled证书，不能登记Turn成功。owned关闭仍为CloseIncomplete，清理报告因session_evidence_invalid保留schema，Worker已退出；不声称清理通过，也不删除恢复资料。

下一项已定位的结构性重复在 observer：`_CheckedClient` 每次读取后运行完整 Session 校验，而嵌套 `validate_session_origin` 又把同一带校验客户端作为其七项验证的传输层，每项读取再次触发原校验，额外放大约49次事实读取。优先审查仅固定原 SDK 传输、继续执行原七项验证的最小修复，不增加紧凑投影、缓存权限或调大期限；该源码发现不单独证明已解决实际失败。

v12 候选仅在相同 Runtime／完整 intent 的 exact `_CheckedClient` 和 exact `SessionControlValidation` 场景固定原 SDK transport，仍构造独立 verifier 读取七项事实，并携带原 Activity info。原 outer 完整检查及 wrapper／transport／info／Runtime／完整 intent 在 await 后复核，不信任 outer.validate 返回值；其他 wrapper 与不匹配调用保留原路径，不新增协议或投影。真实读取计数 RED 为1失败／1通过（56次／7次），修复后同次四模块65通过／2.98秒；另一次原六模块88通过／3.47秒，分别记录不相加。新增11项包含七类读取中漂移、伪造 outer 回执及外部 subclass 旧路径，独立审查与 Ruff／格式／空白检查通过。实际 observer 耗时和整图／收尾门槛仍待安装候选验证。

v12 `frozen-candidate121-s2-origin-transport`：1737文件／424产品，inventory `2509ad148a65efdf7fc9644f20a61c3e6a0989d07bed1258d6e6afd63c96b3c5`。源码／wheel／site一致，安装后四模块49通过／3.41秒，零失败／错误／跳过，424产品及838份测试副本前后无漂移；导入来自独立安装。默认完整canonical及原／continued保存History离线重放通过，Provider0／服务0，实际图门槛另行记录。

v12 实际 graph-sequential：1失败／268.17秒，零错误／跳过，原180秒审批辅助等待仍超时，其余十二项及五项故障未执行。两个原 Tool Activity 都完成，但不是完整 Turn／会话通过；424产品与测试前后无漂移，339已加载模块来自安装。owned Coding 关闭先返回CloseIncomplete，Worker退出后的清理重试出现RPCError（task queue近期无poller）；最终报告Worker已退出，但root退休、scoped Session关闭与Session证据均未确认，schema保留。不能用总耗时缩短证明observer性能或收尾改善；该候选的正常图与关闭仍未验收。后续先按原History定位两个Tool之间及汇合注册的实际关键路径，再做有依据的最小修复。

v13 收尾候选针对上述主路径共用的 `_public_start_binding`：仅 exact Coding4 将首轮重复 Session 读取改为 await 前 detached 的完整预期身份，保留原启动记录／namespace 只读查询与末轮完整七项事实及结果比对。中间不发送 grant／Update／业务写，也不返回正 proof；普通 Session4 保持原两轮，旧3与默认路径保持。不增加跨层上下文、事实缓存或新执行权威。真实主计数 RED 1失败（14项事实）→GREEN（7项）；同次四模块91通过／2.27秒，另一次六模块153通过／2.64秒，各次不相加；独立审查与 Ruff／格式／空白检查通过。安装兼容、实际整图与收尾仍待该冻结候选验证。

v13 `frozen-candidate121-s2-terminal-start-binding`：1738文件／424产品，inventory `0228db22aeefbea9d77e88626e4dd999e60312fb8956b73b67969b237b1f1e7a`。源码／wheel／site一致，安装后五模块57通过／3.78秒，零失败／错误／跳过；424产品与839份测试副本前后无漂移，导入均来自独立安装。默认完整canonical及原／continued保存History离线重放通过，Provider0／服务0，不代表live continuation或实际图通过。

v13 实际 graph-sequential：1失败／343.10秒，零错误／跳过；其余十二项及五项故障未运行。两个原Tool分别65.926138秒、61.905327秒完成，均`ok:true`且有原result candidate；不能由局部读取计数推导真实加速。180秒审批辅助等待在第二child收尾观察期间超时，尚未注册join。取消后约1.09秒才收到该child的succeeded／physical_stopped:true观察；整Turn未通过。424产品及测试前后无漂移，340已加载模块来自安装；owned关闭仍CloseIncomplete、Worker已退出、schema保留。

v13 收尾载荷另有独立证据：原Root取消于13:17:59.080015 UTC，Registry正退休于13:18:10.636168；随后Session的observe已记录call_start，但无call_end接受／Activity完成。原Session History事件188／191的WORKFLOW_TASK_FAILED原因为PAYLOADS_TOO_LARGE，SDK日志消息体2121093字节超过2097152上限23941字节。该错误晚于审批超时，不能用来解释主等待失败。源码关联到`session_deployment_call_end.body_result`中的完整Advance证据，失败入参未进入History，具体Update和大字段仍为关联推断，不能写成已捕获的完整失败载荷。后续优先修复该真实证据传输门槛，完整原生逐请求fresh契约保持；不实施跳过单帧动态事实的preflight批量例外。

v5 `s2-advance` 快照1727文件／424产品文件，inventory SHA256：`d530c203d8d4f7826cc915b2184c1be48937934966bafca380aa1bf17ce6ee53`。v6 `s2-origin-reads` 快照1729文件／424产品文件，inventory SHA256：`b935d23c2abae7a156662f0e5c447b2b8f9751a0bf65e02f37875e1e06eaea74`，首个安装 Agent 通过，矩阵首两项失败。v7 `s2-selector-snapshot` 快照1730文件／424产品文件，inventory SHA256：`ef3fc59506253032671f0660a6fbe761d3a4ad93cf40ca0448afa345e67d7826`；155项相关测试通过，安装后优先复验失败的sequence已通过，原十三项集合及原期限保持。源码、wheel、独立安装424产品文件一致；metadata 仍为未发布 `0.1.0.dev120`。

v8 `frozen-candidate121-s2-preflight-observer` 快照1732文件／424产品文件，inventory SHA256：`ee5f60a4930791029e44c84af770ad0effa87580ac930ec152052726025be093`。该快照的安装失败、定向测试及离线兼容分别记录如上，不与旧快照结果相加；其记录时最小origin合并尚未验证。

v9 `frozen-candidate121-s2-terminal-origin` 快照1733文件／424产品文件，inventory SHA256：`bf084f2053d67a26dafd82d1f4a0b8a8717f0ac099c4dd7755115c860c8ecda7`。最小origin合并的单测、安装兼容与真实Graph失败证据分别如上，不能拼接不同快照为通过。

- 最新v9 graph-sequential首门槛失败，其余十二项未运行；v5／v7已通过的独立Agent／sequence与各版失败记录均保留，不推导当前十三项集合已通过。下一步针对同步CPU与SDK排队测量定位，不增加协议或放宽原期限。
- 验证原审批冷交接、退休回复丢失、显式取消及 effect／native-stop／deployment-end 独立 ACK。
- CONTROL 真正进程死亡后保留原 Turn busy、占位及恢复数据，不制造通用 fence。
- 完成最终安装、约定默认／History 兼容和受影响复验，才判断 S2／P3-2 能否关闭。

结构 native peer 证明 Temporal、PostgreSQL、原生子进程及文件效果协议，不新增真实模型质量或真实 Docker daemon 故障结论。历史真实模型及 Docker 证据按原范围引用；未知义务所需服务与数据继续由原所有者保留。
