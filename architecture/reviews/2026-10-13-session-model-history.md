# dev89 跨 Session 原生模型历史验收

基线 `ff9b417` / dev88；[规格](../../docs/superpowers/specs/2026-10-13-session-model-history-design.md)与[计划](../../docs/superpowers/plans/2026-10-13-session-model-history.md)。本批子集验收通过；最终构建已核验，本地提交以Git记录为准；不推送远端。完整R01–R26目标保持active。

## 本批范围

复用同一个纯 `model_history` 策略，显式 `scope="session"` 增加 frame 方法。原 Local Run/Store 与 Temporal Run/Session History 分别保持唯一执行权威，负责原来源、首次数据快照、准确保存回执和完整根成功发布。

完整输入包含过去已发布和当前原 user/assistant/tool/反馈、原调用参数、签名和最终 JSON；当前业务任务、检索和记忆查询独立。默认完整模式不裁剪或用摘要替代原生链；每 stream 最多128条、8MiB，每 envelope 为999,998 canonical chars。

Agent、顺序、图、并行、Team、动态 Plan/DAG和嵌套沿实际成员发布；ModelPlanner 的 `@planner` 槽位及业务 Agent 分别保存原历史。每 Agent 支持 inherit/ref/disabled、JSON/TOML装配和同步/异步工厂。旧默认、scope=run和十四角色Descriptor v1保持，新显式角色用v2；Local local7/schema13、Temporal joint8/history2拒绝旧读者静默执行。

外部候选写入不能代替原根成功；失败根候选由原发布证据排除。未知ACK检查原稳定ID和准确CAS，不读取最新revision覆盖，不重跑已采纳模型或工具。真实同步处理器未退出时保留原执行租约和Session占用。

## 独立审查

唯一审查报告为 `/private/tmp/ralf-agent-dev89-9b379uz4/review.md`：4个P2、1个Minor，没有新增P1。原复现日志保留。

- Temporal容量检查发生在Run成功后，129轮执行且Session永留busy；前移实际派发与完整episode容量校验，并沿原失败/处理器结束释放占用。原128→129复现已确认模型总调用128、Run failed、Session idle；默认真实服务探针通过，外置128轮另在明确服务配置下验证。
- 替换历史策略把无续接字段的未知原生envelope串入参考文本；在投影及策略前增加公共结构校验。Local/Temporal × run/session × direct/nested八项有效RED，修复后Provider零次；旧run方法指纹不变。
- 通用ExecutionStore被发布层硬耦合到 `.conn`；通用路径改为原可选 `NativeHistoryPublicationStore`，同连接SQLite仅做明确优化。无SQL端口在Memory/外置SQLite的实际两轮及新Engine恢复通过。
- 惰性publication方法及同步未发布返回被认定成功；补齐同步完成返回类型、有限publication结果和准确稳定ID原事务回读。原contextmanager复现明确失败，无假成功；同连接回读不符时发布与Session追加共同回滚，未知异常及清理异常保持类型化失败。
- Temporal绑定预检漏新 `model_history` 角色；六项有效RED后复用原role/scope/ref/selector检查，默认v1编码不变。实际Activity原先仍拒绝，此项未发现模型授权绕过。

同一审查最终定向复核：五份原复现的recheck与54项窄测试通过，不新增第二轮审查。实际Team/Plan容量测试还发现旧child-control的DTO投影会丢失原生bundle；仅新history2沿原Workflow raw diagnostics取证、原观察fingerprint固定完整bundle，旧DTO路径不变。实际低容量父编排测试保持原派发、child ownership及quiet门禁。

## 分项与最终验证证据

证据目录 `/private/tmp/ralf-agent-dev89-9b379uz4`。

- Local实际Redis/PostgreSQL32项：两后端 × 八类实际编排 × Engine/Facade，两轮和新Engine重连通过。
- Temporal64项：原History默认、SQLite、Redis、PostgreSQL × 八类编排 × 普通/受管理Context，两轮及History重放通过。
- Temporal另八项：SQLite native/graph × 普通/受管理Context的四个实际Worker退出窗口；失败根及合法null两个场景；实际ModelPlanner两个场景。Worker丢失未覆盖全部后端和编排的笛卡尔积。
- Local四个实际进程 `os._exit(77)` 窗口：快照采纳、episode冻结、根成功提交前后。另覆盖未知ACK、根失败候选、原线程显式取消及Task取消；取消不释放尚活跃的真实处理器责任。
- 真实Redis及PostgreSQL严格reader各九项：有界完整页、大原文、准确覆盖/receipt/Scope/CAS；一页两个600k原文被跳过的有效RED改为原单项有限页。
- 早期候选安装单独保留；所有审查修复后重建validation wheel，在独立core/SDK环境重新安装。核心原范围77、新发布端口31、绑定/配置/完整reader135，共243 passed、零跳过；核心环境没有Temporal/Redis/PostgreSQL等可选SDK。
- 该安装包实际Temporal：原History/SQLite与恢复/特殊输出/ModelPlanner/父容量42，Redis16，PostgreSQL16，明确容量配置的128→129两项，共76 passed、零跳过。前三组沿原50MiB服务，外置128轮沿另设128MiB服务。
- 该安装包实际Local两数据库/八类编排/Engine与Facade32，加严格reader18，共50 passed、零跳过。五组测试在独立queue/Scope/前缀下并行；SDK与子Worker实际导入独立安装包。
- 审查修复后的四类旧88→新89→旧88原Run审批/回执/完整记录/预算与默认Manifest/DTO字节相同；每条模型2次、业务写1次。Schema13在旧88业务I/O前拒绝。实际旧88 Worker对joint8/history2原Workflow准入产生Unsupported protocol错误，History零Activity/model/tool；测试Workflow准确终止、own Worker正常退出且PID不存在。
- 实际旧88 ModelPlanner Session在首submit复现tuple/list持久化导致SessionBindingMismatch；本批在原Local绑定JSON边界统一，原请求/发布编码不改。新旧默认兼容范围和这个原本不可运行的组合修复分别记录。
- 最终完整源码：6317 passed、589 skipped、746.39s、exit0（session97974/实际pytest PID2760），禁用外部服务和真实模型环境配置。589配置跳过不计通过；上述真实服务另外执行，不把跳过项改标成功。
- 核心安装指南的离线Profile例子及实际安装CLI帮助通过，工作目录在私有临时路径，未在用户仓库生成运行数据库。
- 产品冻结308文件，即307 Python模块和pyproject。Ruff、824文件格式及Git空白通过；文档完成后重建最终wheel/sdist、独立安装与产品字节核对，最终307模块在源码、wheel、sdist、独立core/SDK安装中逐字节相同，1178个源码/文档/例子/测试/评测声明文件进入sdist；最后文档更新后再次构建核对，结果存本证据目录。
- 四项自有服务已准确停止。两个Temporal owner PID12470/session38415、PID697/session49146均捕获TEMPORAL_STOPPED/exit0、实际等待且PID不存在。Redis PID17138/socket及临时PostgreSQL精确容器均不存在；原foreground句柄在root/创建者均已失效，退出码不可捕获，记录为null，未虚报0。相应stop命令均exit0。

原Temporal CLI1.9.1/Server1.32.0服务在外置128轮探针的104个已接受Turn后触发50MiB History限制；终事件3743由history-service终止，不是业务取消或等待超时。另设独立SQLite服务并显式配置 `limit.historySize.error=134217728` 供容量契约验证，原服务未修改、失败History保留。成功的配置探针不能消除默认长期运行限制；Continue-As-New/保留治理继续开放。配置键及默认门槛参考[官方配置源码](https://github.com/temporalio/temporal/blob/main/common/dynamicconfig/constants.go)。

真实服务证明执行和数据协议，不代表真实模型能力。未调用付费模型；不据本批验收关闭DeepSeek thinking/Responses reasoning、完整H3/M1、外部首次采用或对等框架比较。当前声明不提供子失败continue策略，本批不伪造该能力或实际证据。
