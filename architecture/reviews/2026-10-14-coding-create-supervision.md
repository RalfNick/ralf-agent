# Dev112：原 CREATE 监督与未派发证明验收

日期：2026-10-14。范围为第二阶段 R12／R13 的原 CLI 生命周期与严格未派发故障窗口；第一阶段 dev99 保持冻结，完整 R13／第二阶段／R01–R26 继续开放。

## 交付与架构边界

- 原 prepare grant 下持久化固定 CREATE 声明；broker／CLI gate 分别登记、各接收一次许可。两层不可重开，冷恢复只能控制原操作，不重试 CREATE／START。
- 原 broker 持有实际子进程及 namespace／operation lease，Worker 死亡不丢弃真实处理器责任。退出先作 non-reaping 观察，再清理原 group、最后 wait；输出 EOF 不作为退出证明。
- 只持久化结构化终态、完整 CID 或 null、输出摘要与固定 reason。固定源码、解释器／执行文件及实际导入别名；隔离解释器在执行前核对完整源字节。
- 严格 `create_not_dispatched` 证明须原 gate 未 accepted／未 exec、不可重开、原 helper 实际结束、控制处理器排空、原 namespace 成功空查询。PG 先存证据，原 Local／History 采纳，实际关闭成功后 RootCapacity 才释放。
- 原 attempt／prepare grant、未知效果及费用保留；证明不授予再次执行。机械监督器不管理 Run、审批或预算，Local／Temporal 继续各自单一执行权威。
- 新选定 native5／binding20、composition6／binding21；旧18／19使用 immutable dev111 Worker。普通独立 Env 及未选定默认发布保持旧字节。

见[契约](../specs/coding-create-supervision-contract.md)和[使用／升级指南](../../docs/coding-resource-recovery.md)。

## 验证范围

| 门槛 | 结果与范围 |
| --- | --- |
| 完整源码覆盖 | 原风险分组覆盖630个模块、10864用例，原结果10164 passed／698 skipped／2 failed。产品源码全程未变；四个测试模块在验证期间或之后修订，保留原失败，不将原全量宣称为通过。两个失败为旧late-auth阶段断言与旧库存别名替换预期；随后完整受影响模块定向复验，见最终私有 reconciliation |
| 真实 POSIX 监督 | 新三个协议／gate／journal模块27项通过；独立同权限7项通过。默认sandbox私有UDS bind errno1的失败保留；实际授权IPC环境通过。覆盖门关闭、GO后EOF、真实父进程退出、原child／descendants、输出EOF、foreign token与回执 |
| Pure proof／容量 | 75项新纯规则检查通过；选定库存55项检查通过。Local 原Action的实际broker登记后未GO案例通过，无伪造CID停止证明 |
| 修订模块复验 | 最终Runner源码24／安装24通过（46.69s／46.82s）；pins＋inventory源码186／安装186通过。使用同一最终测试字节，保留原失败；这些是完整目标模块复验，未重新执行全部630模块 |
| 真实 Docker | 源码2／安装2通过：实际CREATE后回复丢失、CID持久化失败；每例CREATE1、START0，冷恢复只认领／退休同一原CID并确认缺席 |
| 真实 Temporal＋PG | 最终安装8项通过：原Agent、Team、动态DAG的审批重启／运行取消及owned关闭，原History重放和PG证据。源码8项在最终alias guard冻结前通过，单独保留其快照范围；结构化native peer不构成模型质量 |
| Temporal 未派发 | 源码2／独立安装2通过（77.15s／74.73s），native20／graph21：真实broker登记后由固定测试shim中止GO；CREATE0／START0／Thread0／Turn0，原prepare grant1，PGversion2 proof等于History，容量释放，unknown费用保留，冷Worker不重新执行。每个context三条原History重放；各自4Worker／2broker结束、2control目录及2schema清理 |
| 旧版本 | immutable dev111 原19动态DAG审批冷恢复1通过；当前纯validator拒绝原19及只改标签的20／21。driver误取runtime_manifest导致artifact提取exit1，保留原错误，再从同一成功History的manifest提取；没有重跑覆盖记录 |
| 包与默认一致性 | 392产品模块＋3JSON资产源码／最终wheel／安装逐字节一致。wheel SHA `f0d727d5205e65877c73c6741b1f1e3218b60352bda2d63dbd0fdbddf420f900`；五份未选定默认fixture SHA `35004369d4aa8b8b85cc45f59f00fa3f6ee83be8061c20fbf053b99446d03349` |

私有证据主目录 `/private/tmp/ralf-agent-dev112-root`，实际Docker源／安装分别为 `ralf-agent-dev112-supervised-create`／`ralf-agent-dev112-installed-supervised-create`；实际未派发源目录 `ralf-agent-dev112-no-submit-0ec18f3c19b1`。保存原分组日志／快照、目标复验、History／PG、原CID／进程及精确owned清理证据。配置依赖跳过不等于已交付。

实际未派发安装证据为 `/private/tmp/ralf-agent-dev112-no-submit-installed-f13581557bba`，安装产品origin确认来自独立site-packages，测试／子Worker路径不含repo/src；同一冻结测试SHA为 `cd6bd25cb870cc1e57548d3cfbeeb5d540373b3b87c7c1edd4ff3cfb6dbcc5dd`。

实际Temporal未派发测试的四轮fixture错误保留：pytest重写shim指纹、tuple与JSON list比较、观察器初始化顺序、诊断budget路径。修正只在新测试；最终完整parent／Worker release相等，产品源字节保持。实际Docker初轮资源ID超限、Runner短期限未达到目标故障阶段及原sandbox IPC失败也保留。

最终独立只读审查未发现新的具体P1／P2：核对原proof与prepare grant对应、cold仅控制原broker、固定源／实际alias，以及 stop→transport排空→env实际关闭→PG保存→History确认→RootCapacity释放的顺序。该次复核未运行模型／服务；先前独立7项真实broker与38项stub receipt边界分别计量。安装Runner另一次lost_turn因1.5秒在thread/start后截止而未进入目标Turn窗口，保留23 passed／1 failed，测试期限统一10秒以保证到达目标故障阶段，仍要求恰好两次原提交及unknown／fenced／不重发；产品未变。

自有Temporal、测试PostgreSQL容器已正常停止并等待原进程退出，独立确认原CID／服务PID不存在、Temporal／metrics／PG三个端口关闭。Docker容器移除请求包含匿名卷清理；用户Docker daemon保留。失败日志及证据ledger保留。Ruff／格式／Git空白检查通过；sdist使用已有构建依赖成功生成，隔离构建因sandbox网络无法安装setuptools的初次失败保留，没有改依赖以绕过构建。

## 模型与未完成门槛

本批实际DeepSeek Responses直连验证文本、SSE及自动工具选择三种模式HTTP200；两次强制函数选择在thinking模式返回400。它们是协议兼容探针，不是新版本端到端Coding质量验收。dev109的9/9有限真实Coding任务仅属于原快照。密钥未写入仓库、模型配置、PG或History；连接限制见[模型连接指南](../../docs/codex-model-connection.md)。

- 可能已exec的CREATE，CLI退出／非零／empty inventory均不能证明daemon不会晚到创建；没有可靠终态回复时继续unknown，不释放义务。完整daemon负向完成屏障未交付。
- Linux进程观察实现有单元覆盖，本批实际平台为Darwin；不将其计为真实Linux验收。
- 短控制目录与原声明作为机械ledger保留，正常退出socket移除；保留目录不是活handler。GC／管理员恢复、持久队列、公平调度、跨宿主、Temporal嵌套／sequence Coding及企业凭证代理仍开放。
- 新版复杂真实Coding任务、多模型／语言质量、外部采用与AgentScope对等比较尚未验证。容量释放不消除未知业务效果或费用，不保证任意外部操作恰好一次。
