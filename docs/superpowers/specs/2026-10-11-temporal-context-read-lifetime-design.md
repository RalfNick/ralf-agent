# Temporal Context 读取的实际处理器生命周期

状态：dev68 子集实现与验收通过；基线0917d72/dev67。属于用户已授权持续实施的R01/R02/R14/R19与既有Harness/Session契约；采用当前会话内实施，不再次请求开始授权，不推送远端。

## 目标与范围

原生/顺序以及图、Team、Plan/DAG、嵌套实际Agent的普通Context和受管理Context只读阶段，在观察取消、Activity超时、全事件循环取消后，仍准确持有实际读取处理器和结束通知。只有原History接收响应或超时事实及原实际结束证据之后，才允许推进模型或报告静默/释放Turn。默认实现覆盖原Session/Facts/Knowledge及Artifact读取，可替换组件仍承担同一端口契约。Root读和Session写保持dev67原拥有关系。

已复现dev67缺口：实际ThreadedMemoryAdapter.read_page仍在运行，Native History已quiescent、Turn已释放，wait_session_executions返回True。证据为真实Runtime/原Actor/实际线程，不冒充真实Temporal Service。

本批只读阶段为普通`context`及managed `plan/read/verify/finalize`；summary模型调用和write产物写入继续使用原模型/效果协议，不能把只读关闭API称为所有Worker调用的静默证明。后者与Temporal配置、全局治理/真实质量留在完整能力清单，不缩小R01–R26。

## 架构与选择

复用已有ThreadExecutionTracker/current_thread_tracker/current_thread_group：ThreadedMemoryAdapter已在该上下文中跟踪实际同步处理器，不需修改默认适配器或搬移异步数据库客户端到新事件循环。新增ContextExecutionOwner仅管理实际协程/线程/结束通知，不能发起业务Run、重试模型、写入执行状态或判定业务成功。原Native History保存只读意图/派发许可/响应观察/结束事实，Parent和Session Coordinator继续采用原后代证据。

没有选择把Facade锁/Task.done当作执行结束，因其不能证明底层线程停止；没有选择把整个混合Context放进新线程事件循环，因异步数据库客户端必须留在创建循环。

## 公开装配与兼容

`TemporalRuntime(context_reads=False, context_execution=None)`：默认False保留dev67完整Manifest/请求/History行为；True使用默认ContextExecutionOwner，或者注入实现`identity/execute/wait/aclose`的受管理端口。只给替换组件而未启用时拒绝。开关要求严格bool。宿主固定其原实例、配置及实际方法，所有注册数据/客户端仍borrowed。

显式启用发布`kernel=temporal-3,binding_protocol=2,dispatch_admission=history-1,context_read_protocol`。协议包含version1、固定只读phase集合、owner身份与方法摘要；binding_protocol2必须与完整协议同时存在，binding_protocol1拒绝该新能力。dev67在原Manifest校验阶段拒绝2，不能等模型/数据Activity开始才拒绝。

新源码仍支持binding_protocol1旧发布；不存在新标记时不添加字段/结束事件/读取重试规则。选中Runtime视图继承宿主强制只读拥有关系，不能由每Agent禁用；源/namespace/data身份选择保持原逻辑。新Marker不改变SessionKey/根物理位置。

显式启用的线程数据源还发布`context_read_metadata_bridges`，以原physical摘要关联固定的元数据桥接端口；不改变旧dataset_ports。运行前及I/O前后核对原source和实际bridge方法，防止只固定同步后端而遗漏新增实际异步桥接。仅原Session写注册中的dataset允许该附加端口。

## 原History读协议

每个只读Action固定请求，加入`action_id/release_digest/execution_epoch/phase`以及已有Scope/run_id。`execution_epoch`为原Workflow实际run UUID，在纯测试中可用原State固定epoch；不得用新随机数或当前时间。Action记录完整request_digest及只读阶段。

派发前调用原admit_context_dispatch Update。新阶段只在启用的只读协议及原活动Action中允许；校验Scope、实际epoch、release、phase和完整请求摘要。许可持久化且幂等；无许可超时后原Action失败，迟到派发永久拒绝。

原History只读记录同时持有`response_observed`与`execution_end_proof`。响应接收仍按原Context/managed阶段校验和采纳，原快照不会重新读取。实际结束先到时只记录事实，不清除尚未观察响应的Action；响应先到时不宣称静默。失败/取消后迟到响应只保存证据，不改变业务终态、不再派发模型。

`context_execution_ended` Update的证明严格包含Scope/action_id/release_digest/request_digest/execution_epoch，匹配原已获许可的Action。重复相同证明返回原效果；伪造/其他epoch/请求/phase拒绝。结束证明不是模型输出，也不是保存回执；不增加执行credits。读取未结束时原Active Action或原读未知事实保持非静默，Parent原子预算不被错误结算。

普通Context及四个managed只读阶段为单次Activity尝试。读取失败不自动重跑原模型/工具；已经持久化的Session快照继续source-once。其他阶段保持原重试和独立效果规则。

## 实际拥有关系

`ContextExecutionOwner.execute(operation, *, proof, on_end=None)`接受一个异步操作和非秘密固定证明。默认max_calls8；拒绝关闭、容量不足或重复原证明，不启动额外处理器。原scope/run/epoch/action/request共同构成跟踪group。

所有者独立创建并shield操作Task，设置现有线程跟踪上下文。观察取消不取消实际操作。正常/失败/被全循环取消的Task结束后，必须等待该group实际线程结束，再发送原结束证明；全循环取消也不能丢掉线程拥有关系。未送达的通知仍保留并由wait重试，不把TimeoutError或已取消通知当作ACK。异步端口须遵守现有完成/取消契约，不能私下启动未声明脱离托管的后台工作。

`wait(wait_timeout=30)`返回严格bool；`aclose(wait_timeout=30)`仅在全部原操作与结束通知完成时关闭自己，否则CloseIncomplete。闭合只读API不会关闭数据/模型/客户端池。

Runtime公开`wait_context_executions/close_context_execution`，独立于原Session执行拥有关系。默认创建的owner由Runtime拥有；显式注入的owner是borrowed，关闭本Runtime先等待其工作、拒绝本Runtime新读，但不关闭共享owner。原数据资源和客户端均不由这些API关闭。后续配置层须分别等待这些责任，不能创建Local执行权威来装配Temporal资源。

容量/关闭拒绝未实际启动时可明确返回handler_not_started；重复原Action被拒绝时不能借此证明第一次处理器不存在。全循环取消后的线程/通知必须仍能由现存所有者等待并结算；新循环通知若原客户端不可用，保持未完成，不能静默确认停止。

## 验收

纯状态测试覆盖普通/managed所有只读phase、响应与结束两种顺序、取消/失败/无许可超时、伪造epoch/Scope、重复证明、原budget0与全后代占用；旧默认无差异。

实际默认所有者验证ThreadedMemoryAdapter与原生async、混合sources、全循环取消、迟到通知、容量/重复请求、borrowed关闭；不以模拟线程证明实际线程结束。

真实Temporal Native/sequence及图/Team/Plan/DAG/嵌套私有成员，普通/managed，包含Source snapshot之后的metadata读取、Worker kill/wait/restart与全部History replay、旧67↔新默认/native-v1、旧Worker拒绝新2。实际Redis/PostgreSQL和已有RAG/Artifact组合、source-once及模型/工具不重复；安装包/core-only/文档示例/制品一致验证。

单次fresh-context最终只读审查；重要问题一次RED→GREEN修复，全量/制品/能力文档通过后仅本地提交。真实模型/完整M1、Profile/环境/治理仍为后续独立门槛。
