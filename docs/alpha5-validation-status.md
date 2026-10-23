# Alpha 5 验收与待处理清单

更新：2026-10-23。当前准备`relf-agent==0.1.0a5`，保留`ralf_agent`导入和`ralf`CLI。仅迁移发行元数据、安装提示与发布校验，不新增SDK能力。原a4包、实际Linux验收及历史失败保持，公开安装仍为[a2原包](releases/0.1.0a2.md)。

| 事项 | 当前状态 |
| --- | --- |
| 发行身份及兼容 | a5显式使用relf-agent；导入／CLI／配置与协议标识保持，旧manifest默认ralf-agent |
| 新版原wheel／sdist与外置manifest | 已独立冻结，442产品一致，精确SHA见[a5说明](releases/0.1.0a5.md)；不覆盖a4 |
| 发布与兼容测试 | 243项通过；旧a4原包用新预检及原源码复核通过；历史默认发行名保持 |
| 完整源码回归／macOS ARM64 Python3.12 | 14176通过／891条件跳过，零失败／错误，2283.25秒；不作为远端CI或未配置服务的通过证明 |
| macOS ARM64／Python3.12安装门禁 | 最终原包311基础／16恢复／两starter通过，零失败／错误／跳过 |
| sdist独立重建、安装与连续示例 | 330项与两starter通过，含五阶段连续示例；产品、元数据、许可证及重建wheel SHA一致 |
| 文档与固定教程 | 说明新旧发行关系，原a1教程基线、公开a2安装入口和历史记录保留 |
| Linux ARM64 Python3.11–3.13 | 同两包、2CPU／2GiB／swap0／断网串行，各311／16／两starter通过；峰值326.99MiB，零OOM，容器已移除 |
| 原生AMD64 Python3.11–3.13 | 未运行；需要获准推送与触发a5远端固定门禁，不能复用a4 run |
| 官网与静态检查 | 25项网站测试、类型、双语来源锁、固定a1教程、生产构建、本地链接检查及Ruff／格式通过；未部署网站 |
| 远端CI、账号／Publisher／保护环境 | 本轮不执行；原a4 run不可放行a5 |
| TestPyPI／PyPI、GitHub Release及公开安装 | 未执行，不公开发布，publication_ready=false保持 |

同一导入树不允许新旧发行共装；a5使用独立环境，旧任务保留原环境与匹配组件。更广SDK CI的既有失败见[独立清单](../architecture/reviews/2026-10-23-sdk-ci-dependency-fix.md)，本次不修复或关闭。所有成绩按实际输入、平台和范围分开登记，不合并为全量或企业资格。详见[a5说明](releases/0.1.0a5.md)与[PyPI准备](pypi-publishing.md)。
