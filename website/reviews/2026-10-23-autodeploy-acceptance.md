# Relf-Agent 自动部署与整站验收

日期：2026-10-23（Asia/Shanghai）。主站：[relfagent.com](https://relfagent.com/)。

## 结论与发布证据

自动部署已跑通。`main` 的相关变更会自动执行检查、构建、Cloudflare 发布和发布后的公网验收。

| 阶段 | 源码提交 | Cloudflare 构建 | 结果 |
| --- | --- | --- | --- |
| 首次通过 Git 推送触发正式发布 | `59a7b9b` | `32066289-4714-4ceb-86fd-cd13035086de` | 成功 |
| 修复加载期间不能输入关键词 | `55a4c2e` | `c049b1ff-39b7-4711-9d7f-996ce6505a2a` | 成功 |
| 加入发布后的完整 HTTP 验收 | `732a9655a75db118a1867c0d3035ab195b86b7fd` | [`26e22af4-3a4a-4746-9afa-ab7e87d1ab65`](https://dash.cloudflare.com/6fcab8530fe6ef0b32741fbf005326ce/workers/services/view/ralf-agent-website/production/builds/26e22af4-3a4a-4746-9afa-ab7e87d1ab65) | 成功，95 项全部首次通过 |

完整验收基线为 `732a965`，生产 Worker 为 `ralf-agent-website`，发布版本为 `fa6cb1ef-ad5a-46d1-a294-097d61799f99`。公网验收开始时间为北京时间 **11:45:43**，随后全部通过。GitHub 的独立 [Website 工作流](https://github.com/RalfNick/relf-agent/actions/runs/39896440563)同样通过。

## 自动发布配置

- 仓库：`RalfNick/relf-agent`；生产分支：`main`；根目录：`website`。
- 构建命令：`bash scripts/cloudflare-build.sh`。
- 部署命令：`npx wrangler deploy && npm run cf:verify-live`。
- 构建变量：`PUBLIC_SITE_URL=https://relfagent.com`、`SKIP_DEPENDENCY_INSTALL=1`。
- Node 24 与 Python 3.12.7 由版本文件选择；SDK 教程继续使用固定的公开 a1 基线。
- Cloudflare 监视路径：`website/*`、`docs/*`、`src/ralf_agent/*`、`pyproject.toml`、`README.md`、`.github/workflows/website.yml`。
- 预览分支构建关闭；PR／非 main 分支只由 GitHub Actions 检查。
- GitHub 应用仅新增目标仓库的访问权限；发布令牌由 Cloudflare 管理，未写入代码或 GitHub Secrets。

发布前检查共用 `npm run verify:production`：静态检查、单元测试、双语文档快照、离线教程、Astro／Pagefind 构建、公开源码链接及 Wrangler dry run。任何一步失败均不会进入部署；正式 origin 缺失或不匹配也会提前失败。

发布后的 `cf:verify-live` 使用默认 TLS 校验、有限并发、20 秒请求预算和最多三次尝试。它核对刚发布的同一次 `dist/`，记录每项状态与内容 SHA-256；失败时构建退出非零。发布后检查失败时站点已经上传，需根据日志处理或回滚，当前流程不自动回滚。

## 公网 HTTP 验收

逐项结果见 [HTTP 验收明细](2026-10-23-autodeploy-http-checks.json)，由 Cloudflare 构建日志中的实际结果整理，未将中断的本机扫描记为通过。

| 项目 | 结果 |
| --- | --- |
| 根入口、中文／英文首页、28 篇双语文档，共 31 个有效 HTML 页面 | 全部 HTTP 200，SHA-256 与本次构建逐字节一致 |
| CSS、JS、图片、搜索索引、WASM、结果片段、robots 与 sitemap，共 53 个资源 | 全部 HTTP 200，SHA-256 与本次构建逐字节一致 |
| HTTP 主域、HTTP www、HTTPS www，各检查根路径及两条带查询参数的文档路径，共 9 组 | 全部 301，目标为 HTTPS 主域，完整保留路径与查询参数 |
| HTTPS 主域和 HTTPS www 的请求 | 默认 Node fetch 证书与主机名校验通过 |
| `/__deployment_acceptance_missing__/` | HTTP 404，正文与构建的自定义 404 完全一致 |
| `/en/docs/quickstart` | 跳转至 `/en/docs/quickstart/` |
| 正式站 SEO 元数据 | 正式 canonical、双语 hreflang、robots 与 sitemap 随构建校验通过；404 保持 noindex |

总计 **95 项，0 失败，全部一次通过**。Pagefind 的分块和压缩产物可能随构建改变，因此验收比较 Cloudflare 本次发布的原始产物，避免与另一次本地构建的生成文件混比。

## 中文首次搜索与浏览器交互

本次修复了两个问题：原先首次初始化共用 12 秒预算，且加载期间输入框禁用。现在页面空闲或用户接近搜索入口时提前预热；打开弹窗与预热共享初始化，启动总预算为 30 秒，实际查询仍为 12 秒。加载期间可以立即输入，就绪后自动查询当前关键词。失败实例会清理，超时后的迟到响应不能覆盖新实例，重试保留关键词。

已验证：

- 正式中文首页第一次打开搜索，加载时立即输入 `send_input`，自动返回 3 条中文结果，无需重试。
- 正式中文 API 文档页重新初始化并查询“审批”，返回完整的 14 条中文结果，无需重试。
- 正式英文首页／文档页首次查询 `evaluation`，返回 10 条英文结果。
- 人为将首次 Pagefind 模块响应延迟 **13 秒**，中文输入框仍可立即输入；索引就绪后自动显示 `send_input` 的 3 条结果。
- 在独立本机服务中让首个结果片段请求返回 503，界面显示重试和文档入口；点击重试后重新初始化，保留 `send_input` 并恢复 3 条结果。
- `zzqvbxplmrk` 显示无结果提示；清空、Enter 提交、Esc 关闭、焦点返回和 Cmd+K 重新打开正常。
- 从搜索进入 API 文档成功；复制代码与页面代码一致；中英文切换保留 API 文档主题。
- 中文首页审批演示完成“批准 → 模拟宿主重启 → 恢复原任务”，原 Run 为 `succeeded`，示意写入次数为 1；随后已重置演示。

这是新页面／新实例的首次打开测试；浏览器缓存没有被全局清除。慢网络与失败恢复另外由受控的本机故障注入验证。

## 检查与复审

- 最终固定提交的完整生产门禁通过：25 项单元测试、静态检查 0 errors／warnings／hints、14 组双语文档源快照、双语离线教程、32 个构建页面、1,925 个本地链接／资源目标、48 个公开源码目标及 Wrangler dry run。
- 回归测试覆盖初始化合并、超过旧 12 秒预算、迟到模块、失败清理、重试、查询超时、生产 origin、检查失败提前终止，以及上线内容错误／跳转丢失参数／网络重试。
- 独立只读复审未发现搜索竞态或发布验收的 actionable 问题。
- 本机批量 curl 曾出现 TLS 握手和读取超时；正式 95 项 HTTP 验收在 Cloudflare 构建环境全部首次通过，本机 Chrome 的首次搜索和文档交互测试也均成功。两类证据分别保留，未将本地网络波动描述为已经修复的应用错误。

另有一个独立发现：仓库原有 `ci` 工作流的 SDK 测试矩阵在收集 Temporal 测试时缺少 `temporalio`，例如 [该次 SDK CI](https://github.com/RalfNick/relf-agent/actions/runs/39889955603)。本任务未修改 SDK 或该工作流；此项不属于通过的 Website 工作流和上述网站验收结论。
