# Relf a6 双语网站文档验收

日期：2026-10-23（Asia/Shanghai）。实现提交：`29c0c87202a0c23086a28e9070b54531762e240c`。

## 范围与版本

官网的 14 组中英文指南、首页命令、演示 Run ID 和共享版本说明统一到 Relf。教程固定公开源码 `ba1c81fca67e15e70c1d51d0f4ecbbbcbbb37239`，SDK `0.1.0a6`，发行／导入／命令分别为 `relf-agent`、`relf_agent`、`relf`／`relf-*`。安装使用固定源码和独立虚拟环境，不把源码候选写成已公开发行的 PyPI／GitHub 包。

真实 SDK 标识 `RalfError`、默认 `.ralf` 数据目录、`RalfNick` 仓库账号、现有 Cloudflare Worker `ralf-agent-website` 与历史制品记录保留。旧 Run、History 和函数身份没有自动迁移承诺。其他 SDK CI 待办不在此次网站变更范围内。

## 本地检查与教程闭环

- 隔离 Python 3.12 环境安装固定 a6 源码，`relf --version` 显示 `Relf-Agent 0.1.0a6`；8 个 CLI 的 `--help` 和 `pip check` 通过。
- 中英文直接执行文档代码块：审批首用、独立进程检查／批准／恢复、重复取回原 Run、CLI 与 SDK 持久输入、模型转结构化 Schema 的新请求身份、Session 连续对话与重放、Hybrid 离线示例、五阶段 support 应用及其 inspect／events。
- 两种语言的四组离线任务评估均验证 `status=completed`、`passed=total`、调用数及 `model_quality=null`：business 8/8、15 calls；RAG 8/8、8 calls；Plan 和 Team 各 5/5、17 calls。
- 教程子进程不继承模型凭据；在线 Provider／Embedding 示例未执行，模型示例用确定性 Provider 替代，不能据此声明线上模型质量。
- 完整 `npm run verify:production` 通过：静态检查 0 errors／warnings／hints、25 项测试、14 对双语来源快照、32 个构建页面、1,927 个本地链接／资源目标、49 个远端源码目标、双语 Pagefind 索引与 Wrangler dry run。
- 复核修复后重复双语教程验证及 25 项网站测试、Ruff，均通过。所有 43 个技术来源文件与固定源码一致；构建安装／概览／快速开始页面版本和入口检查通过。

独立只读复审发现一项 P2：原评估验证只解析报告，可能把退出码为 0 的 `not_run` 报告当成成功。已补齐完成状态、总数、通过数、调用数和质量字段断言。以真实无配置 evaluator 生成 `not_run` 报告验证：旧 JSON-only 逻辑错误接受，新逻辑拒绝；实际离线评估仍全部通过。复审无其他可操作发现。

本地浏览器对新构建首次查询 `relf_agent`，中文返回 13 条、英文返回 9 条结果，无需重试；安装页中英文切换保留当前主题。

## 自动发布与线上验收

Cloudflare 的源码监视路径已保存为 `src/relf_agent/*`，与 a6 实际目录及 GitHub Website 工作流一致；其余连接参数和发布权限沿用现有配置。实现提交通过 Git push 触发自动构建，未手工上传 `dist/`。

GitHub [Website CI](https://github.com/RalfNick/relf-agent/actions/runs/39973166113) 已通过，完整日志确认 25 项测试、双语 a6 教程、14 对文档来源、32 页构建、1,927 个本地目标、49 个远端源码链接和 dry run 全部成功。

Cloudflare 构建 [`88d32f30-ff86-47f3-a62b-761951eb7d57`](https://dash.cloudflare.com/6fcab8530fe6ef0b32741fbf005326ce/workers/services/view/ralf-agent-website/production/builds/88d32f30-ff86-47f3-a62b-761951eb7d57) 已由同一提交自动触发并于北京时间 **23:01:56** 成功完成，历时 10m48s；其中 Python 环境安装 5m44s。生产版本为 `d29693bb-6a18-4ced-ab9b-810ecd95d0ad`。


发布后 [95 项 HTTP 验收明细](2026-10-23-relf-a6-http-checks.json) 全部首次通过，0 失败：

| 检查 | 结果 |
| --- | --- |
| 根入口、双语首页和 28 篇文档 | HTTP 200，与 Cloudflare 同一次构建的 HTML SHA-256 一致 |
| 样式、脚本、图片、双语搜索索引、WASM、片段、robots、sitemap | HTTP 200，与同次构建内容一致；连同页面共 84 个文件 |
| HTTP 主域／HTTP www／HTTPS www 各三种路径 | 9 组全部 301 到 HTTPS 主域，保留路径和查询参数 |
| TLS | 默认 Node fetch 证书及主机名校验通过 |
| 自定义缺失页和无末尾斜杠文档 | 404 正文与产物一致；英文 quickstart 307 到规范斜杠路径 |

线上 Chrome 新页面的首次查询也通过：中文安装页打开搜索、在初始化期间输入 `relf_agent`，自动显示 13 条中文结果；从结果进入快速开始成功，显示固定 a6 的 `relf --version`、init、approve、resume 命令。切到同主题英文页，首次加载时输入相同关键词，自动返回 9 条英文结果，随后可切回中文原主题。两种语言均无需重试；未全局清空浏览器缓存。

本次沿用 main 的自动发布，代码完整落在一个实现提交；本记录与计划勾选以独立证据提交补录，并使用 `[skip ci]` 避免再次构建相同站点。没有发布 SDK 包，没有处理或关闭其他 SDK CI 待办。
