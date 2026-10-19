# 版本、设计与验收记录

[文档目录](README.md) · [当前支持状态](implementation-status.md)

历史文档保留发布或验收时的版本、条件与结果。它们用于追溯设计和验证证据；开始使用时请阅读当前指南与实现清单。不同快照的测试数量、制品哈希和模型质量结论不能合并为一次验收。

## 版本与历史入口

| 记录 | 内容 |
| --- | --- |
| [CHANGELOG](../CHANGELOG.md) | 按版本记录的变更 |
| [旧 README 完整快照](archive/README-2026-10-18.md) | 本次整理前的首页，保留版本演进、验收链接及旧入口 |
| [早期实现进度](implementation-progress.md) | M1 Local 阶段的开发记录 |
| [Phase 1 SingleAgent 证据](phase1-single-agent.md) | 对应冻结版本的参考任务证据 |
| [DeepSeek dev21 试验](live-model-quality.md) | 该版本与固定配置下的真实模型结果 |
| [DeepSeek dev28 试验](live-model-quality-dev28.md) | 业务失败、运行事实及边界 |
| [DeepSeek dev29 试验](live-model-quality-dev29.md) | 完成验证试验结果 |

## 架构与开发过程

- [总体设计](../architecture/design.md)与[架构取舍](../architecture/review-resolution.md)。
- [架构视图](../architecture/viewpoints/)：Harness、能力分层及目标设计。
- [运行时契约](../architecture/specs/)：Run、Action、Runner、绑定与部署协议。
- [架构审查与验收](../architecture/reviews/)：按日期保存问题、修复、制品与验证范围。
- [专题设计](superpowers/specs/)与[执行计划](superpowers/plans/)：开发过程材料。

设计与计划可能包含尚未实现的目标；是否支持以[实现清单](implementation-status.md)、[剩余能力清单](remaining-work.md)及所选制品的验收记录为准。发布流程与本地制品见[发布指南](releasing.md)。
