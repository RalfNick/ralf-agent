# dev93：持久用户输入子集验收

状态：本批实现、完整源码、独立审查、真实恢复、安装及旧版本兼容门槛已通过。
完整 R01–R26／H3／M1、真实模型质量和独立采用继续开放。

## 本批范围

显式 `register_user_input` 和固定 `UserInputPolicy` 让 Agent 原工具 Action
提出问题。Local 原事务或 Temporal 原 History 保存问题、答案和幂等控制回执，
不执行 Python 输入 handler／Tool Activity，不产生外部效果 attempt。
答案作为原工具结果或 Planner 自身澄清续接，原任务、Run、Turn、预算及已完成工作保持。

支持原生／顺序、Local 图框架、Team、flat／DAG Plan 和嵌套的原 owner 路由，
选中动态规划的 `needs_input` 消耗原修订额度。Planner 仅接收自身原问题的澄清；
子 Agent 回复保留在子结果、原生历史和显式父完成来源中。
纯 Harness 与 Local／Temporal 各自唯一执行权威保持。

提供 SDK、命名政策 JSON／TOML、Profile 回执优先重连、CLI 和安装后 starter。
A2A 显式输入扩展从公共根 Task 展示原问题与 `ownerTaskId`，回复原子任务并唤醒原根；
混合审批／未知效果保持独立。观察取消、业务取消和真实驱动／线程退出仍分开处理。

## 已取得的证据

各组有重叠，不相加作为总测试数。私有原始证据在
`/private/tmp/ralf-agent-dev93-erffqy3l/evidence`。

| 门槛 | 当前结果 |
| --- | --- |
| 完整源码 | **7339 passed／617 配置依赖跳过**，1224.49s，session25612 实际退出 0；旧候选因已复现缺陷主动终止，不作为成功证据 |
| 独立核心安装 | **259 passed／零跳过**，51.17s；checkout 外真实 wheel，七类可选依赖均未安装 |
| 独立 SDK 安装 | **277 passed／零跳过**，29.63s；新增 Temporal／Sandbox 及原历史／完成／绑定锚点 |
| 真实源码 Temporal | **12 passed／零跳过**，142.34s；24 Worker 实际等待，48 条 History 保存并重放 |
| 真实安装 Temporal | **12 passed／零跳过**，134.96s；另 24 Worker 实际等待，另 48 条 History 保存并重放 |
| 安装后公开 CLI | 新 starter、独立进程提问、复制提示回复、重复原回执、原 Run 恢复成功 |
| 旧 dev92 兼容 | 默认声明／发布／DTO 字节及六类原 Run 双向回执、记录、预算保持，各模型两次／业务写一次 |
| 旧执行器拒绝 | 旧 Local 模型前拒绝；旧 Worker 对选中及 registry-only 新发布零 Activity／模型／工具，实际退出等待 |
| 制品来源 | **327 产品模块**在源码、wheel、sdist、两份独立安装间字节一致；产品与版本 328 项、测试源码 564 项冻结 |
| 服务关闭 | 自有服务 session22436 已退出 0 并实际等待；停止标记及父子 PID 消失已核验 |

真实服务覆盖 Agent／graph／flat Plan／Team／DAG／nested 的问题等待后重启，
以及答案 Update 已提交、响应丢弃、原可重试 Context Activity 已开始而 Provider 未调用时重启。
栅栏只包装原 Activity，保留原参数、名称和产品重试语义。重启复用原 Run／唯一 Turn，
重复答复返回原回执，回放不增加 Provider 调用。

## 独立审查

一次 fresh 全批审查发现六项 Important，均有有效行为 RED，修复后由同一席核验：

1. Temporal 请求未完整绑定原问题；现重建原 Action／source／policy／ordinal 的完整请求。
2. 混合审批／未知效果时丢弃已答子任务唤醒；现保留兄弟控制并推进原可运行子任务。
3. 公共 A2A 无法发现子问题；现提供原 owner，固定 Profile 观察包装，并在业务接受前校验输入端口。
4. Local 聚合子回复触发未声明 Planner 上限；现与 Temporal 保持自身澄清范围，合法 33 子任务完整通过。
5. Sandbox 拒绝合法组合版本；现明确接受 joint 9／10，保留旧默认、标记要求和未来版本拒绝。
6. 完成后立即关闭发出无效取消；现跳过终态业务取消，仍等待实际驱动／线程并保留租约。

同一席最终 API 聚焦 31 passed；原问题、Planner 范围、Sandbox 复核分别为 8／4／15 passed。
无未关闭 Critical／Important／Minor；最终整库、制品与服务门槛由根任务独立验证。

## 继续开放

仅本批有限链路通过上述证据验收，不代表完整 H2／H3／M1 或 R01–R26 完成。
持久 FIFO、业务 deadline、跨权威会话租约、完整治理、流式节点及外部 Runner 继续开放。
Fixture Provider 和实际 Temporal 恢复不证明线上模型规划、答案、记忆或 RAG 引用质量，
也不证明独立采用或对等框架比较优势。

最终打包与静态检查命令、制品摘要、服务消失和本地提交证据保存在同一私有目录。
本地提交以 Git 记录为准，不推送远端。
