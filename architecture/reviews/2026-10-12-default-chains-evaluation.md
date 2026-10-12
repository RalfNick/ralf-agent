# dev85 推荐链路与重复评测验收

基线 `0ca8eb5`／dev84，遵循新的 R01–R26 持续目标：默认单 Agent、语义 RAG、Plan／Team 完整链路优先，独立任务并行，共享协议统一集成。只本地提交，不推送远端。本批是现有组合和评测的有界增量，不关闭完整 H3、M1、企业治理或对等框架比较。

## 实现与契约

- `recommended_harness("plan-and-execute", version="2")` 无显式 planner／plan_mode 时复用 RuleDAGPlanner；首节点接收任务，后节点接收前节点原结果。原版本1和显式选项保持。需要每节点原任务时由应用携带或自定义 ValueRef。
- `recommended_profile(..., version="2")` 显式选择替代 recall 角色时移除继承的互斥默认；显式同时声明两者仍拒绝。完整 Knowledge／Memory 资源声明使用自身适配器配置，不要求无用的顶层 Embedding；保留默认语义适配器时仍要求显式 HTTP 模型／维度。沿原工厂／资源账本装配。
- Memory 读取资源与受管理观察写目标独立；替换 memory_store 不会自动改写 stage_policy 的目标。借用资源仍由宿主关闭，owned 工厂走原 Runtime 关闭。
- 完成后的业务／规划报告增加 summary：逐任务重复通过率、尝试数、调用数、全部重复通过和混合结果计数；缺少维度或未尝试重复仍进入分母。描述性重复数据不证明统计优势或真实任务质量。
- 业务评测验证真实 Provider 声明的输出／时间上限，缺失或不匹配在证据分配前 not_run。未完成／未知Run在重建时只观察，不为测恢复而重试模型；仅终态执行原恢复检查。
- 规划oracle验证必需证据引用默认语义及完整静态输入Schema；未知引用输出仍需运行时和业务验证。Provider前置校验只允许同步完成None，拒绝惰性／异步返回。offline身份不能生成真实质量声明；公开Provider元数据只导出有限类型和生成字段，其余配置保留digest。
- 模型协议兼容测例区分runtime、tool receipt和最终output；文本／工具／完整流的最终响应须确为 `{"ok":true}`。合法JSON但ok=false、数字1、重复键或额外字段不能得通过；早期流关闭仍测消费者清理。

## 验证记录

最终验收于2026-10-13完成：源码 **5520 passed／447配置依赖跳过，855.15s**。独立无Redis／Temporal／PDF／tokenizer扩展的核心wheel安装 **171 passed，14.02s**。Ruff、格式及Git空白检查通过；292个产品模块冻结，源码／wheel／sdist／独立安装逐字节一致。实际远端数据库和Temporal服务本批未重跑，配置跳过不记作这些门槛通过。

八种版本1推荐Profile和两种原推荐Harness请求，在原dev84安装与当前源码间逐字比较一致。真实SQLite推荐Plan回执／根快照在dev84安装→dev85源码→dev85安装→dev84安装重连中保持一致。新版本2的真实SQLite Runtime测试覆盖证据传递、自定义成员、相同回执重连、不重复调用、实际召回及owned／borrowed资源关闭。此前复现的必需引用削弱／静态对象Schema漏检／offline误标均有失败后修复证据。

一次独立review确认1项Important（净化后长offline名称丢失分类）及1项Minor（超大JSON整型字段转换OverflowError）；统一修复并通过三项新失败复现后回归。离线分类从原identity保存为独立标志，报告展示省略不改变证据类别；两个报告投影分别处理整数／浮点有限性。未进行第二轮review，最终全量与安装验收针对修复后的冻结产品。

第一轮全量在发现review问题后主动中断：675 passed／33 skipped、226.06s、exit2，不计最终通过。安装首轮167 passed／4 failed，原因是临时测试资产缺失examples代理入口；只补齐夹具，未修改产品，最终同组171通过。

离线三轮业务24/24、45调用；规划fixture9/9、9调用，所有任务保留三次测量且model_quality=null。安装后CLI业务8/8、15调用及规划3/3、3调用。两段版本2文档例子分别在源码和独立核心安装实际运行；五段Python解析通过，变更文档的本地链接逐项校验。以上是协议／运行／oracle回归，不是任务质量或对等benchmark。

当前进程未配置DEEPSEEK_API_KEY、RALF_PLANNING_MODEL或OPENAI_API_KEY；本批没有付费调用。真实生成／Embedding／记忆利用／端到端Plan和Team质量、独立采用及同配置AgentScope／LangGraph比较保持未验收。

## 后续门槛

优先补齐安装后的语义RAG摄取→索引→查询→答案／引用评分，业务Plan／Team全执行评分与重复真实模型任务；继续单Agent首用和可复用适配契约。随后推进输入续接、deadline、容量、数据保留及服务治理。dev83两个Minor（实际Temporal Sandbox CI／缺失ServerVersion错误分类）继续延期，未由本批关闭。
