# dev15 动态图、嵌套、交接、分布式与质量实施计划

规格分别见 [DAG/嵌套](../specs/2026-10-07-dag-nesting-design.md)、[MQ/A2A](../specs/2026-10-07-remote-handoff-design.md)、[Temporal](../specs/2026-10-07-temporal-execution-design.md)、[规划质量](../specs/2026-10-07-planning-quality-design.md)。用户明确授权继续实现；保留当前工作区增量，不重复设计批准，不提交/发布。

1. 编排主线：先缺失契约RED；spec_codec.py、dag_planning.py、dag_runtime.py；嵌套定义/Manifest/escrow；修改 orchestration/types/engine/config/诊断并保持旧字节身份。验证DAG/patch/嵌套/取消/恢复。
2. 独立交接：messaging.py、redis_streams.py、handoff.py、a2a.py/ASGI、对应新测试。先接口RED，后真实Redis/HTTP、消息重放/崩溃与受管理工具接入。
3. 独立Temporal：temporal.py、temporal_workflow.py、temporal_activities.py、temporal_journal.py、新测试/Worker fixture；先接口RED，再真实Service/两个Worker/20次契约探针/History replay。基础安装依赖不变，显式extras。
4. 独立评测：planning_evaluation.py、冻结 evals/planning-cases.json 与Schema/oracle、examples/evaluate_planning.py、新测试；先fixture/缺失入口RED。与主线ModelDAGPlanner接入后按实际可用模型/预算运行，不伪造评分。
5. 集成：根线程独占公共exports、ports、配置、版本dev15、文档/starter/CI与旧包兼容；其他独立任务不编辑共享文件。在独立契约失败确认后按 dispatching-parallel-agents 隔离实现。
6. 一次最终独立只读审查，重要发现TDD修复；完整真实服务suite、wheel/sdist/安装、实际dev14升级、原模板兼容、文档质量；停止任务临时服务。模型评测的未完成外部条件单独保留，服务/协议未支持能力显式拒绝。

## 执行结果

1–5实现与测试已完成；6的一次独立审查、三处修复、真实服务suite、wheel/sdist/安装、实际dev14兼容和文档验证完成。证据见[审查记录](../../../architecture/reviews/2026-10-07-dag-remote-execution.md)。真实模型付费评测保持not_run，等待Provider/model/调用或费用限制配置；已交付可运行入口，不将离线fixture算模型质量。完整Temporal编排/企业治理与M1剩余门槛未标完成。
