# 官网文档闭环修复与最终复审

用户授权：处理 [全站审阅](/Users/bytedance/Codex-Projects/ralf-agent/website/reviews/2026-10-21-full-site-docs-audit.md) 的全部 P1、P2、P3，中英文同步完善教程、API 和测试评估入口，完成后再完整复审。

完成结果：原六项问题均已处理。当前为 **14 组双语指南、28 篇文档、32 个静态页面**。已完成独立全站复审和本地浏览器验收，复审发现的一项语言标注问题也已修正并复核；本轮范围内没有剩余可操作的 P1/P2/P3。

## 原问题逐项关闭

| 原级别与问题 | 实现与验收 |
| --- | --- |
| P1：不存在的 main 引用 | `repository.json` 固定已发布提交 `0b9b6c9682c40285d91994cd831aa93d7e814bf1`、SDK `0.1.0a1` 与验证日期；组件和 `repo:` Markdown 链接使用同一个构造器。只读核验其属于 GitHub 远端 HEAD 历史，构建逐个检查 48 个不同仓库目标在该 Git tree 中存在。移除未发布的“编辑本页”。 |
| P2：AgentSpec 与会话入口混用 | 模型页使用 `spec`；会话页完整创建 `Agent`、异步入口和 owned Runtime。两种语言的 Session 文件均能独立运行并重放，连续教程另行验证跨进程 Turn。 |
| P2：遗漏持久用户输入 | 新增双语 `user-input`：初始化、等待、inspect、定向回复、resume、结果和回执重放；说明 Schema、digest、拒绝、Session busy 和子任务 owner。能力总览、首页说明、恢复状态表、编排和 API 页面均有相应入口。 |
| P2：英文进阶路径依赖中文资料 | 新增站内双语连续应用教程；模型、Session、混合检索和 Facts 路径具备本地命令及预期结果。所有关键操作均可由英文页面完成；可选中文仓库资料明确标注语言。 |
| P3：修改输出 Schema 后复用 command_id | 两种语言要求换成 `request-structured-001`，解释新定义／新请求与保留历史数据库。离线验证原请求重放保持 Run ID，换 Schema 和新 ID 创建另一 Run 并成功。 |
| P3：API 与测试评估入口不足 | 新增双语 API/CLI Reference 与 Testing/Evaluation：常用签名、默认值、返回类型、控制语义、资源归属、错误、完整离线工具循环测试、兼容探针和业务／RAG／Plan／Team／规划提案评估。页脚与分组目录提供直接入口。 |

文档页显示 SDK 版本、已验证日期与源码提交。安装、快速开始和首页代码固定到同一基线；来源快照同时记录该基线，教程中的 Git 引用不一致会使检查失败。运行页增加 Local、真实服务、远程存储和 Temporal 的支持／验证边界表。

## 操作闭环

- **模型与工具：** 保存完整文件 → 执行 → 检查状态和工具回执 → 修改输出 Schema → 使用新命令身份 → 保留旧记录。真实模型示例仅用替代离线 Provider 验证装配，未调用供应商。
- **Session：** 创建 Agent → 打开 Session → 等待首轮 → 有界确认空闲 → 下一轮 → 原样重放；完整应用另验证两个独立进程中的历史进入上下文。
- **输入：** 生成已安装 starter → 原 Run 等待问题 → inspect 读取 Schema/ID/digest → JSON 回复 → 显式 resume → 结果 → 相同回复回读原回执。错误值、改值复用 ID、终态迟到回复均有实际验证和下一步说明。
- **知识：** 自备 Markdown → 原子摄取 → 显式索引 → 混合查询 → 版本／来源与 grounded 结果；说明散列 Embedding 仅是词法基线、更新后需要重新索引。另提供显式真实 Embedding 探针和装配规则，未执行在线探针。
- **连续应用：** 固定提交获取单文件 → Agent → 可选真实模型 → 跨进程 Session → 本地 RAG → 显式 Facts → 顺序 Workflow → 查询、重启与定制。各阶段独立数据库，避免新定义冒充旧任务恢复。
- **开发验证：** 完整无网络应用测试 → 模型协议检查 → 独立业务／RAG／编排任务 oracle → 可选真实模型质量评估。离线结果始终保留 `model_quality: null`。

## 搜索与构建的附带修复

新增资料使 Pagefind 每种语言从一个查询分块增长到两个，原单块保护正确拦截了第一次构建。未放宽后直接发布：核对 Pagefind 1.5.2 的实际代码后，增加一个严格匹配的构建补丁，将主线程和 Worker 的分块加载 catch 改为重新抛出，交由现有 UI 显示重试。上游版本或匹配位置变化会中止构建；单元测试验证成功、失败和上游变化，浏览器验证分块与结果片段失败后恢复、保留查询并重试。

Markdown 链接转换使用 Astro 7 原生 Sätteri 的不可变节点访问接口，固定其已有处理器依赖版本，未引入旧版 remark 处理器。仓库链接校验与教程验证加入现有网站 CI，CI 使用完整 Git 历史和 Python 环境；本轮未触发远端 CI。

Pagefind 的分块与 preload 用法参见[官方 API 文档](https://pagefind.app/docs/api/)；具体错误传播结论来自本地锁定版本源码和故障验证。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| `npm test`，Node 24.19.0 | 11/11 通过；包括真实 Markdown 链接渲染、未发布目标拒绝和分块错误传播 |
| `npm run check` | 28 文件，0 errors／warnings／hints |
| `npm run docs:check` | 14 组双语与已审阅来源及基线一致 |
| `scripts/check-tutorials.py` | 临时导出已发布 SDK，两种语言的模型→Schema 身份与重放、Session、离线应用测试、输入 SDK、混合检索均通过 |
| 新指南字面命令 | 双语输入 starter、全部连续应用离线步骤、模型检查 starter 和评估命令通过；代码块一致，API 片段仅注释语言不同 |
| 既有示例回归 | 独立 reviewer 复跑 Team、Graph／Config 提交→延后执行→CLI resume，通过 |
| 模型协议离线检查 | 5/5，6 次离线调用 |
| 业务／RAG 评估 | 8/8／8/8；15／8 次离线调用 |
| Plan／Team 评估 | 各 5/5，各 17 次离线调用 |
| 规划提案 fixture | 3/3，3 次离线调用；不执行提案中的业务 Worker |
| 最终全新静态构建 | 32 页、28 篇搜索文档、双语索引，1925 个本地链接／资源／锚点通过 |
| 仓库链接 | 48 个不同发布目标通过；GitHub 远端提交历史只读验证通过 |
| Cloudflare | 最新产物 `wrangler deploy --dry-run` 通过，未上传或部署 |
| HTTP 路由 | 中文连续教程与英文测试页 200；未知路径 404 |

浏览器验收包括：首页审批→模拟宿主重启→恢复→succeeded，原 Run／Action／digest 保持一致；中文 `send_input` 与英文 evaluation 搜索；结果进入新主题、同主题语言切换；英文分块和结果片段 404 故障后的失败提示与恢复重试。390px 英文长文和 API 表格、320px 中文 API 页面均无整页横向溢出，移动目录含 14 主题，代码 12px 并独立滚动。所有临时故障资产已恢复，视口已还原。

教程／评估证据保留于本轮临时目录：输入和连续应用 `/var/folders/22/3kpt4wq55234j3tf77xs091w0000gn/T/ralf-docs-input-b3a6fiyx/`；API 和评估 `/tmp/ralf-api-docs-zekww4m_/exact-commands/`。可重复的核心教程检查已保存进网站脚本。

## 最终独立复审

只读 reviewer 审阅双语首页、全部 28 篇指南、导航和模板、链接转换与校验、教程脚本、搜索错误保护和 CI；使用发布基线核对选定 API/CLI 的签名、默认值、所有权及恢复语义，没有依赖本地更新版 SDK 的新能力。

复审提出一项 P3：四个英文正文链接未标明 `implementation-status.md` 主体为中文。已统一增加语言标注，reviewer 再读确认关闭。最终结论：**原六项问题已解决，当前范围没有剩余可操作的 P1/P2/P3**。

验证范围仍为文档、固定 SDK 的离线执行和本地静态网站；没有新增真实付费模型／Embedding、Temporal 服务、远程数据库或 Docker 的在线资格。本轮未改 SDK 实现、项目名称或其他任务的工作文件，未提交、推送或部署。

![新版 API 参考与文档导航](/Users/bytedance/.codex/visualizations/2026/10/20/01a157d4-e552-73d1-96fe-96d8e01a82f0/ralf-agent-docs-api-closure.png)
