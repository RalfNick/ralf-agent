# dev114：Temporal 策略声明与第三阶段首批验收

日期：2026-10-14；前序冻结提交 `695175e`／dev113。第三阶段以[支持矩阵](../../docs/phase3-support-matrix.md)为依据，本批只关闭首批策略配置及有限恢复门槛，不关闭 R21–R24 或完整 R01–R26。

## 实现与边界

- `TemporalProfile.components.execution_policy` 声明使用内置 `bounded` 工厂，复用原 `TemporalExecutionPolicy`；SDK、JSON、TOML 及同步／异步注册工厂沿原装配路径工作。未知字段、非法期限／容量／allowlist 在内置工厂准备阶段拒绝，整个 catalog 预检后才创建组件。
- 策略值进入原 Runtime Manifest／编排 Release，原 History 保持计时、审批、结果、预算与晚到证据的唯一权威。未增加独立服务状态机。
- 自定义工厂显式返回 `None` 曾被当作省略策略；新增测试复现后，在 Builder 公共采纳边界检查返回类型，拒绝 `None`／dict／意外 awaitable，并完成原 owned 构造清理。省略声明仍合法且保持旧默认字节。
- 策略是不可变值，不拥有客户端；工厂附属资源沿原 BuildContext 登记。等待超时、业务期限、终态、预算结算及实际处理器结束分别管理。Facade 的 `deadline_at` 和 Local 期限仍未交付，不能据此扩大支持范围。

## 检查与实际证据

| 检查 | 最终结果与范围 |
| --- | --- |
| 测试先行 | 初始配置测试 7 failed／42 passed；扩展发现显式 None 返回漏洞并复现。最终 60 项策略测试通过，包含同步／异步替换和实际异步关闭完成 |
| 受影响源码回归 | 313 passed／2 skipped；配置、Registry、Profile、装配／生命周期、期限、指纹缓存与 Coding 配置门禁。两项跳过依赖其他远程配置，不作为本批实际服务证据 |
| 独立安装回归 | 仓库外安装相同 wheel，313 passed／2 skipped；导入路径明确为独立 site-packages |
| 实际源码服务 | 4 passed／0 skipped；原 Temporal Service＋PostgreSQL，21.456 秒 |
| 实际安装服务 | 同一最终测试文件与产品字节，4 passed／0 skipped，18.969 秒 |
| 默认兼容 | 修改前、当前源码及安装后 Profile／identity／完整默认 Manifest canonical 字节相等；未选定策略不增加发布字段 |
| 固定安装 | 396 个产品文件源码／wheel／安装逐字节一致；wheel SHA256 `0c8e6ec6ca0d221a22af94171ab937c95aeebc548e1e84b448018dd467b885a2` |
| 原 Worker 门禁 | 原 immutable dev113 Worker 接受其完整原 Coding Composition 发布；当前 Worker 明确拒绝同一原发布。本批没有重跑旧业务 History，不将离线门禁检查记为历史业务恢复 |

四个实际场景为：JSON／TOML 的审批等待期间关闭 Worker、服务计时到期后重新装配；SDK 原审批等待重启并批准，重复命令只发生一次 PG 写入；SDK 原模型执行期间 Run 到期、零等待关闭返回 CloseIncomplete，晚到原模型回执采纳后才关闭 Worker 和 owned PG 客户端。四份原 History 均 replay；源码与安装共八份，模型为确定性测试 Provider，不计为真实模型质量。

审批过期场景核对唯一原 `approval_expiry_recorded`、Action 的 `approval_expires_at`、过期事件顺序及重启前后完整 TimerStarted 记录，证明未刷新期限。加强测试时曾错误假设 History 仅有一个 TimerStarted，源码／安装各出现 2 failed／2 passed；实际 drive 可合法取消并重建剩余时间计时器，测试修正该假设，保留原绝对期限与重启记录不变的断言。原失败日志／JUnit 保留，最终两套各四场景通过，未修改生产计时逻辑。

本批按风险执行受影响检查，未重跑完整阶段回归；dev113 的 10234／704 仅保留原冻结范围，不能改标成 dev114 全量通过。CI 已增加源码及安装后策略服务入口，但本地结果不代表远端 CI 已运行。

## 所有权与证据保留

测试使用本批自建服务及唯一 queue／Scope／backend，不操作用户其他容器。所有 owned assembly 的原 Worker 和实际模型工作先排空；专用 Temporal 进程结束、自建 PG 原 CID 移除、三个原端口不再接受连接，用户 Docker 仍可用。保存测试 PG dump、Temporal SQLite 与失败／最终报告供本地复查；私有测试证据保留不代表框架备份恢复能力已交付。

私有登记目录为 `/private/tmp/ralf-agent-dev114-root`：`final-acceptance.json`、`package-provenance.json`、`affected-source.xml`／`affected-installed.xml`、`source-services.xml`／`installed-services.xml`、`old-worker-rejection.json` 和 `cleanup-verification.json`。配置凭证不进入产品、文档或提交。

## 兼容、剩余门槛与下一批

本批没有更改 Coding 图 DTO 或业务协议语义，但 Temporal Profile／Builder 的精确源码指纹变化会改变显式 Coding Composition 的 Worker 发布。旧 dev113 Run 继续使用原不可变 wheel／Worker，保留原 Profile、namespace、Scope、journal 与物理资源；不能改标版本或替换原 History。使用与恢复责任见[策略指南](../../docs/temporal-execution-policy.md)。

下一批按矩阵补 Local Run／审批期限及部署准入，随后是托管观察／服务控制、可信身份／ACL／保留，以及框架备份恢复和升级责任。第一阶段 dev99 质量、dev109 有限 Coding 质量和 DeepSeek Responses 兼容 smoke 按原冻结范围复用；本批没有新真实模型调用、通用质量或 AgentScope 对齐结论。完成审查及本地提交，不推送远端。
