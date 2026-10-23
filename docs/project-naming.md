# 项目名称与兼容边界

当前展示名称为 **Relf-Agent**，原名 **Ralf-Agent**。

**Reliable and Extensible Lifecycle Framework for Intelligent Agents**：可靠、可扩展的智能体全生命周期框架。

对外定位：**灵活构建智能体，可靠运行智能应用。** “智能”涵盖已有模型推理、规划、记忆与成员协作；“可扩展”指各层的组件替换与组合；“可靠”指执行、审批、持久化和恢复。名称不扩大支持承诺，实际范围见[实现清单](implementation-status.md)。

## 展示名称与技术标识

| 用途 | 当前使用 |
| --- | --- |
| 项目、官网和当前文档的展示名称 | `Relf-Agent` |
| Python 发行包名 | a5起 `relf-agent`；a2／a3／a4原包为 `ralf-agent` |
| Python 导入路径 | `ralf_agent` |
| CLI 及相关子工具前缀 | `ralf`、`ralf-*` |
| 仓库及 Issues、Release 地址 | `https://github.com/RalfNick/relf-agent` |
| 环境变量、默认目录及配置字段 | 原 `RALF_*`、`.ralf` 等标识 |

a5将发行名统一为`relf-agent`，保留`ralf_agent`导入和`ralf`／`ralf-*`命令，不新增`relf_agent`导入或`relf`命令。请按[安装指南](installation.md)使用精确制品；PyPI公开安装尚待单独验收。旧版本输出、包名和固定教程保留当时实际身份。

a3／a4只更换展示品牌与仓库地址，原发行名仍为`ralf-agent`；其原包不回写。a5是独立改名候选，新的元数据、归档与发布校验使用`relf-agent`，账号及后续发布见[PyPI准备](pypi-publishing.md)。

两个发行项目共享`ralf_agent`文件树与`ralf`入口，不能在同一虚拟环境并存。发行名不同，pip不会把它们自动视为同一项目升级；新a5使用独立环境安装，旧任务保留原环境、配置和匹配Worker，不通过卸载或改名迁移恢复状态。

## 历史与恢复

已发布的 `0.1.0a2` wheel、sdist、校验摘要及 Tag 保持不变。数据库表、Session／Action 身份、Temporal Workflow／Activity 名称、patch 标识、组件指纹与旧 Worker 匹配规则不随品牌替换。恢复仍需原配置与匹配组件，不能通过改名清除未知业务效果。

历史架构、计划、审查和发布记录保留当时的名称、结果与失败；原 LICENSE／NOTICE 及版权归属保持。本次仅迁移发行名；CLI、导入路径及执行协议标识不更换。历史Run与Worker的兼容性仍需对应版本与环境证据，改名不提供自动迁移。

官网采用新展示名称，教程仍明确标注各自的 SDK 版本及固定来源。品牌更新不代表教程基线、产品字节或能力验收发生变化。
