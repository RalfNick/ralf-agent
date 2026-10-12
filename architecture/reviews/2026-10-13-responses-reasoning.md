# dev91 Responses 推理续接：验收记录

本批推进 R05 的显式 Responses 续接，设计和执行边界见[设计](../../docs/superpowers/specs/2026-10-13-responses-reasoning-design.md)、[计划](../../docs/superpowers/plans/2026-10-13-responses-reasoning.md)与[使用指南](../../docs/responses-reasoning.md)。完整 R01–R26 目标仍进行中。

## 已验收范围

本批声明的文本／客户端函数 Responses 推理续接子集已验收。新增显式 `OpenAIResponsesReasoningProvider`／`openai-responses-reasoning`；既有 Provider、默认声明、ModelContinuation／ModelHistory 和执行权威保持。没有新 Engine／History 协议，也没有服务端隐式 conversation。

JSON／SSE 保留原有序 output、推理密文、summary／content、原函数参数和 phase。commentary 保存在原历史中，最终输出只采纳可完成的文字。可选 effort/context/summary/mode 固定到身份；原128KiB上限、256调用、要求原生item ID及1–64字符函数名是本批明确子集。SDK、同步／异步Profile、每Agent provider绑定、Temporal显式续接和四类评测CLI已接通，非法配置在owned工厂／凭据读取前拒绝。

Local覆盖原工具循环／RAG、审批与重复控制、receipt/adoption后的真实进程退出恢复、两Turn重建，以及graph/team/实际ModelPlanner/nested组合。实际Temporal覆盖native/graph的审批和模型回执丢失窗口，以及native最终Session回执恢复；这些特定场景不构成所有编排组合的完整推理模型验收。

## 最终证据

| 门槛 | 实际结果及边界 |
| --- | --- |
| 完整源码回归 | **6792 passed／598 skipped**，856.08s；同一pytest PID28952、session91177实际退出0并等待。没有配置远端服务的跳过项单独保留，不计通过 |
| 协议、装配、Local、评测及旧协议组合 | **494 passed／零跳过**；包括139 Provider／SSE、100装配／CLI、16Local／评测、13review、5公共边界和221既有协议；与完整回归重叠 |
| 独立核心wheel安装 | checkout外独立site-packages，**494 passed／零跳过**（13.44s）；无Temporal／Redis／PostgreSQL／YAML／PDF／tokenizer／server等可选依赖 |
| 安装后使用路径 | 指南原SDK代码和原TOML实跑通过：两次fixture模型请求、真实lookup、原密文／commentary／call续接、最终结果；借用client由调用者关闭。四类已安装console入口及缺凭据零调用共9项检查通过 |
| 实际源码Temporal | **5 passed／零跳过**（44.71s），10个Worker已reap，5个恢复Worker正常退出0，9次原History replay |
| 实际安装Temporal | **17 passed／零跳过**（150.70s）：Responses5、DeepSeek4、Gemini8；新Responses同样10个Worker、5次正常恢复退出和9次replay。源码＋安装共44个Worker PID均已退出 |
| 历史兼容 | 真实dev90→dev91→dev90的plain／continued／run-plain／run-continued四类原Run：原submit、完整record、预算／回执不变，每例仅两次模型和一次业务效果；默认Profile／Provider／Local及Temporal Manifest／DTO字节相同 |
| 制品来源 | **311产品模块**在源码、wheel、sdist和独立core／SDK安装间字节一致；312项冻结记录含pyproject，无冻结后产品改动。最终验收文档同步后重新构建制品 |
| 静态及文档 | Ruff／格式／Git空白检查通过；本批Markdown本地链接、凭据形状检查及产品冻结检查通过；以最终静态证据记录为准 |
| 临时资源 | 私有loopback Temporal PID2360／session83714经SIGTERM正常退出0并实际等待；关闭标记及PID消失确认。未修改用户其他服务 |

测试组有重叠，不能相加当成独立覆盖总数。首次未使用Temporal SDK环境的五项导入失败发生在Worker启动前；最初放在无服务core CI的85项跳过也不计实际服务验收。最终有效结果仅采用上表明确的环境。Git本地提交回执保存在私有证据，原dev90提交为6905741；没有推送或公开发布。

## 独立审查及修复

一次fresh whole-batch审查发现三个P2：早期SSE snapshot丢弃已观察身份／状态／错误、事件信封忽略不支持语义字段、合法neutral nullable字段被拒绝；另一个CI Minor指出source服务测试位于未配置服务的job。13项有效RED复现后统一修复，原审查者的定向复核通过，没有剩余review发现。

根任务另以五项RED／GREEN补齐继承的temperature/top_p/stop/seed变化必须在请求前拒绝，以及JSON／SSE原output_text.logprobs:null保存和续接。最终494项组合包含全部修复。CI source恢复门槛已置于remote服务ready之后、build之前；installed恢复在安装之后。只验证本地结构和同等实际命令，本批没有远端CI运行。

## 证据范围

私有工作证据位于 `/private/tmp/ralf-agent-dev91-zpefzsxu/evidence`。MockTransport只证明协议和运行集成；真实 Temporal Service只证明执行故障窗口，不代替真实模型任务。未经证据确认的线上质量和外部采用继续开放。

本批没有在线模型请求；真实账户／型号支持的推理参数组合、质量／费用、其余Responses媒体／hosted tools／远端会话、模型路由、完整R05／H3／M1／R01–R26、独立采用与跨框架对等比较仍待各自证据。下一阶段优先推进Plan／Team的业务回执验证及受管理模型验证链路。
