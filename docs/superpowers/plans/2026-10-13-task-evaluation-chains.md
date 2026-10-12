# RAG 与 Plan／Team 端到端评测 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans／dispatching-parallel-agents；独立文件并行，共享导出、CLI、证据与验收由root集成。

**Goal:** 实际运行RAG与推荐Plan／Team并报告可复现的任务、来源与恢复结果。
**Architecture:** 复用原Runtime／AgentHarness／Ingestion／Retrieval和执行事实，不增加状态机。每例私有数据，固定案例／限额与独立oracle，默认离线、真实配置显式。
**Tech Stack:** Python3.11+，现有httpx/jsonschema、SQLite、pytest；无新增必需依赖。
**Spec:** [任务链路设计](../specs/2026-10-13-task-evaluation-chains-design.md)。

## Global Constraints

- 不推送远端，不隐式收费、下载或发现凭据；客户端borrowed，评测资源owned。
- 未完成Run只观察，已采纳恢复不重复模型／工具／索引写；原Local／Temporal权威保持。
- 原始内容留私有证据，公开报告仅有限字段／digest；失败及未尝试重复保留。

## Review Focus

- 正确答案配假的／旧版引用仍失败：Task1 oracle负例。
- 可用文档未进入实际模型上下文：Task2以Action引用评分。
- Embedding失败、额度耗尽及取消：Task2关闭／失败分母与真实请求计量。
- 正确最终值但错误工具参数／缺上游证据：Task3工具事实评分。
- 重连未完成Run不能新增外部调用：Task2/3恢复负例。

## Task 1：冻结RAG数据与纯oracle（独立worker）

Files: `src/ralf_agent/rag_evaluation_cases.py`、`evals/rag-cases.json`、`tests/test_rag_evaluation_cases.py`。
Produces: `RAG_OUTPUT_SCHEMA`、`load_rag_cases(path=None)`、`score_rag_answer(case, output, references)`，均有限JSON／纯校验，默认至少八类独立案例。

- [x] 写并运行失败测试：版本／namespace／digest／quote／coverage错误不能得通过，metadata和返回值detached。
- [x] 实现固定case schema与机器oracle，配置无副作用。
- [x] 验证正例、多引用及拒绝／缺证据；提供RED/GREEN。

## Task 2：RAG实际链路（root）

Files: `src/ralf_agent/rag_evaluation.py`、`src/ralf_agent/rag_evaluation_cli.py`、`tests/test_rag_evaluation.py`。
Consumes Task1 APIs；Produces `evaluate_rag(provider=None, *, embedding=None, cases=None, limits=None, evidence_dir=None, offline=False, prices=None, max_embedding_calls=128)`及CLI。

- [x] 写失败测试：真实SQLite摄取／索引／原模型Action引用；无凭据默认not_run；替换Provider/Embedding；失败分母。
- [x] 复用推荐Profile2＋工厂、IngestionCoordinator、Hybrid、审计Provider和独立Embedding计量。
- [x] 验证终态恢复不新增调用、引用负例、期限／预算、拥有关系与实际退出窗口。

## Task 3：Plan／Team全执行（独立worker）

Files: `src/ralf_agent/orchestration_evaluation.py`、`tests/test_orchestration_evaluation.py`。
Produces `evaluate_orchestration(provider=None, *, kind="plan-and-execute", cases=None, limits=None, evidence_dir=None, offline=False, prices=None)`及`load_orchestration_cases()`；provider由外部借用。

- [x] 写并运行失败测试：两种Harness的前序证据、实际工具参数、最终金额、重复回执和缺输入停止。
- [x] 使用版本2推荐Runtime／Harness及原受管理成员，每例独立数据与冻结输入。
- [x] 验证model失败／未知不重试、总调用限额、重复分母及恢复；提供RED/GREEN。

## Task 4：共享入口、文档与最终验收（root）

Files: `src/ralf_agent/__init__.py`、`pyproject.toml`、能力文档与`architecture/reviews/2026-10-13-task-evaluation-chains.md`。

- [x] 注册SDK／CLI，完成安装后默认／真实显式配置教程和能力矩阵。
- [x] 一次独立review，统一修复；冻结产品后全量、独立安装、旧版回执与制品一致性。
- [x] 保存实际证据、未验收范围和后续依赖，仅本地提交；保持完整目标active。

实际验收见[本批记录](../../../architecture/reviews/2026-10-13-task-evaluation-chains.md)。任务检查完成只对应本批声明子集，不关闭真实质量、完整H3／M1或R01–R26。
