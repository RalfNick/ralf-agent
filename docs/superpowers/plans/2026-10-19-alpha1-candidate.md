# 0.1.0a1 候选准备计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 冻结首个 Local 基础 SDK Alpha 范围，统一版本与制品，完成有限候选验收及发布材料后仅本地提交。

**Architecture:** 保持 fc128b8 的产品行为、执行权威、协议和依赖；产品只更改包版本。复用已有测试、starter、连续教程与隔离安装，不增加运行时能力。旧制品及失败证据不可覆盖。

**Tech Stack:** Python 3.11–3.13、setuptools/build、pytest/Ruff、Linux ARM64 Docker。

**Spec:** 用户本轮指令；[发布流程](../../releasing.md)、[当前能力](../../implementation-status.md)、[Linux 修复](../../../architecture/reviews/2026-10-19-dev123-linux-test-fixes.md)。本轮有限范围冻结于 docs/releases/0.1.0a1.md。

## Global Constraints

- 不扩展新功能，不改 Schema／Release／Worker 协议或底层身份算法。
- 函数指纹专项、S2、全量／额外旧 History 资格、真实模型和未选服务不启动；保留原失败和验收门槛。
- 验证矩阵仅覆盖明确选定的基础 SDK；Linux ARM64 仍为2CPU／2GiB、无额外swap，3.11→3.12→3.13串行、测试前断网。AMD64／Windows／远端CI不虚报。
- 原 dev123 wheel、sdist和292文件Linux修复证据不改写。新目录为 dist/alpha1-candidate/，制品不得混入历史包。
- 产品与测试先固定，验证后仅补验收文档；最终sdist须包含修复后的测试／文档，核对sdist重建wheel的产品与元数据。
- 最后一次本地提交使用单次 core.hooksPath 参数；不改持久配置、不推送、不建远端Tag或公开发布。

## Review Focus

- wheel、sdist、安装包、CLI版本及产品字节对应；原包不能仅改名上传。
- 安装不从checkout或editable获取代码；sdist包含新测试辅助模块、教程与许可证。
- 原308用例和3个并发回归不丢失，16个独立恢复与两条starter仍验证业务效果次数。
- 当前安装文档无dev121/dev123推荐歧义；未公开的PyPI命令／Release不作为可用入口。
- 不用不同历史快照的结果宣称本候选通过，不把版本号升级等同历史任务兼容。

### Task 1: 冻结范围与版本

- [ ] 创建首版说明，分基础支持、实验性、未验收；记录API和历史任务限制。
- [ ] 同步pyproject、__version__、README、安装／首用、CHANGELOG、当前状态和发布入口。
- [ ] 检查产品只有版本赋值发生变化；不新增镜像／后端／依赖。

### Task 2: 固定制品与候选验证

- [ ] 将声明输入导出到干净目录，保存逐文件清单；构建唯一候选wheel，验证包内容和元数据。
- [ ] 复用dev123的21模块源码范围（新增Linux回归包含在内）；独立安装9模块、11项异步组合和连续教程，记录实际用例数与跳过。
- [ ] 候选wheel在同缓存Linux镜像串行运行311项基础、16项恢复、两条starter，固定第三方版本、收集资源和退出证据。
- [ ] 文档收口后从固定输入构建sdist；核对产品／测试／文档，离线重建wheel核对产品／元数据，并做sdist安装smoke。

### Task 3: 验收材料与本地提交

- [ ] 一次独立只读整批审查，修正本范围内的阻断问题，不扩功能。
- [ ] 保存delivery.json、SHA256SUMS、源码／安装／Linux证据和发布待办；未执行的公开安装／服务清楚标记。
- [ ] Ruff／格式／Git空白及制品校验通过，单次跳过钩子本地提交；核对无推送和持久钩子配置变化。
