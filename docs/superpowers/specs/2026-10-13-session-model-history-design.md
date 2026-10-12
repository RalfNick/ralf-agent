# 跨 Session Turn 原生模型历史

基线 dev88 `ff9b417`。继续 R01/R02/R03/R05/R07/R26；完整目标为开箱可用和独立替换，不改变 Harness、Local Store/Coordinator 或 Temporal History 的执行权威。

## 依据与选择

两 Turn 实际本地探针确认 dev88 只召回归一化答案，第二轮没有上轮原生工具消息、签名和工具证据。参考本地 AgentScope `agent/_agent.py` 的 AgentState 原生 context 与 fresh-input 捕获；不照搬其可变状态、摘要截断或缺少 CAS 的存储接口。比较报告保存在本批前置证据目录，不作为上游版本/质量结论。

复用一个 model_history 组件、现 SessionStore append/CAS/inspect/dataset 与现实际成员拓扑；原生记录使用隔离地址，一条有限 JSON envelope 原子保存完整 episode。只补严格完整读取，不增加另一套公开 Transcript CRUD/服务、重复数据库配置或用户手填恢复 key。每 Agent 支持独立继承/ref/disabled；一个显式 descriptor v2 的 model_history 角色即可，旧 descriptor v1 的十四类字段和编码不变。

## 共享接口

`CompleteModelHistory(scope="run" | "session", allow_tool_result_projection=False)`；旧缺省 scope=run 的身份和 assemble/validate 方法指纹保持。session 身份为 kind=complete-model-history、version=2、scope=session 和原投影布尔。`model_history_registration` 在 session 模式额外固定两个纯方法，旧注册编码不变。

新增纯 frame 方法：`assemble_frame(frame, references, max_chars, *, context) -> (messages, manifest)`、`validate_frame(frame, messages) -> None`。frame 为有限 JSON：`version:1`、`history:当前原system/user/assistant/tool/feedback列表`、`turns:已发布envelope列表`、`stream:64位digest`、`snapshot:原数据/发布证据对象`。框架 `validate_model_history_frame(frame, messages, *, allow_tool_result_projection=False)` 独立保护完整 past 和 current；替换策略不能绕过。

模型顺序为 system + 每个 past envelope 的 history[1:] + current user + 可选 reference user + current history[2:]。Context/检索/记忆查询始终使用原当前 task；不要让旧 messages[1] 查询读取 past Turn。原 Run messages 继续只保存当前交互，current_task 在原 episode 开始时固定。每个 past Turn 的 system 必须与当前原 system 相同，stream 封印原 owner/发布/epoch；跨完整工具组的相同 call ID 合法，组内重复/孤立/未完成 receipt 拒绝。

`native_history_envelope(stream, source, history, final_digest) -> dict` 生成准确字段：kind=ralf-native-model-turn、version=1、stream、source、history、final_digest。source 准确包含 root_run_id/run_id/node/release_digest/turn_id/turn_seq；node 为原 episode 路径字符串，turn_seq 是非负整数，直接 Engine 提交使用原 root Run ID 与0，Facade 沿原 TurnAdmission。final_digest 为最终已采纳响应 digest。默认只发布成功完整根 Turn 的实际 Agent episode，不伪造 transform/root aggregate。

`validate_native_history_envelope(envelope, *, stream=None) -> dict` 脱离原输入引用并验证有限 JSON/完整工具组/最终 assistant；合法 Schema null 保留原 final content=None，业务合法性由原 final_output 校验。新的 session envelope 实现硬上限999,998 canonical chars，给原单项 RecallPage 的外围列表保留两字符；旧 run 模式的8MiB限制保持。每 stream 最多128个 envelope、合计8MiB；超限明确拒绝，不裁剪。原生地址 `native_history_address(stream) -> str` 为 `ralf-native-model-history-v1:` 加 stream。

`read_native_history(backend, scope, address, *, stream, max_chars=8388608, max_turns=128) -> dict` 为内部 async 受管理数据操作，结果准确包含 snapshot_id、revision、turns；复用原 read_page。固定text=None、每页1条/scan1、字符上限1,000,000，避免大记录占用同页时被原参考召回算法跳过；必须 backend_bounded、skipped=0、scanned=len(items)、固定snapshot、cursor不重复，完整读取所有记录；最后反转为append顺序。原 authority 再核对原发布资格/准确覆盖，不把数据记录本身当作成功证明。append 与inspect沿原Session端口，不新增同义CRUD。

## 保存与权威

Local 同连接 SQLite 在原成功事务中追加原生 envelope，并记录原发布证据；节点重置前冻结完整原链。远程使用原 Run 中的 intent/read/write/inspect/receipt/adoption 和原真实 handler 托管；外部候选写与原成功是两个事务，根成功资格仅由原权威发布证据决定。未知ACK先检查稳定ID，不重跑模型/工具，不读最新revision强行重写；候选外写但根失败不进入下轮原生输入。

通用ExecutionStore不要求SQL连接。新模式的可选publication能力为 `native_history_version=1`、`prepare_native_history()->None`、`native_history_publications(scope,stream)->list[dict]`、`publish_native_history(scope,stream,message_id,evidence)->None`。三方法同步完成、有限JSON，不能返回惰性manager/awaitable/generator。prepare随原有效接受事务启用旧读者拒绝门槛，publish与原根成功同事务并按稳定ID去重；成功前原lookup须回读准确同一证据。适配器自行保证原transaction原子性，不新增另一执行权威；默认SQLite保留同连接原子追加优化。

Temporal 原 Run History 冻结 episode；原 Session History 接受根成功及实际成功成员的完整证据后发布原生 bundle，默认历史不使用 normalized pair裁剪。原声明当前对子失败采用 fail-fast，本批不增加 continue 执行策略；失败/取消根整体不发布，失败成员不产生有效 native episode。外部替换沿原 Session read/save/tree 与 handler-end 门禁，新 snapshot采用一次，Worker重启不换成新数据库内容。所有receipt/source/native guard都由原History复核。

Graph串行/并行、Team、Plan/DAG、嵌套沿现声明路径与真实成员topology封印 stream；相同名字不同路径不串用。同成员重复调用的连续会话沿原固定调用槽定义，不机械按随机call ID创建永不续接的stream。idle rebind默认新epoch，旧回执保留，不修改continuation owner；namespace/资源/Scope沿宿主授权。

## 发布、绑定与配置

session mode 使用 model_history_protocol=2；run模式仍1；无策略不加标记。Local原生新kernel local-7，Temporal新joint8；每步骤使用实际选中策略。旧 DTO、Manifest、默认identity和旧回放保持。SQLite新语义仅在有效接受新Run的事务内激活schema13 fence，接受失败不升级，旧executor业务I/O前拒绝新数据库。

AgentBindingDescriptor 只在显式model_history选择时输出schema_version=2及该角色；缺省和from_dict v1保持原字节。StepComponents新增末尾可选model_history，resolver/catalog固定真实对象与方法；SDK/Profile sync/async沿现Registry注册complete的scope配置。TemporalProfile execution.model_continuation=true与Local components.model_continuation保持原前置要求。session模式要求真正可用的Session source或原Temporal Session History；disabled策略保留该Agent旧行为。资源ownership/lifecycle沿原装配。

默认全部原生past与current先占原max_context_chars/Context计量，再选择refs；最终实际Harness请求统一保护与测量。默认无模型摘要降级、无大工具结果改写；显式允许投影只能改tool.content，原存储保持原文。opaque不进入references/摘要。

结构化原生envelope和opaque参考由框架在投影或替换纯策略前统一拒绝，包括嵌套值；不能先序列化为文本绕过资格校验。实际固定stream已满时模型/工具不得开始；最终envelope或同stream成员累计超限时在Run成功前明确失败，沿原真实处理器结束与quiet释放Session。成功发布须按全部stream原子采纳，不部分发布或保留不可恢复的成功busy Run。

## 完整验收

- 两Turn多工具、原JSON/签名/final/retry，第二轮实际模型请求与当前任务查询；所有组合实际Agent独立选择和owner/namespace/rebind隔离。
- 替换纯策略/Session source/Provider、Profile sync/async和核心安装例子；懒返回、方法/客户端漂移、伪快照/来源、改原链、超限全部模型I/O前拒绝。
- Local事务回滚及真实进程退出、节点freeze/append/根commit；远程ACK丢失/CAS冲突/未知/取消实际线程与busy；准确收据恢复不重发模型/工具。
- 实际Redis/PostgreSQL替换、真实Temporal Session/Worker loss及根/子History replay；旧dev88原Run/Session/默认兼容和旧Worker零业务I/O拒绝。
- 一轮独立review后完整源码、安装包、构建/文档/能力清单；仅本地提交。接口或离线fixture不代表真实模型质量/完整H3/M1/R01–R26验收。

本批按内部步骤并行推进，以上范围不因某部分易通过而改成完成；未验收能力明确开放。用户已经授权持续执行与并行开发，不重复请求实现批准。
