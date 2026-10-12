# dev87 模型续接与 Gemini 函数验收

基线 dev86 `5096210`。本批沿 R05／R03／R07／R26 补齐原模型工具链路，
完整 R01–R26、H1–H5、M1、真实模型质量及外部采用保持开放。
本批声明子集已验收；下表分别列出源码、安装、服务及兼容证据，不把子集绿色当完整目标完成。

## 已实现范围

- 原 `ModelResponse` 三字段保持，新增四字段有限 JSON `ModelContinuation` 与显式响应子类。
- Provider 纯身份绑定原已完成决策；Harness 改写原输出／工具提案拒绝，类型化默认参数随后解析。
- Local 原接收／采纳窗口、native local-5 和 bound 根协议；未启用续接不能丢弃原模型状态。
- Temporal joint6 原 History 接收、结算、零额度纯采纳；旧协议 1–5 不增加阶段或改载荷。
- 原生 Gemini 函数声明、签名 Part 顺序、native／host ID 区分、完整 SSE 和工具组回执匹配。
- SDK、sync／async Profile、每 Agent 绑定、原观察中间件及 RAG／Plan／Team 评测组合接通。

续接只提供数据证据。授权、审批、预算、工具执行、真实结束和未知效果仍由原引擎负责。
使用说明见[模型续接](../../docs/model-continuation.md)，具体规格见[设计](../../docs/superpowers/specs/2026-10-13-model-continuation-design.md)。

## 证据与门槛

| 门槛 | 证据 | 状态 |
| --- | --- | --- |
| 相关源码 | 根接入282、统一包装器／名称修复172、两阶段Temporal314，均为各自定向套件 | 通过，不相加当总测试数 |
| 最终完整源码 | 冻结301个产品文件后的完整回归 | 5882 passed／455配置跳过，818.09s |
| 独立核心安装 | wheel安装后295项新续接／默认组合／评测测试，无Temporal／Redis／PDF／tokenizer extra | 通过 |
| 真实 Local 退出 | 模型接收／决策采纳处 `os._exit(77)`，重建累计模型2次、业务工具1次 | 源码与安装套件通过 |
| 实际 Temporal | native／graph × managed × approval／receipt 共8项，真实Worker kill、重建、重复审批、原签名续接及History replay | 源码8通过；安装8通过 |
| 既有 Temporal | 原DecisionPolicy及custom Context服务链路 | 最终源码17项通过；安装17通过 |
| 旧86兼容 | 8个默认Profile与2个Harness请求字节一致；同一旧Run旧86→源码87→安装87→旧86回执及完整快照一致 | 通过 |
| 旧读取者拒绝 | 实际旧86 Local拒绝新启用Run，模型调用0；旧86纯Temporal Manifest校验拒绝joint6；新引擎仍可恢复原Run | 通过；纯校验不冒充真实旧Worker测试 |
| 构建与包内容 | 300产品模块源码／wheel／sdist／安装一致，1139项必需产品／文档／示例／测试载荷按字节复核 | 通过；最终文档更新后再次构建并复核 |
| 真实Gemini／独立采用 | 当前没有可用配置或实测报告 | 未验收 |

证据目录：`/private/tmp/ralf-agent-dev87-sbfsyl85`。保存源码／安装日志、原默认与Run快照、
失败复现、独立review及产品冻结hash。最终提交只在本地，不推送远端。
本批自有 Temporal 进程 PID62946 已发送正常 SIGTERM，session38000 返回退出码0，
输出 `TEMPORAL_STOPPED`；确认服务已退出后才记录关闭完成。

## 一次独立审查及统一修复

审查发现2项Important和1项名称范围Minor，后者按实际工具链路影响重新定为Important：

1. 审计包装器在身份漂移后丢弃已完成响应。owner／配置／方法三类RED后，改为先交原权威
   保存响应，再以计算出的已变更身份拒绝采纳；只读重建仍可观察原回执，不建立私有恢复缓存。
2. Temporal 在Provider返回与Harness执行之间缺少持久窗口。joint6先回原receipt到History，
   再执行原纯采纳Activity。原模型额度只结算一次，失联的纯采纳不把模型改为unknown。
3. 声明名称允许点／冒号，而调用解码不接受。有效RED后改为预检声明／调用语法交集，
   避免调用模型后才发现无法续接。没有默默替换业务工具名。

实际服务另复现 Sandbox 内外纯DTO／Harness／错误类型身份不一致；共享纯加载边界后恢复
与重放通过。receipt窗口测试的旧断言错误要求阶段状态／response不变化；修正为保留完整
原receipt／dispatch／attempt证据，允许已接收状态推进到已采纳状态，未改变产品行为。

裁定与未覆盖范围：观察式Middleware显式委托原owner；缺native ID的同组重复拒绝、已结束
组可再次调用；未验证的signature-only SSE与增量参数明确拒绝；真实质量、服务最终安装
及文档数量由各自证据验收，不用review的定向绿色代替。无第二review。

## 保留的边界

Provider返回到模型Activity结果被服务记录之前的退出仍可能丢失响应；任意远端模型调用
不保证恰好一次或费用上限。续接最多128KiB，不覆盖多模态、服务端工具、signature-only
或partialArgs参数协议，也没有交付Responses／DeepSeek思考模式续接。
工具签名及完整回路的MockTransport只证明协议，不能证明真实Gemini或通用规划／团队质量。
完整能力仍按[剩余清单](../../docs/remaining-work.md)推进。
