# S2 原 Coordinator 查询协调与第二 Turn 就绪续验

基线 `c08a19f`；2026-10-21。仅修复递归／冷交接第二 Turn ready80 与其取消排空链路，不扩展功能或变更 Local／Temporal／Session 执行权威。

## 原门槛与历史失败

Activity90、ready80、Runner60、审批180、正常十三项／冷交接整链600、其他四故障300、first-close60、cleanup40保持。原360／Activity80及旧批失败各自保留，不回填。前批dev13正式矩阵16/18，递归及冷交接第二Turn未就绪并CloseIncomplete；[原记录](2026-10-21-s2-activity90.md)继续有效。

## 定位与最小修复

同一dev13原包独立递归诊断仍失败，原schema保留，自有Temporal／PostgreSQL停止，零停止错误。只读localhost Prometheus累计观察到71次query-buffer-exceeded（BusyWorkflow）；普通日志未完整显示这些重试。该计数是服务聚合，不能把全部71次归于单一Coordinator，也不把诊断墙钟作为正式验收成绩。

旧代码只让单个verifier内部的两次Query顺序执行，独立Activity／Client仍可同时查询同一原Coordinator。四个确定性RED复现跨verifier单槽拥堵。dev14仅在同一进程、同一event loop内，以原namespace UUID／Coordinator ID／精确epoch协调该两次Query；每个调用独立读取自己的intent／command／History，不缓存事实、授权或来源验证结果，不形成新的分布式锁或执行权威。不同epoch互不阻塞；引用计数包含排队者，全部退出即清理。

锁等待是新增await边界。额外三项RED覆盖排队期间selector替换、checker替换及原checker代码改写。原checker及绑定在await前固定，锁后在求值selector／query之前核对绑定并复核原pins；原读前后校验及shield／排空保留。读失败、调用方取消、队列释放和独立epoch并发均有回归；不删独立Session verifier／来源校验，不缓存成功校验。

## 固定包与验收顺序

1. 受影响源码回归与独立静态审查后固定唯一私有版本0.1.0a2.dev14；源码／wheel／安装产品及测试输入前后逐文件SHA核对，原a1及dev13制品不变。
2. 先独立递归定向验证；该诊断不替代正式18项。
3. 同包graph-sequential-sdk首项通过且自有服务停止后，才运行剩余17项；不得跨包拼接成绩。
4. 新产品进行checkout外安装、原默认Manifest／History兼容检查及相关真实服务验证，记录实际通过、失败、跳过与精确保留。完整无筛选离线回归仍是候选收口门槛；本轮正式矩阵失败后未执行，不引用旧包全量成绩作为dev14通过证据。
5. 文档按实际证据更新；仅本地提交，单次跳过钩子，不推送或公开发布。S2／P3-2／第三阶段在同包门槛未满足前继续开放。

私有定位证据：`/private/tmp/ralf-s2-ready80-diagnosis-20261021`，确定性回归：`/private/tmp/ralf-s2-coordinator-query-fix-20261021`。失败数据库和完整History留在私有目录，安全归档排除连接凭据与其测试密码。

## 递归定向结果

最终受影响源码16模块309通过／零跳过，42.88秒；Ruff与两文件格式通过。独立静态复审确认排队绑定／函数体漂移窗口已闭合，未发现新增取消、池泄漏或跨Client事实共享问题；静态复审不替代服务结果。

私有dev14 wheel SHA `4a2420c736941d1229ccf3d8d6887744f36cd19245a3330890a4085179ff1690`，442产品／955测试文件，源码／wheel／隔离安装逐文件一致。递归独立定向1通过／零跳过，JUnit416.106秒（pytest整体416.91秒），两次业务写入，Session空闲／两root退休、Assembly关闭／Worker退出／schema清理通过。自有Temporal与PostgreSQL停止并清理，零停止错误、旧资源未动；随后才启动同包正式首项。

该诊断服务仍累计47次query-buffer-exceeded，不能声称消除全部查询拥堵或以旧71／新47直接推导性能收益。独立定向通过不拼入正式18项；正式矩阵及完整回归尚待记录，S2／P3-2／第三阶段继续开放。

## 正式首项失败保留

同包正式graph-sequential-sdk首项1失败／零跳过，JUnit359.525秒；第二Turn审批reserve返回deployment_release_failed／命令身份拒绝，累计三次业务写入，不是ready80或Activity90超时。Session／Assembly关闭、Worker退出、schema正证明清理通过；Temporal／PostgreSQL已停止，失败容器／数据库保留，零停止错误、旧资源未动。正式剩余17项及依赖的后续验收未启动，不能以递归定向通过覆盖本次失败。

为识别被通用拒绝响应遮蔽的SDK异常，随后在独立私有测试副本安装原SDK OutboundInterceptor，仅记录Query的Workflow／epoch／kind／耗时及异常，使用同一dev14产品与原期限；不改变产品或正式固定输入，该诊断不算正式验收。证据位于`/private/tmp/ralf-s2-sdk-query-diagnostic-20261021`。

独立静态复核定位：Registry第二轮第二次审批在调度Release(mode=control)后1.334秒收到普通非RalfError映射的deployment_release_failed，随后reserve拒绝；发生在commit_deployment_control和实际叶子审批命令之前，不是Activity超时，也不能从统一文案认定身份不匹配。Query诊断未覆盖namespace／describe／History／解码和本地异常，未复现不代表原拒绝已修复。未据此删除校验或增加重试。

独立SDK Query诊断1通过，全部Query均无异常，关闭／清理通过；它不覆盖原首项拒绝，也没有识别其底层非RalfError。随后用原固定输入、同一wheel／安装独立复验正式首项，通过后自有服务停止并清理、零错误，才运行剩余17项。新正式工作根为`/private/tmp/ralf-s2-coordinator-candidate14-recheck-20261021`；原失败根与诊断根不覆盖，产品及测试输入保持原SHA。原首项非RalfError拒绝仍未归因，不称已修复。

正式首项复验JUnit439.935秒通过后，剩余17项继续串行。并行图四次写入已完成，随后Session.status的namespace_id／DescribeNamespace路径抛原SDK RPCError；Assembly关闭、Worker退出、两root退休及schema清理通过。主失败静态快照没有RPC status，最终JUnit确认状态为CANCELLED／operation was canceled；服务错误计数无DescribeNamespace失败项，不能据此认定服务限流或把它归为Tool90超时。调用方取消与服务端取消尚未区分，未修改重试／身份验证策略。

## 同包正式结果与保留

同包原输入正式首项1通过／零跳过、JUnit439.935秒，四次业务写入；自有服务停止并完成清理后才启动剩余17项。后者15通过／2失败／零跳过，**正式合计16/18，S2未通过**。这与dev13通过数相同，但失败集合不同，不能称整体性能改善或跨批拼成18/18。

| 场景 | 本轮结果 | 关闭与责任 |
| --- | --- | --- |
| graph-sequential-sdk首项 | 通过，439.935秒 | 两root退休／Session空闲／Assembly关闭／Worker退出／schema清理通过 |
| graph-parallel-toml | 失败，369.303秒 | 第二Turn的Session.status发生SDK CANCELLED；四写入、两root退休／Assembly关闭及schema清理通过 |
| recursive | 失败，384.258秒 | 第二Turn等待审批ready80超时；first-close60和cleanup40未完成，CloseIncomplete保留；Worker退出不代表Assembly关闭 |
| cold-handoff | 通过，352.414秒 | 包含交接、退休回复丢失、第二Turn显式取消及关闭断言；一写入符合场景预期 |
| 其他10项正常／4项故障 | 通过，零跳过 | hard-kill保留原精确未知义务，按场景预期验收，不称资源已关闭 |

递归第二Turn叶节点相对root启动40.666秒后启动，49.042秒准入，两个Context完成于55.863／68.011秒，模型完成于61.255／75.631秒。上层状态传播已逼近ready80；仅这些时间点不足以把耗时归为单一校验或查询原因。并行错误不是业务handler超时，原RPC异常保留。

意外递归schema `deployment_coding_4982091bd20e4b93bf4aa1eed199d41c`与hard-kill精确预期schema `deployment_coding_f6e86242cf494b14905c68d0856e0b08`保留。所有本批自有Temporal／PostgreSQL服务已停止，零停止错误；失败容器／卷／数据库保留，旧资源未动。

## 受影响安装与兼容验证

原输入固定26模块隔离安装首轮651通过／10失败／零跳过：八项受沙箱禁止Unix socket bind影响，随后两项收到未关闭socket告警。首轮日志／JUnit保留，未改产品、测试、warnings或筛选；仅允许本机测试socket后同包同输入独立重验，**661通过／零跳过**。源码受影响16模块309通过／零跳过。两组有重叠，不相加为独立覆盖数。

原默认材料逐字节不变（去尾LF后的SHA `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`），两旧History回放通过，两starter各一次业务写入。未调用真实模型、未取得新的平台矩阵或完整离线回归成绩。旧dev13全量通过仅为其历史证据。

## 排除的优化与剩余工作

工作区外完整CONTROL成本诊断的原路径四次CPU为2.519秒（带cProfile）／1.152／1.250／1.306秒；纯代码常量规范化累计仅0.017秒，不增加该缓存。精确JSON树clone的外部成本上界原型也未进入产品：即使限制树深度，调用者接近递归上限时仍可能改变旧deepcopy的RecursionError域，且动态copy分派需额外治理；不为追求门槛引入此复杂度。该诊断无真实服务／模型／SQL／native调用，不能作为S2性能验收。

剩余：递归第二Turn80秒就绪与其60／40秒关闭排空，定位并行SDK CANCELLED及先前Release普通非RalfError，修复后重新固定同包并按首项→17项验收；全量离线回归仍待候选收口。保留现有架构、门槛及全部失败，不增加重试、不删授权／来源校验，不将本轮记为S2／P3-2／第三阶段完成。仅本地提交，单次跳过钩子，不推送或公开发布。
