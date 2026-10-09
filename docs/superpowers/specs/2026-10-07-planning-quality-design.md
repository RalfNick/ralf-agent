# dev15 真实规划评测

实现可配置、可复现的规划评测入口，冻结自然语言任务、成员能力、证据与机器 oracle。模型任务分为顺序依赖、并行证据合并、条件、未知/不足/歧义澄清和拒绝；包括合法多种计划，不把字符串一致当质量。

报告每例结果/失败/拒绝、合法成员/边/参数/停止、Provider request/Token usage来源、规划时延与调用次数；缺失费用/usage为null，失败同样进入分母。DAGProposal 通过同一个公共校验，ModelDAGPlanner 通过受管理子Run产生提案，记录模型和配置 identity，不用 ScriptedProvider冒充真实质量。

预运行冻结最大样本/调用/输出Token/请求超时与用户给出的费用上限。没有可用模型/费用配置时照常交付任务集、oracle、离线fixture与运行命令，真实报告标not_run和原因。询问只需Provider/模型/预算，密钥留本机环境。报告实际成绩，不为达到目标而改oracle或隐藏失败；真实调用不自动等同AgentScope/LangGraph对等实验。
