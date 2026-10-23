# Alpha 6 验收与待处理清单

更新：2026-10-23。`relf-agent==0.1.0a6` 统一 Python 导入 `relf_agent` 和 CLI `relf`／`relf-*`，复用已有能力；配置、数据库和协议标识保持。旧 a5 及更早制品与证据保留。原包 SHA 见 [a6 说明](releases/0.1.0a6.md)。

| 事项 | 状态 |
| --- | --- |
| 公共入口和生成应用 | 442 个产品文件迁移；8 个新命令、独立应用和可执行提示通过；不提供旧入口 shim |
| 受影响的源码回归 | 329 passed，0 failed／error |
| 完整源码回归 | 14234 passed、891 skipped、0 failed／error |
| 原 wheel／macOS 3.12 | 固定 311 基础／16 恢复／两 starter 全部通过；warnings-as-errors、节点摘要和锁定依赖保持 |
| sdist 重建安装 | 重建 wheel 与原 wheel SHA 一致；380 passed、1 skipped，另 8 项安装后身份校验通过；8 个命令 `--help`、两 starter、pip check 通过 |
| Linux ARM64 三 Python | 3.11–3.13 串行；每版原 311／16／2 全部通过，2 CPU／2 GiB／swap0／断网，无 OOM，容器均清理 |
| 网站 | 25 项测试、类型、14 对文档来源、固定历史教程、生产构建及 48 个本地链接通过；未部署 |
| 制品和历史 | wheel／sdist／源码产品一致；Twine strict、离线 preflight 通过；原 a4／a5 包按旧身份 handoff 通过 |
| 原生 AMD64／远端 CI | 尚未执行 a6 自己的验证；不继承 a4／a5 结果 |
| 账号、上传与公开安装 | 未执行，`publication_ready=false` |

sdist 独立安装未含可选 PyYAML，`test_alpha6_workflows` 模块按依赖条件跳过；源码环境已验证该模块。全量源码中的旧 old83／a5 共享模块恢复场景保留原 case 节点，明确跳过 a6 不支持的跨模块迁移；此项不计为恢复验收通过。其他真实服务／模型条件按实际报告记录，未借离线成绩补签。

旧 Run、History 和函数身份不自动迁移；原 SDK 环境、配置、组件与 Worker 继续保留。新包选择独立环境和新任务数据。构建输入快照与最终外置记录分开，具体失败、review 和结果见 [本批记录](../architecture/reviews/2026-10-23-alpha6-entrypoints.md)。本轮仅本地提交，单次跳过钩子，不推送、触发远端 CI、配置账号、部署网站或公开发布。
