# S2 五项失败修复与复验

日期：2026-10-20–21。基线 `3bf7f6c`；仅修复 S2 失败及测试责任，不扩能力、不推送或公开发布。正常十三项及 cold-handoff 整链 600 秒，其他四项故障 300 秒；Tool80／Runner60／审批180／first-close60／cleanup40不变。保留[原五项失败](2026-10-20-s2-600-second-gate.md)和全部360秒失败。

**当前有效状态（2026-10-21）：** 固定dev13 wheel SHA `a4f5fec1ebd0a5783e88c839984f8e582ed24529fad47cf2f7c06769bfbdd8af`；最终同包完整安装回归13819通过／891缺配置跳过，原五项同校正输入5通过／零跳过，所有输入前后SHA一致。四项关闭与清理成立，hard-kill原未知义务按精确证明保留，无意外保留；本批自有服务均停止。并行Tool80及关闭仍未通过，原dev4同输入对照也失败并在收尾挂起后中止；无有效对照通过或因果结论。S2／P3-2／第三阶段与同包完整18项验收仍开放；旧失败、原型与未通过记录不覆盖。

## 根因与修改

- 递归就绪：原 History 时间线显示多层 Control 注册／观察耗时；内部 Control 的开始／结束也生成父级 hint，造成重复观察向上放大。新 History 通过 `ralf-running-control-notification-v1` patch 只省略运行中、没有停止意图的 Control ledger 通知。业务 revision、审批／输入、工具／fence／seal 不省略，终态／取消／停止意图下恢复全部调用通知；Hint仍仅触发原权威读取。旧 History 无 patch 保留原 token。
- 部署结束 ACK：夹具只拦截旧 Update，未拦实际 `execution_ended` Signal，故原测试未覆盖目标窗口。改为拦截原 operation／工具 Activity，保留其他操作。真正触发故障后又复现 Owner 仅靠 wait／close 重试 ACK 的活性缺陷；现在用同一已完成 invocation／原证明退避重试结束通知，业务 handler 不重跑。
- PG 析构警告：不完整关闭的夹具必须保留原资源供当前循环恢复，不能把关闭失败当成功。仅在原循环已关闭、全部自有 Worker 退出后，经公开连接 close 释放测试自有 PG 客户端；单独记 detachment，不修改 Runtime 关闭结果、root／lease／效果或数据库。
- hard-kill：原断言明确要求保留未知调用及 Turn／root，但夹具退出仍被当成正常关闭。现在明确期望 CloseIncomplete，并核对原未知证明、原重复回执、精确预期保留、Worker退出及未允许删除的证据。不能以删除数据或忽略任意异常使其通过。验收 runner 同样只允许经精确证明的预期保留。

两种读集成本优化均已否决并撤回：完整 CONTROL CPU 增加6.054%，窄祖先读取增加11.528%。它们不在最终产品中；保留探针与失败记录，不以查询数减少代替实际收益。

## 固定制品与证据

私有 `0.1.0a2.dev5` wheel SHA `a25686241dbdf91ab285f76c5cf3de44a10eae056df1f6390f4c44b3e1a1cbb0`，442产品文件／952测试输入；源码、wheel及checkout外安装字节一致。原a1、a2.dev4制品不重建，原平台证据不转给dev5。

本机诊断根 `/private/tmp/ralf-s2-five-failures-20261020`，固定安装验收根 `/private/tmp/ralf-s2-five-fix-candidate-20261020`。连接凭据与原数据库仅在私有目录保留，安全证据副本不得包含它们。实际服务为真实时间 Temporal1.32.0＋PostgreSQL；native peer 是结构协议和真实子进程，不等于真实模型／真实Docker Coding质量。

## 验证状态

相关源码124项通过；独立只读审查未发现待修安全问题。默认材料摘要仍为 `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`（不含末尾LF），两份原默认History重放通过，两条安装starter各一次业务写入。Ruff、格式和Git空白检查通过。dev5完整安装回归在新边界修复后主动停止：5800通过／139跳过／零失败，5939项已结束；不是完整回归通过，原日志／中断记录保留。最终制品须重新全量运行。

定向服务复验保留原五项，分成一个递归正常项及四个故障，未运行完整18项矩阵：

| 场景 | JUnit秒（含本项收尾） | 结果／证据边界 |
| --- | ---: | --- |
| recursive-json | 356.733 | 失败；第一Turn完整成功及原树重放，第二Turn审批就绪80秒超时；本项关闭、两root退休、正向清理通过 |
| cold-handoff | 146.294 | 失败；仍在初次审批就绪80秒超时，未触达目标交接窗口；Session关闭CloseIncomplete及未知义务保留 |
| effect ACK | 43.578 | 通过；紧随失败项，-Werror下无PG析构告警；原候选采纳、Turn释放、退休及关闭通过 |
| deployment-end ACK | 38.966 | 通过；实际Signal拦截标记已触达，恢复后不重跑handler，原会话释放、退休与关闭通过 |
| control hard kill | 45.479 | 通过；原未知调用、同一Turn／命令回执及原SDK epoch保持；精确预期CloseIncomplete和root/schema保留，不声明Assembly成功关闭 |

两组自有Temporal均shutdown、PG均停止，零停止错误、旧资源未动。递归失败项正向清理成立，仍保留停止容器及Temporal数据库／失败History；另一组保留两个schema（cold-handoff意外保留＋hard-kill精确预期保留）及对应停止容器／数据。测试客户端detachment是单独证据，不改变关闭失败、持有义务或删除许可。

递归时间线从原Session开始计时：首Turn原root于6.573秒开始，叶节点57.276秒开始，两次Model结束约78.789秒，原Tool于100.694秒执行；该Turn完成。第二root于212.655秒开始，叶节点265.655秒开始；新增两次Context分别4.548／5.966秒，第二次Model到303.378秒才结束，超过原就绪等待窗口，随后原取消及关闭完成。这些是重叠墙钟，不相加为exclusive CPU或把全部耗时归到Context。只减少机械通知还不足以通过；不能继续无证据叠加读集／缓存方案。

用户已明确选择保留现有架构，审查重复校验后做最小修复。补充发现 `_policy` 最后一次完整 Release 校验之后仍读取 policy.identity，回调可在该窗口替换固定 Provider；改为先取得值，最后完整校验后仅比较已固定资源／声明并返回独立副本。真实 temporal-3 kernel 的16个回调位置回归通过，保留有效旧实现复现（第12次读取绕过）及构造失败的独立诊断记录。

进一步否决并撤回两项探针：binding投影复用只有4.015% CPU收益，不足以承担复杂度；只读属性轻量检查慢2.531%，且可能在最终拒绝前触达替换后的服务。最终产品没有这两种优化。原完整CONTROL读集＋6.054%、单层祖先读集＋11.528%也均保留为否决证据。

按实际三层嵌套结构重新测量纯State TOOL admission：ABBA共16次无profile调用，baseline CPU中位1.1360585秒，窄祖先读集0.8257525秒（降低27.314%）；两种读取的证明／输入和原节点读取相同、零写入，完整独立来源读取由7次降为2次。仅深度≥2在本次Activity读集中复用一个最终独立来源核验；节点、Registry、start、父epoch与第二次刷新保持，缺失pin回退原路径；单层原路径不变。没有跨await的权限或事实缓存。探针使用原纯State与SDK形状端口、无真实服务或模型，不代表80秒就绪或S2端到端通过。五次探针构造／输入顺序失败分别保留，不能当产品或性能失败。新增三层及原相关170项通过；候选尚待独立审查、固定安装包和真实服务验收。

S2／P3-2／第三阶段仍未完成，不能把dev4的其他通过项与dev5的3通过拼成同包全绿。继续保留原门槛及失败，不推送或公开发布。

## 最终候选准备（尚未验收）

`0.1.0a2.dev6` wheel SHA `a8fb965ae4d6aeda356e00697a12ec77dad46c433f3ea47c7703339025bd8de0`在真实服务执行前拒收：新读集入口直到首次SDK读取之后才固定，可在该窗口替换；保留原候选和复现，不回写旧制品。`admit/validate_activity`现于首次SDK await前固定本地source原函数／完整库存及祖先入口，初次proof后先检查函数与入口绑定，再通过本地固定函数比较库存；短路拒绝时不调用外来方法或进入后续写入。新增八项（两入口×四替换位置）均先复现旧失败、修复后通过，且foreign_calls为空／零写；已报窗口独立复核通过。后续相关165项、先前其他相关186项分别通过，不相加为全量覆盖。

最新 `0.1.0a2.dev7` wheel SHA `4f3c478c8aa5632bd184ace25a7042af2f90eec48d5674a4cf55073232705886`，442产品／954测试输入，源码／wheel／checkout外安装字节相同。固定根 `/private/tmp/ralf-s2-five-fix-candidate7-20261020`；后续完整离线和定向服务结果如下；不声明候选验收通过。不把早期27.314%纯State诊断视为最终制品端到端表现。

全量回归中发现独立RPC测试的时序前提问题：原用例以5／90毫秒sleep推断子进程就绪和第二请求送达；原完整运行保留，独立原样复跑1通过不能覆盖它。仅在私有测试副本增加200毫秒peer启动延迟，确定复现第三请求TimeoutError；改为显式ready／secondSeen通知，让迟到响应发生在对应超时／取消后，原40毫秒request_timeout保持。正常／200毫秒启动及原RPC模块49项通过，产品无需改变。固定安装wheel保持dev7原SHA；`final-inputs`保存仅该测试的校正前后SHA／954输入清单及明确来源。未覆盖原完整回归或构建同版本新包，后续最终完整回归与服务使用该校正快照。

旧输入全量回归因已固定测试校正而主动SIGINT收口，原终端3434通过／74跳过／1失败，960.52秒／exit2；JUnit推导3435包含中断时已进入的用例，不代表它完成，差异另有说明。原失败确认为第三个thread/read的TimeoutError，与受控慢启动一致。完整原日志、XML和失败均保留，不声明旧轮全绿；随后对`final-inputs`整个套件无筛选重新运行。dev7最终默认材料逐字相同，两旧History重放通过，两条安装starter各一次业务写入；这些不能替代全量或真实服务门槛。

全量第二轮暴露维护快照遗漏：私有冻结工具未复制已跟踪的`evals/`，导致规划／RAG三模块10项读取案例目录失败。此为验收输入工具问题，原完整输入并未齐备；原终端8175通过／225跳过／10失败、1933.99秒及中断收尾保留，不记为全量完成。等待它的串行协调器按失败停止，未启动服务。尝试复制正在构建的旧工作目录又遇到瞬态build文件消失，该未完成副本保留且从未验收；之后从稳定工作区重新构造，不复制活动build目录。

最终完整输入位于`complete-inputs`，显式包含全部八个已跟踪根目录。预检1,428个已跟踪代码／测试／评测／示例／工具／工作流文件逐字一致，另独立核对954个Python／JSON测试输入及442个安装产品；整轮前后均重验。修复支持输入后，受影响三模块113通过／零跳过、6.59秒，原wheel不变；不是将它与8175相加冒称全量。该完整快照随后无筛选运行至结束，结果见下；未取得全量通过。实际Python3.12.7／macOS15.6.1 ARM64，Temporal SDK1.34.0、psycopg3.3.6；本地CLI为1.9.1／Server1.32.0，全部模型未配置。


## dev7 完整回归与第二轮定向服务结果

`complete-inputs`完整回归：13783通过／891配置跳过／6失败，共14680项，2267.81秒。三项aggregate readset仍断言旧Release重建计数（9／6／30），实际为6／4／19；事实检查保持，校正计数。另三项retention单测的dummy System从不启动Worker，却缺少新增夹具所需的processes列表；显式补空列表，不以getattr默认掩盖真实Worker追踪缺失。两模块校正后110通过／7.97秒。`final-validation/six-test-correction.json`保存仅两测试文件的输入差异，954测试／1428支持输入和442安装产品均固定；原六失败完整保留，不能将110项与原结果拼成全量通过。

实际服务定向结果（同一dev7 wheel；不等于完整18项矩阵）：

| 场景 | JUnit秒（含本项收尾） | 结果 |
| --- | ---: | --- |
| recursive-json | 456.370 | 失败；首Turn成功及一次业务写入，第二Turn80秒就绪失败；first-close60秒超时，cleanup40秒CloseIncomplete及原schema保留 |
| cold-handoff | 202.478 | 失败；初次就绪／原Worker交接／首Turn审批执行／原退休和关闭均完成，但lost-release-reply标记不存在；实际退休使用Signal＋Query，夹具仅在旧Update丢回复，目标故障未触发 |
| effect ACK | 38.991 | 通过，紧随失败项且-Werror下无PG析构告警 |
| deployment-end ACK | 39.641 | 通过，实际Signal拦截及原结束ACK恢复 |
| control hard kill | 39.483 | 通过，原未知调用／Turn／回执／epoch和精确预期CloseIncomplete及schema保留 |

两组自有Temporal均shutdown、PG均停止，零停止错误、旧资源未动。递归保留一个意外schema，故障组只保留hard-kill精确预期schema；所有原失败History／数据库／停止容器保留。最初启动工具误将固定CLI路径dev55替换为不存在的dev75，在预检即失败，零测试／零服务；固定字面路径并校验原SHA后才执行上述服务，原工具失败记录保留。

独立History复核：dev7第二Turn从原root启动计，叶节点47.010秒启动，第二Model成功完成77.819秒，depth2首次返回waiting_approval87.557秒，depth1为97.655秒；root约89.7秒已开始取消。dev5对应叶节点53.000秒启动，最后Model90.722秒返回validation_error，并非健康就绪基线。dev7串行传播取消后，约144.582秒才启动root retirement，4.259秒后被60秒接收窗口结束的WorkerShutdown打断；不能称最终release校验拒绝。16条Query expired和559KB警告分别来自首Turn及第二Turn开始前，不作为此次超时根因。

冷交接仅修正测试注入：在原retire_deployment_root处理后的成功deployment_retirement_observation Query返回处丢一次真实回执，未完成／拒绝／其他查询不消费gate，保留旧Update分支。四项新回归先复现1失败／3通过，修正后新旧五项通过；不改变产品退休权威或放宽门槛。递归进一步仅做固定函数CPU诊断，诊断不充当验收；首次因沙箱无法访问Docker在创建容器前失败，确认无容器后以已授权本地服务权限重试，失败记录保留。


## 同步出口收敛与 dev8 固定候选

固定dev7函数诊断有效：零fault、零未完成同步调用，Worker CPU336.102秒／窗口350.460秒。ActivityReading._check累计inclusive5.194秒；完整_current_manifest累计inclusive106.109秒（6296次），validate_release125.960秒（6340次），这些inclusive数相互重叠，不能相加。诊断失败和关闭保留结果单列，全部自有服务已停止；带监控的墙钟不充当80／600秒验收。新增来源读集保护不是主要CPU成本，不再以轻量属性／通用缓存绕过它。

独立代码审查确认四处相邻同步完整重建可合并：admit、普通control、release出口，以及有proof的通用Activity出口；同一SDK返回后无中间await，统一为_policy(expected=原Manifest)，仍先读取策略声明再做最终完整检查。无proof路径不变，入口namespace getter前后的独立检查和实际call-grant await两侧完整Activity校验都保留。新增四项成本边界回归4RED→4GREEN，原真实kernel3策略身份替换16项通过。相关10模块345通过／27.20秒；首次沙箱运行有8项临时Unix socket权限失败，337项通过，原记录保留，以已授权本地资源权限原样重验后才取得345通过，不修改测试以规避权限。

新私有`0.1.0a2.dev8` wheel SHA `6cd26ad1c6d0b29afb5002497db94495341bf975e91cf47a632a82b4848a7749`，442产品／955测试输入。冻结工具已显式复制evals和全部八个根目录，源码／wheel／checkout外安装字节相同；默认材料逐字相同、两份旧默认History重放与两条starter各一次业务写入通过。该原无监控递归场景仍失败（下述结果保留）；在真实服务门槛通过前不标记S2完成，也不先重复运行整轮离线套件以替代端到端反馈。dev7及所有旧制品／失败保留。


## dev8 复验与受限读集继续收敛

同一dev8安装包的递归单项381.985秒，仍在第二Turn80秒就绪期限失败，随后CloseIncomplete和原schema保留；自有Temporal shutdown、PG停止、零停止错误、旧资源未动。root相对时间为leaf47.961秒、最后Model成功77.305秒、depth2 approval80.291秒、depth1为85.761秒、root为89.459秒，随后90.910秒发取消。传播较dev7本次样本提前，单次样本不足以把全部差异归因于同步检查合并；80秒门槛仍差约9.5秒。

独立审查允许两项限定收敛，均保留真实SDK事实和前后独立校验：register前后分别只调用一次已包含完整_fresh和full exit的permission()，保留False拒绝和bridge guard，其他mode不动；ActivityReading的独立来源verifier在完整入口／最终_policy(expected=同Manifest)之间，仅当plain Manifest与intent.binding／submission逐字一致时使用既有_full_release=False，不缓存权限或事实。新回归先复现两失败（register compact读取8应为4、深层完整重建11应为9），修复后相关57通过；独立raw Session事实仍完整读取。

`dev9`（SHA `9e32d659e97c433e4281e5f54e347a376a102236fd4c5071af67951178b4d793`）在真实服务前拒收：完整入口_policy会运行getter，返回后必须先核对原实现再调用eligibility／verifier constructor。真实kernel3 getter三态回归3RED→3GREEN，补checked()后相关60通过；取消／Release漂移后重试重新读取原Session事实两项通过，ancestry模块24通过。

`dev10`（SHA `6e48a6e919b9cdc47a649b75073cc8eb056d76feb8ea0ee03074134ee77b6654`）同样在真实服务前拒收：guard本身在最后source检查之后才调用policy.identity，可把替换延迟到该guard内部。新增guard阶段回归3RED／entry原3GREEN；现将该getter快照移到guard开头，后续只比较普通副本，并要求本次policy局部、reader及Runtime的原对象保持同一实例。相关65通过，实际服务未执行，不重建旧制品。dev10在此额外窗口发现前已有相关521通过及默认兼容／starter通过；它们不覆盖新的反例，也不构成候选验收。

拟dev11在最终只读审查和相关回归完成后才冻结、按原门槛复验；不以局部速度或单测数证明S2完成，不推送或公开发布。


### 已撤回独立 verifier 省重建原型

最终审查进一步指出：来源preflight之前不可先调用可能被换的getter，来源检查之后仍有SDK元数据／端口描述符回调，最后完整Release之后也不可再让这些回调改变已pin Provider。完整封闭该类任意宿主回调需要更广的静态读取边界，超出这次最小性能修复的收益。故**完全撤回**独立verifier的_full_release=False、其新增入口_policy及guard getter重排，产品恢复dev8原独立verifier完整检查路径；先前9／10及所有getter原型的通过和失败均仅是被拒方案证据。源码／测试保存在私有rejected-verifier-boundaries，未作为最终实现、未跑真实服务，不冒称完整静态回调防护已解决。

当前仅继续保留register完整identity／permission重复读集收敛、原四个同步出口合并及已报五项的ACK／夹具／通知修复。保留组件漂移拒绝和失败／取消后重试原事实回归；最终这一组合相关58通过／19.94秒。以新版本重新冻结后先看真实递归门槛，停止叠加局部原型或新增抽象。S2仍未完成。


## dev11 最小候选（验收中）

独立审查确认最终register合并没有新增阻塞问题；既有guard在可信宿主恶意monkeypatch下的完整静态防护作为单独发现记录，本次既未解决，也不因register合并新增，不声称已完成该防护。

`0.1.0a2.dev11` wheel SHA `6d5c8470cce34cca0a7587e6aa89d7704f6471987cf069fcc9ea91592e371e81`，442产品／955测试输入，完整八根支持目录；源码／wheel／checkout外安装逐字一致。最终安装17模块517通过／零跳过，50.86秒，309个实际加载产品模块全部来自安装目录，全部产品／测试／支持输入前后SHA一致。默认材料逐字相同，两原默认History重放和两条starter各一次写入通过；Ruff／格式／Git空白检查通过。

最终串行协调器先递归定向复验，再原首项，再剩余17项；每项成功并确认本批服务停止后才进入下一组，最终才无筛选运行全量离线套件。所有原门槛和失败保留；进行中不推导S2完成。没有真实模型调用，不推送或公开发布。


## dev11 结果与 dev12 深层初始化最小接入

dev11原递归单项1失败／312.77秒，仍在第二Turn的80秒就绪期限失败；没有执行原首项、剩余17项或最终全量回归。本次取消后的first-close／cleanup完成，零剩余schema，Temporal shutdown、PG停止、零停止错误，原数据库／History／停止容器保留。该单样本不推导其他取消组合已经通过，也不能拼接不同wheel的成绩。

用户选择保留现有架构，审查重复校验后最小修复。拟跳过最终deployment publisher的方案在实施前被否决：其实际guard别名is检查不能由fresh Manifest digest代替；既有最终验证和相关测试原样保留。

只将CodingValidation._bootstrap_nodes已有深层只读祖先读取接上当前Activity info。原路径保留leaf及后续三个proof的独立来源验证，新祖先读集保留一组独立raw Session verifier、所有祖先事实／namespace／Registry／pin重读、完整Release出口和只读wrapper；不适用／未pin仍回退。首次SDK await前固定原source_bindings函数／绑定／库存，await后核对才调用，以免在SDK回调中替换后被接纳。未新增缓存、参数开关、状态机或默认能力。

新bootstrap成本回归先复现独立来源10组未收敛为5组；首SDK替换entry／method／sources初3失败／1通过，补来源pin后，包含原事实读取一致、四类漂移及拒写的ancestry模块29通过／14.72秒。纯State加SDK transport double的8次ABBA，中位进程CPU旧0.3673885秒／新0.365624秒，差0.48%，记为CPU中性；独立Session来源读取10→5组，尚不证明真实服务的80秒就绪改善。独立静态review未发现新增阻塞。测试编写中一次await误放同步回调的collection错误另存，修正后才记录有效RED，不把该错误算产品失败。

新私有`0.1.0a2.dev12` wheel SHA `2bacf5efb15e97bfd9fbb116ace49a0957aa13e2eeb8500001a07c0f4e139393`，442产品／955测试输入、完整八根支持目录，源码／wheel／checkout外安装逐字一致。相关安装回归、默认兼容及真实门禁待本轮验证，S2／P3-2／第三阶段仍开放。全部原360／600与单项门槛、失败记录保留，不推送或公开发布。


### dev12 安装及兼容预检

同一固定wheel的19模块安装回归588通过／零失败／零跳过，55.40秒；309个实际加载产品模块全部来自checkout外SITE，442产品、955测试和支持输入前后SHA一致。增加原CodingValidation和deployment Coding协议模块；不把之前17模块517项计入本次总数。默认材料逐字相同（去末尾LF的SHA `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`），两份原默认History重放、两条starter各一次业务写入通过。Ruff、1398文件格式检查、Git空白检查通过。

随后启动无性能诊断钩子的真实递归复验。协调器保持串行；若递归不通过，仍独立核验另外四项原故障，但不启动原首项／剩余17项完整门禁，也不拼成S2全绿。若递归通过，则按原首项→剩余17项顺序。全部自有服务停止后才运行最终不带筛选的离线回归；运行中不作完成声明。


### dev12 原递归通过（单项）

无诊断钩子的真实recursive-json：1通过／418.597秒，零跳过，仍按600秒整链及80秒就绪、Tool80／Runner60／approval180／first-close60／cleanup40验收；两轮各一次业务写入，原回执／History／退休／关闭检查通过，零剩余或意外保留schema，owned Temporal／PG停止及自有成功容器清理均确认，零停止错误、旧资源未动。实际加载354个产品模块全部来自原固定安装SITE，产品／测试输入SHA前后不变。原dev11及更早失败完全保留；本次单样本只证明该候选该场景通过，不将纯CPU微测0.48%解释为端到端提速比例。

协调器现按原顺序进入graph-sequential-sdk首项；同wheel首项通过才执行剩余17项。最终全量离线尚待运行，S2仍未完成。


### dev12 原首项通过、矩阵新失败（中断保留）

原graph-sequential-sdk首项1通过／433.142秒，零跳过；输入前后不变，零schema，owned服务退出且零停止错误。其后依原顺序启动17项矩阵：agent-sdk80.198秒通过、sequence-json133.125秒通过、graph-parallel-toml316.363秒失败。维护SIGINT后JUnit另有一个空名0.004秒中断节点，不能计为通过或完成场景；终端退出2，17项未跑完。中断前进程可执行路径形式预检曾拒绝发信号；随后以固定SITE、pytest探针及本批root核实归属后才发送SIGINT，原记录保留。

失败场景先Tool Activity触及原StartToClose80秒：a分支13:22:46.499排入Tool，13:24:06.504超时；b分支Tool在76.621秒完成。两分支已有业务写入，共两次，但a的完整结果未被采纳，后续原native stop为unknown，不能当作成功执行；调用方审批循环随后180秒超时。first-close60超时、cleanup40仍CloseIncomplete，保留原schema `deployment_coding_56ac9e4672424736af6a0becfb2d94ec` 及未知义务。原History／DB／停止容器保留，旧资源未动；本批Temporal shutdown、PG停止且零停止错误。

原日志有609KB payload警告和Tool期间Query expired；尚不单凭并发发生认定因果。停止本轮后再分析History；没有并发执行CPU回归干扰该性能样本。独立同wheel／原门槛的graph-parallel-toml重现进行中，尚未再次改产品或放宽期限。最终全量离线回归通过显式工具后置标记未启动，不记为完成；修复后重新走完整门禁，原失败不覆盖。


## dev12 并行原样重现与状态读取收敛

同一dev12包在独立新服务原样重跑graph-parallel-toml：1失败／494.588秒，零跳过。第一轮完成，第二轮两个Tool Activity均触及原80秒StartToClose期限，四次业务写入已发生，但只有七次Model调用，未获得完整采纳，不可按写入数算成功。审批180秒及first-close60／cleanup40仍失败，原schema `deployment_coding_80fe39be1f96424486a1a16997ef7be6`、原History／数据库／停止容器保留。自有Temporal／PG停止且零停止错误，旧资源未动；未调整任何产品或测试期限。

进一步审查发现TemporalCodingAuthority.resource_state先check→_state，再调用_state第二次；每次Query两侧都完整验证，且Runner只在第一响应检查、State却取第二响应。改为复用已有私有_state承载原dispatch／Runner关联校验，只接受零或两个参数，零参数路径保持取消／恢复观察；check返回原request，resource_state投影同一新鲜、已完整校验的响应。每次调用仍新读，不缓存，不取消_call前后完整validate／callback pin／JSON隔离。没有增加方法、库存字段、协议版本或新的执行权威，避免给v6精确库存加helper引起旧格式拒绝。

主回归先复现旧实现返回第二份State（1失败／7通过），修改后连同非法arity等10通过；实际callbacks／CodingValidation／独立Session verifier回归，用旧dev12单文件临时恢复确认2 Query的有效RED，finally原样恢复候选后相关六模块171通过／7.98秒。该实际读集测试确认1 Query、Query两侧各一组新鲜Session事实、四次外层完整Release检查，不把事实读取整体移除。独立静态审查未发现新增阻塞。

在新源码上，原dev12首项成功场景的八份selected History纯Manifest校验／SDK replay通过，authority库存键集合不变，零服务／模型调用。先尝试失败cleanup History的独立重放遇到Event8 WorkflowExecutionUpdateAccepted的Nondeterminism及RuntimeWarning；用原dev12安装包原样也复现相同错误，两份失败日志均保留，不将这些失败cleanup History列为重放通过，也不将其归因于本次去重。正常旧selected重放与Worker接续不同：执行中的原发布仍需原固定Worker，不声称任意旧Release能切换到新包。

新固定私有`0.1.0a2.dev13` wheel SHA `a4f5fec1ebd0a5783e88c839984f8e582ed24529fad47cf2f7c06769bfbdd8af`，442产品／955测试输入，源码／wheel／checkout外安装逐字一致。Ruff、1398文件格式和Git空白检查通过；最终安装回归、默认兼容与真实门禁仍待本轮验证。S2仍未完成。


### dev13 安装与兼容预检

固定包安装20模块599通过／零失败／零跳过，57.71秒；309个实际加载产品模块全部来自原安装SITE，442产品／955测试及支持输入前后SHA相同。默认材料逐字相同，两份原默认History重放、两条starter各一次业务写入通过；同一安装包另对原dev12首项八份成功selected History重放及纯Manifest校验通过，authority库存形状不变。各次失败日志保留。现按并行目标→原首项→剩余17项顺序验证，原首项通过才进入完整矩阵；期间无其他CPU回归，全部服务停止后才运行最终全量离线。不将预检或旧包局部通过代替S2完成。


### dev13 并行结果及后续定向诊断

真实并行graph-parallel-toml仍1失败／493.180秒、零跳过；第一轮完成，第二轮两个Tool80秒StartToClose超时，四业务写入／七Model记录不足以确认成功。审批180及first-close60／cleanup40未通过，保留schema `deployment_coding_87ad0720f9c74616a5004703560e4b25`、原History／DB／停止容器；自有Temporal／PG停止、零停止错误、旧资源未动。原首项、17项矩阵、最终离线全量均未启动。相邻资源Query去重的语义与局部回归成立，但没有解决真实并行性能门槛，不归因为全部耗时的根因。

先独立串行执行同包的另外四项原故障，再只读CPU诊断；不与性能场景并行跑其他CPU测试。诊断沿用现有有界sys.monitoring，私有副本仅改变一个测试CPU夹具，增加同步指纹helper耗时及Code purity缓存命中／miss／容量／重置计数，不修改产品或期限。小探针已验证10次实际executable_digest为9命中／1miss、零fault；诊断不同输入／监控开销不计为S2验收，不先按假设修改缓存或再增加能力。


### dev13 四故障复验与部署结束 ACK 的测试竞争

同一安装包、原期限、无性能监控的四项结果：

| 原场景 | JUnit秒（含收尾） | 结果 |
| --- | ---: | --- |
| cold-handoff | 376.014 | 通过；实际退休Query成功回执丢失注入一次，原Worker交接、审批、第二Turn取消、退休与关闭成立 |
| effect ACK | 44.201 | 通过；效果回执恢复、会话释放、原业务次数与关闭成立 |
| deployment-end ACK | 41.430 | 失败；放开ACK后向已自动封存的leaf发送新drive，产品按封存契约拒绝 |
| hard-kill | 43.439 | 通过；精确预期CloseIncomplete与原未知Turn／调用／root义务保留，不声明Assembly成功关闭 |

真实leaf History的event158是结束通知；event172 `deployment_seal` 时间14:16:23.636857Z，event174新`drive`时间14:16:23.640581Z，封存早3.724ms。这是测试主动推进与Owner自动ACK恢复的竞争，未放宽产品seal guard或将root退休恢复套到leaf。测试只对deployment-end省去显式drive，直接沿原`_eventually`观察；effect／native-stop原drive及全部busy、closure、退休、原生提交和业务次数断言保留，不捕获或吞掉DefinitionMismatch。

独立校正输入目录`ack-race-validation`沿用同一dev13 wheel；测试清单与支持输入仅该文件SHA变化，未重建同版本制品。deployment-end **1通过／40.027秒、零跳过**，schema清空、自有Temporal／PG停止且零错误。原41.430秒失败、原日志及History不覆盖；此次独立通过不是完整四项或18项通过。原四故障组仅保留hard-kill精确预期schema `deployment_coding_77dee7fb99c24f1b8bd5a5cc59b76acf`，无意外保留；停止失败容器／原数据库与历史仍在。

### 有效CPU诊断与优化边界

私有`cache-cost-diagnostic`只变更一个测试监控夹具，产品／wheel／安装字节不变；监控计时有效、零fault／零未结束调用。监控窗口进程CPU248.363秒、墙钟288.610秒，整个仪器化测试1失败／335.198秒；这些包含监控成本，不能代替无监控S2，也不是原493.180秒场景的精确关键路径归因。原80／60／180／600／60／40期限不变。

指纹共6,189,414次调用；六份代码纯度缓存均未观察到reset，最大542／1024，容量抖动假设不成立，不修改缓存容量。按函数聚合，`executable_digest` inclusive90.049／exclusive58.320 CPU秒，`_current_manifest`2761次／inclusive76.582秒，Coding协议22008次／84.445秒，composition协议22336次／63.394秒。inclusive有嵌套，不能相加；密集同步监控本身会放大成本。

只读聚焦审查没有找到同时满足安全与实质收益证据的新最小热点候选。Registry的`validate_request → validate_bindings`还承担Scope核验，不能直接删除；纯History协议校验改动会改变固定pure implementation，必须另做兼容设计，当前不当成无影响微调。一个非热点Worker同步重复虽可静态收敛，但没有收益证据，未为此继续冻包。保留当前验证过的最小改动，不新增缓存／状态机、删独立权限／身份检查或调整期限；并行Tool80及其后关闭仍是未完成项。

### 最终离线回归

所有本批自有服务停止后，在同一dev13安装包与校正后的测试输入上无筛选运行`pytest -q --tb=short -Werror`，未配置模型／外部服务变量；缺配置的服务测试按实际跳过记录。首个预检因支持清单未同步该测试SHA在收集前拒绝，已保留；仅修支持清单后，默认沙箱又拒绝测试所需本机Unix套接字。确认原测试进程身份后中止该尝试，日志与中止记录保留，再以具备本机测试能力的独立目录重验；没有据此修改产品或屏蔽异常。当前正在运行，结束后按实际结果登记，不以相关599项代替全量通过，也不以离线通过关闭S2。


### 首次最终全量结果与观察器校正

同一安装包在具备本机socket／进程检查能力的隔离目录完成无筛选`-Werror`全量：**13818通过／891缺配置跳过／1失败，14710项，2247.59秒**；436个实际加载产品模块全部来自原安装SITE，产品／测试／支持输入前后SHA一致。唯一失败为`test_other_coding_four_modes_keep_original_validation_order[register]`：测试只记录`validate()`，而注册去重后实际调用完整`permission()`，故只看见control。相关真实读集回归已核对权限／完整校验次数；没有删除产品校验。

只在原测试子类增加permission追踪并调用真实`super().permission()`，断言entry permission→control→exit permission；cancel／recover和observe原验证顺序保持。三模块48项通过／15.96秒，无新产品改动或wheel重建。第一次全量失败不改记通过；新独立`order-spy-correction`固定校正输入（相对最初dev13仅ACK竞争及本Spy两文件）重新运行完整套件，结束后按实际结果登记。

原dev4的graph-parallel-toml曾在原17项中**374.348秒通过**（原wheel SHA `6cf80ff5a776e397625da3c220b84b31a001018b82d0c215f7fffef827250f62`）。因此当前并行失败还必须当成产品增量回归风险，不单称已有性能限制；这不是相同输入／环境的AB因果证明。计划在离线回归通过后，以原旧包与当前校正夹具跑一次对照，再以同一dev13和相同校正输入串行复验原五项；只用新自有服务，保留所有原期限／失败，不将旧包对照、五项定向或不同输入拼成当前18项验收通过。


### 校正输入的完整安装回归通过

固定dev13产品／wheel不变，`order-spy-correction`校正输入完成全量：**13819 passed／891 skipped，零失败／错误，14710项，2212.62秒**。无选择过滤、`-Werror`，436个实际产品模块全部来自固定安装SITE，产品／测试／支持输入前后SHA一致。891项是未配置模型／外部服务的实际跳过，不算能力通过；首次全量唯一失败保留，不回填。当前源码与同包原始安装相关599项、默认材料／两默认History／两starter及八成功selected History兼容预检分别有效，不相加为同次总数。

协调器在完整回归通过且退出后，才启动同校正测试输入的原dev4并行对照；对照只用于定位，既非dev13验收，也不能证明根因。停止该组全部自有服务后，才启动dev13原五项定向复验。当前尚未取得后续结果，完整18项／S2仍未完成。

只读History对比补充：原dev4四个Tool分别68.302／65.390／68.218／68.210秒完成；dev13第一轮64.427／62.098秒完成，第二轮80.002／80.001秒超时。这是服务器墙钟而非CPU或匹配AB因果；已检查的dev13非Session History未见同证明重复发送deployment_call_ended Signal，尚不能据此排除发送前错误，也不支持直接判为重试风暴。没有因这些假设新增产品改动。


## 2026-10-21 本批最终验收与剩余边界

### 原五项同包、同输入串行复验

`ack-race-validation/original-five/five-targets`使用唯一dev13 wheel、同一组955测试输入（相对最初冻结仅部署结束ACK竞争和调用观察器两文件校正），产品／测试前后SHA一致。未开启CPU／异常监控，354个实际产品模块均来自固定安装SITE。原正常与冷handoff整链600秒、其余故障300秒，以及就绪80／Tool80／Runner60／审批180／first-close60／cleanup40均不变；不改记原360秒失败。

| 场景 | JUnit秒（含该项收尾） | 结果与原证据 |
| --- | ---: | --- |
| recursive-json | 418.807 | 通过；原两Turn／两次写入、审批、树重放、Session释放、两root退休及Assembly关闭／清理成立 |
| cold-handoff | 367.790 | 通过；原Worker交接、实际退休Query成功回执丢失、审批恢复、第二Turn取消与关闭成立 |
| effect ACK | 37.794 | 通过；原效果回执故障恢复与一次业务写入、Session释放、退休及关闭成立 |
| deployment-end ACK | 33.977 | 通过；实际Signal故障与自主恢复，未重跑handler，观察原封存／退休及关闭 |
| control hard-kill | 38.511 | 通过；精确原未知调用／Turn／回执／epoch及保留义务成立，预期CloseIncomplete，不声明Assembly成功关闭 |

**5 passed／0 failed／0 skipped，897.89秒。** 前四项schema正向清理；仅保留hard-kill精确预期schema `deployment_coding_9e18d7a85f484ed4a20dd2d0ac0e7f96`，实际剩余集合与预期严格相等，零意外保留。该项Worker已退出，原未知证明／数据库／停止容器保留，测试客户端detachment不构成Runtime关闭或释放证据。全部本批自有Temporal shutdown、PG停止，零停止错误，历史资源未修改。这一组同包结果可用于原五项修复验收，不能代替其他13项或完整18项。

### 同输入旧包并行对照未通过

原dev4产品／原wheel不重建，配合同一校正测试输入运行graph-parallel-toml，仅用新建服务。出现审批TimeoutError、四次业务写入／七次Model记录及CloseIncomplete；Worker退出后，测试仍在事件循环收尾，服务创建后608秒时尚未返回。核实本次唯一pytest PID／进程组、原SITE4与本批路径后，只发一次SIGINT，未发SIGTERM或SIGKILL；退出2，原JUnit只有空名0.002秒中断节点，**没有可计通过的完整场景**。原失败／挂起证明与schema `deployment_coding_b5b68f47c76440b8a1e8a9e6852efb2d`保留，自有服务随后停止且零错误。维护中止不是600秒通过，也不是把外层900秒看门狗改成验收期限。

原dev4历史374.348秒通过及这次对照失败分别保留；新输入／宿主环境等因素尚未拆分，不能断言当前问题完全由新产品增量引起，也不能据此宣布新包无回归。只读进程CPU汇总排除了inline命令，覆盖不全，不能用于排除CPU竞争；没有记录原始命令或修改旧进程。未继续据猜测叠加产品优化。

### 工程检查与交付

最终无筛选安装回归13819通过／891实际缺配置跳过、零失败／错误；源／测试未再改变产品行为。相关测试观察器48通过与先前599项安装预检分别保留，不相加；默认材料、两默认History、两条starter以及八份旧成功selected History兼容证据仍对应同一产品。旧worker固定Release的执行接续仍需旧包，纯重放不等于跨版本换Worker。

整批只读审查未发现新增阻塞，Ruff、**1406文件格式检查**及Git空白检查通过。安全证据副本已保存到`dist/s2-five-failures-20261020`（1443文件、约144MiB），排除连接凭据、原数据库和完整敏感History；日志／摘要／工具／私有制品与受保护原件哈希已核验，拒收制品仍只作历史记录。SHA256SUMS摘要`93c4552fbc3bf6f9ceae14922f9f3915f08e192375e529898a3472bb9f904d59`，已对18个已知自有测试密码确认副本不含明文；原件继续在私有目录及停止容器中保留。仅本地提交，单次跳过钩子，不改持久化配置、不推送或公开发布。

**本批原五项修复已有同包证据；S2整体仍未完成。** 当前dev13并行Tool80／审批／关闭失败、当前同包原首项及其余17项完整验收仍待通过；不能拼接dev12首项、旧dev4其他正常组合或不同诊断输入来关闭P3-2／第三阶段。真实模型与真实Docker Coding质量也不由结构peer替代。
