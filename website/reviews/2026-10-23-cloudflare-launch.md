# Relf-Agent Cloudflare 上线与验收

日期：2026-10-23（Asia/Shanghai）

## 发布结果

- 主站：<https://relfagent.com/>；中文：<https://relfagent.com/zh/>；英文：<https://relfagent.com/en/>。
- 生产 Worker：`ralf-agent-website`，控制台显示部署版本 `15bcdf49`、100% 就绪。
- 发布方式：在已登录的 Cloudflare 控制台上传 `website/dist/`，共 86 个文件、2,241,749 字节。HTML handling 为 `force-trailing-slash`，not-found handling 为 `404-page`。
- 构建源码基线：本地 HEAD `b545aba`；域名环境示例、Wrangler 路由及本报告属于当前工作区的部署记录。构建命令为 `PUBLIC_SITE_URL=https://relfagent.com npm run build`。
- 产物清单 SHA-256：`4ee779723c8b65359174acd110878680c6a65a69fc6dd65892187c90cf93b49e`。计算方式：按相对路径排序，对每个文件记录 `相对路径 空格 文件SHA256`，以换行连接，再计算 SHA-256。
- `relfagent.com` 以 Custom Domain 绑定该 Worker；Cloudflare DNS 表显示根域为已代理的 Worker 记录。
- 本次是手工发布，未连接 Git 自动部署。后续源代码变更需重新构建并发布。

## DNS 与重定向

`www.relfagent.com` 配置已代理的 A 记录 `192.0.2.0`，TTL 自动，用于 Cloudflare 边缘重定向。

单一重定向名称：`Relf-Agent — HTTPS and www to apex`，已启用。

```text
匹配：(http.host eq "www.relfagent.com") or (http.host eq "relfagent.com" and not ssl)
目标：concat("https://relfagent.com", http.request.uri.path)
状态：301
保留查询字符串：开启
```

HTTP 根域、HTTP www、HTTPS www 各检查以下 3 条路径，共 9 组全部通过：

- `/`
- `/en/docs/api-reference/?utm_source=launch&probe=1`
- `/zh/docs/quickstart/?q=approval%20resume&x=1`

目标均为相同路径及查询字符串的 `https://relfagent.com` URL。HTTPS 根域正常返回页面，不产生跳转循环。DNS 与区域重定向由控制台维护，Wrangler 配置仅包含根域 Worker 绑定。

## 公网 HTTP 与产物核验

详细结果：[2026-10-23-launch-http-checks.json](./2026-10-23-launch-http-checks.json)。

| 项目 | 结果 |
| --- | --- |
| 31 个有效 HTML 页面：根入口、中英文首页及 28 篇文档 | 全部 HTTP 200，与本次本地产物逐字节 SHA-256 一致 |
| 53 个公开资源：CSS、JS、分享图、搜索索引、WASM、结果片段、robots 和 sitemap | 全部 HTTP 200，与本次本地产物逐字节 SHA-256 一致 |
| HTTPS 主站及 HTTPS www | curl 默认开启证书与主机名验证，成功响应的 `ssl_verify_result` 为 0 |
| 9 组域名／协议跳转 | 全部 301，保留路径与查询参数 |
| `/en/docs/quickstart` | 重定向到带尾斜线的 `/en/docs/quickstart/` |
| 不存在路径 `/__launch_acceptance_missing__/` | HTTP 404，返回本站自定义错误页 |
| 页面元数据 | 正式 origin 为 `https://relfagent.com`；canonical、双语 hreflang 与 OG URL 由该 origin 生成；根入口 canonical 指向 `/zh/` |
| robots 与 sitemap | 允许抓取，sitemap 为正式域名的 30 个中英文页面入口；404 为 noindex |
| GitHub 资料入口 | 48 个固定提交中的文档路径通过；基线提交 `0b9b6c9682c4` 已核验属于远端 HEAD `b545aba8c4f7` 的历史 |

`_headers` 为 Cloudflare 配置文件，404 HTML 通过不存在路径核验，不作为普通 200 资源计数。

## 浏览器与手机验收

- 中文首页及英文首页均可正常打开，品牌为 Relf-Agent；中英文首页切换正常。
- 中文“审批”搜索返回 14 条中文结果，点击进入恢复文档；切换英文保留 `/docs/recovery/` 主题。
- 英文“evaluation”搜索返回 10 条英文结果，点击进入 `Testing & evaluation`。
- 中文 API 文档页重新初始化搜索成功；`send_input` 返回 3 条中文结果，首条为持久用户输入指南。
- 手机视口 390 × 844 下，中英文首页及中英文 API 文档均满足页面宽度 390，无整页横向溢出。英文评估文档的手机目录可展开，并可进入 API 文档；主导航可展开和关闭。
- 英文首页审批演示完成 `Approve this operation → Simulate host restart → Resume original run`，宿主由 `process_01` 变为 `process_02`，原 Run 最终为 `succeeded`，显示一次示意写入。
- 英文首页 canonical 为正式 `/en/` 地址，页面引用资源中无 `http:` URL。
- 完成后已恢复浏览器默认尺寸，并保留中文正式官网标签页。

## 本地验证

- `npm run check`：28 个 Astro 文件，0 errors、0 warnings、0 hints。
- `npm test`：12/12 通过。
- 正式域名 `npm run build`：32 个页面、28 篇双语搜索文档、1,925 个本地链接／资源目标通过。
- `npm run docs:links -- --remote`：固定文档提交与远端历史核验通过。

## 验收观察项

首次中文搜索初始化出现一次加载失败，重试后成功；英文搜索首次初始化及中文文档页再次初始化均通过。首次批量 HTTP 检查也遇到部分 TLS 握手／读取超时，降低并发并只复验失败请求后，84 个页面与资源全部通过，未出现内容校验不一致。详细 JSON 保留了复验次数与网络错误记录。本次未修改现有搜索超时、重试或索引逻辑。

浏览器截图保存在本任务可视化产物目录：`relfagent-live-home.png`、`relfagent-live-search.png`、`relfagent-live-mobile.png`。
