# Alpha 6 验收与待处理清单

更新：2026-10-24。`relf-agent==0.1.0a6` 统一 Python 导入 `relf_agent` 和 CLI `relf`／`relf-*`，复用已有能力；配置、数据库和协议标识保持。旧 a5 及更早制品与证据保留。原包 SHA 见 [a6 说明](releases/0.1.0a6.md)。

**当前维护源码与冻结包分开判断：** 本次新增同步装配中断清理修复，仅存在于 a6 后的未发行维护源码；原 a6 wheel／sdist、manifest 和下表原包成绩保持，不包含该修复。未重建同版本包或准备新候选。维护回归与原始失败另见[review 修复验收](../architecture/reviews/2026-10-24-alpha6-review-fixes.md)。

| 事项 | 状态 |
| --- | --- |
| 公共入口和生成应用 | 442 个产品文件迁移；8 个新命令、独立应用和可执行提示通过；不提供旧入口 shim |
| 受影响的源码回归 | 329 passed，0 failed／error |
| 完整源码回归 | 14234 passed、891 skipped、0 failed／error |
| 原 wheel／macOS 3.12 | 固定 311 基础／16 恢复／两 starter 全部通过；warnings-as-errors、节点摘要和锁定依赖保持 |
| sdist 重建安装 | 重建 wheel 与原 wheel SHA 一致；380 passed、1 skipped，另 8 项安装后身份校验通过；8 个命令 `--help`、两 starter、pip check 通过 |
| Linux ARM64 三 Python | 3.11–3.13 串行；每版原 311／16／2 全部通过，2 CPU／2 GiB／swap0／断网，无 OOM，容器均清理 |
| 网站 | 已迁移固定 a6 源码教程并于 2026-10-23 部署；25 项测试、14 对双语指南、49 个固定源码目标、网站 CI 和 95 项 HTTP 核对通过，见[独立网站记录](../website/reviews/2026-10-23-relf-a6-docs-acceptance.md)；网站资格不代签 SDK 发布 |
| 制品和历史 | wheel／sdist／源码产品一致；Twine strict、离线 preflight 通过；原 a4／a5 包按旧身份 handoff 通过 |
| 原生 AMD64／远端 CI | 尚未执行 a6 自己的验证；不继承 a4／a5 结果 |
| 账号、上传与公开安装 | 未执行，`publication_ready=false` |

sdist 独立安装未含可选 PyYAML，`test_alpha6_workflows` 模块按依赖条件跳过；源码环境已验证该模块。全量源码中的旧 old83／a5 共享模块恢复场景保留原 case 节点，明确跳过 a6 不支持的跨模块迁移；此项不计为恢复验收通过。其他真实服务／模型条件按实际报告记录，未借离线成绩补签。

旧 Run、History 和函数身份不自动迁移；原 SDK 环境、配置、组件与 Worker 继续保留。新包选择独立环境和新任务数据。构建输入快照与最终外置记录分开，原失败、review 和结果见 [a6 原包记录](../architecture/reviews/2026-10-23-alpha6-entrypoints.md)。原入口提交 `ba1c81f` 后已按授权推送，网站迁移和部署有上述独立记录；这些后续事实不改写原准备批次的操作范围。

本次 2026-10-24 维护仅本地提交，单次跳过钩子，不推送、触发远端 CI、配置账号、部署网站或公开发布。维护源码的产品树与原 a6 manifest 不再相同，原包的远端门禁应使用匹配的固定源码；不能修改原 manifest 的 SHA 来接纳维护源码，也不能用维护回归替原包补签平台资格。
