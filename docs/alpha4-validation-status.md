# Alpha 4 验收与待处理清单

更新：2026-10-23。已完成 `0.1.0a4` 本地候选及原包的 Linux ARM64／原生 AMD64 三 Python 版本验收。准备提交 `b545aba` 已推送并建立默认 `main`，官网 `https://relfagent.com` 已上线；本批远端暂存及固定门禁使用 `86823f9`。账号配置、TestPyPI／PyPI上传及公开安装仍待验收。a2／a3 原包、原门禁和历史失败保留；公开入口仍为 [a2](releases/0.1.0a2.md)。

| 事项 | 本批状态 |
| --- | --- |
| 版本、元数据、独立 wheel／sdist 和外置 manifest | 最终两包冻结于 `dist/alpha4-candidate/`；2046来源／442产品／975测试输入，精确SHA见[a4说明](releases/0.1.0a4.md) |
| 发行工具、手动工作流和错误输入拒绝 | 源码200项通过，零失败／错误／跳过；手动YAML与嵌入脚本核对，不代表远端执行 |
| Twine 严格检查 | Twine7.0.0对最终两包严格检查通过，元数据／入口／许可证核对 |
| macOS ARM64／Python3.12 安装门禁 | 最终原311／16及两starter通过，零失败／错误／跳过；181.886秒，每case业务只写一次 |
| sdist 重建安装、近期修复及连续示例 | 重建wheel与原wheel的SHA相同，独立安装292项／两starter通过；包含69项近期契约、35项Coding验证和五阶段示例 |
| 网站、文档与历史摘要保护 | 12网站测试，14对双语来源，Astro28文件零诊断；32页／1925本地链接与资源；原教程基线不变 |
| Linux ARM64／Python3.11–3.13 | 原两包每版311基础／16恢复／两starter通过；最高326.21MiB；2CPU／2GiB／swap0／串行断网，零失败／错误／跳过／OOM |
| 原生 Linux AMD64／Python3.11–3.13 | [run39892578674／attempt1](https://github.com/RalfNick/relf-agent/actions/runs/39892578674)同包每版311／16／两starter通过；最高287.57MiB；原资源要求保持，零失败／错误／跳过／OOM |
| 账号、项目控制权、OIDC／保护环境 | 未核验／配置；需要维护者准备 |
| 准备代码与主分支 | `b545aba` 已推送；`main` 默认入口已建立，原 `feat/m1-local-runtime` 保留 |
| 官网入口与配置 | 官网已上线；GitHub About 已配置，本批将域名配置和说明纳入主分支维护 |
| 原包暂存与远端固定CI | 暂存run39892431094及门禁run39892578674均通过，固定86823f9；下载报告与原包复核通过，临时草稿清理，未公开发行 |
| a4 上传和公开安装 | 未执行；需要发行账号配置及后续授权，不以平台门禁代签公开发行 |

上轮完整离线源码回归为14,089通过／891条件跳过／零失败与错误，属于 `672d0cf` 修复基线，不能代签 a4 安装、Linux 或真实服务。旧五项 Coding 失败和其后一轮 Workspace 超时均保留，历史瞬态原因不追认；见[原记录](../architecture/reviews/2026-10-22-coding-regression-fixture-readiness.md)。原 dev19 S2 及指纹／模型成绩仍按原制品和环境引用。

本批精确制品、实际范围及待办见 [a4 说明](releases/0.1.0a4.md)、[验收记录](../architecture/reviews/2026-10-23-alpha4-preparation.md)与 [PyPI 指南](pypi-publishing.md)。不同范围不相加为全量验收；跳过不标为通过，`publication_ready=false` 明确保留。

独立只读复核未发现P1／P2或Minor。原a2交付50项、公开交付249项、a3候选76项和前批回归档案64项校验保持；首轮预备包、网站环境／链接拒绝和所有历史失败单独保留。没有改期限、业务断言或固定node集合。本批未重跑全项目14k源码回归，不将前批成绩冒充a4新包验收。

主分支与官网入口同步的实际检查见[维护记录](../architecture/reviews/2026-10-23-main-open-source-entry.md)。原制品、包元数据和固定门禁不重建；包内旧分支链接继续可用，工程优化后置。

本轮Linux与远端CI实际证据见[同包验收](../architecture/reviews/2026-10-23-alpha4-linux-validation.md)。每平台／版本单独取证，不相加为全量回归；现有检查器返回`verified_alpha4_publication_input`，但账号、上传和公开安装仍待完成，`publication_ready=false`保持。后续发布须匹配原生门禁的完整SHA与准确attempt；Actions输入保留14天，过期或提交变化按原流程重验。
