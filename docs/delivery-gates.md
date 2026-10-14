# 分阶段交付门槛

日期：2026-10-14；第一阶段已冻结在本地提交 `7e530f8`／`0.1.0.dev99`，第二阶段当前批次为 `0.1.0.dev113`（所选环境／执行门槛已通过，随本地提交冻结）。已验收的dev112原CREATE监督保持，当前状态以[支持矩阵](phase2-support-matrix.md)及本批证据为准。
按用户修订后的目标管理交付，R01–R26 保留完整目标；适配器数量、测试数和 dev 版本数作为辅助信息。

## 第一阶段：四条参考业务链路

固定 Local 执行权威，复用现有 SDK、工厂、Profile、Agent／子 Run、工具回执与父级完成政策。
Temporal 部署一致性放在第二阶段。每条链路分别关闭以下门槛：

| 门槛 | 必需证据 |
| --- | --- |
| I 安装应用 | wheel 安装后、checkout 外运行完整默认应用，不依赖仓库 examples |
| C 配置替换 | 模型、工具／数据的配置或 SDK 注入示例，明确版本与资源所有权 |
| L 生命周期与恢复 | 必要审批、显式取消、观察取消、原 Run 重启／重复提交；效果不重复，实际处理器排空后关闭资源 |
| Q 真实重复质量 | 固定最终配置、冻结任务和独立 oracle，至少三次重复；失败及未尝试项保留；RAG 另需真实语义向量和实际可见引用 |
| D 文档与冻结 | 可复现命令、支持边界、报告／配置摘要、审查和本地提交；通过后冻结阶段范围 |

质量目标沿用 [M1 候选验收线](m1-acceptance.md#3-真实模型任务集)：任务整体至少 90%、
各案例至少 80%，保护与效果条件必须通过。每案例仅三次重复时，需三次全部通过才达到 80%。
本阶段只验收以下有限参考任务，不宣称完整 M1、通用模型质量或跨框架优势；未知费用保持未知。

| 链路 | 固定范围／复用入口 | 当前状态 |
| --- | --- | --- |
| 单 Agent | 八类工单诊断、审批、拒绝和停止；`evaluate_business`，准确 `apply_fix` 回执完成验证 | 原安装／生命周期核对通过；未改业务／执行／Provider 字节的 dev98 真实重复 24/24，dev99 首用安装／配置四场景通过 |
| 语义 RAG | 八类知识问题、引用与弃答；`semantic_rag_reference`、原摄取／Hybrid／当前来源回读 | dev99 固定本地神经模型＋真实生成 24/24，引用／来源／恢复均通过；实际模型 GC 释放、取消清理和安装应用通过 |
| Plan | 五类库存任务；规则 DAG、researcher／writer 与库存父级回执 gate | dev99 成员验证＋关闭 JSON mode 三次重复 15/15；安装取消／崩溃／原回执恢复与旧 98 默认兼容通过 |
| Team | 同五类库存任务；固定 Supervisor 与库存父级回执 gate | 相同独立最终配置 15/15；安装取消／崩溃／原回执恢复与旧 98 默认兼容通过 |

dev98 Plan／Team 两轮独立固定配置（JSON-object 开／关）均为 3/15，保留全部失败。
父级 gate 正确拒绝缺工具证据的答案；本批只通过原 Agent 完成验证增加有界成员反馈。
库存工具只读，默认写审批标为“不适用”，不人为添加写操作；取消与持久恢复仍必须验收。
这些质量结果不证明自主模型规划、未知团队策略、复杂重规划或 Coding 已通过。

RAG 首轮没有来源泄漏或无效引用；一次答案把数字 `30` 返回成字符串 `"30"`，原严格
评分器正确拒绝。新增显式 `typed_answers` 只明确用户问题所要求的原生 JSON 类型，
保持数据集／oracle 与旧默认，不通过答案改写、类型强制转换或删除失败行提高成绩。

dev99 启用成员验证且开启 JSON mode 的第一次完整配置中，Plan／Team 仍各 14/15：
一个 bolts 案例的成员持续编造库存，无工具回执，运行被正确拒绝。保持同一 wheel 和任务集，
关闭 JSON mode 的独立完整三次评测各 15/15；该配置作为参考推荐，不将两配置合并或删除失败。
模型均为显式 DeepSeek flash、非思考、温度 0、2048 输出 token、45 秒、每链路最多 96 调用。
单 Agent 与 RAG 使用 JSON mode，Plan／Team 推荐关闭；语义模型资产及配置固定见
[接入指南](phase1-semantic-rag.md)，成员配置见 [Plan／Team 指南](parent-completion.md)。

质量结果只覆盖上述参考应用。完整回归为 8397 passed／617 配置依赖跳过；两套安装各
254 项相关检查通过，351 产品模块保持一致。四条链路 I／C／L／Q／D 已通过验证，随本地提交冻结第一阶段范围。按
[本批验收](../architecture/reviews/2026-10-13-phase1-business-chains.md)记录提交闭环，
随后固定第二阶段环境组合；整个 R01–R26 目标继续进行。

## 第二阶段：环境与执行

当前执行依据为[固定支持矩阵](phase2-support-matrix.md)。其所选组合、必需门槛和明确不支持项优先于下面各dev历史段落；安全拒绝的未选择组合及后续适配器不自动阻塞阶段收口。dev113按既定公共组合门槛补顺序／递归成员，其他新增范围须说明具体所选阻塞。

dev109 已补[专用模型连接](codex-model-connection.md)和三项有限 POSIX Coding 的真实三次重复基线（9/9、78 oracle 检查）。Local 原 Action 与真实 Temporal／PG 审批重启、取消、安装和旧 Worker 门禁分别验证；后者使用结构化原生 peer，不替代真实模型证据。dev110 一层 Agent Team／Dynamic Coding 的恢复验收见[本批记录](../architecture/reviews/2026-10-14-temporal-coding-orchestration.md)。dev111 已验收[同根跨父容量和原 CID 正向恢复](coding-resource-recovery.md)，该有限门槛不再列作未实现。dev112 按[监督契约](../architecture/specs/coding-create-supervision-contract.md)补原CLI监督与严格未发送证明，Local原Action、真实Docker正向恢复及Temporal／PG源码／安装原History验证见[本批验收](../architecture/reviews/2026-10-14-coding-create-supervision.md)，相应有限门槛已通过。dev113补所选嵌套／sequence成员：源码／安装各六个实际场景、36份原History重放、完整回归10234 passed／704配置跳过及独立安装214项通过；自建服务实际退出，第二阶段所选门槛关闭，见[本批登记](../architecture/reviews/2026-10-14-temporal-coding-nested.md)。daemon已发送请求的自动负向恢复、跨宿主和复杂Coding质量为当前矩阵明确的后续范围；所选故障必须保留unknown、原义务及安全诊断／处置，不因未能自动恢复而危险重试。第一阶段 dev99保持冻结。

进入阶段时固定所选部署组合；先核对已有实现，再补阻塞项。

首批 [Codex 通信／启动日志基础](codex-runner-foundation.md)已交付，dev101
继续完成[固定配置／原生控制检查](codex-coding-preflight.md)与有限实际命令 read/write/test、
路径／网络拒绝和 setsid 后继整容器停止探针。完整 Runner 不标为完成。
dev102 新增[保留环境与共享 PG 启动日志](codex-coding-environment.md)，原 container
ID／generation 冷检查、实际整容器停止和 PG 原意图事务已有有限证据。原始 Docker
argv 仍可重启，未形成旧启动失效保护。下一门槛按[原 Action 委托契约](../architecture/specs/delegated-coding-action-contract.md)集成
Local／Temporal 的一次阶段准入、共享日志的 History 绑定、停止采纳、冷恢复与专用认证／真实 Coding Turn。
配置读回、Schema、假服务和进程组回收不能替代业务工具隔离与原 History 证据。
完整 G3／G5／G7／G8 和 R13 未关闭；最终受影响源码 301 项零跳过、P1／P2 实际复验闭环，安装证据见[本批登记](../architecture/reviews/2026-10-14-codex-environment-journal.md)。

dev103 [有限 Local 委托](local-coding-delegation.md)将原审批、一个预算预留／attempt、
一次阶段准入、停止采纳及未知效果接回原 ToolAction；opt-in 移除原容器，实际旧 argv
失效已验证。首期只支持 SDK 根级未绑定 Agent／顺序 Workflow；公共 Store 待停止查询
和显式 local-10／Schema 14 门禁保护冷关闭与旧读取器。原 Thread／Turn 业务恢复使用
结构化假服务验证，真实环境的无模型控制与停止证据独立登记；未验证专用认证或真实
Coding 模型 Turn。G1 的 per-Agent／JSON／TOML、完整 G3／G5、Temporal／PG History、
G7／G8／R13 与第二阶段继续开放，最终验收见[本批记录](../architecture/reviews/2026-10-14-local-coding-delegation.md)。

dev104 补齐 G1 的有限 Local per-Agent／声明路径：显式可选 Runner 角色、精确资源借用、
单 Profile 多 Runner 和 JSON／TOML 异步工厂；Descriptor 3／local-bindings-18 保护旧读取器。
owned 关闭先隔离原 Engine，再采纳原资源停止证据；失败保留原租约和清理账本供重试。
图／Team／动态／嵌套与 Temporal 明确拒绝，尚无 Temporal 原 History Runner 准入。
本批旧读取器／安装及恢复范围见[登记](../architecture/reviews/2026-10-14-coding-bindings-and-profiles.md)。
完整 G1 的 Worker、G3／G5、G7／G8 和 R13 仍开放，专用原生认证和真实任务质量未验证。

dev105 补 Local 复杂组合：图 Agent／直接 Tool、并行节点原 Action 投影、Team／Dynamic
和嵌套原子 Run。父级取消／失败只有原后代实际停止后才进入终态；未知效果及持有额度
独立保留。原 Runner 资源串行占用、被禁用工具不参与占用；退出回执可在 owned 关闭
隔离期间保存。本批[登记](../architecture/reviews/2026-10-14-coding-local-composition.md)
分别记录协议夹具、进程冷恢复、旧读取器与安装范围。完整 Temporal History／PG 准入、
专用原生认证和真实 Coding 质量仍开放，不标记整个 G1–G8 或 R13 完成。

dev106 将有限 Agent／顺序 Coding 接入原 Temporal History 和同一 PG EffectJournal，
显式协议 11 固定一次阶段 grant、原 Tool claim／实际进程 owner、prepare 资源意图和
先 PG 后 History 的回执采纳。SDK／JSON／TOML、Runner 精确引用及 owned 关闭重试
已通过有限验收；实际服务、固定 process-peer 业务协议与原生环境控制分开登记，
最终源码／安装／旧 Worker 与故障窗口以[本批登记](../architecture/reviews/2026-10-14-temporal-coding-delegation.md)为准。
PG／History 固定 readonly 配置 file bind 的真实原生控制、配置内容／inode保持、原 CID
移除和 History／PG 收尾已通过；此前两次未保护配置失败及手动清理证据保留。
原默认发布保持，复杂 Temporal Coding 仍拒绝。专用认证不可用、真实 Coding 任务质量
未执行，跨宿主恢复、完整 G1–G8／R13／第二阶段继续开放，见[指南](temporal-coding.md)。

dev107 进一步补原 Temporal 串行 Agent 图，显式协议 12 固定原父子 SDK 身份，
关闭先排空真实提交并关闭当次已接受准入，原后代停止与预算结算分别采纳。
完整回归、固定安装与服务矩阵以[本批登记](../architecture/reviews/2026-10-14-temporal-coding-composition.md)为准；
并行／Team／Dynamic／嵌套、跨宿主、专用认证和真实 Coding 质量继续开放。

dev108 扩展原静态 Agent 图的有界并行，原 History 按有效 Runner 资源授权背压，
全部原后代停止、PG 精确对应与收尾重扫、failed-stop 原恢复已实现。最终 wheel
六条实际并行／共享 Runner／审批重启／取消／关闭恢复路径通过；源码与安装的
完整门槛见[本批验收](../architecture/reviews/2026-10-14-temporal-parallel-coding.md)。
旧12由原匹配107 Worker恢复，默认／11保持；Team／Dynamic选择阶段、全局容量、
嵌套／直接Tool、专用受控认证及真实Coding质量仍开放。DeepSeek官方Responses
真实连接已通过，但尚未接入固定native Profile，不能据此关闭质量门槛。

| 必需项 | 清单与完成门槛 |
| --- | --- |
| 工具、Workspace、Skills、Sandbox 和首个外部 Coding Runner 完整链路 | R12／R13：固定授权、实际调用结束、结果与效果证据、关闭与恢复 |
| Local／Temporal 公共组合与配置一致性 | R01–R04／R19：各自唯一权威、历史版本续接／拒绝、Worker 重启与必要故障窗口 |
| 所选远程数据与消息交接 | R15–R20：明确 Redis／PostgreSQL／向量库／MQ／A2A 组合，以真实服务证明范围与生命周期 |
| 发布与安装兼容 | R25：固定部署配置、版本门槛、升级恢复和可复现安装应用 |

流式 Workflow、高级多模态／实时、额外数据库／Broker、其他 Runner 与索引策略保留在
R06／R09／R13／R15–R20，按场景分期，不自动进入当前第一阶段。

## 第三阶段：服务化与企业治理

必需项为 R21–R24 的 deadline／审批期限、容量与保留、持久观察、Agent Service／恢复管理、
企业身份与资源权限、迁移／备份恢复／故障验证；结合 R25／R26 完成独立采用与正式质量验收。
阶段开始时固定范围，核心 SDK 与企业运行时分别验收；接口预留不代表平台交付。

当前执行按[第三阶段支持矩阵](phase3-support-matrix.md)的五批门槛推进。dev114 首批接通原 Temporal 期限策略配置，见[配置指南](temporal-execution-policy.md)与[验收登记](../architecture/reviews/2026-10-14-temporal-policy-profiles.md)。dev115 补 Local 持久期限与原链路恢复，见[本批登记](../architecture/reviews/2026-10-14-local-deadlines.md)。部署容量、托管观察／服务控制、身份权限／保留及框架备份恢复继续开放；首批通过不代表阶段完成。

## 范围与报告

- 正确性、数据丢失、重复效果、资源泄漏和固定链路质量阻塞在本批修复。
- 非阻塞扩展进入 [后续清单](remaining-work.md)，新增范围必须指出阻塞哪个门槛。
- Embedding／Vector conformance Suite 与额外 SQLite 适配器保留为私有原型，本次未加入产品或标为完成。
- 开发运行受影响检查，阶段集成／交付运行完整回归、安装与兼容；同一冻结版本的有效证据可复用。
- 每批报告成果、关闭门槛、剩余阻塞与下一批目标；完成率按任务拆分和工作量估计，不能按测试数计算。

完整 H3／M1 与 R01–R26 仍未完成；第一阶段的有限链路门槛独立登记，不扩大质量结论。
