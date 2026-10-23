# Relf-Agent website

独立的 Astro 静态官网。当前展示品牌为 **Relf-Agent**：**Reliable and Extensible Lifecycle Framework for Intelligent Agents**，可靠、可扩展的智能体全生命周期框架。定位：灵活构建智能体，可靠运行智能应用。

原项目名为 Ralf-Agent；`ralf-agent` 安装包、`ralf_agent` 导入、`ralf` CLI 与原 SDK 保持。仓库已更名为 [RalfNick/relf-agent](https://github.com/RalfNick/relf-agent)，`repository.json` 与当前页面链接已同步。源码默认分支为 `main`，基于已审核的 `b545aba`；原开发分支继续保留。官网 **[relfagent.com](https://relfagent.com/)** 已上线，本批同步已使用的域名配置与维护说明。教程继续固定原 a1 基线；公开安装仍使用 a2，a4 仅完成候选本地验证与源码推送，未公开发行。旧计划／审查与 Cloudflare 资源名保留。无需服务端、模型密钥或 Cloudflare 账户即可本地查看。

网站上线的现场证据见[上线验收记录](reviews/2026-10-23-cloudflare-launch.md)及其HTTP明细；该记录对应原部署构建，不是本轮重新部署或现场浏览器复验。网站采用手工部署，未连接Git自动部署。

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

官网已于 **2026-10-23** 通过 Cloudflare 控制台直接上传 `dist/` 上线，生产 Worker 为 `ralf-agent-website`。主域名为 [relfagent.com](https://relfagent.com/)，中英文入口分别为 [/zh/](https://relfagent.com/zh/) 和 [/en/](https://relfagent.com/en/)。当前采用手工发布，尚未连接 Git 自动部署；后续内容更新需要重新构建并上传 `dist/`，或使用已登录的 Wrangler 部署，不能只修改仓库就视为线上已更新。

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

后续部署与线上核对流程（本批不重新部署）：

1. 在 Cloudflare 确认 `relfagent.com` 已完成注册，并在域名概览中显示为活动。刚提交注册时成功页可能先于域名列表更新。
2. 在本目录执行 `PUBLIC_SITE_URL=https://relfagent.com npm run build` 和 `npm run cf:check`，检查正式地址元数据与静态资源。
3. 确认目标 Cloudflare 账户并获得发布授权后，执行 `npx wrangler deploy`。Custom Domain 会由 Cloudflare 创建所需 DNS 记录和证书，无需手工添加指向服务器的 A 记录；若已有同名 CNAME，应先核对其用途，避免覆盖已有服务。参见 [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)。
4. 验证 `https://relfagent.com/`、`/zh/`、`/en/`、两种语言的文档与搜索、`/robots.txt`、`/sitemap.xml`，以及不存在路径的 HTTP 404。证书签发和域名生效必须以公开访问结果为准。
5. 当前 `www.relfagent.com` 和HTTP入口已由Cloudflare区域规则301重定向至HTTPS根域，保留路径及查询参数，见上线记录。该DNS／重定向配置由控制台维护，不包含在当前Wrangler根域Worker绑定中；后续修改时参照 [www 到根域名的重定向](https://developers.cloudflare.com/rules/url-forwarding/examples/redirect-www-to-root/)核对已有用途。

需要自动构建时，在 Workers Builds 中选择仓库子目录 `website`，构建命令 `npm ci && npm run build`，部署命令 `npx wrangler deploy`；将 `PUBLIC_SITE_URL=https://relfagent.com` 设置为**构建环境变量**，仅设置 Worker 运行时变量不会改写已经生成的 HTML。预览构建不传该值，保持 noindex。GitHub Actions 当前工作流只验证，不部署。也可使用 Pages 静态构建，根目录 `website`、输出目录 `dist`，但当前 Wrangler 配置面向 Workers。

## 内容维护

- `src/components/Home.astro`：双语首页文案与 SDK 示例；Capabilities.astro 展示六类能力和用途。
- `src/content/guides/{zh,en}/`：十四组双语 Markdown 精选指南。
- `src/styles/`：共用视觉与文档样式；支持手机布局、键盘操作与 reduced motion。
- `src/lib/`：审批演示状态机、语言与 URL 元数据。
- `src/lib/site.ts` 的 `brand`：统一展示名、英文全称、中文含义与双语定位；不控制 SDK 或持久化身份。
- `docs-source-lock.json`：本轮审阅的指南与技术源文件哈希。

搜索通过 Pagefind API 显示当前语言的文档。加载前用正文中必有的“审批／approval”验证索引与 WASM 就绪，每次查询等待全部结果片段，失败保留关键词并可重试。当前每种语言为两个查询分块。Pagefind 1.5.2 原实现会吞掉部分分块错误，因此 `scripts/strict-pagefind.mjs` 在构建时给主线程与 Worker 的同一个已知 catch 增加重新抛出，防止显示不完整结果。补丁只匹配一个准确位置，版本或实现变化会中止构建，必须重新审阅；单元测试与浏览器故障注入覆盖失败和重试。开发模式没有生成索引时显示重试与文档入口。

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
