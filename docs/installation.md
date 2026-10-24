# 安装与环境

需要Python3.11+。默认本地SDK使用SQLite，不要求Redis、PostgreSQL、Temporal、Docker或模型凭据。完整能力、可选依赖及平台资格分别验收，见[当前支持](implementation-status.md)。

## 当前 a7 源码或本地原包

`relf-agent==0.1.0a7`沿用 `relf_agent` 导入与 `relf`／`relf-*` 命令，包含 `2d17808` 的装配中断清理修复。原包、精确SHA、本地及外部待办见[a7 说明](releases/0.1.0a7.md)和[a7 清单](alpha7-validation-status.md)。未验证的PyPI／远端安装不作为已交付入口。

在**包含 a7的源码目录**创建新环境：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -c 'import relf_agent; print(relf_agent.__version__)'
relf --version
```

维护者也可以安装精确的本地原wheel：

```bash
python3.12 -m venv /tmp/relf-a7
source /tmp/relf-a7/bin/activate
python -m pip install /ABS/relf_agent-0.1.0a7-py3-none-any.whl
python -m pip show relf-agent
python -m pip check
python -m relf_agent --version
relf --version
```

预期版本`0.1.0a7`，CLI显示`Relf-Agent 0.1.0a7`。`pip show`检查的是发行名`relf-agent`，Python导入检查的是`relf_agent`，两者用途不同。新包不提供`ralf_agent`和`ralf`别名。

安装后按[首用教程](getting-started.md)生成自己的工程，再用[连续教程](support-journey.md)逐步接入Session、RAG、记忆和Workflow。wheel包含生成器，仓库`examples/`从源码或sdist获取。

## 可选能力

从当前源码安装可使用`python -m pip install -e '.[pdf,tokenizer]'`；从已核对的本地wheel安装extra可使用`python -m pip install '/ABS/relf_agent-0.1.0a7-py3-none-any.whl[pdf,tokenizer]'`。发布后才使用相应索引的`relf-agent[extra]`并独立验证。

| extra | 用途 |
| --- | --- |
| `pdf` | 受限文本PDF解析 |
| `tokenizer` | tiktoken协议计量 |
| `skills` | YAML Skill文档 |
| `redis`／`postgres`／`remote` | 对应远程数据适配 |
| `temporal` | Temporal执行与对应存储依赖 |
| `server` | HTTP服务运行 |
| `dev` | 本地开发、构建和测试工具 |

extra只是依赖选择，不等于某个服务组合已经验收。`RALF_*`配置、`.ralf`数据目录与现有协议名保持。

<a id="从公开-alpha-安装"></a>

## 历史公开 a2 及原 a3–a6

原公开a2下载地址和SHA保持，其导入是`ralf_agent`、CLI是`ralf`：

```bash
python -m pip install 'https://github.com/RalfNick/relf-agent/releases/download/v0.1.0a2/ralf_agent-0.1.0a2-py3-none-any.whl#sha256=dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46'
ralf --version
```

原 a6 已使用新导入和 CLI，但不含本次中断清理修复；其[原包和验收](releases/0.1.0a6.md)保持，不能以 a6 成绩放行 a7。

这组命令只在独立旧环境使用，配合[a2原说明](releases/0.1.0a2.md)，不要接着运行上文 a7 示例。原a3／a4的发行名也是`ralf-agent`；a5发行名已为`relf-agent`，但仍是旧导入与旧CLI。旧任务必须保留原环境和匹配Worker；原包／验收不回写，不自动迁移History、未知效果或指纹。详见[名称边界](project-naming.md)。

## 排障

| 现象 | 检查 |
| --- | --- |
| 找不到`relf` | 激活a7 环境，执行`python -m pip show relf-agent`核对位置及版本 |
| `import relf_agent`失败 | 是否实际安装了a5或更早包，是否使用另一个Python环境 |
| 只有`ralf`能运行 | 当前是旧SDK环境，不要以别名掩盖版本差异 |
| 缺少可选依赖 | 为同一a7 环境安装对应extra，参照专题能力边界 |
| 原Run提示定义／绑定不匹配 | 保留旧版本、旧定义和组件，按[恢复指南](recovery-guide.md)核对，不清除身份检查 |
