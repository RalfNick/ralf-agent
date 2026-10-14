# Temporal 有界并行 Coding 图验收

本批基于 `c8edd65`／dev107；dev108 的有界静态 Agent 图子集已通过源码、固定安装、
实际服务与兼容门槛。本记录不代表完整 R01–R26、R13 或第二阶段关闭；
第一阶段 dev99 保持冻结。

## 交付范围和执行权威

原开关 `coding_execution=True, coding_composition=True` 发布协议 13／组合版本 2／
`bounded-agent-graph`。支持单层静态 Agent 图，有界并行及独立依赖 join；原父子
History 管理调度、审批、结果和预算，PG 仅记录资源证据。没有增加调度器或第二
状态机。Team／Dynamic 的原选择阶段授权、实际结束与迟到响应边界仍需实现。

原 Runner 每次持有一个实际执行。不同 Runner 的子业务可重叠；共享 Runner 的
候选在原父 History 排队，不先创建无法运行的子 intent。占用按实际有效工具授权
计算，工具别名去重、排除的工具不占资源。财务已结算但缺物理证明的原子 Run
仍占 Runner 和并行槽。物理停止但未知的整笔子 cap 不因此结算。

关闭先排空原 SDK 提交、关闭已接受准入，逐个尝试身份已确认的原叶停止和祖先
采纳。首个失败不会阻止其余独立叶。PG 的每条原资源必须精确对应 History Action、
完整 native request、Runner、effect 和 SDK epoch；已 fenced 行及最终扫描仍要
核对物理结束和祖先采纳。关闭失败保留原接收器和资源账本。

## 实际问题与修复

- 实际共享 Runner 并发复现 `CoordinatorBusy`：原 Runner 只能有一个 `_active`。
  新父级资源背压解决该问题；实际不同 Runner 重叠和共享 Runner 串行分别测试，
  不以换测试工具掩盖原错误。
- 关闭 fail-fast 和合法 PG 行遗漏：全子义务汇总、完整资源/History 匹配、收尾重扫。
- 独立审查 P2：PG pending=false 不能证明独立 Agent／顺序 Run 的真实 owner 结束。
  原 epoch 取消、物理证明和最终扫描已补齐；迟到 fenced 行还须确认原祖先采纳。
- 实际停止失败后的 stable cancel 只返回旧回执，`stop_retry` 闩锁未重新启用。
  关闭重新核对原叶及原父的完整请求、epoch 和业务关闭状态，再按 revision 去重
  恢复原停止调度；不创建新原生 attempt／Thread／Turn。
- 独立审查 P2：general drive 会把 cancelling+blocked 改成 running+ready。
  `retry_blocked` 保留原停止及回执恢复后禁止取消中业务重开，方法独立纳入纯指纹。
- 多资源测试 peer 原先忽略 Docker 名称／标签过滤，误认第一个 CID；夹具现在按
  原 CLI 过滤条件查询，并用顺序准备的独立名称空间测试确认。保留错误原 fixture
  的实际失败、确定性 RED 和修复后的 GREEN，不将它们计入成功质量成绩。

独立审查已逐项复验停止证明与恢复 P2，并检查三个资源调度 helper 及
`retry_blocked` 的独立指纹与突变拒绝。最终窄检查 196 项通过；相关重叠检查数量
不相加。源码实际六条路径最初五项通过、关闭重试一项失败；修复后该原失败路径
通过 50.69 秒；最终固定 wheel 的完整六条矩阵全部通过（294.71 秒，零跳过）。

## 兼容与质量证据边界

实际原 dev107 安装及匹配 Worker 的协议 12 审批重启路径通过（1 passed／34.84 秒），
原子 SDK epoch 与重复提交保持。当前 Worker 明确拒绝旧 12，不能用旧 SHA 白名单
假装执行原实现；历史所选发布需要保留其原匹配 Worker／wheel。

真实已安装 dev107 Worker 在注册／业务 I/O 前拒绝新协议 13；正常基线允许注册，
新发布 Activity/Worker/business 调用均为零。默认字节 SHA-256 仍为
`35004369d4aa8b8b85cc45f59f00fa3f6ee83be8061c20fbf053b99446d03349`。
原完整 native Coding 协议、默认声明与已验收107逐字节一致；117 原生及 PG callable
和三份 JSON 资产另核对。保存的7份旧未选中 History 在最终源码及 wheel 安装中
重放通过；不宣称当前源码能重放原12。

用户已授权真实 DeepSeek 连接，官方[Codex 接入说明](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)
声明 Responses 支持。本批实际单次 `deepseek-flash` `/responses` 探针 200／completed／
预期 JSON，实际输入41／输出28（含推理22）token。这仅证明专用端点可用，未运行
受管理 Coding Turn。密钥只在探针进程内存，不写仓库、Run／Action／PG 或发布包；
全局 Codex／Hermes 配置未改。当前固定原生 Profile 仍需显式专用连接集成。

## 最终验收

- 源码覆盖全部 592 个测试模块。首次完整结果为 9250 passed／670 配置依赖跳过／
  1 failed；唯一失败是旧测试把现已支持的协议 13 当成未来版本。仅将该测试的
  不支持版本哨兵改为 999，源码与固定安装中的整个文件各 15 项通过。核对结果为
  **9251 passed／670 skipped／零未解决失败**；原始失败日志保留，产品字节未为此改动。
- 安装后受影响的 190 个测试模块，核对结果 **2371 passed／435 配置依赖跳过**。
  同一哨兵导致的原始失败另行保留；不将定向重跑数量重复相加。
- checkout 外的最终 wheel，实际 Temporal／PostgreSQL 与确定性原生进程 peer：
  六条并行／依赖 join／独立与共享 Runner／审批重启／取消／部分停止失败恢复路径
  全部通过，零跳过。另有 **13 条** 原 Agent／顺序、串行图和 owned 关闭兼容路径
  全部通过（349.96 秒，零跳过）。原 History 均按准确 namespace 读取和重放。
- 原已安装 dev107 与匹配 Worker 的协议 12 审批重启实际通过；旧 Worker 在业务
  I/O 前拒绝新 13。保存的七份未选中旧 History 在源码与安装中重放通过。
  SDK／JSON／TOML 原开关和严格类型检查通过，不宣称逐种配置均重跑全部实际矩阵。
- 378 个产品模块在源码、wheel 与物理安装中一致，原 378 模块全部保留，355 个
  未改；117 项原生／PG／生命周期方法及三份 JSON 资产与已验收107一致。
  最终 sdist 包含当前文档、测试与服务夹具；私有服务配置、凭据和日志不入发布包。
- Ruff、格式与 Git 空白检查通过。新版 Ruff 0.16.10 默认开始格式化 Markdown，
  项目显式排除 Markdown，维持原 Python 检查范围，未重写历史教程。自有 Temporal／PG 启动会话退出为 0，精确 PG
  容器已移除、Temporal 端口关闭，Docker daemon 仍可用；未操作其他服务。

固定 wheel SHA-256：
`6fa019116e96a7a030cb911e33e118d01b06566fee95dd0681cb4742a49d5c3d`。
本批真实服务证据不替代实际模型 Coding 质量，也不将此前原生容器隔离探针记作
本批重新验证。新图使用原物理停止／财务结算分离协议，不保证任意外部效果恰好一次。

## 仍开放

跨父 Run 的共享 Runner 全局队列／池、Team／Dynamic 选择阶段、嵌套／直接 Tool／
外部 patch、跨宿主、Docker create/CID 不确定恢复、专用受管认证与真实 Coding
oracle 质量，以及完整阶段门槛保持开放。实际测试曾出现超过 SDK 512KiB 警告线
的诊断载荷；未达到2MiB拒绝线，不据本批少量节点推断大图规模能力。

接入见[并行图指南](../../docs/temporal-parallel-coding.md)，契约见
[并行执行契约](../specs/temporal-coding-parallel-contract.md)。
