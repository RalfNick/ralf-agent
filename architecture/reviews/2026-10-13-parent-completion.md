# dev92：Plan／Team 业务完成验证验收

状态：本批功能子集验收通过；完整R10／H3／M1／R01–R26继续开放。本地提交以Git记录为准，不推送远端。

## 交付范围

显式 `completion_policy`提供可替换纯业务gate与可选受管理模型stage，支持Local的flat／DAG Plan与Team及Temporal对应原父级History。真实已采纳计划、当前业务子Run、原工具参数／结果／回执和消费证据共同组成固定来源；模型不能绕过gate，也不能替换候选答案。来源、稳定 `rN.verifier.verdict`子Run意图、proposal接收、verdict采纳和最终Session保存分别留证。

Plan反馈送入下一次实际规划并受原步数／修订／宿主额度限制；Team只接受或拒绝。停止结论保留原提案且不借用无关旧修订。完成期间拒绝外部DAG patch，采纳及最终发布重新核对计划、业务来源、真实结束及准确预算。根Session写响应丢失时以原固定提交回执及真实handler结束证明恢复，不能要求丢失的ACK，也不能豁免其他预算变化。

提供SDK／Profile、安装后库存Plan／Team参考组合及显式独立评分。原推荐版本1／2与未选政策的旧Local定义保持；Temporal显式policy registry发布binding9／parent-completion1，旧Worker在业务I/O前拒绝。纯Harness职责、Local事务和Temporal History各自唯一执行权威保持。

## 最终运行证据

各组有重叠，不能相加作为总测试数。私有原始证据位于 `/private/tmp/ralf-agent-dev92-fqocahc1/evidence`；最终文档静态检查与制品重建以该目录终态记录为准。

| 门槛 | 实际结果 |
| --- | --- |
| 完整源码 | **7126 passed／605 skipped**，1043.20s；pytest PID74508／session47473实际等待退出0。配置依赖跳过项不计通过 |
| 独立核心wheel | checkout外独立site-packages，**522 passed／零跳过**；无Temporal、Redis、PostgreSQL、YAML、PDF、tokenizer及server可选依赖 |
| 独立SDK安装 | checkout外原Temporal／绑定／Session／模型历史与新增契约，**413 passed／零跳过** |
| 真实源码Temporal | **7 passed／零跳过**，103.50s；14个Worker实际reap，7个恢复Worker退出0，23条实际History重放并保存 |
| 真实安装Temporal | **7 passed／零跳过**，98.65s；另14个Worker实际reap，7个恢复Worker退出0，另23条History重放并保存 |
| Local进程恢复 | 七窗口×flat／DAG／Team共21项包含于源码和核心安装；源、child意图、模型接收／采纳、proposal、verdict和最终成功恢复均保持worker2／judge1／effect1 |
| 文档与参考链路 | 原文SDK／TOML、重复提交和三个module CLI成功；Plan／Team离线任务各15／15、各51模型fixture调用，model_quality为空 |
| 旧dev91兼容 | 默认Profile／Local与Temporal manifest／Provider／Descriptor／DTO字节一致；普通／续接／完整历史／Plan／Team六类原Run双向回执、记录与预算一致，各model2／effect1／原工具回执1 |
| 旧执行器拒绝 | 旧Local模型前DefinitionMismatch；旧Worker对selected及registry-only新发布拒绝，零Activity／模型／工具；PID75600退出0并已等待 |
| 来源与冻结 | **321产品模块**在源码、wheel、sdist和独立core／SDK安装间字节一致；322项产品冻结含pyproject，548项测试源码冻结。最终文档同步后重建制品并复核原测试模块 |
| 服务关闭 | 自有Temporal PID86340／session78894退出0并实际等待，停止标记及父子PID消失确认；29个本批验收Worker均回收 |

真实Temporal覆盖纯gate审批、Plan verifier模型接收、DAG／Team proposal接收、取消迟到接收、正常根Session保存及根写ACK丢失后恢复。最后一项先执行原真实append与独立SDK结束Update，再丢弃Activity响应；Host确认未知write、精确提交回执与原结束证明后恢复到真实adopt窗口。重启后原write保留nonok／无revision响应，实际append attempt／commit各一次、根消息一次、spent6。重放不增加模型、工具或写入。

## 审查与失败记录

一次fresh审查发现四项Important：Temporal完成期间变更DAG后发布旧候选、停止结论混入旧来源、Local自定义stage绕过实际Context纯性，以及连续replan复用过期feedback。均有有效行为RED；修复后同一reviewer原四复现4项及补充38项通过。

同一复验又发现根Session预算归一错误要求已丢失的write ACK。原端口有效RED保留；修复后同一reviewer28项及额外6个严格类型／结束事件反例通过。正常ACK仍需准确整数revision与stop；丢失ACK需原grant、精确结束证明、原结束事件及提交回执。foreign／duplicate／changed allowance／未结束写／计划与来源漂移均拒绝。产品和第七夹具经同一reviewer闭环，没有新增fresh审查。

早期服务尝试的工具tuple/list比较、sandbox late import及Session夹具等待错误phase失败均保留，不计最终通过；冻结后源码与安装七用例重新完整执行。文档入口错误解释器／缺PYTHONPATH、私有例子runner目录冲突等装配错误另存，不计产品RED或成功证据。

## 继续开放

仅有限literal结果证明工具消费，摘要／Artifact投影不等同完整原值。库存是具体业务oracle，不能据此声称任意自然语言任务正确。Local直接工具图可显式仅验原回执；Temporal图仍只支持Agent节点，共享DTO不扩大执行范围。验证Context目前限实际内建纯实现，自定义输入可通过纯prepare替换；业务Context扩展端口保留。

Fixtures、MockTransport与实际Temporal恢复不证明线上模型规划／答案／引用／记忆质量；独立开发者采用与对等框架比较没有本批新证据。durable send_input／FIFO、Team隐式repair、更多领域与非模型验证、长期History治理及完整R01–R26继续开放。本批服务观察到大History blob警告，没有据此关闭容量与保留治理门槛。
