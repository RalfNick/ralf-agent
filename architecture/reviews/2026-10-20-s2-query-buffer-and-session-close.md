# S2 一致性查询缓冲与独立 Session 关闭

日期：2026-10-20；基线 `a83c55b`。仅定位并修复既有查询／关闭链路，不新增能力。原 Tool80／Runner60／审批180／scenario360／first-close60／cleanup40，以及首项通过才运行其余十二正常／五故障的依赖不变。原 a1 制品与全部失败保留，不推送或公开发布。

## 因果定位

前批 a2.dev3 原首项在 360 秒被取消，实际 JUnit465.431秒含收尾、3次业务写入；日志有 `consistent query buffer is full`，关闭任务在原 Coding 状态／权限查询，Session stop task 尚未启动。此前离线 11.262% 完整调用 CPU 收益没有使整链通过，不据此继续局部缓存调优。

本轮先检查 SDK 工作线程竞争：同一个完整 held Registry 查询／两个 Runner 的实际发布材料，8／2／1／8线程各32次，CPU3.415／3.436／3.236／3.377秒，返回摘要及原State不变。单线程差异不足以解释整链，未调整SDK线程默认值或增加容量。该探针无服务／模型，只收窄纯查询线程竞争假设。首次探针把含set的Registry状态当JSON快照而报错，未产生可采纳时序；修正为deepcopy原始状态比较后才采纳结果，原失败保留。

随后核对与实际服务匹配的 [Temporal v1.32.0 配置](https://github.com/temporalio/temporal/blob/v1.32.0/common/dynamicconfig/constants.go#L2707)：`history.MaxBufferedQueryCount` 默认1。新自有真实时间本地服务、不覆盖动态配置，用一个正在处理原Workflow Task的Workflow发送两个并发一致性查询：一个成功，另一个明确返回 `RESOURCE_EXHAUSTED / consistent query buffer is full`。相同版本、另一新数据库，顺序发送同两查询均成功。两个诊断服务关闭、数据库及回执保留；最初脚本Protobuf导入失败保留，不算有效复现。诊断只验证SDK／服务机制，不代替真实RALF整链。

RALF的 `SessionControlValidation.validate` Coding分支确实并发向同一个原Coordinator发出intent和command两个查询。两项单槽原SDK形状端口的完整校验测试均以相同RPC错误失败，确认该调用方式会自己争抢默认缓冲槽；真实服务复现和产品RED分别记录，不把受控端口当作真实服务。

## 最小修复与边界

- 同一Coordinator的intent／command查询改为顺序发送，namespace／describe仍可并行。两份事实仍新鲜读取，所有原namespace／epoch／History／完整材料检查保持；未缓存事实、权限或通过结果，也未提高服务端缓冲。每个读取的错误（含子取消）均保留；失败或调用方取消仍排空已启动读取，最终不得返回成功证明。原SOURCE／端口及I/O前后检查不删。
- Assembly独立启动原有Session stop task，再等待Coding物理排空；二者仍必须完成，才关闭执行Owner、Worker和资源。超时／调用方取消保留两个原任务供重试，不增加执行权威，也不改业务cancel／drive的原命令路径。该问题以“Coding悬挂时Session fence未启动”两项RED复现。
- 原起源读取测试改为namespace／describe／第一个Query可同时启动、第二个Query随后读取；最终仍核对四份事实、History与最终复核。端口在读取中漂移时，后续Query不得派发；该负例核对所有已启动读取结束且没有采纳。不是删去原取消或漂移断言。

相关首轮验证：关闭45项、查询与观察49项分别通过，不拼成一次全量。一次同审查者聚焦审查及增量复核无可行动P1／P2或minor；其独立关闭9项／查询21项通过，未运行服务、模型、完整回归或S2。

## 固定私有制品与实际门禁

`0.1.0a2.dev4`，wheel SHA-256：

```text
6cf80ff5a776e397625da3c220b84b31a001018b82d0c215f7fffef827250f62
```

目录 `/private/tmp/ralf-s2-query-buffer-fix-20261020`；442产品／949测试输入固定，源码／wheel／隔离site一致。SDK从本包site导入，父环境仅供固定第三方依赖，不执行其editable `.pth`。本候选不覆盖a1／dev3，不继承旧包平台或实际服务结果；显式源码固定的历史发布继续使用匹配immutable Worker。

安装445个受影响模块首轮 **6508 passed、1 failed、694配置skipped，597.69秒**；417个已加载SDK模块来自本候选site，442／949输入不变。唯一失败为 `test_owned_session_coding_physical_close_precedes_session_drain_and_worker_stop`：旧关闭桩在Session函数进入时即断言Coding已完成。它混合了准入fence与排空完成，和本批修复目的冲突。原日志／XML／文件保留。

只修该单测：Session桩先记录fence，再等待Coding完成，最后记录drain；原物理完成→Session排空完成→退休→Worker停止→资源关闭断言继续保留。没有更改产品、wheel、期限或跳过该用例；旧／新SHA与其余948输入不变另存。相关5模块源码及独立安装分别 **26 passed、零跳过**。不重复未变产品的其余模块，不拼接两轮为同次全量全绿，`qualification-result.json` 明确保留原失败及定向复验范围。

默认完整材料字节与原输出一致（去尾LF后SHA `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`），两份原History重放、两条starter各一次业务写入通过，然后执行未改场景／期限的原S2首项。

### 原首项真实结果：仍失败，关闭子问题取得证据

同一wheel、新自有真实时间Temporal 1.32.0＋PostgreSQL，原 `graph-sequential-sdk` **1 failed、零跳过，JUnit398.311秒／pytest399.31秒含收尾**。原360秒在第二Turn审批的 `engine.status` 查询期间取消；8次原生提交／4次业务写入，四次写入完成不等于整链成功。最终完整日志的 `consistent query buffer is full` 为0次，仅说明本次选定运行未再出现该告警，不保证所有并发组合。

本次 `cleanup.json` 明确：`assembly_close_succeeded=true`、`close_error=null`、`workers_exited=true`，两accepted root均retired、无retained root，原Session／效果／停止证明允许删除本批自有schema。此前关闭错误未再复现，关闭修复在这一实际整体取消场景通过；不外推剩余故障矩阵。原History、效果导出、Temporal数据库及本批停止失败容器保留；旧失败资源未动。自有服务已停止、outer600看门狗未触发，未启动剩余十二正常／五故障。**S2、Task2／3／4及第三阶段仍开放。**

### 耗时归因边界与下一步

只读导出的八份原History，输出事件类型、数量、时间和原文件SHA，不导出payload或连接凭据，不重启服务。四Tool Activity执行wall分别40.938／38.412／39.199／41.784秒；两个父root共35次CONTROL Activity，执行wall分别累计76.686／75.617秒，排队累计各约0.079秒；13次Session控制Activity执行wall累计86.797秒、排队累计0.068秒。这些跨度会重叠，**不能相加为关键路径或当作CPU**。

信号计数显示父root收到22／20次子wake，Coordinator收到48次child wake，提示内部进度与父级观察可能放大工作量。代码核对发现这些通知也覆盖物理停止、回执和退休变化；尚无证明安全合并的反例／完整边界，因此本批没有删除通知、修改token协议、增加查询容量或缓存权限／事实。后续应先在完整调用中确认通知与观察重复的实际因果，并保留未知效果、审批和原停止唤醒，不能按信号数直接判为可删冗余。

本机安全副本位于 `dist/s2-query-buffer-20261020/`，包括固定wheel、各轮RED／GREEN、原回归失败与定向修正、安装身份、兼容、首项及只读History时序摘要；SHA逐份核对。完整原始服务数据仍在上述受保护目录，凭据不复制。

## 历史与范围

前批a2.dev3完整回归6502通过／3夹具失败／694配置跳过、后续36项定向修正，以及原360秒失败分别保留；本候选的回归与真实服务需另行取证。原失败schema、停止容器、Temporal数据及导出不动；本轮只创建新自有资源。模型质量、真实Docker Coding任务、外部采用及长期R01–R26不在本批范围，未测不标完成。
