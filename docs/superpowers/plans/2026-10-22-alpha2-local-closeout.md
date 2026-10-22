# Alpha 2 本地发布收尾计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将包含近期修复的 `0.1.0a2` 固定为唯一当前 Alpha 候选，完成可复现制品、本地安装与交接材料后仅本地提交。

**Architecture:** 保持 `8e09ec7` 的 SDK 行为与执行权威；产品仅改包版本。复用既有 311 基础／16 恢复／2 starter 门禁及依赖锁，保留原 a1 输入和历史验收，分别记录 dev19 专项与新候选证据。

**Tech Stack:** Python 3.12、setuptools/build、pytest/Ruff、现有离线 wheelhouse。

**Spec:** 用户本轮指令；[发布指南](../../releasing.md)、[固定门禁](../../release-gate.md)、[dev19 验收](../../../architecture/reviews/2026-10-21-s2-session-parent-hints.md)。

## Global Constraints

- 不扩功能、不改依赖、Schema、运行协议、算法或业务门槛；SDK 仅版本赋值改变。
- 旧 a1、dev19 及全部失败和私有原始证据不覆盖；不把旧包平台成绩回填新候选。
- 干净导出只包含 Git 跟踪文件及本批明确声明的新文件；排除网站等无关未跟踪内容。
- 本批执行本地 macOS ARM64／Python 3.12 安装、基础门禁和 sdist 重建；Linux 与远端 CI 列为待验，不自行启动。
- 保留旧 a1 手动工作流的原版本执行入口，避免默认 manifest 更新后读取 a2 输入。
- 源来源明确为 `8e09ec7` 加本批发行工作区，以逐文件摘要固定；不冒称原提交已包含新版本。
- 制品内嵌 manifest 为构建时快照；最终制品摘要在外置 manifest 固定，避免 sdist 自身 SHA 循环依赖。
- 完成后单次跳过钩子本地提交；不改持久钩子配置，不推送、触发远端 CI、创建公开 Tag 或发布。

## Review Focus

- 当前版本／CLI／wheel／sdist 与外置 manifest 一致；旧 a1 摘要精确保留。
- 新候选不能默认继承 a1 平台通过，也不能把 S2 已验收重新写为后置。
- 原 311／16 node 身份、断言和两次单效果 starter 保持；新源码已包含原受控Session测试校正，不重复改写新sdist。
- sdist 的完整产品、测试辅助、文档和许可证可离线构建；不存在源码路径偷导入。
- 版本外的产品逐字节不变，历史 selected Worker 限制和已知未知异常充分披露。

### Task 1: 固定版本、门禁与当前文档

- [x] 先更新发布门禁测试，验证新默认版本、历史 manifest 和当前版本一致约束的 RED。
- [x] 保存原 a1 manifest；更新 `pyproject.toml`／`__version__`、当前文档和候选说明。
- [x] 将旧 a1 工作流 checkout 固定到原通过的 `0b9b6c9`，保留其原包行为；不新增或触发 a2 远端工作流。
- [x] 构建前运行 gate／preflight／staging 维护测试及 Ruff、格式和文档链接检查。

### Task 2: 构建并验证不可覆盖的候选

- [x] 导出声明输入到新隔离目录，冻结产品／测试／文档清单；离线构建 wheel／sdist。
- [x] 依据两包精确摘要生成最终外置门禁 manifest；原基础集合与资源标准保持。
- [x] 源码外执行默认基础门禁（311／16／2），记录实际安装模块、版本和效果次数。
- [x] 从 sdist 离线重建 wheel，核对完整产品、元数据与许可证，并安装验证两条 starter 和连续示例。
- [x] 核对只有版本文件与 dev19 产品不同；旧包摘要与失败证据保持。

### Task 3: 收口与本地提交

- [x] 整理 `delivery.json`、`SHA256SUMS`、本地报告及待验 Linux／远端／公开交付列表。
- [x] 进行一次整批只读复核，修正本批交付问题；不重启服务或模型专项。
- [x] 完成本地预检、受影响维护测试、文档和 Git 检查；仅暂存本批明确路径。
- 单次跳过钩子的提交与核对按用户授权执行，实际回执以本轮Git日志为准；到远端CI交接边界停止。

执行结果见[本轮验收](../../../architecture/reviews/2026-10-22-alpha2-local-closeout.md)。本文件在构建后补记完成状态；制品保留其已登记的原输入快照。
