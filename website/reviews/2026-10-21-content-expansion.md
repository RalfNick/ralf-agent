# 官网能力与文档补充

用户授权：在已优化的网站上进一步丰富文档和能力说明，中英文沿用同步维护。

本轮选择：保留 Astro、深蓝青色视觉、前置审批演示与离线主 CTA。将精选指南从六组扩展为十组，新增能力总览、会话／记忆／RAG、集成扩展、运行部署；补充现有概念、模型工具、编排及排障。首页展示六类能力和实际用途，精选入口保持六个，文档目录按起步、构建、运行分组。仅修改 website，不部署，不改 SDK、名称或其他进行中的工作。

内容依据来自仓库既有技术指南与实现。区分默认 Local 基础路径和需要显式配置的实验性组件，不将已有适配器写成全协议／全后端可用，不把离线结果写成真实模型质量。新增可执行命令优先使用已有 starter 和连续工单示例。

验证计划：检查双语主题／来源／链接完整性；执行新增离线路径及代码示例；网站类型、状态测试、源哈希及构建检查；浏览器检查文档导航、新主题搜索、语言切换与手机长内容布局，最后做独立内容复核。

## 已完成内容

- 新增四组双语指南：能力总览、会话／记忆／RAG、集成与扩展、运行与部署。包括任务选型表、组件关系、三条学习路径、模型协议选择、摄取与检索、Local／Temporal 区别、配置与资源生命周期。
- 扩充原指南：Agent／Runtime／Engine 入口、命令与效果身份、工具往返与输出 Schema、业务完成验证、图节点选择、Team 策略、计划修订、并发额度和按错误码排障。
- 首页六类能力分别解释功能、典型用途和文档入口。精选文档保持六个入口；完整十主题由总览和分组目录承接。主 CTA、首屏定位与前置审批演示继续保留。
- 文档导航分为“开始使用／构建能力／运行与维护”；移动端同步，编号正确显示到 10，语言切换保留当前专题。页头文档入口和文内面包屑进入能力总览。
- 更新文档来源快照、构建必备主题列表、README 页面与维护说明；未改 Python SDK、命名或其他任务的工作文件，未部署。

## 实际验证

使用当前本地 SDK 在独立临时目录生成项目，无模型凭据或在线模型调用：

| 路径 | 结果 |
| --- | --- |
| RAG starter | Postgres 查询返回 grounded=true、文档版本／来源／摘录；无证据查询 grounded=false、空引用与拒答 |
| Ingest starter | 示例 Markdown 原子摄取 knowledge_committed，查询返回原文与 version=1 引用 |
| Config starter | 即时执行 succeeded；submit-only 后 inspect 为 queued，再 resume 为 succeeded |
| Session 连续工单 | 两个独立进程的 Turn 均 succeeded，第二轮 session_records=1 |
| Facts 连续工单 | 保存并召回 response-style=concise，同时保留知识来源 |
| MCP starter | 本地真实子进程工具 waiting_approval；按 inspect 输出批准，另进程 resume 后 succeeded；重复提交保留原 Run |
| 新增 Python／TOML 片段 | 两种语言的 AgentSpec 输出 Schema 实际构造成功，基础 Profile TOML 解析成功 |

网站检查：`npm test` 5／5；Astro 检查 23 文件，0 errors／warnings／hints；来源同步检查 10 组双语指南；静态构建 24 页、20 篇搜索文档，1129 个本地链接／资源与锚点检查通过。每种语言仍为单查询分块，原搜索就绪检查约束成立。Cloudflare 静态资源 dry run 通过，没有上传或发布。

浏览器：1728px 桌面检查六类能力、分组侧栏及十个主题；390px 中文首页／长文和 320px 英文文档／移动目录／搜索没有整页横向溢出。代码保留 12px 并独立横向滚动；移动文档链接最小高度 44px。中文 MCP 搜索返回集成等新增主题；英文 embeddings 搜索首项为会话记忆专题，结果均为英文路径。语言切换保留 sessions-memory 路径，移动主导航可进入能力总览。

## 独立复审

独立只读 reviewer 对照 frontmatter 技术源逐项审阅双语说明、API／CLI 示例和导航。发现 MCP 示例的 inspect 未带原工厂，会输出 YOUR_MODULE 占位批准命令；已在中英文补充 `--factory agent_app.runtime:create_engine`，并实际执行修正后的批准／恢复。最终结论：**没有剩余 P1／P2 发现**。

验证限于当前源码与本地离线装配，不新增在线模型、远程数据库、Docker 或 Temporal 验收结论；这些能力按专题说明及原支持记录使用。

![新增能力说明](/Users/bytedance/.codex/visualizations/2026/10/20/01a157d4-e552-73d1-96fe-96d8e01a82f0/ralf-agent-capabilities-expanded.png)

![分组文档与能力总览](/Users/bytedance/.codex/visualizations/2026/10/20/01a157d4-e552-73d1-96fe-96d8e01a82f0/ralf-agent-docs-expanded.png)
