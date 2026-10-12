# dev91 Responses reasoning 实施计划

设计：[已授权连续开发范围内的设计](../specs/2026-10-13-responses-reasoning-design.md)。独立文件并行，根任务统一集成；不推送。

## 1. 原生协议（Provider 任务）

- [x] tests/test_responses_reasoning.py、test_responses_reasoning_stream.py 先证明缺失适配器/边界失败，记录有效 RED。
- [x] src/ralf_agent/responses_reasoning.py、responses_reasoning_codec.py、responses_reasoning_stream.py 实现 OpenAIResponsesReasoningProvider 及纯编解码；不改旧 Provider/Engine/History。
- [x] 验证 raw 有序 output、phase 语义、原参数、128KiB、256 calls、ID1024/name64、所有推理参数、工具组/owner、完整 SSE 和客户端关闭；运行相关旧协议。

## 2. 装配与评测 CLI（Assembly 任务）

- [x] tests/test_responses_reasoning_assembly.py、test_responses_reasoning_cli.py 写 SDK/registry、sync/async、绑定、Temporal、缺 opt-in 零 owned 工厂与四 CLI 选择的 RED。
- [x] src/ralf_agent/__init__.py、runtime_builder.py、四 *evaluation_cli/model_check_cli.py 接入；新推理字段按适配器验证，旧默认字节不变。
- [x] 新 JSON/TOML Profile 默认/ref 和四 CLI 缺凭据零调用测试及既有声明回归。

## 3. 运行/恢复（Integration 任务）

- [x] tests/test_responses_reasoning_runtime.py、test_responses_reasoning_evaluation.py 从缺失 Provider 的有效失败开始。
- [x] 验证 JSON/SSE 原工具循环+RAG、审批和双重复控制、receipt/adoption真实进程退出、两Turn重建、graph/team/ModelPlanner/nested、评测不宣称质量。
- [x] temporal_responses_reasoning_worker.py、test_temporal_responses_reasoning_service.py 验证 native/graph×approval/receipt 与原final Session恢复；记录 PID/队列/原回执/效果/重放与真实关闭。没有服务时跳过不能计通过。

## 4. 集成与文档（根任务）

- [x] docs/responses-reasoning.md 提供可安装 SDK/TOML/CLI 例子及替换/限额/恢复边界。
- [x] 同步 R05/H3/M1/remaining-work/模型矩阵/CHANGELOG，版本 dev91；CI 加 source/wheel 的 DeepSeek/Responses 实际服务覆盖。
- [x] 一次 fresh whole-batch review，发现用 RED/GREEN 修复，再冻结产品。
- [x] 完整 pytest、Ruff/format/空白；wheel/sdist 构建及模块字节校验；独立核心/SDK安装、文档真实例子、旧90默认/原Run兼容。
- [x] 自有 Temporal 服务停止并实际 wait：PID2360、session83714 实际退出0，关闭标记及PID消失已核实。
- [x] 最终完整源码结果及未验收范围已记录；提交范围已冻结，本地提交结果以私有 Git 回执为准，不推送。

## Review Focus

每一项归属于相应测试：commentary 不能误作 JSON/最终完成；SSE added 密文前缀不能误判与final冲突；signed raw参数与ToolAction默认分离；缺opt-in/无关CLI选项在任何owned I/O前拒绝；最后一次模型回执恢复和跨Turn须保存所有原reasoning/phase，而非仅最后工具组。
