# dev82 被动 Skill 目录与自动上下文验收（候选）

基线b3cb8ce／dev81；Task1 66a3080，Task2 c1aa9c9。完整R01–R26继续ACTIVE，仅本地提交。

纯可替换SkillSelector／确定性词项与中文bigram默认选择，借用原SkillCatalogPort的SkillDirectoryRetriever，输出原Knowledge DTO。原KnowledgeContext／每Agent Knowledge资源／Local Run与Temporal History保持唯一采纳和执行权威。metadata permissions=none，正文仍由原授权skill_get Action读取。完整目录有界、Scope／names限制、来源版本和方法身份固定、线程／文件guard由原owner管理。

源码相关153 passed（10.22s）；真实Temporal8 passed（52.18s）零跳过。六类Agent／sequence／Graph／Team／Dynamic／nested在首次模型决策前提供目录，原审批工具读取正文，重启／重复命令／重复审批与History重放；另两项实际File metadata读取阻塞、取消后保留root FD、CloseIncomplete、真实结束释放、重新Worker查询原cancelled且零模型调用。

前两次实际取消失败是测试夹具在Worker关闭后查询，以及共享默认Scope让CommandRegistry指向已关闭旧队列；已使用唯一Scope并在原队列重启Worker，未放宽终态／FD／无模型断言。

安装／完整回归／固定旧81兼容／唯一最终只读审查／原自有服务停止实际等待仍待完成，不声称最终验收。无新模型调用、密钥操作或远端推送。语义Skill选择、自动正文激活、插件／Sandbox／Runner和真实质量继续开放。

## 裁定与成本

最终闭环时加入本批完整账本裁定与延期项。
