# Alpha 4 Linux 同包验收

日期：2026-10-23。按用户授权，补齐 a4 的 Linux ARM64 与原生 AMD64 固定门禁，可暂存原包并手动触发远端流程；保持 2 CPU／2 GiB／swap0、Python 3.11–3.13 串行、测试容器断网。保留历史失败，不扩展功能、不重建包、不公开发布或配置 PyPI 账号。

## 输入与固定身份

使用 `dist/alpha4-candidate/` 中的最终原 wheel／sdist，SHA 仍为：

| 制品 | SHA256 |
| --- | --- |
| `ralf_agent-0.1.0a4-py3-none-any.whl` | `053b5d536de35a1a8969afd766ddfa40a03f010bad52ac72f368fb3406a217a2` |
| `ralf_agent-0.1.0a4.tar.gz` | `53e0e824657b39be237157427b437b8a69949e5557fa9599d8523fdd2ec67b7e` |

外置 `release_gate_manifest.alpha4.json` SHA 为 `1f03bc0e9742bd6db2be92504e92c5a971360537318e6e3b009483a6c538e12c`。原 311 基础／16 恢复完整 node 身份、两条 starter、17 依赖哈希锁、固定镜像及全部期限不变；原 manifest 的构建时 pending 描述不回写，后续实际平台资格由外置证据与维护清单补充。

准备时远端 `main` 从 `aa17985` 更新至 `86823f9949f4084f10e58e3afca5e7808562b57a`，第一次来源核对因此在任何派发前停止并留档。逐文件确认新增内容仅为官网维护，SDK、a4 工作流、门禁与测试均不变后，固定新的完整 SHA；暂存与原生门禁均使用该提交。不推送新的源码或更改默认分支。

## Linux ARM64 实测

Mac ARM64 宿主、Linux ARM64 Docker daemon；Docker client／server 均为29.0.1。复用原缓存镜像与原锁定 wheelhouse，安装和测试容器 `network=none`；只用绑定命令生命周期的 `caffeinate -i` 防止空闲睡眠，不改全局电源设置。

| Python | 基础／恢复／starter | 门禁耗时（秒） | cgroup 内存峰值（MiB） |
| --- | --- | --- | --- |
| 3.11.17 | 311／16／2，通过 | 75.829 | 326.21 |
| 3.12.15 | 311／16／2，通过 | 86.013 | 293.54 |
| 3.13.16 | 311／16／2，通过 | 81.233 | 295.85 |

三版严格串行，零失败／错误／跳过／OOM；每条 starter 业务写入一次。实际 cgroup CPU 为 `200000 100000`，内存上限2147483648、swap上限0；退出码、JUnit、node摘要与报告身份复核通过，三个容器均已移除。本范围属于 Docker 内 Linux ARM64，不表述为原生 Linux 宿主验收。

## 远端原生 AMD64

既有默认 Git 凭据在内存中核验为 RalfNick；不输出或保存令牌。临时草稿仅有两份原包、`draft=true` 且未发布，不创建正式发行 Tag。

- 暂存：[run39892431094／attempt1](https://github.com/RalfNick/relf-agent/actions/runs/39892431094)，已成功。取回 Actions ZIP 后核对服务端摘要、暂存 proof 与原包 SHA，字节一致。
- 原生门禁：[run39892578674／attempt1](https://github.com/RalfNick/relf-agent/actions/runs/39892578674)，成功；暂存与门禁同为固定提交 `86823f9`。运行位于 Linux x86_64 宿主和 AMD64 Docker daemon，实际启用 `--require-native`，不是 Mac 模拟执行。

| Python | 基础／恢复／starter | 门禁耗时（秒） | cgroup 内存峰值（MiB） |
| --- | --- | --- | --- |
| 3.11.17 | 311／16／2，通过 | 160.282 | 287.57 |
| 3.12.15 | 311／16／2，通过 | 171.611 | 261.50 |
| 3.13.16 | 311／16／2，通过 | 175.408 | 264.95 |

三版严格串行，零失败／错误／跳过／OOM，各 starter 业务写入一次。实际 cgroup 与容器 inspect 均匹配原 2 CPU／2 GiB／swap0／断网要求；client／server 均为29.0.1。结束后的退出状态、完整JUnit与node摘要、镜像架构、来源工具／manifest及原包SHA逐项复核通过，全部容器已移除。

两份 Actions artifact ZIP 按服务端摘要验证后安全解包。现有 `check_alpha4_publication.py` 另行只读核对仓库ID、run／attempt／event／路径／提交身份、三版实际报告及两份原包，返回 `verified_alpha4_publication_input`。它只移除原生AMD64与远端CI两项待核验责任；`publication_ready=false`、`public_upload=false`保持，不能把这份预检当作上传授权。

## 维护文档检查

同步当前a4清单、发行指南、平台与账号待办，以及中英文安装页状态；原a1教程与公开a2安装指令保持。README／发行展示契约8项通过，14组双语来源复核并登记后检查通过，Git空白检查通过。SDK、测试、工作流与固定manifest均未修改，不重复全量源码、真实模型或其他服务验收。本轮维护文档留在工作区，不推送新提交或重新部署官网。

## 交付与后续边界

操作脚本、来源漂移记录、实际容器输入／报告／JUnit、暂存及原生 CI 回执分别保存在本地忽略目录 `dist/alpha4-linux-validation-20261023/`，附完整校验和。原 `dist/alpha4-candidate/` 不追加或覆盖任何文件；a2／a3、原a4及历史失败的544项保护校验保持。本轮平台测试没有失败；准备阶段来源漂移停止记录、运行中日志接口的404观察另行保留，不冒充SDK失败或通过成绩。

取回证据后删除本次未发布临时草稿，原有Tags／Releases保持；成功的Actions输入与证据按原工作流保留14天，另有本地副本。后续发布必须使用相同门禁run／attempt及同一checkout SHA；若发布提交变化或Actions输入已过期，按原流程重新暂存／验收，不能放宽来源检查或重建同版本包。

末次远端核对时 `main` 已被独立官网维护任务继续推进；本批没有推送该类提交，也不把 `86823f9` 的门禁报告改挂到新的发布checkout。GitHub `testpypi`／`pypi` 环境仍未建立，a4发布工作流运行数为0，后续需要维护者准备账号与Publisher／环境配置。

本次不运行 `alpha4-pypi-publish.yml`，不上传 TestPyPI／PyPI，不创建 a4 公开 Release，不切换 a2 安装推荐。账号控制权、Trusted Publisher、保护环境、上传及公开安装仍需后续分别取证。S2、指纹、真实模型与其他服务资格仍只引用原制品和环境，不因基础门禁通过而新增资格；工程优化后置。
