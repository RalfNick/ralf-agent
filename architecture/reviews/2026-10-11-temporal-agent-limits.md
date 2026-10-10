# dev61 Temporal Agent Limits 验收

日期：2026-10-11；基线为已提交 dev60 / 5c7c598。范围是 R01/H1f 的 Temporal 宿主及每 Agent 限制策略；完整 R01–R26/H1–H5 保持开放。

## 实现与边界

新增纯 LimitsPolicy Activity 返回 host/agent 原始提案，由原 Run History 校验并采纳 AgentSpec 交集。实际 Agent 节点独立保存 caps，Context／managed 压缩／模型使用原值，工具 Actions 批次整体准入。登记版本、实际对象和方法固定；disabled 不关闭宿主，预算／审批／效果恢复不变。默认无 limits 发布不变；新限制使用显式 limits_protocol=1/temporal-3。没有第三套执行权威。

纯策略不能含模型、存储或业务 I/O；数值在每实际 Agent 节点首次推进时采纳，不由 Parent 或客户端计算。父级共享工具额度、全局容量、货币费用保证、其余角色与完整 H3 质量不在本批交付范围。

## RED → GREEN 与审查

- 首轮8项缺接口 RED；非法 bool 协议、缺 registration 和宿主模型请求 Scope 分别复现修复。
- 独立只读 review 的 P2：宿主 limits 无 BindingCatalog 时显式 inherit/disabled 受旧协议门槛拒绝，2项 RED→GREEN；有 limits 的发布启用 temporal-3。
- Minor：畸形失败 code 可成为 null／bool／object，5项 RED→GREEN，统一稳定 validation_error。
- 实际 SDK 沙箱的 P2：纯模块抛出的 AgentLimitExceeded 与 Workflow 异常类身份不同，工具超限卡在 Workflow Task 重试。纯规则返回布尔准入，原状态机自行拒绝；实际6项普通／managed 宿主／自定义策略全部 GREEN，业务工具零派发。
- 自定义纯 Python 策略遵循已有指纹要求：有限 JSON 闭包配置，推荐模块级类型导入。测试中的闭包类型捕获被原注册规则拒绝后，改用模块级策略；未放宽身份固定规则。
- 独立 review 无其他 P1/P2。声明外的共享额度、隐藏 I/O 的隔离执行及真实模型质量继续分别验收。

## 实际证据

任务目录：`/private/tmp/ralf-agent-dev61-a9_qqoh4`；Python3.12.7／Temporal SDK1.34.0／官方 CLI1.9.1、Server1.32.0。本轮未调用真实收费模型，未推送。

- 源码实际恢复12项通过（93.11s）：Agent／sequence／Graph／Team／动态 DAG／嵌套，各普通／managed。限制采纳后安全 Context read 期间杀 Worker，重启、重连、完成并 replay；审计证据每节点策略响应一次、业务模型一次。
- 修复后源码实际宿主／自定义策略6项通过（6.86s），限额0时工具零派发，并 replay。
- 最终安装 wheel 在仓库外实际18项通过（83.82s），覆盖上述恢复与超限组合；安装绑定契约85项通过（1.96s）。
- 209个 Python 模块在源码、wheel、sdist 和实际安装中逐字节一致。最终文档归档在全量结果写入后重建校验。
- 独立 core-only 环境没有 temporalio/redis/psycopg/tiktoken/pypdf；实际 wheel 离线索引／原 Run 回执恢复，以及纯 limits 协议采纳和模型完成通过。这不是无 SDK 的服务部署声明。
- 实际60→61→60安装默认 Context/Run/Manifest/SQLiteArtifact/21 starter保持；默认 Temporal1/2/3与原 Knowledge release相等。实际旧 Worker 审批 → 新 Worker 审批/重复回执/单次工具 → 旧 Worker 查询原回执，以及新代码 History replay通过。旧安装拒绝新限制发布，模型零派发。
- 最终全量 `3492 passed / 164 skipped`（523.45s，56122退出0）；跳过项是未配置的服务／模型条件。Ruff、752文件格式与Git空白通过。未运行本机Python3.11/3.13矩阵。
- 本批自有 Temporal Service83761退出0，stopped标记确认；所有测试 Worker在 finally 关闭。

## 验证过程说明

第一轮实际恢复测试在停止 Worker 后先 attach/query，服务无 poller，2项失败；改为先重启 Worker再重连，未计原失败轮为验收。第一轮全量在修复期间中断（1026通过/12跳过，227.39s），不算完整回归。一次安装契约在升级目录时过早启动，8项混合代码失败；等待最终安装结束再运行85项全部通过。最终验收仅采用固定代码/版本的完整运行。
