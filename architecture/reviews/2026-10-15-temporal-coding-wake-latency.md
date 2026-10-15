# Temporal Coding：Parent 唤醒与 SDK 读取延迟

日期：2026-10-15。状态：所选修复已通过dev120验收，最终范围见[验收记录](2026-10-15-temporal-deployment-coding.md)；以下保留各次冻结版本及失败，不当作当前交付状态。

最终同416产品字节的v30完整离线11847 passed／804 skipped；安装normal原13通过／1失败保留，测试按有界显式关闭重试契约修订后，normal单项复验1通过（152.70秒）。诊断单项另记，不合并成同次14全绿，也不宣称原服务失败唯一因果已证。原unknown与恢复资料仍保留。

## 原失败与边界

公共 Coding 并行图的原保留记录中，两次原生写入已发生，但 Tool 返回
`runner_outcome_unknown`。Parent 的实际调用开始／结束登记递增业务唤醒计数，
使自身观察 Activity 满足下一轮等待条件，未产生正常的等待 Timer。
原 History 随重复观察超过服务上限。该证据不能证明原生工具、授权或模型成功。

原 History、PostgreSQL 记录与对应冻结源码继续保留。复验使用独立测试 Scope，
不重发原业务；不提高 Runner 期限或 History 上限。

## 当前修复

- 仅对显式公共 publication2／3 的 Parent，机械调用登记继续通过原纯状态与
  ACK 契约，但开始登记不再触发业务唤醒。publication2 正常非终态观察保留原
  0.5 秒等待；publication3 已改为子事实变化通知与 dirty generation，正常无变化
  等待不再使用该定时轮询。失败读取的有界重试与明确 drive 恢复另行保留。
- 终态且满足原物理静止条件时，首次调用结束仍唤醒退休流程，包括结束回执
  在退休验证等待期间到达的窗口；重复结束不持续唤醒。外部取消、子 epoch
  固定和停止回执的唤醒不变。默认及私有 v1 继续调用原继承处理器。
- 同一次 Coding ancestry 验证中，同一固定 Parent epoch 的 proof 与 children
  独立读取并发执行，两者完成后校验实际 namespace，再验证完整身份、意图和
  child epoch。读取失败时收拢另一读取后传播原异常，不留下后台校验任务。
  不缓存跨调用的取消或准入状态；缺少 pin 时的 Update 前后校验保留。
- 测试夹具可显式启用 SDK 分项计时。私有日志仅记录时延、次数、安全调用名
  和异常类型，不记录密钥、连接串、Manifest、业务参数或结果。

## 已取得的检查

根执行者针对上述修复及原 control／bridge／fixture 执行 `-W error` 检查：
100 passed，0 failed。独立审查未发现新增可操作问题。冻结 v4 包含 1197 个
源码、测试及包元数据文件；实际服务复验使用该副本。

冻结 v4 扩展后的受影响检查为836 passed、93配置依赖跳过、0 failed。
Ruff、1182 个文件的格式检查和 Git 空白检查通过。独立 dev119 安装的默认
Profile／Manifest／orchestration 发布与 v4 源码一致；原 History 重放、原
epoch／回执／结果续接通过，当前 Provider 新调用为0，两个测试 Worker 已退出。
该证据不替代 dev120 安装后验收或所选 Coding 服务矩阵。

首个 v4 服务启动在连接本机 PostgreSQL 前被沙箱网络限制拒绝，未启动 Worker
或业务，不能作为产品行为证据。随后使用已授权的本机服务访问进行复验。

实际并行图复验仍失败（1 failed，239.84秒）：两次 Thread start 已采纳，但
没有 Turn grant／receipt，也没有 native commit。一侧 Tool 在77.55秒返回
unknown，另一侧触发80秒 Activity timeout。2979 个 SDK 计时 span 均结束，
只有一次读取取消；并发读取缺少原调用栈，不能据此断言 Runner 的具体超时 await。

Parent 保留的 History JSON 为70,899,744字节、1321 events，包含74次 observe、
2次 register和16个0.5秒 Timer。Activity 调度输入与完成结果合计约66.30 MiB；
服务日志仍出现 History 超限错误。因此本次证明自身机械 ACK 不再完全绕过等待，
但没有关闭 History 增长或 Turn 前验证延迟。SDK 分项等待存在重叠，不能相加
当作业务总耗时。失败记录和匹配 v4 源码继续保留，不重发原业务。

## 未关闭的门槛

后续 v5／v6 增加只读身份投影、每次调用独立 bootstrap、紧凑 CONTROL 载荷和
子事实变化通知，原逻辑 DTO 与执行权威保留。v5 实际试跑暴露 SDK sandbox
激活期导入问题，已用真实 importer 激活期测试复现并补预加载。v6 的受影响
开发检查为705 passed／46配置依赖跳过，不能替代完整阶段检查。

Trial09 实际服务复验仍失败（1 failed，92.64秒）：准入成功，两个 register
CONTROL 返回 `definition_mismatch`，尚未进入旧路径的 candidates Query。
Parent 为60 events、330,722字节；observe／Timer、Thread／Turn、业务写入
均为0。当前故障集中在新只读校验路径；不据此报告性能改善或编排成功。
上述源码快照及私有试跑证据保留。进一步使用真实 SDK importer 激活期执行根的
`node` 查询复现：Native 成功，Parent 在 `node_identity_digest` 内导入
`temporal_startup_options`，被运行中导入检查拒绝。之前回归只执行 CONTROL
请求构造，未覆盖查询执行；修复补 Parent 显式预加载，并扩展激活期回归。
该修复不放宽原身份或授权校验。冻结 v7 的 Trial10 复验仍失败（308.33秒）：
两个 Tool 均触发80秒 StartToClose timeout，一侧 stop Activity 也触发同一期限；
关闭返回 `CloseIncomplete`，PG schema 保留，owned 根尚未释放。

本次 Parent 为350 events／2,134,239字节，CONTROL 为register2、observe10、
cancel2，Timer为0。501个完整 compact 查询响应均无领域错误；查询等待中位数
为0.560秒、p95为1.330秒，另有一次读取取消。原容器各完成两次 create/start/
kill/rm，但 child History 中没有 Thread／Turn grant 或 receipt，也没有原生
业务提交。载荷增长已缓解，仍不能以本次失败代替审批 idle-window、执行或关闭验收。
查询投影每次重复验证完整实现并计算原身份，下一步先区分纯计算与 SDK 排队成本。

使用 Trial10 真实 Graph Root 输入与准入回执离线重建状态，开启 cProfile 执行20次
`node(root,None)`：中位16.49ms、p95为20.20ms，总336.97ms；完整协议验证调用60次。
这不是Trial09输入，也不是服务端分段计时。纯投影成本仅为观测到的SDK查询等待
的小部分，不能据此把主要瓶颈归于重复纯验证。下一步应测 Worker 调度、往返、
序列化及Activity事件循环阻塞，避免先扩展纯缓存或改变新鲜权限检查。

冻结 v7 全部196个 `test_temporal*.py` 的开发检查首次为2699 passed／552 skipped／
1环境错误（Redis私有Unix socket被沙箱拒绝）；仅该用例在获准的宿主访问下复核
1 passed。合并证据为2700通过，非同次完整绿色回归；服务配置跳过项不作验收。
独立 dev119 安装版与 v7 默认发布字节、原 History 重放／续接及原 epoch／回执／
结果一致，候选 Provider 新调用为0；仅清理该兼容探针自身 History。

Trial10 完整夹具目录已复制到私有证据目录。pytest 默认保留策略此前删除了部分旧
试跑临时目录，旧源码、日志与派生摘要仍保留，不能继续宣称其原始文件全部在本地。
原 Temporal 服务 History／PG 记录未删除；后续只读导出恢复所需证据。后续试跑
使用独立私有 `--basetemp`，避免测试清理旧验收记录。

## Worker 延迟定位与 v9 待验收修复

原私有服务控制器已重新核验存活，46份原 History 已只读导出，合计173,548,446字节；
其中25份选择部署协议，18份的部署源码指纹可匹配保留快照，7份尚未匹配。该匹配
只覆盖部署源码，不能替代完整 Worker 恢复校验。原 PostgreSQL 已做私有只读 dump，
未停止或修改服务；这些诊断备份不算框架备份恢复能力验收。

仅增加安全分段计时的 v8 Trial11 仍失败（312.767秒）：两个 Tool 和两个 stop
Activity 均达到原80秒期限。prepared 回执距 Tool 调度已63.209／74.856秒，
没有 Thread／Turn 或原生业务提交。499个 compact Query 响应有效且没有领域错误。
Query／Describe／Namespace 的p95分别为1.356／0.287／0.189秒；Worker loop lag
p95为0.487秒、最大0.883秒。所有142个WFT完成，无上一轮 BAD_UPDATE，说明该错误
不是延迟的必要条件。并发跨度不相加为业务耗时。关闭仍为 `CloseIncomplete`。

另用匹配 Trial10 的双 Base Runner 声明与受控零网络 SDK 回执测量真实稳态校验：
中位约640ms；独立 CPU 复核约644ms，1ms asyncio observer 最大延迟约651ms。
cProfile 确认8次 `_check` 共24次完整 `validate_release`／Manifest 重建。
同构双 Connected Runner 约2.65秒；这些是声明夹具测量，不是实际服务比例或质量结果。

v9 修复只合并同一边界的重复工作：`_policy(expected=...)` 保留读取策略前后的两次
完整固定发布校验，移除第三次重复校验；已有不可变身份 snapshot 时跳过不含RPC的
bootstrap调用。所有 Namespace／Query／Describe 的真实 await 边界和最终检查保留，
不缓存权限、不减少实时读取、不改原期限。稳态完整重建上限由24降为12；新增回归覆盖
策略读取期间变更、方法和 snapshot 替换、await期间发布变化、关闭后的新鲜权限拒绝。
受影响140项及协议／guard／bridge等103项检查分别通过（范围有重叠，不相加）。
独立审查未发现边界削弱。冻结 v9 的完整 Temporal 开发检查已完成，实际并行图
结果如下；尚未宣布该组合交付。

冻结 v9 同次全部197个 Temporal 测试文件检查为2710 passed／552外部服务配置跳过／
0失败或错误（112.18秒，`-W error`）。552项未运行，不能将该结果称为全部 Temporal
验收通过，更不能代替所选服务门槛。同声明夹具复测确认6次 `_check`、12次完整
重建：Base 中位306.57ms、Connected中位1259.93ms，较各自基线下降约52%；独立
CPU复核约325／1242ms。源码指纹前后一致，私有基线与复测报告分别保留。

实际 Trial12 仍失败（268.912秒）：prepared缩短到36.431／56.406秒，但两个 Tool
仍达到80秒期限，未出现 Thread／Turn grant或原生业务提交。两个 stop Activity
已在56.729／63.915秒完成，返回 `effect_outcome_unknown`。Compact Query的
中位／p95为0.369／1.003秒；loop lag为0.048／0.262秒。实际试跑期间还运行独立
开发检查和声明profiling，不据此给出受控吞吐比较；业务验收仍未通过。

本次 Assembly close返回成功，但保存的History没有deployment seal／Registry
retirement完成记录，不能把物理关闭等同Root退租。审查发现测试夹具曾仅依据该返回
值终止History并删除schema；Trial12已发生该清理，不能宣称其PG恢复数据仍在。
后续修复限于测试清理：删除前匹配原Registry成功接受与完成退休证据，写effect未adopted
（含zero credits）或缺证据均保留恢复材料。预期未知结果用例验收保留成功，其他保留
单独记录，不把它改称产品CloseIncomplete。原生preflight的安全分段计时已补测试，
随后按下述 v10 门槛冻结，复验prepared到首次Thread grant的具体阻塞。

## v10 清理门槛与当前验收状态

测试清理的独立删除证据门槛已实现并审查通过。Assembly close 的成功单独登记；
删除前读取原 Registry 的真实 SDK History，以 Update accepted event ID／update ID
关联成功接受与完成的 `release_deployment_root`，核对原 Scope、namespace、首次请求／
Manifest 摘要、业务及 Registry 的 first／original SDK epoch 和完整退休 certificate。
不依赖已停止 Worker 的状态 Query，也不要求 Root 已收到丢失的退休回复。

缺失、pending、失败、reset、身份或 certificate 不匹配以及证据读取失败均拒绝删除；
PostgreSQL 中非只读且未 adopted 的写入另外否决删除，包括零费用写入。只有成功组件
关闭且这些证据全部通过，夹具才可终止原已退休 Histories、删除 schema 和 socket。
否则保留 application、schema、socket 路径、原 Histories 与关闭后 PG 快照，独立记录
expected／unexpected retention，继续传播原业务失败；不把该保留状态虚称产品
`CloseIncomplete`，不执行 drive、强制退租或重发业务。

离线 SDK protobuf event／清理生命周期／隐私及原 fixture 检查同次37 passed，
`-W error`；根执行者的整合 focused 检查114 passed，Ruff／格式／空白检查通过。
原45项实际矩阵完整 collect，不能据此算45项实际通过。预期 unknown 场景明确验证
原 run ID／Scope／epoch 的资料保留；模拟端口仅用于离线门槛测试，不是服务证明。
冻结 v10 共1207个文件，Trial13 在新 Scope 复验 graph-parallel／TOML，结果为
1 failed／0 errors，271.667秒。未进入 Thread／Turn，也没有业务 commit；Assembly
close 成功，owned Worker 均退出。删除门槛正确保留 schema：原 Registry 为1 accepted／
1 retained，原因为 `root_retirement_unconfirmed` 与 `unadopted_write`，证据读取错误为0。
这关闭了测试清理误删恢复数据的具体缺陷，不证明业务、原效果恢复或整体矩阵通过。

私有 `trial13-native-timing-summary.json` 显示，peer1 九项 preflight 的调用本身中位
4.343ms、最大10.175ms，相邻调用间隔2.527–4.477秒，整体区间29.858秒；peer2 只到
`experimentalFeature/list`。这些分段证据不能把间隔归因于 peer 操作本身，也不能宣称
prepared→Thread 阻塞已关闭。后续 selected3 控制去重与纯 fingerprint 缓存的实现及
检查见下述 v11 记录，整体性能与实际图的门槛仍未关闭。

Trial13 启用了诊断计时：SDK elapsed 包含 started 同步日志写入及 Query 响应摘要，
但不含计时前的 origin 栈扫描和 elapsed 取值后的 finished 日志写入；原生 peer 计时
也增加同步文件 I/O，因此不能将区间归因于纯 RPC 或全部框架耗时。正常模式不装配
TimedWorkflowService 代理、LoopTiming 插件及其后台任务，原业务 DTO／控制响应保持；
带计时的 CLI 字节差异单列。后续以固定 v11 的 `run-selected-services.py source` 在
fresh Scope／case、无 timing env／marker 的正常模式复验 graph，失败后才另开独立
计时定位；原 Trial13 失败与数字保留，该正常模式复验尚未取得结果。

冻结 v10 源码的一次 Local bounded DeepSeek smoke 已完成：`deepseek-flash`，17.484秒，
state succeeded；native 前审批成立，attempt1，原 action 已 fenced，原 native candidate
及 `add.sh` 均存在；runner／engine／journal 已关闭，diagnostic codes 为空，持久文件
凭据扫描未发现凭据。凭据未写入仓库、发布包或全局配置，仅登记脱敏摘要，不复制私有
报告、模型内容或产物。usage unknown，未运行独立 oracle；这不是 dev109 的3×3质量
重评、质量优势证明或 Temporal／Coding3 服务验收。

| 本批必须关闭的门槛 | 现有证据与尚缺部分 |
| --- | --- |
| 所选 Coding3 原业务与原树 | Agent SDK 已有先前单场景实际通过；13种拓扑与配置／工厂、跨 Scope／mixed2／3、重复控制及首次接受恢复仍需同一冻结版本的完整源码和安装后矩阵 |
| 通知与紧凑读取 | 纯投影、SDK activation、dirty generation／await race／重复 ACK 回归已通过；真实长审批 idle window 中 History bytes／events／Activity／ledger 不增长，以及批准／取消／恢复后的原树闭合仍需实际证明 |
| 原生和效果的独立闭合 | Trial13 已证明失败时测试夹具不误删未退休／未 adopted 数据；真实提交后仍活跃、零费用 unknown、双 ACK、Worker 死亡后的精确冷调用 fence、hidden／旧 revision／无 PG 行子集及产品 owned close／恢复仍需实际矩阵；不以 Tool end、进程退出或额度清零代替 |
| 真实 Docker 与安装兼容 | 原 CID／daemon／CLI 故障窗口单独运行；genuine process peer 仅作结构证据。还需最终安装、默认及不可变旧 History 的兼容复验和源码／包身份记录 |
| 性能与质量边界 | 已完成同声明 CPU 重复工作优化；实际 prepared→Thread 阻塞尚未关闭。dev109 冻结模型质量沿原范围引用，本批未改业务模型路径，不无条件重复完整质量评测；受影响业务链路仍须实测 |

## v11 去重、纯摘要缓存与默认兼容

冻结 v11 共1209个文件。只在 selected3 的只读 CONTROL 验证中合并同一验证边界的
重复完整 walk；原真实身份、关闭／取消及权限事实仍跨实际 I/O 新鲜校验。默认路径的
调用顺序、既有 API、期限和协议 inventory 不变，不把只读验证结果缓存成新执行权限。

纯 Python executable fingerprint 另增加 primitive defaults 的摘要缓存：以不可变
code、即时 canonical 标签及 primitive tuple／keyword-item snapshot 为键，保持原
`python-code-v1` 字节。canonical 标签区分 bool／int／float 及正负零；原地 keyword
变更和 code／defaults 替换即时反映，complex JSON、容器子类、closure／wrapped 继续
走原 serializer。缓存最多1024项，defaults 的 canonical 总字符数超过8192时不入
缓存。审查复现的 JSON 默认 decoder 污染已用不可变 snapshot 消除，不新增 decoder
依赖；该缓存不保存可变权限或业务状态，也不是整个进程内存的固定上限承诺。

根执行者组合 focused 检查113 passed，selected3 CONTROL 受影响71 passed（含34项
新检查），fingerprint 作者范围124 passed、独立范围44 passed；均为 `-W error`，
范围有重叠，不相加。Ruff／格式／空白检查通过。总体声明 profiling及完整仓库回归
仍待完整结果；实际 graph 的失败结果见下文，不从 focused 通过推导性能或业务通过。

独立不可变 dev119 installed → v11 source 默认兼容探针已实际通过：完整默认
Profile／Manifest／orchestration 发布字节相等；原 History replay 与 continuation
保留原 epoch、回执和结果；old Provider调用2次，current调用0次。两个探针 Worker
退出，仅关闭探针自己新建的只读 Run／Registry Histories，未停止共享服务或处理旧失败
Histories。私有证据保留于 `default-compat119120-v11`；该结果不替代最终 dev120 安装
及所选 Coding3 实际服务矩阵。

## Trial14 与尚未完成的全仓检查

正常模式 Trial14 使用冻结 v11，1 failed，181.621秒。Root 失败原因是
`definition_mismatch`；两个 child 各198 events，History分别953,506／953,078字节；
Parent为366 events、2,063,666字节。没有 Tool Activity timeout 或 ActivityFailed，
Thread／Turn／业务 commit 均为0。不能以本次未出现超时证明执行链路已恢复。
Assembly close 成功，但原根未退休且写effect未adopted，新的删除门槛保留schema及
恢复材料；组件关闭成功仍不代替原Root／效果闭合。

v11 的 full-repo 检查共收集12,399项；停止时互不重叠的状态为4,400 passed、75 skipped、
2 failed、7,922未执行。这不是完整绿色回归。两个失败已定位为旧的“Temporal部署准入
一律拒绝”测试期望过时；仅修测试并补2项正向检查，相关 focused 85 passed，不改产品。
该 focused 结果不能补算未执行项或拼成 full-repo 全绿；整批仍须完成续跑。

Trial15 的全局 `sys.settrace` 诊断为1 failed、233.44秒，出现明显执行扰动、Query
buffer full、BadUpdate及nondeterminism，未定位Trial14的主拒绝。Assembly close报
RPCError，Worker退出，Thread／Turn／业务commit均为0，schema及原证据保留。
该次诊断不能作为性能或实际业务验收，也不能据此归因新的产品缺陷。

替代诊断在冻结v13中保持默认关闭、独立marker／env，仅测试Worker在Python3.12使用
[`sys.monitoring`](https://docs.python.org/3.12/library/sys.monitoring.html) 的RAISE事件；
不启用CALL／LINE／PY_START／PY_UNWIND，不安装sys／threading trace。仅记录产品
源码路径内所有异常的静态module／class、basename／function／line及pid，私有0600
日志最多64个唯一类型与位置，不记录消息、locals、参数、请求或凭据。不抢已有tool，
退出禁用事件、注销callback并释放自身tool；诊断I/O及清理失败不替代原业务异常。
Python3.11明确不安装，无trace fallback。代表函数在监控前／期间／后co_code等
代码字段、executable_digest及未缓存摘要完全一致，63项focused独立复核通过。
诊断与SDK timing分离，v11至v13产品源码不变，不改协议／权限／期限。
Trial16 的RAISE-only诊断定位主拒绝到 `temporal_coding_runtime.update` 第167行：
Thread授权的 `permission=False`。独立SDK时间线确认，两个leaf的自动denial cancel
分别早于各自首次Tool timeout 5.678／6.448秒；Registry scoped close及Parent stop
更晚，因此取消不是首次拒绝的来源。本次诊断不作性能或验收声明。

确定根因是 `coding_execution_rules.grant` 正常prepare即设置 `pending_stop=True`，
表示未完成的原生资源义务；compact projection却将它并入 `stop_requested`，使后续
Thread授权被拒。冻结v14只修正这一投影：`pending_stop`仍严格bool校验且继续阻止
物理闭合／退休，实际cancel、stop_needed／stop_active、Parent stop、终态和seal
仍拒绝新grant，原grant权限、关闭及退休规则不变。真实grant／adopt三阶段的纯测试
和投影到SDK validator的权限测试均RED→GREEN；315项focused通过，Root独立113项
复核与其重叠，不能相加。

正常模式Trial17为1 failed、257.36秒，2个Thread、0 Turn／业务commit，审批观察达到
180秒期限。两个Tool各80.002秒超时；Thread grant发生时，Tool已分别使用68.335／
67.556秒。两个stop Activity在47.098／48.541秒返回 `effect_outcome_unknown`，不是
stop超时。原Tool授权处的DefinitionMismatch消失，但Parent release仍因unknown不能
闭合而拒绝，不能称所有DefinitionMismatch已消失。两条PG记录的物理状态均为
stopped／fenced／retired／transport closed且pending_stop=False；效果仍为2 dispatched、
0 adopted，Root未退休，schema继续保留。SDK无BAD_UPDATE或nondeterminism，仅有两次
Tool timeout及cleanup shutdown；本次仍未通过业务或恢复验收。

冻结v15仅合并纯同步段重复检查：fresh稳态由6次完整check／12次发布重建降为4／8，
最后一次Namespace返回后的纯DTO段与其外层检查合并，validate／permission在await
fresh返回后立即保留完整outer check。伪造fresh、端口／发布／Activity身份漂移仍拒绝；
每轮SDK Query3／Describe3／Namespace2不变，无权限缓存或期限调整。作者111项与
Root138项focused检查通过，范围重叠不相加。正常Trial18最终1 failed、255.98秒，
2 Thread、1 Turn、1次文件commit；仍未通过，详细时间线待审计补齐。

v16按契约将相邻注册walk合并扩到selected3的有限business allowlist：thread/start、
turn/start、thread/read继续用business Schema，独立原始grant及PG execute判断不变，
最后取消Query两侧仍完整新鲜校验，Local／legacy／其他方法顺序不变。Trial19使用v16，
1 failed、257.57秒，2 Thread、2 Turn、2次结构化peer文件commit。保留History审计确认：
Turn receipt在Tool启动后73.989／76.304秒采纳，两Tool均在80.002秒SDK超时；实际
handler end ledger ACK在各自SDK超时后5.692／7.364秒完成，tool_execution_ended ACK
在超时后6.559／9.447秒完成。这些是实际结束证据，不能追认超时Activity的业务结果。
两分支均无terminal observation、result candidate或effect ACK；physical_stopped=True，
但两个effect仍dispatched、零adopted，Root未退休且schema保留。Assembly close成功、
Workers退出，物理资源闭合不代替未知业务效果。

Parent为466 events／2,959,082字节，children各248 events／1,090,272及1,089,321字节，
Timer为0；无BAD_UPDATE、nondeterminism或WorkflowTaskFailed。两次文件commit仅证明
结构化peer效果，不证明真实模型质量或效果采纳。该次有1秒OS采样，不能称零observer
性能验收，也不能由重叠时间区间推导完整CPU／RPC成本拆分。本轮另一个pure fingerprint
尝试实测负收益，已撤回，无当前增量。

selected3稳态原Scope只读read-set边界已实现，通过Root220项focused及独立审查。
这是明确语义变更，不等价于旧的“每个await都完整检查Manifest”：首I/O前及公开callback
返回前完整校验，独立外层Runtime.validate_release保留，fake_check／fake_fresh不能绕过；
中间namespace／gather边界保留client／service、既有_ports函数／源码及传输绑定、
live Activity claim、request／snapshot及actual SDK身份检查，每次Query／Describe／
双UUID读取均不减；不在中间重建全部Runtime组件，其配置／身份／嵌套代码仍由入口／
出口full检查。
组件或capacity／policy配置漂移可以让已固定的原Scope只读取证完成，但必须在出口完整
拒绝，不能采纳证据、返回可用权限、发Update／原生请求或PG写。传输／claim／namespace／
源码漂移仍在既有中间身份边界拒绝；此方案不提供即时read-auth撤销，有该要求的部署
不能使用此例外。bootstrap、默认／legacy、原grant／native／写入边界均不合并，无权限或
SDK结果缓存、期限变化及新authority。

冻结v17的Trial20实际graph-parallel-toml通过：1 passed、269.63秒。两个连续Run均
succeeded，Registry count为0且下一提交被接受；Tool80秒、Runner60秒、整体360秒
期限均未改变，本次无trace或OS sampling。该证据仅关闭这一实际组合的失败门槛，
不推导整体性能或完整矩阵通过。独立保留证据审计确认4个Tool成功完成，耗时分别
71.240／78.126／77.031／73.678秒；4个effects adopted及4条effect evidence；45个
已开始actual calls全部有原end ACK，8个业务Histories全部sealed。两个原Root各有
成功退休证书，单额度在首Root退休后周转接受第二Root；删除门槛报告accepted2／
retired2／retained0，Assembly close、owned Workers退出和schema删除均成功，无证据
错误。捕获History中timeout及nondeterminism均为0。

Tool耗时仍接近80秒上限。这是一次结构化peer组合的正确性验收，不是延迟SLO、
性能成本改善幅度或稳定性基线。当前offline全仓回归与Trial21单Agent在独立进程
并发，宿主14 CPU；Trial21不是受控性能样本，不改变Trial20无trace／sampling说明。

当前源码实际已通过两个拓扑组合：上述graph-parallel-toml，以及Trial21的agent-sdk
（1 passed、48.91秒，与offline回归并行，非性能样本）。基础A组Trial22另为8 passed、
37 deselected、172.96秒，覆盖never-used owned close、sync／async／host策略工厂、
reserve／start丢回复后的原alias／queue／epoch恢复、ordinary2与Coding3共享quota、
以及关闭acceptance后late original start仅stop-only。私有证据在
`/private/tmp/ralf-agent-dev120-root/selected-service-21.log`／`.xml`及
`selected-service-22.log`／`.xml`，Trial20审计为同目录`trial20-normal-summary.json`／`.md`。
37项deselected不计通过；其余拓扑Trial23运行中，尚无该组结果，其他门槛保持待验。

v17离线续跑现已完成，exit0：本轮6,828 passed／801 skipped／4,941 deselected，
777.78秒；4,941项另有严格字节与节点匹配的复用证据，去重后当前12,570个节点为
11,769 passed／801 skipped。执行后1,672个public files changed0、product source
unchanged。私有证据在`/private/tmp/ralf-agent-dev120-root/development-v17-resume-3lio006m/`
的pytest.log／pytest.xml／collection.json／post-byte-check.json／run.json。这完成当前
源码离线基线，不是一次连续全绿；deselected仅经严格复用才计入，服务配置skip不代验收。

Trial24的D组首个never-GO实际负例agent-False在业务断言后被Werror判失败：保留的
Unix socket owner在GC时泄漏，1 failed、20.03秒，其余8项未执行，不能隐藏为通过。
审计正仅针对fixture根因开展TDD，不删未知状态或过滤warning；其私有原证据为
`selected-service-24.log`／`.xml`。Trial23其余拓扑组仍运行中。

其余 Coding 编排／恢复矩阵、真实 Docker、独立安装与最终默认兼容仍待验收。
Trial30的native-stop原UNAVAILABLE预写故障保留为失败证据：stop ACK失败使原执行栈在
result_candidate持久化前结束，后续物理停止和end ACK不能补出业务结果。无持久candidate
的自动结果恢复未交付，必须保留unknown效果／额度／恢复资料，不能泛化fence。测试现将
原栈仍活的有界hold／release正例与该UNAVAILABLE保留负例分开，两者实际复验均待完成；
不把原失败改称正向恢复成功。
离线基线完成不关闭实际服务门槛。旧路径的固定间隔观察仍产生 History；当前 selected3 实现及单场景
载荷下降不能证明长期审批实际 History 已有界，也不能代替真实模型 Coding 质量。SDK Session coordinator
准入、分布式真实模型质量及第三阶段其他必需能力继续按各自门槛推进。


## 截至 Trial38 的分项验收补记

本节更新前述当时“运行中／待复验”的状态，保留原失败及其冻结来源。dev120尚未发布。
13种源码拓扑已分次各有通过：Trial20 graph-parallel-toml、21 agent-sdk、23前5项
sequence-json／graph-sequential-sdk／team-sequential-sdk／team-router-json／
team-supervisor-sdk，及28的dynamic-flat-toml／dynamic-dag-sdk／dynamic-model-json／
checked-team-sdk／team-sequence-toml／recursive-json。Trial23的dynamic-flat失败没有被
改算通过；28是新Scope复验。这些跨候选记录不能称为当前候选同次完整服务矩阵。

| 实际记录 | 已证明及限制 |
| --- | --- |
| Trial27前三项＋38 | 真实Docker／CLI四项通过：never-GO agent-True、CREATE hold、reply-loss，以及unreachable。27的unreachable原失败保留；38仅该项在新Scope复验1 passed、102.01秒。结构化process peer不据此扩成真实模型质量证据。 |
| Trial33 | 跨Scope Coding close隔离1 passed、28.63秒；不代替产品owned-close整体收尾。 |
| Trial35 | 2 passed、196.45秒。审批正例是停止pollers、drain原handlers／end ACK后的优雅交接，再冷启动核原epoch／pending／receipt和退休；另一个真实活跃CONTROL硬杀负例核unknown／quota／资料保留。原25失败保留，任意CONTROL硬杀回收未交付，不能借Tool cold fence扩大权限。 |
| Trial36 | 四个独立ACK正例native-stop／tool-end／deployment-end／effect通过；无candidate负例取PG TEXT record的observations时TypeError，整组4 passed／1 failed、134.07秒。仅测试解码已修（含正例unknown分支同类问题），尚未实际复验，不把该负例记为通过。原30业务candidate未持久化失败仍保留。 |
| Trial37 | deadline固定15秒，1 passed、30.06秒。Action dispatched、零额度unknown、截止后无business grants、原receipt／held quota／资料保留有正证据；记录commit_observed=false，缺commit日志不是no-dispatch证明，也不证明deadline-after-commit。原29等待commit的前置时序失败不改算成功；commit-alive／fail-stop沿原cancel参数单独引用。 |
| D34阻塞 | 无PG资源行的approval child之agent owned-close 1 failed、74.27秒，出现Worker call admission is closed，原Root未退休；该组后续项未执行。仍需产品修复及真实复验，组件成功退出不能代替原Tree退休。 |

本节逐项核对私有 `selected-service-33` 至 `selected-service-38` 的XML与日志；
路径根为 `/private/tmp/ralf-agent-dev120-root/`，37另有原deadline-dispatched-and-unknown.json。
后续Trial39–45的分项结果见下一节；未改写私有进度文件。原11769 passed／801 skipped
是冻结v17严格节点／字节复用的离线续验基线，后续候选产品与测试变化仍须续验，不能
称当前全绿，也不把skip／deselected当实际通过。最终安装／默认兼容、产品owned-close与
其余必需恢复门槛未关闭；完整batch2、SDK Session coordinator、真实分布式模型质量及
第三阶段能力继续按原范围推进。本补记不改变协议、期限、执行权威或原能力边界。

### Trial39–45：恢复、关闭与审批 idle 的分项证据

冻结v20的Trial39原Tool Worker在turn／candidate两个窗口死亡后的恢复均通过（2 passed，192.92秒）；Trial40的同Runner压力、已封存根再次drive、释放回执丢失及动态修订恢复均通过（4 passed，334.21秒）。这些是原结构化peer与真实Temporal／PostgreSQL证据，不代表真实模型质量。

Trial41在冻结v21中验证单Agent owned-close通过，递归关闭暴露清理代码误读真实proof不存在的release_digest字段，以及原CONTROL observe/cancel被关闭门禁拒绝（1 passed／1 failed，106.05秒）。修复后冻结v22的Trial43已有三项通过：原零额度cancel、无持久candidate的unknown保留负例、单Agent owned-close；递归关闭仍以CloseIncomplete失败，后续parallel关闭未执行（整组3 passed／1 failed，271.76秒）。原CONTROL全部返回ok=True，进一步诊断定位到Parent在物理停止后跳过未settled child，忽略后续结算wake；原失败保留。

Trial42的10秒审批idle前后，三个原epoch的236个事件、1,591,843 JSON字节及8条调用记录完全相同。随后批准的业务链路因两个Tool约80秒超时而失败（整例271.54秒）：已有两次结构化业务commit，但没有candidate采纳，unknown效果与原资料正确保留。idle子结论成立，整个用例未通过；未证明宿主负载或具体热点是超时原因。隔离复验保持原Tool80／Runner60及业务断言。

Trial44隔离复验的10秒idle子断言也通过：三个原epoch前后均为236个事件、1,594,152 JSON字节及8条调用记录，原调用ledger一致。随后业务链路仍发生Tool约80秒超时，整个用例1 failed、267.91秒。它证明该审批窗口没有新增History／Activity调用，不证明完整用例、业务延迟或性能验收通过；没有放宽Tool80／Runner60或后续成功断言。

冻结v23的Trial45单Agent与recursive owned-close均通过（分别13.25／113.60秒）。selected3的合法dirty子通知现可在物理停止后继续采纳原观察与信用结算；旧协议、无dirty时的安静行为及unknown／closure门槛保留。该组parallel owned-close在业务前因fixture换用SDK Client，触发原Assembly客户端／queue固定校验而失败（整组2 passed／1 failed，134.57秒）；仅fixture已修，等待Trial46实际复验，不能把该项或整个owned-close矩阵记为通过。

以上结果逐项对应私有`selected-service-{39…45}.xml`／`.log`；Trial44的子断言证据为其case中的`approval-idle-history-summary.json`。这些分次、跨冻结候选记录不合并为同次完整服务验收，不证明真实模型质量或dev120性能收口。

全量离线v21串行运行已由Root主动中断，保留日志及所有临时资料，冻结公共字节未改变；其不完整结果不复用。将以固定完整快照的互不重叠module分片执行全量回归。完整回归、最终安装与兼容仍待验收，dev120未发布或提交。

### Trial46–48：完整 idle 用例通过，并行关闭仍待验

Trial46没有形成JUnit；asyncio退出超时后，Root核对原pytest PID1001并发送SIGTERM（退出-15）。primary失败原因尚不明确，2条未end原调用及PG资料保留归档，不记通过，也不推断为已定位的产品失败。

冻结v24的Trial47完整用例通过：`selected-service-47.xml`为1 passed／0 failed／0 errors／0 skipped，151.117秒。case的`approval-idle-history-summary.json`显示10秒审批idle前后三个原epoch的220 events、1,574,051 JSON bytes及7条调用记录完全相等，ledger摘要不变。批准后4次原生提交、2次结构化peer文件commit，succeeded、2个effects adopted、Registry count0、seal和physical stopped断言均通过。该记录将此前Trial42／44的idle子结论推进到这一个完整业务用例通过；没有提高Tool80／Runner60，也不证明性能SLO、真实模型质量或整个dev120验收完成。

v25的416份产品源码与v24完全相同，仅补测试primary诊断。Trial48同一parallel owned-close为1 failed、123.37秒，primary已定位为fixture对closing Engine查询diagnostics触发ValidationError，正在仅修测试；日志另有原`ralf_coding_stop`被关闭门禁拒绝，其时序及产品影响仍待定位，不能先归因为primary或宣布清理正确。不以Trial47替代并行故障关闭、当前候选完整回归、最终安装或默认／原History兼容门槛。SDK Session coordinator仍未实现，阶段3批次2未关闭。
