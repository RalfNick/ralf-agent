# 项目名称与兼容边界

当前展示名称为 **Relf-Agent**，原名 **Ralf-Agent**。

**Reliable and Extensible Lifecycle Framework for Intelligent Agents**：可靠、可扩展的智能体全生命周期框架。对外定位：**灵活构建智能体，可靠运行智能应用。** 名称不扩大支持承诺，实际范围见[实现清单](implementation-status.md)。

## 当前公共入口

| 用途 | a6起使用 |
| --- | --- |
| Python发行名／安装名 | `relf-agent` |
| Python导入 | `relf_agent`，例如`from relf_agent import Agent, AgentSpec` |
| CLI及相关工具 | `relf`、`relf-check-model`、`relf-check-adapter`、`relf-evaluate-*`、`relf-watch-events` |
| Python模块入口 | `python -m relf_agent` |
| 仓库与官网 | `https://github.com/RalfNick/relf-agent`、`https://relfagent.com` |
| 保持的配置及数据标识 | `RALF_*`、`.ralf`、原数据库／Schema／RPC字段和Workflow／Activity名称 |

这是公共Python包和命令入口的迁移，未添加第二套执行实现或`ralf_agent`兼容shim，也不注册旧`ralf`命令。公开类和函数名称保持，例如异常类仍为`RalfError`。安装位置、生成starter和可执行操作提示都使用新入口。

## 原版本与迁移

| 原包范围 | 发行名 | Python导入 | CLI |
| --- | --- | --- | --- |
| a1–a4 | `ralf-agent` | `ralf_agent` | `ralf`／`ralf-*` |
| a5 | `relf-agent` | `ralf_agent` | `ralf`／`ralf-*` |
| a6起 | `relf-agent` | `relf_agent` | `relf`／`relf-*` |

a5和a6的发行名及归档前缀相同，Python模块与CLI却不同，因此新manifest同时固定`distribution_name`、`python_module`与`cli_name`；旧manifest缺省继续解释为旧入口。不要通过包文件名猜测导入或命令。

为a6创建独立虚拟环境和新任务数据；将应用的`from ralf_agent ...`／`import ralf_agent`、`python -m ralf_agent`及命令脚本分别改为`relf_agent`、`python -m relf_agent`和`relf`。相关工具命令同步改为`relf-*`。可选依赖仍使用`relf-agent[extra]`，环境变量不用改名。详见[安装指南](installation.md)。

旧任务、未知效果、待审批Run和Temporal History保留原SDK环境、定义、配置、组件与Worker，不通过升级、卸载或改名继续运行。模块名称参与组件／函数身份，改名会产生新的身份；保留匹配规则不等于旧指纹仍相同，不提供自动状态或History迁移。新旧发行不要混装或互相卸载。

## 历史证据

原a2／a3／a4／a5制品、校验和、Tag、审查与验收文档保持原字节和当时命名。旧包成绩不放行a6；新包各范围需自己的实际记录。原LICENSE／NOTICE和归属信息保持。

官网固定a1教程仍使用其真实的旧导入和命令，并显式标注版本；当前a6入口与那些历史示例不混用。网站改文案不代表已经部署或迁移其SDK基线。
