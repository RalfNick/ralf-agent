# dev40／H3a 自动规则记忆阶段验证与审查

基线 `9fcbb84`／dev39；范围为本阶段最终工作区。按
[设计规格](../../docs/superpowers/specs/2026-10-09-managed-memory-stage.md)与
[实现计划](../../docs/superpowers/plans/2026-10-09-managed-memory-stage.md)
连续开发、TDD、一名全新上下文只读审查、一轮修复；只做本地提交。

## 交付与架构边界

- Local 原生 Agent／顺序 Workflow，在输出验证和必需 Session 保存后执行
  可选规则记忆。原 Engine 保存来源、提案、预算、CAS 意图和独立回执；
  不建立额外执行权威，不隐藏模型调用或后台任务。
- ManagedMemoryPolicy 固定借用的宿主写目标、Scope、namespace、字段 allowlist、
  有限 timeout 和每事实一个 execution credit。与只读 Facts 绑定分开，
  每 Agent stage_policy 支持 inherit/ref/disabled，JSON／TOML 可装配默认工厂。
- 辅助失败不重跑业务；未知写入保留额度并只查询；已持久化的有效回执直接
  结算，不依赖事实继续存在、未过期或后端当前在线。终态不会升级为成功。
- 来源为 completed-result-observation，不能证明整体 Run／外部业务成功；
  后续取消／提交失败可留下观察。既有显式 MemoryPipeline 的成功来源契约不变。
- 内存／SQLite／Redis／PostgreSQL 精确键查询，legacy 端口持久化有界扫描游标；
  真实线程继续由原 Engine 跟踪。反复变动的大 legacy namespace 仍建议接精确端口。
- 新能力首次准入原子激活 schema7，并需要可选 Store 激活／独立额度证据端口。
  默认关闭；schema1–6 和已有发布身份保持。没有完成完整 H3 或 AgentScope 对等验收。

## 独立审查与一轮修复

审查发现三个 Important，无 Critical／Minor；均按真实用户影响确认并修复：

1. namespace 中已有 8192 个事实时，无游标进度的重复扫描永久卡住。加入内置
   精确键查询与 legacy 续读进度；内存／SQLite 大数据及 recall-only 复现 RED→GREEN。
2. 恢复只检查提案摘要，允许缺失预算或状态矛盾造成未记账写入／隐藏未知结果。
   恢复及只读回执先检查 Schema、合法状态、来源／提案／回执和独立额度的所有者、
   数量、占用与结算。缺失额度、错误所有者／数量、伪造回执和状态回退均 RED→GREEN。
3. 回执已保存、结算尚未提交时，TTL 过期／修订／离线使确认被降为永久未知。
   精确回执按已保存证据直接幂等结算，以上三类故障窗口 RED→GREEN。

同一轮补充线程桥内部相同 backend_id 的对象替换检查，复现 RED→GREEN。
最终修复后定向 **48 passed**；没有发起第二次审查。全量回归另外发现旧远程
Session 测试把业务 terminal 当作托管 quiescent；故障注入也可能在仍被托管的
窗口修改记录。保持既有 wait／busy／取消行为，测试显式等待托管收尾后再检查
空闲或注入静止记录损坏。定向 **73 passed**，最终全量通过。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 最终全量、warnings-as-errors | 2619 passed／66 服务配置相关跳过 |
| 冻结 release wheel 安装后定向契约 | 140 passed／1 PostgreSQL 配置跳过 |
| 本机隔离 Redis、记忆及原适配器 | 37 passed／2 PostgreSQL 配置跳过；安装后亦执行 Redis |
| 实际 dev39→dev40 默认定义回执／Manifest／恢复 | 11 类，包括原生／顺序／绑定／图／并行／团队／Plan／DAG／嵌套／transform |
| 实际 dev39 schema2–6 Session 续接／原回执 | 5 类通过，恢复不调用模型 |
| schema7 前向拒绝和新版恢复 | dev39 读写两种打开均拒绝；dev40 丢失 CAS 确认重启只查询、无重复写 |
| SDK／wheel 源文件 | 157 模块名称和内容一致；原 294 个 root exports 全部保留，新增 ManagedMemoryPolicy，共 295 |
| starter 回归 | 实际两版各生成 21 种，文件摘要全部相同 |
| 静态与仓库检查 | Ruff、格式、变更文档本地链接、凭证模式卫生、Git 空白检查通过 |

本轮没有调用真实付费模型、核验公开发布或推送远端。未配置 PostgreSQL／Temporal
等服务的跳过不等于这些服务的验收。安装后和新旧包检查由实现者执行，独立审查
没有独立认证这些结果。

## 实施取舍与未交付范围

- 按用户持续开发／本地提交授权沿用当前 feature checkout，不停在审批菜单；
  代价是共用 checkout 的隔离风险，由初始干净状态、无并行写入及完整 diff 控制。
- 复用已授权的 inline 设计／执行方式，不新增常规确认；代价是实现者承担范围判断。
- 首期规则、原生／顺序及完成结果观察：避免改变执行权威；代价是高级／Temporal
  自动阶段、自动模型选择和后台 Job 仍未交付，已在准入明确拒绝。
- 提交前审查工作区完整包，包含 tracked diff 和所有新增文件；代价是未提交范围
  可能漏收，由 Git 文件清单和最终本地提交复核控制。
- wait 仅观察业务状态，保留活动任务／真实线程占用；代价是检查空闲或注入
  静止故障前需要另观测托管收尾，测试已据此修正。
- PostgreSQL 实测未配置，保留显式跳过；代价是不能据此认证实际 PG 部署。
- 分发／全量证据由实现者分别验证；代价是作者盲区，保留真实安装包和旧新版行为检查。
- 不抵御对全部权威记录的协调伪造；代价是没有被攻破执行权威的加密完整性保证。
  独立缺失／矛盾的恢复证据则必须拒绝。

ContextPipeline、自动模型摘要／提炼阶段、Graph／Team／动态／嵌套／Temporal
组合、后台辅助任务、语义修订／撤回和企业治理继续按
[能力清单](../../docs/remaining-work.md)推进。
