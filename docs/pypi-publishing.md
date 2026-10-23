# PyPI 发布准备与人工核对

发行名 `ralf-agent`，展示名 Relf-Agent，仓库 `RalfNick/relf-agent`。当前推进独立 `0.1.0a4` 候选，包含 `210a79e` 公共契约修复和 `672d0cf` Coding 测试夹具修正。实际本地／平台状态见[a4 清单](alpha4-validation-status.md)。本批不推送、触发远端 CI、核验账号或上传；以下外部步骤须另行授权。原 a3 两包和原 `pypi-publish.yml` 保留，不用于发布 a4；原结果见[a3 清单](alpha3-validation-status.md)。

## 需要维护者配置

1. 在 PyPI 和 TestPyPI 分别准备账号、验证邮箱并启用 2FA，核对 `ralf-agent` 项目创建／维护权限。GitHub 账号不能代替这两处权限；项目查询 404 也不保证名称可注册。
2. 在两处账号的 Publishing 页面添加 pending Trusted Publisher（已有项目则在项目设置添加），字段如下。pending 配置不占有项目名称。
3. 在 GitHub 仓库配置两个环境 `testpypi`、`pypi`，为正式环境设置维护者审批和允许发布的 ref。不要将 Token 写入仓库或聊天；本工作流使用 OIDC，不需要长期 PyPI Token。

| Publisher 字段 | TestPyPI | PyPI |
| --- | --- | --- |
| PyPI project name | `ralf-agent` | `ralf-agent` |
| Owner | `RalfNick` | `RalfNick` |
| Repository | `relf-agent` | `relf-agent` |
| Workflow filename | `alpha4-pypi-publish.yml` | `alpha4-pypi-publish.yml` |
| Environment | `testpypi` | `pypi` |

参见官方[首次 OIDC 发布](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)、[Publisher 字段](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)、[2FA](https://docs.pypi.org/your-account/two-factor-authentication/)和[名称规则](https://docs.pypi.org/project-management/choosing-a-name/)。

## 经另行授权后执行的顺序

本地交付不授权以下外部操作。先审核本地提交、精确制品 SHA 和支持矩阵；本流程自动核对原生AMD64，不代签本地Mac、Linux ARM64或其他平台。正式发布前需人工核对声明支持的平台实际报告，未验收范围不得写为通过。必要推送获批后再执行：

1. 将两份原 a4 包暂存到本仓库未发布草稿，tag 必须以 `ralf-alpha4-private-stage-` 开头，资产只能是原 wheel／sdist。不要创建正式发行 Tag 或公开该草稿。
2. 手动运行 `alpha4-stage-candidate.yml`，输入草稿 Release ID。脚本只 GET 草稿资产，核对名称、长度和固定 SHA；`contents: write` 仅用于草稿可见性。暂存 artifact 名为 `ralf-alpha4-original-candidate`。
3. 在同一确定源码提交运行 `alpha4-release-gate.yml`，输入暂存 run ID。它以当前 dispatch 的不可变 `github.sha` checkout，使用 a4 外置 manifest 和原依赖锁，在原生 AMD64 串行运行三版 Python 的原冻结门禁。上传全部成功／失败证据；只有全部通过才生成 `ralf-alpha4-qualified-RUN_ID-ATTEMPT`。
4. 核对实际门禁报告后，手动运行 `alpha4-pypi-publish.yml`，选择 `testpypi`，输入成功的门禁 run ID 和准确 attempt。发布工作流与门禁须同一 `github.sha`；后续改动后需重新运行门禁，不能拿分支名或旧报告替代。检查器还核对仓库 ID、来源工作流、event、成功状态、三版原生报告、实际资源、容器移除及全部工具／原包 SHA。
5. TestPyPI 上传后，核对页面、名称、Alpha 版本、LICENSE／NOTICE 和文件 SHA；在源码目录外安装实际上传的版本并运行两条审批／恢复 starter、连续示例。依赖先从正式 PyPI 安装；TestPyPI 安装本包使用 `--no-deps`，不要依赖混合索引解析。
6. TestPyPI 核对通过且获准正式发布后，使用相同门禁 run／attempt、同一提交和同两包，再手动选择 `pypi`。发布 job 先通过对应环境保护，只获得 job 级 `id-token: write`；它不 checkout SDK、不构建，只核对转交后的两份原包再交给固定提交的 PyPA Action。
7. 正式上传后，从普通网络、无 GitHub 认证、源码外新环境执行 `python -m pip install 'ralf-agent==0.1.0a4'`，检查 `pip check`、CLI／import 版本、两 starter 和连续示例。核对 PyPI JSON 中每份文件的 SHA，再更新安装指南和公开推荐。
8. 保存远端报告及上传／安装回执，清理本批暂存草稿；保留原失败、a2／a3 制品与新包摘要。GitHub a4 Release／Tag 如需创建，单独获准并固定准确源码，不移动 a2 Tag。

TestPyPI 与 PyPI 互相独立，上传演练见[官方指南](https://packaging.python.org/en/latest/guides/using-testpypi/)。两处发布都必须仅上传已核对的两包，不使用包含历史数据库／日志的 `dist/*`。失败时先核对实际已存在文件；工作流不使用 `skip-existing` 隐藏上传冲突，也不自动覆盖或重建同版本包。

## 本地复核

```bash
python3.12 tools/release_preflight.py --manifest tools/release_gate_manifest.alpha4.json \
  --wheel /ABS/ralf_agent-0.1.0a4-py3-none-any.whl \
  --sdist /ABS/ralf_agent-0.1.0a4.tar.gz --output /ABS/new-a4-handoff
python -m twine check --strict \
  /ABS/ralf_agent-0.1.0a4-py3-none-any.whl /ABS/ralf_agent-0.1.0a4.tar.gz
```

预检不运行平台门禁、不登录账号、不发布，`publication_ready=false` 不代签外部步骤。sdist 的构建输入 manifest 和最终外置 manifest 分开；复现只核对产品／元数据，不要求重建 ZIP 时间戳相同。SDK 版本号不授予旧 Worker／Schema 的额外兼容资格。
