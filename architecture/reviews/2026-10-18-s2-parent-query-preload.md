# S2恢复：Parent观察查询预加载

用户2026-10-18明确要求“恢复S2，按原门槛收尾”。本批从`94ceafc`继续，先验证当前候选原`graph-sequential-sdk`，通过后才运行原其余十二正常组合和五项故障；不新增能力。原Tool80、Runner60、approve180、scenario360、first-close60及cleanup40保持。S2／P3-2及阶段整体当前仍未关闭。

## 当前原期限基线

隔离安装候选`26546603a6bd9370dfc0bca71f48ecc83310ba3d52a8259fd1847d3a62e61ade`，442产品、930测试输入前后相同。实际Temporal普通持久服务及PG16执行原首项，严格`-Werror`，没有诊断开关：1 failed／零跳过，JUnit132.686秒。首先在80秒首次审批等待失败；首个CONTROL生命周期Query返回`validation_error`，尚未调度业务工具。关闭亦未完成，失败数据和自有停止服务完整保留，未触碰旧失败资源。它不是360秒性能通过证据。

原失败工件`/private/tmp/ralf-s2-resume-baseline-20261018`包含result、shutdown、原History和PG导出；私有连接文件不纳入发行。根History SHA256为`fd2c4dc54ebd2428e5085197c659f9b4d6ad0c9cb0d2c606ddb9b98fcbfeb8ca`。临时路径供本机审计，公开复现入口仍为仓库原测试和所需服务。

## 最小修复与回归

实际SDK重放原History并注入同形只读查询，发现Parent从透传基类继承`view`，其四个观察helper在Sandbox首次激活后才导入。SDK产生`UserWarning`；原测试`-Werror`将它提升为异常，原查询边界转为`validation_error`。无严格告警时查询成功，但告警不可忽略。

生产改动仅在Parent既有`imports_passed_through`初始加载区加入四个既有transport模块；Run已有相同预加载。没有改变查询授权、状态、生命周期、持久证据或执行权威。真实SDK Importer新回归在修改前复现有效Parent查询1 failed（Run对照通过）及其余三观察入口3 failed；修复后七个相关模块118 passed。原History在严格告警下只读查询与重放通过，History未改写，不用合成新运行替代原证据。

新wheel SHA256为`73435ccf42c53e4d53c151640f280c6644af381505702d652905cb6fda888c05`，442产品／930测试输入，源码／wheel／隔离安装逐文件一致。安装后118 passed，默认完整材料SHA256`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`保持，原及续接默认History重放、首用审批／重复回执／新进程恢复单业务效果通过。

首轮扩大319个Temporal模块回归在受限沙箱中4321 passed／617 skipped／9 failed／1 error：失败为原Unix socket绑定权限和由此产生的未关闭socket告警，Redis子进程亦不能绑定。保留该失败，不据此修改产品或降级告警；相同输入在允许本地测试进程的环境中重跑：4331 passed／617配置skipped／零失败与错误，237.04秒，442产品及930测试输入前后不变。跳过项不作为真实服务验收。

## 待验收

修复包原360秒首项已终态：1 failed／零跳过，JUnit441.066秒（含收尾）。原360取消发生在第二Turn审批等待，随后owned关闭未完成，最终清理遇到无poller；四次业务提交最终存在，两根accepted及retired，但Session关闭证据不足。保留PG schema、原History和效果日志，自有Temporal／PG已停止，旧资源未动。工件在`/private/tmp/ralf-s2-parent-preload-live-20261018`，442产品／930测试／安装包输入前后不变。此结果解决首次查询阻塞，但不构成性能通过；其余十二正常／五故障仍未启动。

同一原360场景的独立CPython monitoring诊断也已终态：1 failed／零跳过，JUnit392.751秒，原整体取消落在第二Turn审批等待；本次assembly关闭、Worker退出与安全删除证明均通过，导出后schema清理，失败容器及本机证据保留。产品／测试／wheel输入不变，不包装或改写产品方法，不记录参数或凭据，跳过Workflow执行上下文；先行真实SDK Importer smoke2通过。工件为`/private/tmp/ralf-s2-parent-preload-monitor-20261018`，`activity-monitor.json` SHA256为`aee717690b1a01ae995dea527364f648ca27f6ae78c9e4cf3285051d77cc1509`。它是诊断，不能与无监控验收拼接或据其时长推导改善。

诊断记录三次完整Tool外层墙钟44.184／40.712／45.144秒；对应`_execute_tool`自身协程段CPU3.700／3.556／3.859秒。托管子Task及其他并发任务不包含在该协程CPU段内，不能用相减值声称网络耗时。全进程`validate_release`4672次、CPU161.956秒，内含`_current_manifest`4616次、CPU145.481秒；指纹6484690次、CPU77.897秒、canonical3770989次、CPU56.733秒。这些是监控下的嵌套累计值，不能相加，也不直接外推无监控运行。CONTROL transport主体26次完成、累计CPU50.681秒，未分别记录外层owned start／end ACK的完整CONTROL CPU；该缺口仍保留。所有所选函数start／return匹配，pending段为0。

本批关闭首次Query误拒绝这一正确性缺陷，尚未取得完整调用性能收益。原无监控终态审计`terminal-audit.json` SHA256为`c2882f9912d62ad88434a0b3add29b204e02d558fe7fe0c985a40aa05902e9a3`：四Tool均SDK Completed／ok:true，42.661／38.726／42.013／45.789秒；四次业务写入、两根退休不代替Session关闭和两Turn成功。下一步必须在当前完整调用上证明发布重建／绑定校验的安全优化收益，再复验原首项；不恢复已否决的缓存放行或快速复制方案，不降低门槛或启动剩余矩阵。

首项未通过前不解锁其余矩阵；安装与离线回归不能替代实际性能、故障或真实模型质量。较早候选的全量回归及服务证据继续仅按原版本范围引用，不合并为当前包全绿。

## 审查与本批结论

一次独立只读审查未发现四导入改动、五项SDK Importer回归和相关S2文档的可执行正确性问题；审查未运行服务或验证性能。受影响源码／安装、319模块回归及Ruff／格式／空白检查通过；此批未重复上一候选37分钟全量，因此不声称当前候选已完成P3-A或S2。仅本地提交本批六个文件，其他并行文档维护变更保留。
