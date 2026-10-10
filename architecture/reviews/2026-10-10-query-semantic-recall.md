# dev49 H3 Query transform 与语义 Facts 验收

日期2026-10-10，基线 b12b9c5/dev48。沿 R15/R17 与 H3 原组合设计，复用原存储、Run/History、
ReferenceSelector 和装配 ledger，不新增执行权威或事实索引。

交付：有界 sync/async QueryTransform、确定性 Identity/Alias 默认、原 Retriever 包装与来源前后验证；
SemanticMemoryStore 窗口候选语义排序、TaskRecallPlanner 和保留语义顺序的纯 OrderedReferenceSelector；
显式 async HTTP／原生 sync/async后端工厂、语义记忆组合、Query Hybrid/词法配置、JSON/TOML、借用/拥有。
新组合 Embedding 资源保存实际传输/流释放证据，不以 HTTPX 已关闭标志表示成功释放；旧 Embedding 类保持。

来源变更/TTL/方法/资源/维度/有限性/输入变异、预算/Scope/惰性输出均有专项。
实际进程在 model_response_recorded 后退出，恢复审批不重复同一 Action 的两类 transform、Embedding或模型；
最终每类transform2次、模型2次、Embedding2请求、业务写入1次。Query Knowledge 的原 Chunk 验证链路已覆盖。
图中的 Facts绑定与真实回环HTTP通过；Temporal 只验收 Knowledge查询与原History上下文结果重放。

独立只读审查发现3项 Important：完整候选最后等待后的TTL、原生嵌套资源同标识替换、校验器修改证据。
按实际过期／错误来源／过时正文披露影响保留该级别；三项均进入一次修复：TTL与修改用例先失败，
7类原生资源替换在纠正测试的keyword-only构造后，移除guard明确失败，恢复后通过。
专项94 passed；没有 Critical、没有延后 Minor。

最终wheel的186个Python模块逐字节与源码一致；仓库外实际安装包86项新增契约通过。
dev48↔49六类原Profile共12组审批恢复：等待重启、重复submit/approve、完成且业务写入各1次，
Profile／Context／既有与新提交Manifest完全相同。另2组semantic-knowledge只验收接受Run/身份，
没有模型／Embedding或向量服务调用，不将其称为远程端到端验证。
旧dev48对3类新声明在创建执行数据库前拒绝。最终完整回归3105 passed／92条件依赖 skipped（473.30s）；wheel／sdist、Ruff、格式和Git空白检查通过。
新能力任务最终分组59／139／32 passed；安装86 passed（5.40s）。全部本地Markdown链接目标存在。
没有调用真实模型或重跑远程服务，92项跳过不算服务认证或真实质量通过。

## 决策与代价

- 按用户持续授权沿当前分支执行，不重复设计/计划确认；代价是共享分支历史，以文档、测试和最终审查约束。
- 首期为有界候选窗口语义排序，不新增全库索引；代价是窗口外事实可能漏召回。
- 默认确定性改写，SDK支持自定义异步 transform，不提供内置生成改写；代价是使用者需自配模型改写适配器。
- 新语义工厂使用独立版本化的受管理 Embedding生命周期；代价是新身份和需SDK自管的宿主代理/CA配置，旧类保持。
- Temporal只交付Query Knowledge集成；代价是语义Facts需后续独立Facts-context协议。
- 新语义组合选纯有序引用策略，避免词项再次排序；代价是混合来源排序需求要显式替换selector，旧组合保持。

真实质量、全库索引/语义修订、分布式Facts上下文、可选本地模型及完整H3/M1仍待完成。

## 审查边界决策（按登记顺序）

- 以完整工作区diff/新文件审查后提交，因用户要求先验收；代价是可能遗漏文件，以显式清单和安装验证约束。
- 不认证全库索引生命周期，窗口权威与限额保持；代价是窗口外事实可能漏召回。
- 不内置生成改写／本地模型下载，提供可替换完成端口；代价是用户需要适配器。
- 不扩展Temporal Facts/Worker发布协议，复用现有Knowledge快照；代价是分布式Facts需后续协议。
- 不宣称真实相关性／答案／引用质量，确定性与回环证明行为；代价是上线前需要真实任务评测。
- 不重新认证远程数据及Temporal服务，未使用这些真实环境；代价是服务组合仍需独立验证。
- 候选物化限制不等于数据库内部字节／扫描限制；代价是内部工作量可能超过返回上限。
- 不保证准备恰好一次付费或费用硬上限，只复用已接受Action；代价是接受前崩溃可能重复付费准备。
- 保留旧Embedding生命周期，独立新资源保持旧身份；代价是旧类限制仍存在。
- 自定义后台／私有／线程工作由适配器拥有，原生公共组合资源与完成结果受检查；代价是其他内部需自己的所有权契约。
- 全量／安装／跨版本验收由作者完成；独立审查未认证且两项localhost受沙箱阻断，代价是依赖登记的作者最终运行证据。
