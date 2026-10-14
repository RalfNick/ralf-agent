# 原 CREATE 监督与未发送证明

基线：dev111／`6ea59ff`。本契约补第二阶段 R13 的真实 CLI 生命周期与故障窗口；第一阶段 dev99 默认业务保持冻结。LocalEngine／Temporal History 继续独占 Run／Action 执行权威。完整第二阶段、已发送但 daemon 回复丢失的负窗口、跨宿主与复杂 Coding 质量仍需各自验收。

## 职责与单次执行

受管理默认 Coding 组合增加显式版本的机械 CREATE broker。它只延续原 prepare grant 下的固定命令；不管理 Run、审批、预算，不创建新 Action，不重授 Thread／Turn，不重试 CREATE 或启动恢复的容器。原请求始终带固定 dispatch、Runner、物理根、generation、operation digest、命令／解释器／执行文件和 helper 实现身份。

Worker 持久化原操作声明后启动尚无执行能力的 broker。broker 自行登记真实 PID／birth／原 token，并 fsync 后报告 ready；Worker 核验实际 Popen 子进程及登记，才发送唯一外层 GO。broker 启动固定的 gated CLI 子进程，后者在收到内层 GO 前不能 exec Docker、连接 endpoint 或发送请求；它先自行登记，broker 持久化准入，再发送一次 GO。子进程持久化 accepted 后在同 PID exec 原固定 argv。禁止 shell、`preexec_fn` 和隐式凭据／环境继承。

父进程在 spawn 与 PID 落盘之间退出不能留下未登记且能发请求的子进程。两个门都不可重开。收到有效 GO 后再收到 EOF，仍是已准入，不得改判为未发送。缺失登记、receipt、socket、PID 或 gate EOF 本身不构成完成证明。

## 原处理器所有权

原 broker 保有实际直接子进程句柄，负责有界输出、期限、控制和真实结束。原 namespace／operation lease FD 明确贯穿 broker、gate、CLI；父 Worker 退出不丢弃活原处理器的 OS 所有权。根级持久容量义务仍阻止新业务，不靠 PID 消失或 TTL 清空。

冷 Worker 只能经固定原控制通道 query／abort／drain，不能发 GO、启动替代 executor 或调用 prepare。控制通道校验私有 owner／mode／inode、原操作 token／部署／generation；需考虑 Unix socket 路径长度，短控制目录也必须显式固定。原 broker 控制自己的尚未 reap 的子进程；冷 PID／birth 观察不是信号权限。

进程退出须在不 reap 的情况下观察，再清理原 group，最后 wait。修复既有 reap 后无条件 `killpg(old_pid)` 的复用竞态；stdout／stderr EOF 不能替代 CLI 真实退出。平台没有稳定/non-reaping 观察能力或存在未知外部 reaper 时失败关闭。broker 也已死亡但 CLI 活跃时保留 unknown，不能靠 check-birth→kill 的竞态路径清理。

## 持久证据

操作日志区分 launch intent、broker 登记、CLI gate 登记／准入与不可变终态；按 writer 分离记录，避免旧 Worker 覆盖后来的 child receipt。写入须有界、atomic／fsync、nofollow、重复 JSON key 拒绝和固定文件／锁身份。

只保存结构化结束状态、输出完整性与摘要、合法完整 CID 或 null，不保存任意 stderr、异常文字或凭据。完整 CID 是正向候选，须完整 inspect 原标签／配置／身份并保存 locator 后，才能沿原 stop／rm／独立缺席确认退休。CLI 非零、超时、输出越界、部分 CID、强制退出或 empty inventory 在可能 exec 后继续 unknown。

唯一可新增的本地负向证明是：原 gate 不可重开且从未 accepted／exec，实际 helper 已结束，加上原 exact name／完整标签的成功空 namespace 查询。该证明是 metadata-present 的专用 `create_not_dispatched`，不得套用“prepare grant 未消费”的 `unprepared`、metadata-absent 的 `namespace_absent`，或伪造 `CID=null` 的容器 fence。

原 pure rule 校验完整操作与 prepare grant 对应、无 prepared／Thread／Turn 矛盾；PG 先保存机械证据，再由原 History／Local 采纳。真实工作线程与控制处理器排空且采纳成功后，RootCapacity 接受严格原 token／dispatch／Runner／generation 的未发送投影并释放。失败保留原义务；效果／费用未知、既有 attempt／grant 不清除，不授权再执行。

## 版本与验收

新选定 native v5／binding20、composition v6／binding21。旧18／19由 immutable dev111 Worker恢复；未选定默认发布与独立环境默认 identity／metadata形状保持。新增 broker／gate／process watcher／日志与 IPC／纯规则／schema／typed constants 及库存生成函数必须手列固定；History只验证纯规则及 IO SHA，不导入或执行进程逻辑。

操作声明固定完整 helper 源文件摘要，Env 在原资源身份生成时固定该源码集合，不在 grant 后重新选择当前实现。独立隔离解释器在 compile／exec 前核对全部源字节。Worker 库存同时核对实际导入别名与 canonical helper，拒绝对象重绑定，不能借缓存过的库存掩盖运行时实现变化。冷控制也复核原声明；不通过新声明替换原 ledger。正常退出移除固定原 socket，操作声明及短控制目录作为证据保留；目录保留不是处理器仍活跃，GC 尚未交付。

验收覆盖两个 spawn→登记窗口、fsync 与 gate发送顺序、部分／重复／GO后EOF、父 Worker真实退出／原broker存活、broker退出／原CLI活、stdout EOF但进程未结束、descendants／期限／输出失败、原PID／PGID复用、foreign token／generation／endpoint、receipt采纳失败、同根跨父背压、无重复attempt／CREATE／START、安装包、旧发布恢复和真实Temporal／PG。所有自有进程、socket、目录及容器须实际清理，不能用Future完成代替。

## daemon 负向边界

当前 CLI 不提供关联原 CREATE 的持久 operation-status。原 CLI 结束或空 inventory 不能证明 daemon 不会晚到创建。完整且持久关联原请求的同步 daemon reply 可以成为调用结束屏障，但错误不是对象缺席，仍需后续完整查询／原对象清理；版本与后端语义须另行固定。回复丢失依然 unknown。本批不得为省略真实 CLI 监督而替换成未经验证的直接 Engine／proxy adapter，或把所有负窗口标为完成。
