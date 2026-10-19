# 安装与环境

[文档目录](README.md) · [首用教程](getting-started.md)

Ralf-Agent 需要 Python 3.11+。本地开发使用 Linux 或 macOS，CI 覆盖的 Python 版本与检查以[贡献指南](../CONTRIBUTING.md)和[工作流](../.github/workflows/ci.yml)为准。

## 从源码安装

```bash
git clone https://github.com/RalfNick/ralf-agent.git
cd ralf-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ralf --version
```

基础运行依赖为 `httpx` 和 `jsonschema`。默认 SQLite、离线 Demo 与独立 starter 不需要模型密钥或外部服务。安装后按[首用教程](getting-started.md)完成提交、审批与恢复。

上面的 clone 命令演示源码安装方式，不保证远端已包含本地候选版本。本轮 dev121 尚未推送／公开发布；要复现本轮交付请使用下方精确 wheel，或当前对应的本地源码，并核对 `ralf --version`。

## 从本地 wheel 安装

在独立虚拟环境中，把占位路径替换为实际制品路径：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0.dev121-py3-none-any.whl"
ralf --version
ralf init my-agent
```

当前推荐 dev121 的 Local 基础 SDK 本地制品，目录及 SHA 校验见[发布指南](releasing.md#本轮本地交付)。旧 dev120 各目录属于历史候选，不要仅按同名 wheel 选择。本项目文档尚未核验公开 PyPI／GitHub Release 中的对应发行包，推荐使用源码或明确获得的 wheel。wheel 包含独立工程生成器，仓库 `examples/` 通过源码获取。

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
