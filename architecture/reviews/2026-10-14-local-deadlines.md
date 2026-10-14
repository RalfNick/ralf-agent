# dev115：Local 持久期限、恢复与独立审查

日期：2026-10-14；前序本地提交 `dce62b0`／dev114。第三阶段以[支持矩阵](../../docs/phase3-support-matrix.md)为依据，本批实现批次 2 的 Local 期限部分。部署准入容量尚未交付，批次 2、R21–R24 与完整 R01–R26 均未关闭。

**本批源码与独立安装同范围各 695 passed、零失败／零跳过，398 产品文件逐字节一致。** Local 期限部分验收通过；部署容量及第三阶段剩余门槛继续开放。仅本地提交，不推送远端。

## 实现范围与权威

- `LocalExecutionPolicy` 是不可变值，Local SDK／Profile 的 `local-bounded` 以及同步／异步注册工厂沿原 Builder 装配。内置声明预检拒绝非法时间；显式错误返回不能成为省略策略。Local 与 Temporal 策略明确区分。
- `deadline_at` 作为调用方请求身份传递；相对期限属于首次解析的发布。原命令回执查找先于再次解析，重复提交不刷新时间，改变绝对时间产生幂等冲突。省略默认的 Profile、提交请求、Manifest 与 Schema 保持原兼容承诺，原 dev114 默认 Profile／完整 Manifest 及原已完成 Run 回执字节比较通过。
- 原 SQLite 接受事务持久化 Run 期限及摘要；首次审批事务保存原时间与摘要，恢复复核类型、公式与发布。父期限取最早有效值，图 frame 使用原父权威；Engine-owned timer 只调用原事务的期限／取消及后代传播。
- 可选 `LocalDeadlineExecutionStore` 保持 mandatory ExecutionStore v1，固定原 Store／backend／方法绑定。SQLite 显式准备 Schema 15 并保留原 Session／Turn 与 native history publications；省略不升级。原不可变 dev114 Reader 对实际 Schema 15 数据库明确拒绝，当前 Reader 正常读取。
- Facade 观察超时／取消不取消业务；低层 drive Task 的既有取消语义单独保留。实际模型、同步线程、delegated work、未知预算和资源义务不会因到期释放。晚到回执可原样记录、结算，不能派发新业务或覆盖期限原因。
- 暂停 Run 保持同宿主计时；关闭撤销 timer，原绝对时间保留，重启／resume 检查原时间。无运行宿主期间不承诺后台执行。timer 失效通过原诊断与 `ExecutionHostFailed` 观察暴露，恢复原绑定后才能 resume。

用户接入、JSON／TOML 和替换方式见[Local 期限指南](../../docs/local-execution-policy.md)，精确职责见[Local 期限契约](../specs/local-deadline-contract.md)。

## 独立审查与回归重点

独立审查使用额外测试复现了以下实现缺口，要求修复后分别补验，不能由初始基础测试通过替代：

1. Run 与被其上限约束的审批同时到期，错误选为审批失败；必须采用 Run 取消及 `deadline_exceeded`。
2. 同步阻塞模型或 Harness 提案跨过截止时间后，仍创建新 ToolAction；同步 Session append 和图／Team／Dynamic 完成策略跨过期限后，仍可提交成功。采纳／完成边界需重新读取原时间，不能只依赖 event-loop timer 获得调度。
3. 已采纳期限后，Provider 发布漂移触发 `_fail`，原期限原因被覆盖；晚到合法／非法响应及业务效果仍分别记录、结算和保留未知。
4. 仅审批期限的 Team／Dynamic／嵌套父 Run 没有自身 pending Action，子到期后父仍停在等待审批，原 child escrow 未收口；必须沿原父链传播、观察并按证据结算。
5. 审批时间延长、删除或错误类型未校验，仍可批准；恢复原时间事实与审批采纳需共同校验。
6. timer 绑定漂移或 current/open 任务意外取消，未进入公开等待／诊断；现按创建时固定的父级 locator 报告宿主失败。正常审批退休和主动关闭取消 timer 不误报，恢复须原绑定。
7. 同步 Team／Planner 返回或存储 writer 获取跨期，仍可提交新子 Run／预算；现采纳前、取得原事务后共同复核，原期限事务提交后拒绝新准入。
8. 新 Facade 已支持期限但 capability 仍声明 False；现按原 Store 的可选端口声明，缺失端口拒绝显式期限而普通默认仍可运行。

新增回归还覆盖策略换对象、Store 方法绑定变化、缺失／惰性可选能力的提前拒绝。审查修改限于独立测试；共享 Engine／Store／Facade 修复由原实现者集成，不增加另一套状态推进权威。

## 最终检查与实际证据登记

| 检查门槛 | 范围 | 最终结果 |
| --- | --- | --- |
| 测试先行与审查修复 | `test_local_deadlines.py` 的初始 RED、独立补充 RED 及对应 GREEN | 初始 41 案例后的独立 RED 保留；最终核心 62＋review 5 全部通过；中间源码 2 failed／687 passed、修复中的新 capability RED 原样登记 |
| 策略／装配／替换 | SDK、Local Profile、JSON／TOML、内置预检、同步／异步注册、错误返回及 owned 清理 | 70 配置案例，源码／安装均通过 |
| 受影响源码回归 | Engine、顺序／串并行图、Team／Dynamic／嵌套、上下文／记忆采纳、Facade 与生命周期 | 最终源码 695 passed、零失败／零跳过；前轮 692 passed 后新增独立审查修复，不冒充最终冻结证据 |
| 原 Store 与 Schema | 默认 1、原 14→15、首次准备失败回滚、原 Session／native publications 保留、readonly 与旧 Reader 拒绝 | 7 Schema＋20 可替换 Store 端口案例，源码／安装均通过，原 Reader 实际拒绝 |
| 实际线程／所有权 | 真实同步 handler Barrier、到期时原线程与 Coordinator 仍占用、晚到确认／未知、实际结束后关闭 | 核心真实同步线程及 asyncio Barrier 案例通过；到期保持原 handler／Coordinator，结束才释放；不把效果结算等同物理结束 |
| 冷进程恢复 | POSIX 原 owner SIGKILL；SDK／JSON／TOML 原审批到期与批准后重启；原时间、effect key、命令回执和单次业务写入 | 源码／安装各 6 真实 POSIX 进程案例通过；SDK／JSON／TOML，9 个被 SIGKILL owner＋12 个正常恢复进程均有终止断言 |
| Facade 与宿主失效 | 观察超时／取消、调用方绝对时间、owned CloseIncomplete、原 timer 失效诊断和原绑定 resume | 7 Facade 案例及意外取消 review、正常退休／关闭事件循环探针通过 |
| 独立安装 | 仓库外固定 wheel、产品逐字节、独立 site-packages、同一测试与进程恢复入口 | 独立 site-packages 仓库外同 695 passed 零跳过，398 产品一致；新测试及 process worker 同冻结字节 |
| 默认与 Worker 兼容 | 原 dev114 默认声明字节、旧 Reader、实验 Worker 完整原发布接受／拒绝及原不可变 Worker 恢复责任 | 原 dev114 Local 默认完整字节／回执一致；Schema 15 旧 Reader 拒绝。Temporal composition 指纹保持，但 native CREATE 的 __init__ 来源摘要随版本变化，实际 check_source_inventory 拒绝原摘要，保留原安装／Worker；本批未重跑 History |
| 格式与提交 | Ruff、格式、空白检查；本地提交与工作区状态 | Ruff、格式与空白检查通过，CI YAML 解析通过；CI 增加安装后期限测试，未运行远端 CI；仅本地提交 |

各最终报告应关联同一冻结源码与测试文件，注明 wheel／安装的实际导入路径、产品校验、私有证据位置与原进程退出。中途失败、跳过或修正测试假设原样保留；不能将后来的绿色结果改写为早期已经通过。

## 生命周期、兼容与剩余门槛

原 Run／Action／命令／预算、Session 和结果证据仍由原 SQLite authority 保持。到期只是受管理业务控制，不能证明外部操作未发生，也不能代替 handler 实际结束。未知效果保留原义务及核验／人工处置路径，危险重试拒绝。计时宿主停止或失败的原数据库继续保留，使用原 Scope、Profile、组件、数据身份恢复；不得为达成完成率清未知账、延长原时间或替换陌生后端。

Schema 15 的显式启用是实验兼容门槛；旧 Reader 拒绝，原默认省略继续保留。声明默认兼容不表示当前源码可替代任何旧 Coding／Temporal Worker；精确指纹变化时保留原不可变安装与匹配 Worker，恢复原发布，不能改标 History。最终 wheel SHA-256：`8597f3c475e42c53009c88791c73e4ef7ee82ece4d8135b7988649ef5402bc12`。私有证据在 `/private/tmp/ralf-agent-dev115-root`；导入实际位于该目录的 `installed-venv/lib/python3.12/site-packages/ralf_agent`，不通过源码 editable 包验收。审查端口与旧 Reader 证据在 `/private/tmp/ralf-agent-dev115-storage-audit`，独立真实 PID 清理记录在 `/private/tmp/ralf-agent-dev115-config-tests`。最终源码／安装进程的独立清理记录见根证据目录。

本批并非完整阶段收口，未执行的新阶段全量检查不能引用为当前版本通过。第一阶段 dev99 与第二阶段 dev113 的既有业务／模型证据只按原冻结范围复用；这里的模型与业务夹具不产生新的真实模型质量、性能优势、AgentScope 对齐或外部采用结论。

下一交付继续完成批次 2 的部署准入容量与恢复／关闭释放责任；随后为 hosted 观察及服务控制、可信身份／资源 ACL／保留，以及框架备份恢复与升级。以上仍为阶段必需能力，不因本批期限接口可用而删除。
