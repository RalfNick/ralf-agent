# dev75 Read-only Workspace 子集验收

基线de59df6/dev74，新增同步WorkspacePort、文件／内存默认实现、受管理三项只读工具及async声明。原Engine／History／Action／Policy／线程跟踪器不变；每Agent workspace角色、写入、Skills／Sandbox／Runner及完整R01–R26仍开放。

Task1缺失API：16断言失败＋56fixture setup错误（0.92s），均因公共API缺失；不把setup错误算作行为复现。首次72 passed（1.03s）；额外实际根FD初始化失败泄漏／list只检查目录版本漏掉文件变化，两项真正RED／74已有通过（1.05s）。修复后正式76 passed（0.70s）。初次文本补丁未匹配格式化except，仍保留失败，之后精确修正并闭环。

Task2缺失Source／factory12项失败，另12项原未知适配器拒绝已通过（0.76s）。测试修正局部monkeypatch上下文、prepare返回tuple、重复root参数、required command_id；这些均为fixture／命令错误，不计产品RED。原工具中抛权限拒绝会保守等待核验；新增声明Scope准入测试真正RED（0.66s）后在分配port前拒绝，保留原权威。最终相关167 passed（1.55s），正式91 passed（1.52s）。真实Temporal FS／Memory两项通过（8.33s，无跳过），包括审批重启、重复控制、接受后文件变化、原结果与History恢复。

独立审查和重新冻结后的完整回归、安装、旧74兼容门槛通过。两次自有Temporal原41382／17275及64834／17276均已停止并等待实际启动进程exit0，核对stopped标记；只读工具本批未使用PG或真实模型，未推送。

判断及代价按顺序记录：

- 持续开发授权覆盖重复设计／计划／完成确认，仅本地提交；判断错误需在发布前修订，无远端授权。
- 先交付只读Port而非Workspace角色／写入／Sandbox，最小可替换边界；需要写入／Coding的应用仍需后续能力。
- 使用真实root摘要／device／inode身份，不创建UUID元数据；移动／替换root需新发布，原恢复需要原root。
- 有界完整允许视图排除.git/.ralf，超过限额拒绝；大目录需后续分页，保护路径需其他显式策略。
- 相对root与原base_dir词法拼接，避免context.path掩盖最终符号链接；依赖符号链接root的配置须显式选择真实root。
- 无scopes时取可信装配Scope，显式列表仍固定；换Scope装配会改变原source身份并拒绝旧Run续接。
- 声明Scope必须在配置allowance内、分配port前核对；不能仅为其他Scope预装配，SDK显式注入仍可使用。

一次独立只读审查：全25路径、focused103通过、258模块冻结一致；无Critical，8项Important均保留进入一次统一RED→GREEN修复。根初始化别名／竞态、canonical祖先别名、Scope字符串子类、拒绝输入临时分配、直接SDK关闭派发、非UTF8 root FD泄漏、SDK只读Policy和NUL二进制均需闭环。第6项为模拟Linux式path resolution＋真实FD证据，本机无法创建原始无效UTF8目录名。

延后Minor：C1 Unicode控制字符路径／root仍被接受；现有拒绝范围是ASCII控制字符和DEL，完整Cc策略待后续。不将此项混入Important修复。

审查取舍与代价（完整18项Declined，按原顺序）：

- Atomic snapshots against malicious concurrent writers：metadata checks remain, no filesystem transaction is certified；代价：change-and-restore needs external exclusive leases/isolation。
- Mutations after the final validation syscall：finite checks certify only observed read evidence；代价：applications need stronger snapshot/lease semantics if later mutation matters。
- Malicious custom-port Python or forged identities：trusted implementation contract stands, no sandbox claim；代价：untrusted adapters need isolation/authentication。
- Private adapter/frozen-dataclass escape-hatch mutation：outside public contract; ordinary Scope subclasses become Important fix；代价：integrators must protect trusted objects。
- Privileged kernel/mount/bind-mount manipulation：not host-admin isolation; ordinary root replacement is Important；代价：requires actual OS/container isolation。
- Hard wall-clock for stalled filesystem calls：true operation ownership remains until OS call exits；代价：shutdown can exceed application timeout。
- Hard total interpreter RSS for valid inputs：files/path/content bounds stand, rejected oversized temporaries are Important fix；代价：valid metadata and shared process usage need separate quotas。
- Windows or missing POSIX operations：explicit refusal before allocation stands；代价：portable alternative/custom port required。
- Native Linux surrogate-root reproduction：real FD leak under simulated OS resolution is Important, native Linux not certified here；代价：additional Linux service/fixture acceptance still needed。
- Directory pagination/beyond-limit traversal：bounded complete view refusal stands；代价：large directories need later paging。
- Protected .git/.ralf reads：excluded host policy stands；代价：other explicit policy is required for protected content。
- Identity continuity after explicit root reconfiguration：new release is required; silent ancestor alias continuation is Important fix；代价：old Runs need original resource or migration。
- Enterprise ACL/authentication from Scope：trusted host allowance only；代价：enterprise actors/ACL still need separate implementation。
- Workspace writes/leases/write receipts/unknown writes：deferred actual protocols remain open；代价：write/Coding applications cannot use this read subset alone。
- Agent Workspace role/Context loading/Skills/Sandbox/Runner：separate capabilities remain open；代价：applications still assemble explicit sources until follow-up。
- Production/live model quality：no model-quality certification in read-only review；代价：requires actual repeated task evaluation。
- Independent repeat of historical installed/compatibility/package gates：reviewer inspected supplied evidence; executor owns frozen revalidation；代价：no independent certification of those previous runs。
- Whole suite/service shutdown/frozen build/post-fix certification：executor must finish final gates, no second review；代价：cannot claim release/full goal complete from focused103 alone。

新增修复取舍：原注册函数增加可选纯validate_tool_policy，严格同步None返回，发布handler前拒绝；同名无关自定义方法须改名或实现该新契约。支持文本明确为UTF8无NUL，不承诺完整二进制分类；其他可解码二进制需要显式解析策略。BASE→WORKTREE审查覆盖初始25路径，Task3最终本地提交；之后仅一轮复现及冻结门槛，没有第二次审查认证。

统一修复复现：初次19失败含1项空registry应为dict的fixture错误；规范化无效UTF8模拟补充真实FD后，21项真正RED／1项旧reserved-key guard已通过（1.00s）。八项Important修复后的相关389通过（40.50s）；同一有界处理问题再补自定义输出JSON复制峰值RED（9450340字节，0.65s），先限制文本再canonical复制后，最终相关390通过（39.06s）。无第二次review；第一次冻结全量4430 passed／339配置依赖跳过（699.00s，原73871 exit0）及安装／实际恢复通过，但之后 Important 7 变体要求重新冻结验证，原结果仅作为历史证据。

第一次冻结核心安装126 passed（2.83s）／SDK190 passed（3.15s）、真实源码2 passed（8.91s）／安装2 passed（9.26s），必需服务项无跳过；组间有重叠。实际74↔75 Local／默认Temporal／native save-v1／CLI版本2恢复与22个原模板内容通过，所有兼容Worker原启动进程等待退出。258模块／源码／wheel／sdist／两安装环境、元数据75、安装示例／依赖检查／CI YAML通过。第一次全量源码通过。此后执行了重新冻结验证；最终结果以下文新冻结证据为准。

最终冻结补充：SDK 边界检查复现了 Important 7 的字符串子类比较绕过变体；补充测试先失败，新增普通字符串类型校验后相关 391 项测试通过（42.97 秒）。先前 4430/339、core 126、SDK 190 等属于前一次冻结证据；最终提交使用下列重新冻结后的完整回归和安装恢复结果。

重新冻结安装验收：核心127 passed（2.55s）／SDK191 passed（2.71s），真实源码2 passed（8.05s）／安装2 passed（8.79s，均无跳过）；旧74 Local／CLI／默认Temporal／native save-v1双向兼容及22模板通过。258模块源码／新freeze／wheel／sdist／两安装环境和75元数据一致；两份已安装指南示例、依赖检查、CI YAML、Ruff／格式／空白检查通过。自有64834已等待实际exit0。重新冻结完整回归原57600实际exit0：4431 passed／339配置依赖跳过（704.50s）。上述安装／服务／兼容组间存在重叠，不能加总。最终文档sdist同步和逐字核对后，仅本地提交并运行正式Task3收口；完整R01–R26保持开放。
