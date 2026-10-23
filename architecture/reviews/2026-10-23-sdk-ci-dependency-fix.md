# SDK CI 依赖修复与其他失败清单

Date: 2026-10-23 (Asia/Shanghai).

按用户确认的范围，本轮完成依赖修复并整理其他失败；其余 SDK 运行时问题留作后续处理。
修复已推送，原先报错的 23 个模块共 390 项测试通过。云端 CI 已结束：工作流总体为
`cancelled`，其中 Python 3.13 测试任务为 `failure`（49 项失败），其余任务取消。
整个 SDK CI 未通过。网站生产门禁与 Website CI 复跑通过，本轮未修改或重新部署网站。

## Scope and root cause

Fix commit: `3878e74a691792d2c8559d1af76b4343c0fd7f20`.

The Python 3.11/3.12/3.13 SDK test matrix ran all tests after installing
`.[dev,pdf,tokenizer,skills]`. Twenty-three test modules import `temporalio`
during collection, so those imports failed before the tests could run. The
existing `temporal` extra already declares the SDK and PostgreSQL driver.

The matrix now installs `.[dev,pdf,tokenizer,skills,temporal]`. The contributor
setup command and CI description use the same extras. SDK runtime code,
dependency declarations, website source, and deployment configuration are
unchanged.

## Reproduction and focused verification

A fresh Python 3.12.7 virtual environment installed the original CI command.
`python -m pytest --collect-only -q` exited 2 with the same 23 missing-module
errors (14,116 other tests collected).

After installing with the corrected command:

- The original 23 modules: **390 passed in 86.25 seconds**.
- Full collection after installing the extra: **15,021 tests collected in
  7.02 seconds, no collection errors**, exit 0.
- Two subprocess tests that block optional Temporal imports: **2 passed**.
- `python -m pip check`: no broken requirements.
- Ruff check and format check: passed (1,428 formatted files).
- `git diff --check`: passed before the fix commit.
- Independent read-only review: no blocking findings.

The full local result and cloud CI status are recorded below; focused results
alone do not establish that the entire SDK workflow passes.

## Website verification

The complete production gate passed on an isolated archive of the committed
website, excluding concurrent, uncommitted release-documentation work:

- Static checks and **25 tests**, 14 bilingual source-document pairs, offline
  tutorials, 32 built pages, 28 indexed documents, 1,925 local link/asset
  targets, 48 published repository targets, and Wrangler dry run.
- The cloud [Website workflow, attempt 2](https://github.com/RalfNick/relf-agent/actions/runs/39897717629)
  was re-run and **passed**, job `120238117031` (50 seconds). This workflow
  performs validation and `wrangler deploy --dry-run`; it does not publish the
  production Worker.
- Fresh browser checks: Chinese API documentation, Chinese search for
  `审批` (14 results), language switching to the same English API topic, and
  English search for `evaluation` (10 results) passed.
- `https://www.relfagent.com/zh/docs/api-reference/?ci=3878e74` resolved to
  the HTTPS apex with the path and query intact.

Only `.github/workflows/ci.yml` and `CONTRIBUTING.md` changed in the fix commit.
Neither matches the website or Cloudflare build watch paths. No production
redeployment was needed for this CI-only fix. The production source remains
`e8e2ac32369f2bbf0f7aecb0581bae5a322b53ba`, Worker version
`7a912297-3c6b-4885-af52-a24b00a27a71`; its prior post-deployment gate passed
**95/95 HTTP checks**, with acceptance metadata timestamp
`2026-10-23T04:00:18.289Z`. These 95 checks are the existing deployment evidence,
not a new production deployment or a new full HTTP scan in this repair.

## 云端 SDK CI 最终结果

Fix workflow: [ci run 39899564122](https://github.com/RalfNick/relf-agent/actions/runs/39899564122).

状态核对时间：**2026-10-23 14:10:41 Asia/Shanghai**。工作流于北京时间
13:10:38 结束，总体结果为 `cancelled`，不能记为成功。

| 任务 | 最终结果 | 已确认范围 |
| --- | --- | --- |
| [Python 3.13](https://github.com/RalfNick/relf-agent/actions/runs/39899564122/job/120237741589) | failure | Python 3.13.16：14,031 通过、941 跳过、49 失败、2 warnings；耗时 51:49 |
| [Python 3.11](https://github.com/RalfNick/relf-agent/actions/runs/39899564122/job/120237741657) | cancelled | 测试执行中取消，无完整 pytest 摘要 |
| [Python 3.12](https://github.com/RalfNick/relf-agent/actions/runs/39899564122/job/120237741721) | cancelled | 测试执行中取消，无完整 pytest 摘要 |
| [remote-contracts](https://github.com/RalfNick/relf-agent/actions/runs/39899564122/job/120237741968) | cancelled | 首个服务契约步骤 274 通过；后续 Two-worker Temporal contracts and History replay 未完成 |

四个任务均已越过依赖安装；矩阵的 Ruff 与格式检查通过。Python 3.13 完成全量测试，
没有缺少 `temporalio` 的收集错误。测试阶段失败后，后续打包和安装后的契约步骤未完成，
不能由源码测试结果推算为通过。

### Python 3.13 的 49 项失败

以下按最终错误摘要归组，数量合计 49。分组表示共同症状，不表示已经确认同一根因。
完整节点名称、错误和任务元数据见 [机器可读清单](2026-10-23-sdk-ci-failures.json)。
以下条目均保留为待办，本次不实施修复；后续按组复现并单独处理。

| 后续优先级 | 分组 | 数量 | 实际错误与下一步调查 |
| --- | --- | --- | --- |
| P1 | Connected Coding 捕获校验 | 30 | 均报 `ValidationError: Connected Coding compiler capture changed`。覆盖构造、声明、生命周期和 Temporal 注册；先比较 Linux/Python 3.13 下的单文件复现、完整执行顺序与捕获指纹。 |
| P1 | 崩溃恢复计数 | 2 | `test_composite_binding_crash`、`test_parallel_workflow` 的 external_commit 场景出现 `assert 5 == 4`；先核对计数对象、原始持久记录和恢复前后差异。 |
| P1 | Facts 索引维护恢复／关闭 | 4 | 2 个进程恢复用例未到预期崩溃点或恢复后仍为 running；2 个取消／资源关闭用例 TimeoutError。先核对实际驱动等待边界及资源责任。 |
| P2 | Temporal Coding 测试 fixture 路径 | 10 | fixture／retention 报 FileNotFoundError，涉及 `/private/tmp/ralf-dcoding-*.sock`。核对 Linux 临时目录和资源创建／清理顺序。 |
| P2 | HTML 异常输入契约 | 2 | malformed declaration 未抛出预期 ValidationError；starter 的 malformed-html 场景断言失败。先复现当前 Python HTML 解析行为及 SDK 的错误转换。 |
| P2 | PDF 异常输入契约 | 1 | malformed Form 文本未抛出预期 ValidationError；本地也复现，且不依赖 Temporal 安装，详见下文。 |

`remote-contracts` 配置 `timeout-minutes: 45`，实际运行约 45 分 21 秒后记录为取消；
最后执行的 Temporal 步骤没有 pytest 最终摘要。时长与配置上限一致，但取消的精确原因
尚未独立核实，不能把已取消的步骤当成完整服务验收。

## 完整本地测试结果

The full `python -m pytest -q` run finished with exit 1:
**14,079 passed, 940 skipped, 2 failed in 2,315.05 seconds (38:35)**.

The failures were:

- `tests/test_codex_cli_process_lifecycle.py::test_stdout_eof_does_not_kill_cli_before_its_successful_actual_exit`:
  `ExecutionHostFailed: Docker CLI deadline exceeded`. Re-running its complete
  module separately produced **8 passed in 2.14 seconds**. This successful
  repeat does not erase the full-run failure, and no runtime fix is claimed.
- `tests/test_pdf_ingestion.py::test_pdf_malformed_form_text_is_refused_before_parent_can_swallow_error`:
  the expected `ValidationError` was not raised.

本地与云端按平台分别记录，不将不同环境的通过数相加；单独复跑成功也不覆盖原全量失败。

One additional local failure has been independently reproduced with both
`temporalio` and `psycopg` imports explicitly blocked:
`tests/test_pdf_ingestion.py::test_pdf_malformed_form_text_is_refused_before_parent_can_swallow_error`
fails because the expected `ValidationError` is not raised (`pypdf 6.21.2`).
This failure does not require the newly installed Temporal dependencies.

The unchanged `remote-contracts` job also has a distinct pre-existing failure:
[run 39894352516](https://github.com/RalfNick/relf-agent/actions/runs/39894352516),
job `120221194620`, reported **129 failed, 394 passed** in the two-worker
Temporal contracts/History replay step. Many failures are
`temporalio.workflow._exceptions.NondeterminismError`, rather than missing
imports. SDK source, tests, `pyproject.toml`, and this job's installation command
are unchanged between that evidence and this repair. No History failure is
claimed fixed by adding the missing matrix extra.

依赖修复与贡献指南已随 `3878e74` 推送。本记录与机器可读失败清单作为仓库验收证据归档；
其余 SDK CI 问题保持待办状态，后续单独处理。其他会话的发行文档改动保留。
