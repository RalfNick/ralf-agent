# 预览版本验证与发布

当前基础交付包版本为 **0.1.0.dev120 开发预览**，运行时代码固定于 `b871f61`。默认Local链路、现有Provider／工具、上下文、记忆／RAG及审批恢复已按本轮范围收口，见[当前状态](implementation-status.md#当前交付摘要)；完整阶段、真实模型／服务和企业目标分别记录，不由版本号推导完成。下文dev6–dev9条目保留为历史兼容说明，仅在具体变更影响原承诺时按范围补验，不要求每轮重跑整个历史阶段。

本仓库的 CI 执行检查和构建，不自动发布到 PyPI／GitHub Release。以下是维护者的发布流程；发布、推送及权限配置由维护者明确执行或授权，不由文档验证自动触发。目前尚未核验 PyPI 或 GitHub Release 中有对应发行包。


## 本轮本地交付

本轮交付物放在仓库的 `dist/basic-sdk-b871f61/`：`ralf_agent-0.1.0.dev120-py3-none-any.whl`、`SHA256SUMS` 与 `delivery.json`。这是本地制品，未推送或发布到远端；当前支持范围只以[当前摘要](implementation-status.md#当前交付摘要)为准。

```bash
python -m pip install "/ABSOLUTE/PATH/ralf-agent/dist/basic-sdk-b871f61/ralf_agent-0.1.0.dev120-py3-none-any.whl"
ralf --version
ralf --format text init my-agent
cd my-agent
python -m agent_app --ticket INC-001
```

完整审批与跨进程恢复按[首用教程](getting-started.md)执行；模型与工具定制从[SDK指南](sdk-model-tools.md)开始。安装前在制品目录执行 `shasum -a 256 -c SHA256SUMS` 核对文件；路径及命令由使用者替换为实际位置。

本轮复用固定产品的完整离线源码回归（12,749通过／838配置依赖跳过）、原独立安装62项及其他已登记基础证据；最终wheel已通过隔离安装、版本／入口、starter审批、重复审批、恢复及原命令回读验证，业务只写入一次，结果见 `delivery.json`。wheel与交付记录的SHA-256校验通过。该smoke不改称完整安装矩阵或新的真实模型质量，阶段未验收项保持不变。后续CLI核验便利命令等可选项不进入本轮，现有SDK人工核验可用。

## Temporal 工具结束证据补丁

原 `basic-sdk-b871f61` 制品保留，不替换其哈希。后续发现默认无 `ToolExecutionOwner` 的 Temporal 工具存在P1：超时工具经人工确认效果后，另一个工具成功可能让父任务提前结算。新补丁 `dist/p3-tool-end-20261016/` 的同版本wheel独立校验、安装与验收，细节见[补丁记录](../architecture/reviews/2026-10-16-temporal-unowned-tool-end.md)。该批证据绑定该精确制品，后续增量按各自验收选择；不能只凭 `dev120` 版本号区分。

补丁用 `ralf-unowned-tool-end-evidence-v1` 标记保护新Run，默认Card／普通发布身份保持。无标记旧History为确定性重放保留原行为，**没有自动升级或追溯修复**；重放通过不等于原风险消失。默认Local起步不受本问题影响。无Owner的原工具超时后，即使外部已看到线程退出，没有原History结束回执仍保留义务；没有新增人工清除入口。旧未知Run的安全迁移／处理仍是开放项，不能据本补丁关闭P3-3或P3-5。

## P3-3 scoped 人工恢复增量

后续已验收制品 `dist/p3-scoped-manual-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，SHA256 `4c90e3312f611676e6bc12d126810511621dffe1b2bff6949638766692c417ac`，附 `verification.json`／`SHA256SUMS`。它包含上述新Run结束证据修复，并补原普通Tool在默认scoped满容量后的有限人工核验路径。源码／隔离安装各1,233项及实际SDK图child验收见[本批记录](../architecture/reviews/2026-10-16-temporal-scoped-manual-recovery.md)。默认Local基础制品仍冻结，P3-3／其他阶段未关闭，旧不安全Run未追溯升级；所选实验发布指纹变化后，旧History仍使用原匹配Worker。中间候选与失败包不作为交付物替代此精确制品。

## 1. 准备版本与兼容说明

1. 同步 `pyproject.toml` 和 `src/ralf_agent/__init__.py` 中的包版本。
2. 更新 [CHANGELOG](../CHANGELOG.md)、[实现清单](implementation-status.md) 和已验证的使用指南。
3. 分别审查包版本、内核 Manifest 身份、SQLite Schema 和命令摘要的兼容性；安全补丁不自动意味着旧 Run 可恢复。
4. 明确列出已支持的 OS／Python、适配器和验证类型。当前 CI 为 Linux、Python 3.11／3.12／3.13；本地开发可在 macOS 验证。

dev6 新增 Harness／Executor 固定身份与接收阶段语义，内核改为 local-4。dev3–dev5 的 local-3 Run 可观察、取消及人工核验，继续需原版本和原配置；不静默迁移。SQLite Schema v1、dev3 起的调用方 submit 摘要保持不变，相同请求可找回旧回执，但不能用新内核续跑。dev1／dev2 历史 submit 摘要重放仍需原版本；自动摘要／Run 迁移尚未交付。

dev9 保留 dev8 默认 Manifest 和缺省 Chat identity。实际制品验证需先安装 dev8 创建任务，再安装 dev9 用原默认工厂重放回执并续跑；同一离线 HTTP fixture 也要验证旧 Chat 配置。启用 Recall／Knowledge／planner／profile、生成参数或流模式会固定新的身份；不能在旧 Run 上静默启用新策略，也不能因同一提交找回回执就忽略配置不匹配。

## 2. 在干净检出中验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
git diff --check
python examples/evaluate.py
python -m build
```

使用干净构建目录，确保本次 `dist` 里只有将要发布的版本；不要用 `dist/*` 混入历史 wheel。离线评测检验运行时审批／恢复／业务写入契约，不构成真实模型质量基线。记录源码 commit、测试环境和构建产物 SHA-256。

## 3. 在源码目录外安装 wheel

这里 `/path/to/ralf_agent-0.1.0.dev120-py3-none-any.whl` 是实际构建文件的占位路径。使用新的虚拟环境和源码目录外的临时目录，避免 editable install 或 PYTHONPATH 掩盖打包遗漏。

```bash
python3 -m venv /tmp/ralf-wheel-check
source /tmp/ralf-wheel-check/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0.dev120-py3-none-any.whl"
python -m pip check
mkdir /tmp/ralf-release-smoke
cd /tmp/ralf-release-smoke
ralf --version
ralf --format text init my-agent
cd my-agent
python -m agent_app --ticket RELEASE-001
```

确认停在 waiting_approval，然后按 [首次使用指南](getting-started.md) 从独立进程 inspect、批准、resume。再重提原命令，核对回执／Run ID 稳定和业务写入没有重复。检查包内包含 starter，生成项目不导入 `examples`。源码包还应包含文档、许可证和测试所需文件。

dev6 制品还需核对 Harness／ToolExecutor／DTO 公开导入、默认与自定义组件身份拒绝恢复，以及两个接收提交后的真实进程故障回归。源码示例使用 [execution_components.py](../examples/execution_components.py)；wheel 不要求包含或导入仓库 examples。保存新／旧内核的拒绝续跑证据，不能只验证一次无故障运行。

dev7 制品还需在源码目录外运行 `ralf init my-knowledge-agent --template rag`，测试中英文来源与无证据拒答，独立进程 resume、原引用版本和 tombstone／TTL 不被启动过程复活。核对 Recall／Knowledge／Vector 的公共导入；两个 RAG 崩溃窗口分别保持原快照及直接采纳已收响应。Embedding 未配置时不产生远程调用。

dev8 制品还需运行 `ralf init my-config-agent --template config`，在只改默认版本后从新进程恢复旧任务，核对原 profile／模型／工具及精确命令回执。补充资源构造／关闭失败重试和真实线程活动时切换拒绝；核对 ExecutionEngine、KnowledgeContextPort、RecallPlanner 与配置 API 的公开导入。配置缺少旧版本时应拒绝续跑，原回执查询不依赖该版本装配。

dev9 制品还需验证三个 HTTP/SSE 协议和 DeepSeek 固定 non-thinking 参数，独立 model 模板的占位/缺凭据拒绝及实际离线 HTTP 配置运行。核对全部公开导入和原 oncall/rag/config 模板字节保持一致。fixture 请求不能记为线上兼容/模型质量成绩；真实付费调用另行执行与记录。

## 4. 人工发布与安装核验

发布者先确认项目名控制权、维护者权限、目标仓库和预览版本号。审查 release notes、许可证、产物清单与摘要后，再通过授权的 PyPI 上传方式或 GitHub Release 界面发布已验证的精确产物；不要把新打包或依赖重新解析视为等同于此前验证的 wheel。

发布后从目标发行入口下载或安装对应版本，在新的虚拟环境中执行同样的 wheel 冒烟与恢复流程。只有这一步通过，README 才能把该 PyPI 安装命令／Release 下载链接列为已验证入口。保留上传记录、产物摘要和安装验证报告；不要把仓库存在等同于发行包可安装。

## 5. 发布后的维护边界

发布说明应注明预览 API、当前能力和升级限制。漏洞处理见 [安全政策](../SECURITY.md)，功能／缺陷贡献见 [贡献指南](../CONTRIBUTING.md)。

变更固定身份或存储格式前，先实现迁移／拒绝策略与真实恢复测试。未知业务效果先核验；回滚程序版本并不自动回滚数据库或远端写入。修复发布不能依赖删除执行日志来获得干净状态。

dev12 制品还需在源码外运行 `ralf init my-parallel --template parallel`，验证历史 Profile 恢复、分支 Session／审批、共享预算与五个崩溃窗口；旧 dev11 native/v1/v2 请求／Manifest 保持精确，dev11 续跑 v3 在派发前拒绝。检查终态资源尚未静止时仍保留 Session 预留，原生授权回调核验不会再次派发。

## P3-3 原Run必要控制增量

制品`dist/p3-run-command-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，SHA256
`185b1d23c5967ba29daad647be9d56f9a3ac36559150dc9ac14d275165c900b2`，附独立
`verification.json`／`SHA256SUMS`。它包含前批修复及本次原Run必要控制运输窄修。
源码／隔离安装各1,272项；相同wheel三个实际SDK场景分别通过，原失败、warning及
各自运行快照详见[验收记录](../architecture/reviews/2026-10-16-temporal-run-command-capacity.md)。
此前12组制品不变。默认Card／普通发布与保存History兼容通过；所选实验指纹变化，
历史所选发布仍需精确匹配Worker。不可变旧Worker只保留原Update兼容路径及其上限，
没有追溯修复或未知义务清除。完整P3-3、原P3-2失败及后续门槛均未关闭。
