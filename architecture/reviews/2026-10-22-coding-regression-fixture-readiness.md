# Coding 整轮失败取证与夹具准备

日期：2026-10-22。基线 `210a79e`。按用户要求处理上一批完整离线回归的五项 Coding 失败，保留原期限、业务断言、失败记录和历史制品；不扩功能，不准备 a4，不推送、触发远端 CI 或公开发布。完成后仅本地提交，按授权单次跳过 Git 钩子。

## 原始观察与取证限制

上一批无筛选离线回归为 **14,077 passed／891 条件 skipped／5 failed**，退出 1。五项随后在相同源码和期限下单独执行为 5 passed，不能拼成整轮通过。[原记录](2026-10-22-alpha-review-contract-fixes.md)保持。

| 原失败 | 整轮观察 | 当前能够确定的边界 |
| --- | --- | --- |
| Supervisor success | accepted／exec_started 为真，CID 为空；测试约 3.262 秒 | 门控接受不等于 CLI 成功，不得补造 CID 或再次 CREATE |
| Supervisor timeout `[hold]` | 5 秒内未见 CLI `invocations` | 失败发生于测试等待 CLI 入口阶段，未进入后续正常超时断言 |
| Supervisor unknown control token | 5 秒内未见 CLI `invocations` | 尚未发送坏 token，不能据此归因于控制消息校验 |
| Supervisor worker exit `[True]` | Worker 就绪后 5 秒内未见 CLI `invocations` | 尚未执行目标 Worker kill，不能据此认定冷恢复或关闭错误 |
| Transport hook | 原审批后的 Run 为 `waiting_reconciliation` | 未取得确定结果时保留原未知效果，不得改为成功或重发 Turn |

原 pytest 临时目录已被清理，旧 broker-result／运行数据库无法恢复。现存原日志、JUnit、命令结果及原收集顺序复制到独立私有目录并保存 SHA256；不声称保存了原五项的完整进程回执，也不从断言反推唯一底层原因。新的诊断在 call 结束、夹具 teardown 前保存脱敏阶段记录、文件时间和 Runner 观察；不输出令牌、环境密钥或真实服务数据。

## 产品、夹具、顺序与宿主的区分

- **产品行为：** 未复现稳定的产品状态机、重复提交、停止或关闭缺陷。442 个跟踪产品文件与 `210a79e` 逐字节一致；本批没有修改产品、版本、依赖、Schema、协议、执行权威或指纹实现。不能将“未复现”写成产品不存在问题。
- **夹具准备缺口：** 原环境夹具已有 `--fixture-ready`；Supervisor 和 native CLI 工厂没有统一执行该准备步骤，新建 shebang 文件首次进入 Python 的成本会占用原操作期限。补齐此准备契约，不修改业务调用，不重试业务来预热，也不把 readiness 充当容器、Thread、Turn 或停止证明。另修正工厂顺序：就绪失败必须发生在 Runner 日志、租约和 Engine 创建之前。
- **执行顺序：** 相邻 13 文件复验 318 passed／2 条件 skipped。完整收集原测试集合后按原序执行到 transport hook，1,593 passed／42 条件 skipped／13,338 未执行；目标五项均通过。该诊断只是前缀，不能写成全量通过；尚无可复现的前置状态污染证据。
- **宿主时序：** 使用默认临时目录对 24 个新脚本做首次／再次启动配对：首次中位 0.113 秒、最大 0.300 秒，再次中位 0.026 秒、最大 0.049 秒；本次未观测到超过 3 秒的启动。默认临时目录下原五项另得 5 passed／8.94 秒。只能确认首次成本差异，不能将原五项逐一归因于 macOS 冷启动、某个安全组件、机器负载或睡眠。

本批修复的是可以确定和验证的夹具准备／失败装配边界。**原五项历史失败的唯一瞬态触发原因仍未能追认。** 新完整复验结果单独登记，不改写原失败，不以多轮局部成绩代签整轮。

## 最小修正与反例

- 三种合成 CLI 使用同一个测试 helper：仅 PATH 环境，单次 `--fixture-ready`，沿用既有准备阶段 5 秒上限；要求退出成功、stdout／stderr 为空、可执行文件字节不变。失败直接拒绝，不重试。
- Supervisor 就绪发生在 namespace lease 和 CREATE operation 之前；就绪分支在参数解析和业务入口之前返回，目录中不产生业务／门控／环境记录。
- native CLI 在工厂返回前就绪；公共 `original_engine` 在准备通过后才创建 RunnerJournal。已有模拟 Docker state、原 Action 审批、受保护 transport hook 与唯一 Thread／Turn 提交断言保持。
- 新增可控首次 3.2 秒启动，先在准备阶段完成，再以原 3 秒期限执行真实合成 CLI 和审批后的 Agent 业务链；就绪失败退出、输出污染和改写脚本均不得进入产品。
- 新增 entry-hold：即使 CLI 已就绪，阻塞业务入口仍按原 3 秒期限真实终止，要求 child_ended／helpers_ended／control_drained、CID 为空且不得重发。原 hold／EOF／输出上限／后继进程及坏 token 测试保持。
- 原 Supervisor 3 秒、Runner 3 秒、入口 barrier 5 秒，以及所有 S2 和历史制品门槛均不变。准备操作仅限测试合成可执行文件，不加入真实产品路径。

## 验证记录

新增六项准备／超时反例先得到 6 failed；补齐后两模块 34 passed。随后补出的装配失败反例先得到 1 failed：就绪失败前已生成 Runner 日志与 owner 文件，调整工厂创建顺序后，最终两模块 **35 passed／31.66 秒**。上述为受控反例，不冒充原五项的复现。

初次跨 Codex／Local／Temporal Coding 范围检查 **2,272 passed／139 条件 skipped**；其后补出的创建顺序修正由上述最终 35 项及后续固定输入完整回归覆盖，不将局部轮次相加。

### 第一轮完整复验与宿主时序

无筛选完整回归 **14,088 passed／891 条件 skipped／1 failed**，零 error，41 分 50 秒，退出 1。**原五项全部通过**；新增失败是未修改的 `test_workspace_write_processes.py::test_real_crash_recovers_original_effect_without_duplicate_replacement[before_rename]`，原 20 秒子进程超时，尚未进入目标 rename 崩溃窗口。该轮不是完整通过，不与随后 7 项局部通过拼接。

失败目录在下一次 pytest 清理前单独复制，只有原 `note`，没有 `.ralf`／写入日志／效果证据。系统电源事件显示本轮 21:50:45 合盖睡眠，之后多次 DarkWake；该夹具目录于 21:59:31 创建，处于 21:59:19 开始的 DarkWake 段，子进程在约 20.147 秒后超时。该测试本身未跨过下一次 Sleep，不能仅凭这些事件断言精确阻塞点或唯一因果；可以确定整轮后段宿主未保持连续正常唤醒，且失败前没有可恢复的写入效果日志。保留退出码、JUnit、失败目录与筛选后的电源事件。

不修改 Workspace 产品或夹具，不增大原 20 秒期限。使用仅绑定测试生命周期的 `caffeinate -i` 防空闲睡眠保护后，原 Workspace 进程模块 **7 passed／11.20 秒**。随后以相同 1,413 个产品／测试文件完整复验；第一轮前后 SHA 全部一致。该保护不更改全局电源设置，也不能绕过合盖睡眠，执行时仍需保持开盖。

更早的五项 Coding 原失败轮次为 17:42:24 至 18:22:57，其电源事件区间没有 Sleep／Wake／DarkWake 记录，**不将两轮失败归为同一睡眠原因**。

### 第二轮完整复验

相同 1,413 个产品／测试输入，沿用原清洁环境、期限和条件跳过规则，完整收集、不筛选、不重试：**14,089 passed／891 条件 skipped／零 failed／零 error，39 分 18.58 秒，退出 0**。本轮单独形成完整结果，不拼接第一轮或局部轮次。测试开始前及结束后 SHA 全部一致；442 个产品文件与 `210a79e` 全部相同。只增加测试生命周期的 `caffeinate -i` 和 call 结束后的只读取证，不修改业务执行、超时、重试或调度行为。

| 原失败节点 | 第二轮状态 | 用例总时长（含 fixture） |
| --- | --- | --- |
| Supervisor success | passed | 0.522 秒 |
| Supervisor timeout `[hold]` | passed | 3.378 秒 |
| Supervisor unknown control token | passed | 0.489 秒 |
| Supervisor worker exit `[True]` | passed | 1.448 秒 |
| Transport hook 原审批链路 | passed | 1.617 秒 |

Workspace 原进程模块七项在本轮整轮环境全部通过；原 `before_rename` 用例为 0.880 秒，原 20 秒期限与真实崩溃／唯一替换断言保持。执行区间为 22:13:08 至 22:52:29；系统电源日志在该区间未见 Sleep／Wake／DarkWake 事件，测试生命周期的防空闲睡眠断言已确认，未更改全局电源配置。这些证据不用于追认第一轮精确阻塞点或更早五项的唯一原因。

本轮 JUnit SHA256：`2bb2a05823b17182dbe26297df7e7fef78bace9c58b12ace2847601a6119e8a1`。七份原日志／JUnit／命令／收集顺序的 SHA 全部保持。原 a2 公开交付档案249项、原a3候选76项校验全部匹配，未替换历史制品。

最终 Ruff 全量检查、1,424 文件格式及 Git 空白检查通过。独立只读复核未发现可行动问题，明确保留历史归因限制；没有调用真实模型或真实 Temporal／PostgreSQL 等服务，不把891条件跳过标为验收通过，也没有新增安装／平台／发布资格。

所有原始证据保留于 `/private/tmp/relf-coding-regression-20261022/`，历史文件使用 `original-` 前缀且不覆盖；原目录 `/private/tmp/relf-review-fixes-20261022/` 保留。日志、JUnit、摘要、诊断脚本和失败目录另归档至 Git 忽略的本地私有目录 `dist/coding-regression-fixture-readiness-20261022/`，附独立 `SHA256SUMS`。它们不进入发行制品或本地提交，也不依赖可公开读取。跟踪记录保存实际范围、失败与限制，不公开密钥、令牌或原生挑战内容。

## 交付边界

本批只收尾测试夹具和证据记录，不重建或替换原 a2／a3 制品，不准备 a4，不恢复发布推进。原 a3 仍不包含维护源码中的三个 P2 与检索漂移保护；任何未来交付须使用唯一版本和独立候选／平台门禁。原 dev19 所选 S2、指纹、真实模型及平台成绩仍只属于各自原制品和环境，不由本批离线测试扩大资格。
