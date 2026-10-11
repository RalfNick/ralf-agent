# dev76：每Agent只读Workspace绑定验收

基线93c32b8/dev75；本批不改变原Engine/History/Action/Source执行权威。WorkspaceBindingResource借用已注册的单一Source工具，纯交集只收紧AgentSpec/tool_set授权，保留业务工具；Local显式记录使用kernel11，Temporal显式角色需要宿主catalog发布protocol1。文件写入、subroot selector、Skills/Sandbox/Runner与完整R01–R26仍开放。

当前源码相关118 passed（5.41s），实际六类Temporal Agent/sequence/graph/team/dynamic/nested各完成审批重启、重复控制、固定root、保存后文件变化与History重放，6 passed（37.94s，无跳过）；组间有重叠。正式Task1为88 passed（5.52s），Task2为79 passed（3.11s）。以下初始候选记录保留原执行顺序；最终证据见后文。未调用真实模型或推送。

TDD：资源公共API缺失26失败（0.78s）→26通过（1.02s）；Local实际选择9类失败及1个既有审批通过，修正原子Run初始恢复以抛DefinitionMismatch拒绝的fixture后，基线resolver的单项真实RED（0.63s）。额外业务工具名不应套Workspace名称上限、惰性Registry不应产生未等待coroutine，两项RED（0.68s）→相关88通过（5.26s）。配置映射缺失10失败（0.82s），补默认工厂／种类准入后，JSON/TOML、实际文件根只分配一次、借用资源与纯预检10项及原装配合计44通过（1.52s）。Temporal角色／协议10失败／1个原Owner守卫已通过（0.73s）→35相关通过（2.17s）。

测试修正不计产品RED：Team审批需要原child run_id；默认ToolPolicy需人工审批；RuntimeInstance直接转发binding_catalog，没有engine属性；原TemporalState使用step property和copy.deepcopy恢复。Ruff自动修复误移除共享pytest fixture导入导致13 setup errors，恢复显式re-export后118通过。首次实际服务4通过／Team与Dynamic两项fixture等待失败（29.09s），固定8次立即观察不足以等待原Worker推进；改为60秒有界观察和0.05秒yield，生产状态机未改变，六项最终通过。原失败日志均保留在本批临时记录。

判断及代价，按顺序：

- 持续授权覆盖重复设计／计划／收口菜单；只本地提交，判断错误须发布前修订，没有远端授权。
- 借用原native Workspace工具而非私有Source窥探或新客户端字段；其他工具必须显式适配，不能据此声称Sandbox。
- ref要求至少一个原先已授权的匹配工具，保留业务授权；使用者须先声明对应固定前缀／root工具，不能用绑定扩权或重映射同名工具。
- Temporal仅在宿主catalog注册Workspace资源时启用protocol1，保持旧默认发布；disabled-only Agent也须宿主显式启用此能力。

以下审查与冻结证据逐项追加；不得由以上子集测试宣称完整框架、企业治理或模型质量完成。

一次独立只读审查：28路径、87相关测试通过（3.05s）；无Critical，1项Important保留：三处Python字典相等把True／1／1.0视为相同，但其规范JSON身份不同。普通受支持custom WorkspacePort已复现Local选择A却读取B、Temporal接受错配根，必须在一次RED→GREEN修复中用规范JSON比较。1项Minor延后：构造成功后live registration变成非法形态，仍拒绝读取，但报ValidationError而非DefinitionMismatch；不将Minor混入修复。

审查取舍与代价，完整四项Declined按原顺序：

- 任意可信Python伪造Workspace metadata或访问其他文件仍为可信宿主边界，不声称Sandbox；代价：不可信插件需隔离／认证。
- 文件写入／subroot selector／路径ACL／租约／Sandbox与Runner仍为后续能力；代价：此读取选择不足以覆盖Coding或企业隔离。
- 继承的Unicode C1路径保持dev75已记录行为；代价：需应用内容策略和后续Cc校验。
- 模型质量／完整Local-Temporal对齐／全R01–R26不能由确定性子集证明；代价：需要真实重复模型、服务及独立采用验收。

其他证据判断：旧75 optin探针是实际安装的Local/History接受代码拒绝，未另外启动旧Worker运行新optin发布；默认旧Worker双向恢复已实测。代价：新optin旧Worker服务资格仍未证明。冻结完整回归／制品／关闭／提交由执行者补齐，不做第二次审查认证；87项focused测试不足以宣布本批或全目标最终完成。

Important 修复：10 项 true RED（0.91s）覆盖五种边界×True/1、1/1.0；三处比较改为规范 JSON，10 项 GREEN（0.64s），相关160 passed（7.51s）。最终安装核心59 passed（4.46s）、扩展160 passed（8.60s）；真实源码6 passed（38.65s）、安装6 passed（31.91s），均零跳过。实际旧75↔76 Local／CLI／默认Temporal／持久会话恢复、22原模板、259产品模块与元数据一致、三段安装指南通过；所有子Worker已等待退出，自有Service70190已停止且实际exit0。完整回归仍待最终输出，不由上述子集宣称全部能力完成。

额外真实旧 Worker 门槛已补：实际安装 dev75 的原 TemporalWorkflow 收到 dev76 Workspace opt-in，在 init／History 绑定校验拒绝；History 记录 WorkflowTaskFailed，无任何 ActivityTaskScheduled，模型／工具审计文件均不存在。原错误是 `Unsupported Temporal binding role or resource selector`。这意味着不兼容队列必须由宿主正确路由，不能期待旧 Worker 自动迁移。探针首次仅异常文案断言错误，保留失败并确认清理；新临时数据库纠正后 actual exit0，Worker 和自有17278服务均停止并等待退出。先前独立审查的旧 Worker 未实测限制由此补上；没有第二次审查或产品修复。

最终冻结全量：session89503 actual exit0，4501 passed／345配置依赖跳过（709.82s）；这些跳过不能代替远端完整矩阵或真实模型质量。全部259产品源码与制品／两种安装一致；原代码在完整回归期间未再修改。Ruff956文件／格式／CI YAML／Git空白、依赖校验和安装指南通过。正式Task3和本地提交记录随后追加；不推送远端。
