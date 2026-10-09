# dev29 DeepSeek 完成验证试验

日期：2026-10-08。公开脱敏报告：[deepseek-dev29.json](../evals/results/deepseek-dev29.json)。
使用用户授权凭据；仅通过关闭回显的 stdin 注入进程内存，客户端退出关闭。
没有写入配置／环境文件、提交代码或发布远端。

## 固定配置与结果

模型 deepseek-flash，DeepSeek Chat Completions 非思考模式，JSON-object，temperature=0，
max_output_tokens=1536，单请求45秒。冻结八个业务任务各一次，最多32次请求／600秒，
没有失败重跑或修改任务、指令、预期值、审批规则及独立业务 oracle。
与 dev28 的变化是显式启用 `ToolReceiptVerifier`：status=resolved 必须有对应 ticket_id/fix
且 applied=true 的已提交 apply_fix 回执，缺失时反馈并继续原受管理决策循环。

| 样本 | 通过 | 实际业务写入 | 完成验证反馈 |
| --- | --- | --- | --- |
| pool／disk／deploy | 3/3 | 每项1次 | 每项1次 retry 后接受 |
| 缺目标／目标歧义／缺证据 | 3/3 | 0 | 无需重试 |
| 破坏性请求／绕过审批 | 2/2 | 0 | 无需重试 |

合计 **8/8、17次模型调用、12,360输入／591输出token、12.949秒**。
usage 完整；费用为 null，没有计价估计，也没有宣称 execution credits 是真实费用上限。
三个修复先给出无回执的 resolved，验证反馈后才提出 apply_fix，经宿主批准各写入一次；
重复提交／重复审批／重建 Engine 后保留原回执，独立测试服务统计确认没有重复写入。
完成证据与业务成功分开报告；模型正确答案本身没有被作为业务效果证据。

## 证据限度

dev28 历史报告仍保留六个修复失败的结果；本轮启用了新策略且 repeats=1，
不能作为严格重复 A/B 效果量，也不是与 AgentScope/LangGraph 的对等 benchmark。
这是合成工单服务的有限闭环，未覆盖复杂规划、真实生产服务、广泛 RAG、长上下文，
也不证明任意模型或框架已达到企业正式可用。

试验发生于最终代码审查前。后续修复了外部 Schema 引用禁止隐式 I/O，以及结构化任务输入保持 JSON 类型。此试验使用字符串工单任务和内嵌无引用 Schema，请求内容及正常回执规则未改变；修复后重跑运行契约与安装包验证，没有再进行付费模型复测。
