# Relf-Agent website

独立的 Astro 静态官网。当前展示品牌为 **Relf-Agent**：**Reliable and Extensible Lifecycle Framework for Intelligent Agents**，可靠、可扩展的智能体全生命周期框架。定位：灵活构建智能体，可靠运行智能应用。

原项目名为 Ralf-Agent；本次仅更新展示名称，`ralf-agent` 安装包、`ralf_agent` 导入、`ralf` CLI、实际仓库地址与原 SDK 保持。教程继续固定 `repository.json` 中的 a1 基线；最新公开 a2 链接另行标注。旧计划／审查与 Cloudflare 资源名保留。无需服务端、模型密钥或 Cloudflare 账户即可本地查看。

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

选定实际公开域名后，复制 `.env.example` 为 `.env` 并设置 **HTTP(S) origin**（不带子路径、查询、凭据），重新构建。也可由 CI 构建环境传入：

```bash
PUBLIC_SITE_URL=https://你的实际域名 npm run build
```

设置后生成 canonical、双语 hreflang、robots、sitemap 与 Open Graph 元数据；根路径的 canonical 指向 `/zh/`。404 保持 noindex。`public/og.png` 是分享图片，`public/og.svg` 保留可编辑矢量源。

## Cloudflare

采用 [Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/)，`wrangler.jsonc` 只托管 `dist/` 静态资源，无 Worker 业务代码、数据库或秘密绑定。目录式 URL 使用尾斜线，未知路径返回自定义 404；`public/_headers` 定义响应头与构建资产缓存。

本地验证与 Cloudflare 路由预览：

```bash
npm run build
npm run cf:check
npm run cf:dev
```

`cf:check` 是 `wrangler deploy --dry-run`，不会上传或部署。`cf:dev` 在本机模拟 Workers 静态资源路由，可验证真正的 404 状态。

未来上线时，再配置 Cloudflare 账户、实际域名和 `PUBLIC_SITE_URL`。在 Workers Builds 中选择仓库子目录 `website`，构建命令 `npm ci && npm run build`，部署命令 `npx wrangler deploy`；本次没有绑定账户或运行部署。也可使用 Pages 静态构建，根目录 `website`、输出目录 `dist`，但当前 Wrangler 配置面向 Workers。

## 内容维护

- `src/components/Home.astro`：双语首页文案与 SDK 示例；Capabilities.astro 展示六类能力和用途。
- `src/content/guides/{zh,en}/`：十四组双语 Markdown 精选指南。
- `src/styles/`：共用视觉与文档样式；支持手机布局、键盘操作与 reduced motion。
- `src/lib/`：审批演示状态机、语言与 URL 元数据。
- `src/lib/site.ts` 的 `brand`：统一展示名、英文全称、中文含义与双语定位；不控制 SDK 或持久化身份。
- `docs-source-lock.json`：本轮审阅的指南与技术源文件哈希。

搜索通过 Pagefind API 显示当前语言的文档。加载前用正文中必有的“审批／approval”验证索引与 WASM 就绪，每次查询等待全部结果片段，失败保留关键词并可重试。当前每种语言为两个查询分块。Pagefind 1.5.2 原实现会吞掉部分分块错误，因此 `scripts/strict-pagefind.mjs` 在构建时给主线程与 Worker 的同一个已知 catch 增加重新抛出，防止显示不完整结果。补丁只匹配一个准确位置，版本或实现变化会中止构建，必须重新审阅；单元测试与浏览器故障注入覆盖失败和重试。开发模式没有生成索引时显示重试与文档入口。

`repository.json` 集中记录 SDK 版本、已发布提交和验证日期。组件调用 `repositoryUrl()`，Markdown 使用 `[标题](repo:docs/example.md#section)`，由 Sätteri MDAST 插件转换；不要再写死分支。构建检查所有生成的仓库链接，使用固定 Git tree 确认目标存在，不显示未发布的“编辑本页”。`npm run docs:links -- --remote` 另外只读核验固定提交属于远端 HEAD 的历史，需要网络和对应 Git 对象；CI 使用完整 checkout。英文指向中文的可选资料标注语言，关键操作应提供站内双语路径。

`npm run docs:examples` 需要 Python 3.12 和 SDK 基础依赖（先在虚拟环境安装 SDK）。脚本在临时目录导出固定提交的 SDK，直接提取两种语言的教程代码，验证模型示例改输出 Schema 后的新命令身份、重放、Session、输入、离线应用测试和混合检索。真实模型示例只替换成确定性 Provider 验证装配；不会运行付费模型／Embedding 探针。完整连续应用和评估命令的本轮验证记录见 reviews。

修改技术源文档或任一翻译后，`npm run docs:check` 会提示需要同步。对照每篇 frontmatter 的 `sources` 审阅中英文，确认两者一致后记录并提交新快照：

```bash
node scripts/check-docs.mjs --record
npm run docs:check
```

哈希检查用于发现变更，不会自动判断翻译语义。新增主题时同时更新 `src/lib/site.ts`、两个语言目录与文档快照。

仓库的 `.github/workflows/website.yml` 覆盖网站、技术资料和 SDK 变更，执行静态检查、双语教程离线验证、已发布链接检查和 Cloudflare dry run；不发布网站或修改 Python 运行时。依赖由本目录的 `package-lock.json` 固定。
