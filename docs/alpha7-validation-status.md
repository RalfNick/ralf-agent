# Alpha 7 验收与待处理清单

当前候选 `relf-agent==0.1.0a7`，导入 `relf_agent`，CLI `relf`／`relf-*`，纳入 `2d17808` 的同步装配中断清理修复。原 a6 两包及历史证据保持；a7 使用独立制品和实际结果。详情与原失败见[准备记录](../architecture/reviews/2026-10-24-alpha7-candidate.md)，兼容与发布范围见[a7 说明](releases/0.1.0a7.md)。

## 本地实际验收（2026-10-24）

| 验证范围 | 本次结果 |
| --- | --- |
| 受影响源码，31 个测试模块 | **503 passed**，零失败／错误／跳过，warnings-as-errors；不是全量 SDK 回归 |
| a7 发布配置与安全反例 | 57 passed，包含真实 pytest 收集与新增中断阶段摘要核对；属于上行范围的子集，不重复相加 |
| 原 wheel，macOS ARM64／Python 3.12.7 | **311 基础＋16 恢复＋9 中断清理**，零失败／错误／跳过；两 starter 各一次业务写入；原阶段与期限不变 |
| sdist 重建后安装，源码 SDK 目录外 | **498 passed／2 skipped**，零失败／错误；跳过仅为最小依赖无 PyYAML 的两工作流模块，源码环境已通过；两 starter 各一次业务写入 |
| 发行与安装身份 | wheel／sdist／源码／重建 wheel 的 **442** 产品文件一致；METADATA、8 个 CLI、LICENSE／NOTICE、`pip check`、Twine 7.0.0 `--strict`、离线发布预检通过 |
| 官网固定 a6 | 25 项、类型检查、14 对双语文档摘要、49 个固定仓库目标与双语离线教程通过；基线 `ba1c81f` 保持，不部署网站 |
| 原制品与历史 | **731** 个预先保护文件摘要一致；a6 原两包、交付目录、旧 manifest／工作流／检查器及历史 review 保留 |

产品相对 `2d17808` 只改两个文件的版本号与安装提示，`runtime_builder.py` 直接保留该提交的修复，不改功能、依赖或 Schema。完整源码回归、真实模型、S2／函数指纹专项未在本轮重跑，也不借历史成绩授予 a7 新包资格。

### 推荐本地原包

目录为 `dist/alpha7-candidate/`；外置 `tools/release_gate_manifest.alpha7.json` 为最终交付清单。仅选以下两份原包，不能上传整个 dist 目录。

| 原包 | SHA256 |
| --- | --- |
| `relf_agent-0.1.0a7-py3-none-any.whl` | `6f4e11f7e1e421dcf31f6085777338fecdefd34248381bd06c8eae3a9f32ea32` |
| `relf_agent-0.1.0a7.tar.gz` | `c6afdb08c69adcb4fe46c32b65d6c0029d3b1179db178cf32fc24da5df323d5b` |

最终外置 manifest SHA256：`41ebadcb3ac263a8b1cded3b0b0edbe9067e2a598caaccecdd9b192d7e0aa7f7`。构建输入清单 SHA256：`81c12eb2555f0cbdaf6cabde859ae641062a7e545ed606b2960d79fb7b33df3c`；包含 2098 个源码输入、990 个测试／示例文件及442个产品文件。来源为基线 `2d178082282368a901651b4a5fbc39cfa5f84119` 加本批维护工作区；**不是某个 Git 提交的逐文件 archive**。最终文档成绩与最终包 SHA 在冻结后追加于这三份记录；归档内仍为准备快照，避免自引用，不代表归档遗漏运行代码。

### 后续外部步骤

a7 的 **Linux ARM64** 与 **原生 AMD64／远端固定门禁**尚未执行，必须使用以上同两包，按 2 CPU／2 GiB／swap0、断网、Python 3.11–3.13 串行独立验收。原生工作流已准备为 `alpha7-release-gate.yml`，暂存、门禁和发布须匹配同一准确提交与 run／attempt；新增9项也必须完整通过。下一步需要推送和远端 CI 授权，本批停在本地提交。

PyPI／TestPyPI 的 `relf-agent` 项目权限、`alpha7-pypi-publish.yml` Trusted Publisher、受保护环境、上传、公开下载后安装均未配置或执行。`publication_ready=false`；没有正式 Tag、推送或公开发布。公开推荐、网站升级和独立采用另行验收。
