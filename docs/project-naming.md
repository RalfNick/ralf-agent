# 项目名称与兼容边界

当前展示名称为 **Relf-Agent**，原名 **Ralf-Agent**。

**Reliable and Extensible Lifecycle Framework for Intelligent Agents**：可靠、可扩展的智能体全生命周期框架。

对外定位：**灵活构建智能体，可靠运行智能应用。** “智能”涵盖已有模型推理、规划、记忆与成员协作；“可扩展”指各层的组件替换与组合；“可靠”指执行、审批、持久化和恢复。名称不扩大支持承诺，实际范围见[实现清单](implementation-status.md)。

## 展示名称与技术标识

| 用途 | 当前使用 |
| --- | --- |
| 项目、官网和当前文档的展示名称 | `Relf-Agent` |
| Python 发行包名 | `ralf-agent` |
| Python 导入路径 | `ralf_agent` |
| CLI 及相关子工具前缀 | `ralf`、`ralf-*` |
| 仓库及 Issues、Release 地址 | `https://github.com/RalfNick/ralf-agent` |
| 环境变量、默认目录及配置字段 | 原 `RALF_*`、`.ralf` 等标识 |

本次只更新品牌，不提供 `relf` 命令、`relf_agent` 导入或同名安装包。继续按[安装指南](installation.md)使用已验证的精确制品；PyPI 尚未发布。CLI 版本输出、旧模板或固定源码中出现 Ralf-Agent 属于原 SDK 的实际输出。

## 历史与恢复

已发布的 `0.1.0a2` wheel、sdist、校验摘要及 Tag 保持不变。数据库表、Session／Action 身份、Temporal Workflow／Activity 名称、patch 标识、组件指纹与旧 Worker 匹配规则不随品牌替换。恢复仍需原配置与匹配组件，不能通过改名清除未知业务效果。

历史架构、计划、审查和发布记录保留当时的名称、结果与失败；原 LICENSE／NOTICE 及版权归属保持。将来若迁移包名、CLI 或导入路径，需要独立版本、兼容入口和恢复验收，本次不承诺这些入口已实现。

官网采用新展示名称，教程仍明确标注各自的 SDK 版本及固定来源。品牌更新不代表教程基线、产品字节或能力验收发生变化。
