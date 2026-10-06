# 预览版本验证与发布

当前代码版本为 **0.1.0.dev9**，固定内核身份为 **local-4**。本轮新增模型协议/参数/能力与完整 SSE，保留公共扩展端口、装配、分页召回、本地 RAG 与两个独立接收阶段。发布检查须登记完整集成与制品结果。这是 M1 核心预览，不能以版本号或本地测试宣称企业部署、Temporal 或真实模型质量已验收。

本仓库的 CI 执行检查和构建，不自动发布到 PyPI／GitHub Release。以下是维护者的发布流程；发布、推送及权限配置由维护者明确执行或授权，不由文档验证自动触发。目前尚未核验 PyPI 或 GitHub Release 中有对应发行包。

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

这里 `/path/to/ralf_agent-0.1.0.dev9-py3-none-any.whl` 是实际构建文件的占位路径。使用新的虚拟环境和源码目录外的临时目录，避免 editable install 或 PYTHONPATH 掩盖打包遗漏。

```bash
python3 -m venv /tmp/ralf-wheel-check
source /tmp/ralf-wheel-check/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0.dev9-py3-none-any.whl"
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
