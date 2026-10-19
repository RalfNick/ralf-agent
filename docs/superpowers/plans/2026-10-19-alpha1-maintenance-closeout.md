# Alpha 首版剩余维护优化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成用户确认的首版冻结范围内维护优化，复用原 a1 制品，不新增 SDK 功能。

**Architecture:** 继续使用既有离线核心门禁；Linux 包装器在采纳报告时核对完整请求身份、所选结果与资源，并自动记录维护工具来源。镜像通过标准 Docker 导出／加载搬运。缺少真实平台或网络证据的能力保持未验收。

**Tech Stack:** Python 标准库、pytest、既有 Docker ARM64 镜像和锁定 wheelhouse。

**Spec:** 用户本轮确认“首版范围内全部剩余优化”，以及[首版冻结范围](../../releases/0.1.0a1.md)和[现有门禁](../../release-gate.md)。

## Global Constraints

- 不改 src、版本、运行依赖、Schema、执行权威或原 a1 制品。
- 函数指纹专项、S2 和原失败／门槛继续后置；不运行全量套件。
- Linux 保持2 CPU／2 GiB、swap0、network=none和三个Python版本串行。
- 不推送、不建公开Tag、不公开发布；最后单次跳过钩子本地提交。
- AMD64／远端CI／公开发行／独立采用无实际证据时不标完成，不为网络阻塞反复重试。

## Review Focus

- 子报告状态为通过，但制品／工具摘要、架构或原测试结果不匹配，必须拒绝。
- 子报告资源无限制、有OOM或skip，不因passed字符串而放行。
- 报告缺字段、字段类型错误、迟到或与本轮输入漂移，不能确认通过。
- 新增来源记录应在Docker创建前落盘；异常创建原清理规则保持。
- 离线镜像导出只搬运既有镜像，不声称在未验证宿主或AMD64原生通过。

### Task 1: 报告采纳与自动来源记录

**Files:** Modify tools/run_release_gate_linux.py, tools/release_gate.py, tools/release_gate_manifest.json; Test tests/test_release_gate.py, tests/test_agent_sessions.py, tests/test_session_turn_wait_contract.py.

**Interfaces:** verify_report(report, spec, minor, inputs, artifacts) 返回bool；inputs为本轮四份维护工具摘要，artifacts为实际复制的制品摘要。现有CLI和ARM64默认保持。

- [x] 先写有效完整报告及错误制品／工具／架构／结果／资源／缺失字段的回归，观察有效RED。
- [x] 验证本轮报告身份、完整311／16／2结果、资源与OOM，记录matrix-input.json及包装器快照。
- [x] 门禁单测与现有异常清理测试GREEN；执行同一a1包实际ARM64三版本串行门禁。

补充定位：首轮3.12原Session测试遗漏idle条件，受控宿主暂停稳定复现；只修测试，原sdist保持不变。维护manifest显式固定校正前后SHA及唯一替换，核心门禁在原输入树验证后处理；311／16 node和业务门槛保持，原失败不覆盖。

### Task 2: 离线复现与能力状态收口

**Files:** docs/release-gate.md; docs/session-api.md; docs/releases/0.1.0a1.md; docs/remaining-work.md; docs/implementation-status.md; architecture/reviews/2026-10-19-alpha1-maintenance-closeout.md.

- [x] 用标准docker save导出现有三镜像，核对归属、导出文件及SHA；提供load和离线验证路径。
- [x] 保留Docker Hub超时／下载结果；可取得固定AMD64镜像才按原限额验证，否则列为未验收，不增加未验证适配器。
- [x] 区分已完成的本地维护与外部发行／CI／采用步骤，保留所有原失败和后置项目。
- [x] 独立整批只读复核一次，修复影响门禁正确性的发现；Ruff／格式／文档链接／制品不变校验通过后，本地提交，不推送。
