# 模型适配与流式响应实现计划

> 在当前非主分支按 executing-plans 实施；单人实现，交付前按 requesting-code-review 委派独立只读复核。用户持续授权完善项目，沿用已有执行方式。

**Goal:** 用户可配置国内兼容模型和原生 Anthropic/Gemini 文本模型，并使用可验证的生成参数/完整流式结果。

**Architecture:** 公共能力与流事件 DTO、共享 HTTP/SSE 边界、独立协议转换器；Engine 保持完整响应接收/采纳，仅新增可选纯请求预检。Registry/starter 提供显式开箱入口。

**Tech Stack:** Python 3.11+、现有 httpx；不增加 SDK 或运行依赖。

**Spec:** [模型层设计](../specs/2026-10-06-model-adapters-design.md)。

## Global Constraints

- dev9，local-4/ExecutionStore v1/dev3 摘要不变；默认 Chat identity 与旧离线 starter 保持一致。
- 流工具提案仅在完整完成后返回；不自动重试、降级或执行工具。
- 凭据仅从显式参数/对应环境变量取得；Profile/Manifest 不保存密钥，错误不显示响应正文。
- Gemini 文本工具能力明确 False；不丢弃签名来宣称支持函数往返。
- 本地协议回归不是在线模型兼容；没有真实模型质量成绩。

## Review Focus

- 网络发出前快照/能力/参数校验；mutable 配置变化须反映实际身份。
- SSE 终态后尾部异常、空结束、碎片参数、非有限或重复键 JSON，不能提交部分提案。
- 取消/提前停止流时实际响应/client 生命周期；无隐藏重试与连接泄漏。
- Anthropic 多工具/系统信息和 Gemini 用量、拒绝/截断、不支持的消息/历史不静默丢失。
- 实际旧 wheel 恢复和默认 identity；安装后的 starter 不依赖源码目录。

## Task 1: 公共能力与 Chat 协议

**Files:** providers.py、model_protocol.py/model_http.py；tests/test_model_chat.py。
**Interfaces:** ModelCapabilities(text=True,tools=True,streaming=True)；ModelStreamEvent(kind,text="",response=None)；StreamingModelProvider.stream；OpenAIChatProvider(...,temperature=None,top_p=None,stop=None,seed=None,stream=False,capabilities=None)。

- [x] RED：精确旧 identity、参数/能力/请求及工具 SSE 拼接；错误/截断/取消/用量/限制行为。
- [x] GREEN：共享验证与 SSE HTTP 边界、Chat 完整/流式协议，保留 ModelProvider import。
- [x] 验证旧 Provider/Engine 测试；新增请求预检在派发前执行，旧 Provider 兼容。

## Task 2: 原生协议

**Files:** model_native.py；tests/test_model_native.py。
**Interfaces:** AnthropicProvider(model,...,api_version="2023-06-01")；GeminiProvider(model,...)；两者完整/流式和纯 validate_request。

- [x] RED：原生认证/URL、生成字段、system、工具往返/用量；原生 SSE 完成/错误；Gemini 工具在零调用时拒绝。
- [x] GREEN：独立转换及严格响应；默认不启用 thinking/server tools 或多模态。
- [x] 定向真实两阶段 Engine 审批及断流不派发工具。

## Task 3: 声明式接入与真实模型模板

**Files:** runtime_builder.py、starter.py/cli.py、__init__.py、docs/model-adapters.md；tests/test_model_assembly.py。

- [x] RED：新增 adapter、环境变量隔离/非法配置、model 模板独立运行/缺凭据/占位报错；原 starter 内容兼容。
- [x] GREEN：配置 preflight、DeepSeek 明确 preset、公开导入和可编辑真实模型模板。
- [x] 更新版本/使用指南/支持矩阵；写明证据等级和 Gemini 限制。

## Task 4: 复核与交付

- [x] 独立复核并修复实证问题；全套 pytest -q -W error、Ruff、空白/文档片段检查。
- [x] 构建 wheel/sdist；仓库外实际 dev8 → dev9 精确回执/Manifest 恢复、协议与 model starter 验证。
- [x] 恢复 editable、记录实际结果、保存本地提交；不推送或发布。

实际验证：721 项测试通过；独立复核五项 P2 已闭环，10 项复核回归通过。安装包默认 dev8 恢复/回执/Chat 身份、旧模板字节及三协议 fixture 和独立模型模板均验证。在线模型质量和收费调用未执行。完整结果见 [实现进度](../../implementation-progress.md) 与 [Review](../../../architecture/reviews/2026-10-06-model-adapters.md)。本轮保存本地提交，不推送或发布。
