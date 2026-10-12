# RAG 与 Plan／Team 端到端任务评测

沿 R01–R26／H3／M1 的既有架构交付实际链路评测，不新增执行权威。前置基线为 dev85 `3d053a5`；完整能力目标保持。用户已经授权持续并行开发、逐批验收和仅本地提交。

## 两条独立链路

RAG 使用原 IngestionCoordinator、SQLite Knowledge、显式向量索引／Hybrid、KnowledgeContext 与版本2推荐Runtime完成摄取→索引→查询→答案。默认离线 Provider 与 HashEmbedding 只验收运行协议；显式注入真实生成／Embedding 组件才有对应质量证据。组件由宿主借用，数据库／Runtime由评测拥有，所有关闭与恢复沿原协议。

固定RAG案例格式：`id/category/question/documents/expected`。document为`document_id/text/namespace/metadata`，每例唯一(namespace,id)，查询namespace为`manuals`；可加入private干扰来源。expected为`status/answer/support`，support是document_id→必须在原文quote中出现的支撑片段。答案输出`status/answer/citations`；citation为`document_id/version/quote`。纯oracle分别校验答案、引用可用性和支撑覆盖；引用必须来自真实模型Action的knowledge_references，并且对应文档原文实际出现在最终Action请求中；截断后仅接受可见原文，不接受metadata或未展示候选。引用版本／digest／namespace必须一致；拒绝伪造、旧版本、无关引用及引用片段不在原文。answered必须有支撑；needs_input／refused必须answer=null且无引用。冻结案例、重复和失败均进入分母。

Plan／Team使用版本2推荐Harness、独立成员、实际工具和原受管理子Run；固定有限库存／金额任务，评分检查真实前序结果、工具参数、最终值和停止。kind支持plan-and-execute／team；缺输入和不存在目标不得虚构。重连终态沿原权威；未完成／未知仅观察，不为评分重试外部调用。团队质量不能由成员存在或提案合法推导。

## 公共评测约束

复用EvaluationLimits、受管理审计Provider、安全identity、repeat summary与0600独占证据路径。真实Provider声明与输出／超时限额匹配；硬货币上限不能保证时返回not_run。Embedding另有单文本Adapter调用上限与审计；有原生embed_result时固定该接口，保留每批usage。内置HTTP单文本调用为一批；任意第三方适配器内部请求次数不由通用端口保证。未知usage不合并成已知费用。原身份与实现固定，关闭借用客户端仍由调用方负责。Provider=None默认not_run，不隐式读凭据、联网或下载模型。恢复工厂仅重开已持久化的来源和索引，不重做摄取或Embedding。

报告导出数据／组件配置digest、逐例checks、调用、来源化usage、时延、停止和恢复。不导出原问题、答案、引用正文、任意Adapter私有字段或异常字符串；原始内容留私有执行数据库。offline类身份与Hash不冒充真实语义质量；真实生成与语义检索质量分别说明。不存在真实模型、服务或外部采用证据时保留未验收，完整RAG／Plan／Team质量、M1与对等比较不因测试通过而关闭。

## 验收

每条链路有SDK、离线默认及显式真实配置入口、至少一个组件替换、重复回执与进程／恢复窗口测试、安装场景。oracle负例必须抓到正确答案配伪造引用／旧版本／缺必要支撑，以及正确最终金额配错误工具参数／缺上游证据。全量回归与安装包一致性在共享产品冻结后统一运行。
