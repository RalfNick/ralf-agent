# 安装与环境

[文档目录](README.md) · [首用教程](getting-started.md)

Relf-Agent 需要 Python 3.11+。本地开发使用 Linux 或 macOS，本轮实测平台见[Alpha范围](releases/0.1.0a2.md)，CI配置不等于已运行通过；CI的Python版本与检查以[贡献指南](../CONTRIBUTING.md)和[工作流](../.github/workflows/ci.yml)为准。

## 当前 a4 本地候选与原制品

当前源码版本 `0.1.0a4` 包含 `210a79e` 公共契约修复和 `672d0cf` Coding 测试夹具修正。独立本地 wheel／sdist 及精确 SHA 见[a4 说明](releases/0.1.0a4.md)，实际安装、平台及待发布状态见[a4 清单](alpha4-validation-status.md)。本批不推送、触发远端 CI 或公开发布；`pip install ralf-agent==0.1.0a4` 不是当前公开安装入口。

原 a2／a3 包和全部历史失败保留；原 a3 不含近期修复且发布暂停。公开安装仍是下方 a2 URL；本地新包不能沿用旧包成绩或旧 Worker 资格。

## 从公开 Alpha 安装

当前公开入口是[GitHub Release v0.1.0a2](https://github.com/RalfNick/relf-agent/releases/tag/v0.1.0a2)，尚未发布到PyPI。原wheel已在源码目录外的新环境实际安装，审批、崩溃恢复和重复提交通过；仓库改名后的以下下载地址另经匿名下载核对，原包SHA保持：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'https://github.com/RalfNick/relf-agent/releases/download/v0.1.0a2/ralf_agent-0.1.0a2-py3-none-any.whl#sha256=dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46'
ralf --version
ralf --format text init my-agent
```

Release同时提供原sdist和只列这两包的`SHA256SUMS`。公开安装实测为macOS ARM64／Python3.12、正常PyPI基础依赖解析；Linux ARM64／原生AMD64三Python版本使用冻结依赖门禁分别验收。具体范围和原失败见[公开交付记录](../architecture/reviews/2026-10-22-alpha2-public-release.md)。

## 从源码安装

```bash
git clone https://github.com/RalfNick/relf-agent.git
cd relf-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

基础运行依赖为 `httpx` 和 `jsonschema`。默认 SQLite、离线 Demo 与独立 starter 不需要模型密钥或外部服务。安装后按[首用教程](getting-started.md)完成提交、审批与恢复。

上面的 clone 命令演示源码安装方式。公开Tag`v0.1.0a2`固定验收代码`3a92720`；默认分支另维护最新安装文档。要复现交付请使用下方精确wheel，或对应源码提交，并核对`ralf --version`。制品的固定来源、平台和追加测试校正见[验证清单](alpha2-validation-status.md)，不能仅凭远端分支名称推导同一验收范围。

## 从本地 wheel 安装

在独立虚拟环境中，把占位路径替换为实际制品路径：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0a4-py3-none-any.whl"
ralf --version
ralf init my-agent
```

当前本地候选为 0.1.0a4，目录及 SHA 校验见[a4 说明](releases/0.1.0a4.md)；公开安装推荐仍为 a2，见[发布指南](releasing.md)。dev123及更早目录属于历史制品，不要仅按同名 wheel 选择。GitHub Release的对应原包已公开核验；PyPI未发布。wheel 包含独立工程生成器，仓库 `examples/` 通过源码获取。

## 按需安装可选依赖

以下命令在源码仓库根目录、已激活的虚拟环境中执行。只安装所选功能需要的 extra；依赖声明以 [pyproject.toml](../pyproject.toml) 为准。

| 功能 | 安装命令 | 使用说明 |
| --- | --- | --- |
| 解析标准 Skill 文档 | `python -m pip install -e '.[skills]'` | [Skill 文档](skill-documents.md) |
| 文本 PDF 摄取 | `python -m pip install -e '.[pdf]'` | [PDF 摄取](pdf-ingestion.md) |
| tiktoken 计量 | `python -m pip install -e '.[tokenizer]'` | [Token 与分块](tokenization.md) |
| Redis 适配器 | `python -m pip install -e '.[redis]'` | [远程数据](remote-data.md) |
| PostgreSQL 适配器 | `python -m pip install -e '.[postgres]'` | [远程数据](remote-data.md) |
| Redis 与 PostgreSQL | `python -m pip install -e '.[remote]'` | [异步装配](async-assembly.md) |
| Temporal 与 PostgreSQL 客户端 | `python -m pip install -e '.[temporal]'` | [Temporal 执行](temporal-execution.md) |
| ASGI 服务启动 | `python -m pip install -e '.[server]'` | [异步服务](async-handoff.md) |
| 开发、测试与打包 | `python -m pip install -e '.[dev]'` | [贡献指南](../CONTRIBUTING.md) |

安装客户端依赖不会创建 Redis、PostgreSQL、Temporal 或 Docker 服务。服务地址、凭据、资源权限和生命周期由运行方显式配置。

## 常见安装问题

| 现象 | 检查方式 |
| --- | --- |
| 找不到 `ralf` | 激活安装时使用的虚拟环境，执行 `python -m pip show ralf-agent` 确认环境 |
| 无法导入 `agent_app.runtime` | 在生成项目的目录中执行；`--factory` 指向该工程原工厂 |
| 无法导入 `examples` | 使用源码仓库并从根目录执行，或改用 wheel 中的 `ralf init` 模板 |
| 提示缺少可选模块 | 根据上表安装 extra，再按对应指南配置外部资源 |
| 任务配置不匹配 | 保留原数据库和原配置，按[恢复指南](recovery-guide.md)处理，避免切换新默认续跑旧任务 |
