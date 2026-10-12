# DeepSeek Thinking Implementation Plan

**Goal:** 补齐R05思考续接适配以及R07/R01完整配置与业务链路，保留完整长期目标。
**Architecture:** 新Provider+现有ModelContinuation/ModelHistory；Local和Temporal原执行权威。
**Spec:** [Native continuation design](../specs/2026-10-13-deepseek-thinking-design.md)。

## Parallel tasks

- [x] A：独立deepseek_thinking.py，JSON/SSE/续接原消息、严格参数/usage/owner/证据限额；新协议测试先RED后GREEN。
- [x] B：SDK导出、Registry、Local/Temporal Profile、模型兼容/规划/RAG/团队CLI；配置与旧默认回归。只编辑装配/入口，不编辑执行权威。
- [x] C：新Local原生/编排/Session恢复测试、实际Temporal Worker恢复/replay夹具；不修改Provider/装配产品文件。
- [x] Root：集成、真实服务、旧默认/安装验证、文档/能力/验收与版本；一轮独立review、最终全量回归；本地提交以Git回执确认。

## Gates

- [x] 原模型响应和原argument字符串完整保留；默认工具参数只作用于实际执行。
- [x] 最终assistant reasoning跨Turn继续回传；无跨Agent原生历史污染。
- [x] 原审批/未知效果/取消/收到→采纳持久化恢复；Temporal实际服务和History重放。
- [x] 无新增核心依赖，独立安装执行；旧dev89默认和原Run兼容。
- [x] 文档如实区分协议、真实服务、模型质量和采用；完整R01–R26不标完成。
- [x] 最终验证完成并准备本地提交；提交以Git回执确认，不推送。
