# Relf-Agent website

独立的 Astro 静态官网。当前展示品牌为 **Relf-Agent**：**Reliable and Extensible Lifecycle Framework for Intelligent Agents**，可靠、可扩展的智能体全生命周期框架。定位：灵活构建智能体，可靠运行智能应用。

原项目名为Ralf-Agent，仓库为[RalfNick/relf-agent](https://github.com/RalfNick/relf-agent)。a6统一发行名`relf-agent`、导入`relf_agent`与命令`relf`／`relf-*`；a5及更早包继续使用原入口。本网站的可执行教程和首页安装演示仍明确固定原a1，使用其实际`ralf_agent`／`ralf`；公开a2、原a4／a5和当前a6分别验收。每页说明版本边界，不把新名字塞入原包命令。官网[relfagent.com](https://relfagent.com/)已上线，本批仅更新本地文案和验证，不部署、推送或公开发布SDK；Cloudflare资源名和历史记录保持。

首次手工上线的现场证据见[上线验收记录](reviews/2026-10-23-cloudflare-launch.md)及其 HTTP 明细。自动构建入口、检查门禁和 Cloudflare 连接参数见下方“自动构建与发布”；连接状态与实际发布结果以 Cloudflare 构建记录为准。

## 本地开发与预览

使用 Node 24 LTS（`.nvmrc`），在本目录执行：

```bash
nvm use
npm ci
npm run dev
```

开发地址以终端输出为准，默认 `http://127.0.0.1:4321/`。根路径与 `/zh/` 提供中文首页，`/en/` 提供英文首页。首页演示是固定数据状态机，刷新后重置，不调用 Python、模型或业务服务。

搜索索引在构建时生成。验收完整搜索与最终静态页面时使用：

```bash
npm run check
npm test
npm run docs:check
npm run docs:examples
npm run build
npm run docs:links -- --remote
npm run preview
```

Astro 7 的预览命令会输出预览进程状态与停止方式。查看或停止：

```bash
npx astro preview status
npx astro preview stop
```

`npm run build` 会输出 32 个页面（3 个首页入口、28 篇双语文档与 404），创建双语 Pagefind 搜索索引，检查本地链接、资源与页内锚点。十四组文档按“开始使用／构建能力／运行与维护／查询与验证”组织，包含连续应用教程、持久用户输入、API 与 CLI 参考、测试与评估。源码教程固定 a1；公开 a2 与 PyPI 未发布的状态分别说明。

## 域名与搜索引擎

未设置 `PUBLIC_SITE_URL` 时，HTML 为 `noindex, nofollow`，robots 禁止抓取，不输出 canonical 或 sitemap，适合当前本地预览。

官网已上线，主域名为 **`https://relfagent.com`**。中文入口为 `/zh/`，英文入口为 `/en/`，文档继续与官网部署在同一域名下。复制 `.env.example` 为 `.env` 并取消 `PUBLIC_SITE_URL` 的注释，重新构建。该值必须是 **HTTP(S) origin**（不带子路径、查询、凭据）。也可由 CI 构建环境传入：

```bash
PUBLIC_SITE_URL=https://relfagent.com npm run build
```

设置后生成 canonical、双语 hreflang、robots、sitemap 与 Open Graph 元数据；根路径的 canonical 指向 `/zh/`。404 保持 noindex。`public/og.png` 是分享图片，`public/og.svg` 保留可编辑矢量源。

## Cloudflare

采用 [Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/)，`wrangler.jsonc` 只托管 `dist/` 静态资源，无 Worker 业务代码、数据库或秘密绑定。目录式 URL 使用尾斜线，未知路径返回自定义 404；`public/_headers` 定义响应头与构建资产缓存。

官网已于 **2026-10-23** 首次通过 Cloudflare 控制台上传 `dist/` 上线，生产 Worker 为 `ralf-agent-website`。主域名为 [relfagent.com](https://relfagent.com/)，中英文入口分别为 [/zh/](https://relfagent.com/zh/) 和 [/en/](https://relfagent.com/en/)。同日已连接 Workers Builds，由 `main` 分支的网站相关更新触发检查、构建和发布；手工上传或 Wrangler 部署保留为维护方式。

区域内已配置以下跳转，均保留路径与查询字符串：

- `www.relfagent.com`：代理 A 记录 `192.0.2.0`，仅用于让流量进入 Cloudflare 重定向规则。
- 单一重定向 `Relf-Agent — HTTPS and www to apex`：匹配 `(http.host eq "www.relfagent.com") or (http.host eq "relfagent.com" and not ssl)`，动态目标 `concat("https://relfagent.com", http.request.uri.path)`，状态码 **301**，保留查询字符串。HTTPS 主域名不匹配该规则，避免循环。

DNS 和重定向规则由 Cloudflare 控制台维护；当前 Wrangler 文件只声明主域名的 Worker 绑定，不包含区域规则。迁移账户或重建区域时，需同时恢复以上配置。

本地验证与 Cloudflare 路由预览：

```bash
npm run build
npm run cf:check
npm run cf:dev
```

`cf:check` 是 `wrangler deploy --dry-run`，不会上传或部署。`cf:dev` 在本机模拟 Workers 静态资源路由，可验证真正的 404 状态。

`wrangler.jsonc` 已声明 `relfagent.com` 为 Worker 的 Custom Domain；资源名继续使用 `ralf-agent-website`，与展示品牌分开。该声明只在实际部署时生效，本地构建与 dry run 不会绑定域名或发布内容。

手工部署与线上核对流程：

1. 在 Cloudflare 确认 `relfagent.com` 已完成注册，并在域名概览中显示为活动。刚提交注册时成功页可能先于域名列表更新。
2. 在本目录执行 `PUBLIC_SITE_URL=https://relfagent.com npm run build` 和 `npm run cf:check`，检查正式地址元数据与静态资源。
3. 确认目标 Cloudflare 账户并获得发布授权后，执行 `npx wrangler deploy`。Custom Domain 会由 Cloudflare 创建所需 DNS 记录和证书，无需手工添加指向服务器的 A 记录；若已有同名 CNAME，应先核对其用途，避免覆盖已有服务。参见 [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)。
4. 验证 `https://relfagent.com/`、`/zh/`、`/en/`、两种语言的文档与搜索、`/robots.txt`、`/sitemap.xml`，以及不存在路径的 HTTP 404。证书签发和域名生效必须以公开访问结果为准。
5. 当前 `www.relfagent.com` 和HTTP入口已由Cloudflare区域规则301重定向至HTTPS根域，保留路径及查询参数，见上线记录。该DNS／重定向配置由控制台维护，不包含在当前Wrangler根域Worker绑定中；后续修改时参照 [www 到根域名的重定向](https://developers.cloudflare.com/rules/url-forwarding/examples/redirect-www-to-root/)核对已有用途。

### 自动构建与发布

GitHub Actions 与 Cloudflare 共用 `npm run verify`：静态检查 → 单元测试 → 双语源文档同步检查 → 固定 SDK 的离线教程 → Astro/Pagefind 构建 → 公开 GitHub 文档基线核验 → Wrangler dry run。任一步失败立即终止。`npm run verify:production` 额外要求 `PUBLIC_SITE_URL` 精确为 `https://relfagent.com`，避免正式站生成 noindex 或错误 canonical。

**现有** Worker 的 Settings → Build 已连接仓库，保存以下配置；实际发布是否完成，以构建记录为准：

| 配置项 | 值 |
| --- | --- |
| GitHub 仓库 | `RalfNick/relf-agent` |
| 生产分支 | `main` |
| 根目录 | `website` |
| 构建命令 | `bash scripts/cloudflare-build.sh` |
| 部署命令 | `npx wrangler deploy && npm run cf:verify-live` |
| 预览构建 | 关闭；PR 和非 main 分支由 GitHub Actions 检查，不发布生产站 |
| 构建变量 | `PUBLIC_SITE_URL=https://relfagent.com`、`SKIP_DEPENDENCY_INSTALL=1` |
| 运行时版本文件 | `.nvmrc` 为 Node 24，`.python-version` 为已验证的 Python 3.12.7 |
| 构建监视路径 | `website/*`、`docs/*`、`src/ralf_agent/*`、`pyproject.toml`、`README.md`、`.github/workflows/website.yml`（相对仓库根目录；Cloudflare 的 `*` 包含子目录路径） |

`cloudflare-build.sh` 补齐浅克隆历史，安装锁定的 Node 依赖，在独立 `.venv-build` 中安装 SDK 基础依赖，随后运行完整正式验证。Cloudflare 仅在构建命令成功后执行部署命令，上传这次验证生成的 `dist/`。无需在 GitHub 仓库中复制 Cloudflare Token；GitHub 应用仓库权限与 Workers Builds 使用的部署令牌在各自控制台管理。

发布成功后，`cf:verify-live` 使用默认 HTTPS 证书验证，逐项核对本次 `dist/` 的公开页面与资源 SHA-256，并检查自定义 404、尾斜线，以及保留路径和查询参数的 9 组 HTTP／www 跳转。检查采用有限并发和最多三次尝试，结果写入忽略的 `.wrangler/live-acceptance.json`，构建日志同时保留逐项结果。这样也能准确核验每次构建生成的 Pagefind 分块，避免跨构建比较其内容哈希。验收失败会使该次构建显示失败；此时站点已经发布，需根据日志处理故障或回滚到上一部署。

只将 `PUBLIC_SITE_URL` 设为 Worker 运行时变量不会改写静态 HTML，必须设置**构建变量**。独立预览构建不传该值，保持 noindex。GitHub Actions 只验证，共用检查入口；生产发布由 Workers Builds 负责。官网与 SDK 仍在同一仓库、独立部署；不需要另建网站仓库。

## 内容维护

- `src/components/Home.astro`：双语首页文案与 SDK 示例；Capabilities.astro 展示六类能力和用途。
- `src/content/guides/{zh,en}/`：十四组双语 Markdown 精选指南。
- `src/styles/`：共用视觉与文档样式；支持手机布局、键盘操作与 reduced motion。
- `src/lib/`：审批演示状态机、语言与 URL 元数据。
- `src/lib/site.ts` 的 `brand`：统一展示名、英文全称、中文含义与双语定位；不控制 SDK 或持久化身份。
- `docs-source-lock.json`：本轮审阅的指南与技术源文件哈希。

搜索通过 Pagefind API 显示当前语言的文档。页面空闲（最迟约 2 秒调度）及搜索入口的指针／键盘意图会提前预热；预热和打开弹窗共享一次初始化。加载期间即可输入或修改关键词，就绪后自动查询当前输入，不必等待输入框解锁。初始化总预算为 30 秒，实际查询预算仍为 12 秒。用正文中必有的“审批／approval”验证索引、WASM 和第一个结果片段，每次查询等待全部匹配片段；后台失败不打断页面，用户打开搜索后仍可明确重试。超时或失效的实例会清理，迟到响应不能恢复旧实例，重试会导入新的模块实例并保留关键词。

当前每种语言为两个查询分块。Pagefind 1.5.2 原实现会吞掉部分分块错误，因此 `scripts/strict-pagefind.mjs` 在构建时给主线程与 Worker 的同一个已知 catch 增加重新抛出，防止显示不完整结果。补丁只匹配一个准确位置，版本或实现变化会中止构建，必须重新审阅；单元测试与浏览器故障注入覆盖失败和重试。开发模式没有生成索引时显示重试与文档入口。

`repository.json` 集中记录 SDK 版本、已发布提交和验证日期。组件调用 `repositoryUrl()`，Markdown 使用 `[标题](repo:docs/example.md#section)`，由 Sätteri MDAST 插件转换；不要再写死分支。构建检查所有生成的仓库链接，使用固定 Git tree 确认目标存在，不显示未发布的“编辑本页”。`npm run docs:links -- --remote` 另外只读核验固定提交属于远端 HEAD 的历史，需要网络和对应 Git 对象；CI 使用完整 checkout。英文指向中文的可选资料标注语言，关键操作应提供站内双语路径。

修改仓库 URL 或 Markdown 链接转换配置后，先运行 `npm exec -- astro sync --force` 清除内容层缓存，再执行 `npm run build`。共享配置变化可能不会使已缓存的 Markdown 链接失效；构建检查会拒绝旧仓库地址，避免仅部分页面使用新链接。

`npm run docs:examples` 需要 Python 3.12 和 SDK 基础依赖（先在虚拟环境安装 SDK）。脚本在临时目录导出固定提交的 SDK，直接提取两种语言的教程代码，验证模型示例改输出 Schema 后的新命令身份、重放、Session、输入、离线应用测试和混合检索。真实模型示例只替换成确定性 Provider 验证装配；不会运行付费模型／Embedding 探针。完整连续应用和评估命令的本轮验证记录见 reviews。

修改技术源文档或任一翻译后，`npm run docs:check` 会提示需要同步。对照每篇 frontmatter 的 `sources` 审阅中英文，确认两者一致后记录并提交新快照：

```bash
node scripts/check-docs.mjs --record
npm run docs:check
```

哈希检查用于发现变更，不会自动判断翻译语义。新增主题时同时更新 `src/lib/site.ts`、两个语言目录与文档快照。

仓库的 `.github/workflows/website.yml` 覆盖网站、技术资料和 SDK 变更，执行静态检查、双语教程离线验证、已发布链接检查和 Cloudflare dry run；不发布网站或修改 Python 运行时。依赖由本目录的 `package-lock.json` 固定。
