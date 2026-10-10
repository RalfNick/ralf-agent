# dev50 H3 模型查询改写验收

日期2026-10-10，基线017db85/dev49。依据已批准 H3/R17 架构及本轮 spec/plan，借用原 async ModelProvider，
保留原 Facts／Knowledge 数据权威、Local Run／Temporal History 和资源 ledger。

已实现 ModelQueryTransform：工具为空、仅查询文本、严格有界 JSON、默认保留原查询、固定 Provider／方法／身份／输入。
已接通命名 Provider 配置、JSON/TOML、作用域 Knowledge/Facts 的别名 preflight；原八类默认声明不变。

SDK 与组合专项77 passed；配置／旧工厂专项43 passed。原生 HTTP 实际进程故障及 Temporal Knowledge 重放3 passed。
进程在 model_response_recorded 事务提交后退出，恢复原 Action 不重复准备；重复审批与终态 drive 只产生一次业务写入。
这些是协议／恢复证据，不是线上模型质量成绩。

独立只读审查发现一项 Important：模型 Facts 在拒绝提案前读取来源。按实际后端访问和固定组件边界影响维持该级别。
一次修复中12个原生消费者用例 RED→GREEN，覆盖空／重复／超限／非 JSON／拒绝／工具提案及五类 Provider／参数变化。
新增固定 query-first 路径，旧默认 recall 方法与身份保持；专项96 passed。没有 Critical 或延后 Minor，不做第二轮审查。

最终 wheel 仓库外64项新增契约通过；187个 Python 模块与源码／wheel／sdist／安装包逐字节一致。
dev49↔50旧八类默认 Profile 共16组：12组实际审批恢复，各自原回执／原 Manifest 相等且业务写入一次；
语义 Knowledge／Memory 四组仅验证提交恢复与新发布身份，不调用未配置服务。旧 wheel 三项新 model 声明在建库前拒绝。
最终冻结回归3168 passed／92 skipped，529.76s；Ruff／格式／Git 空白检查通过，wheel／sdist 构建通过。
本轮未调用真实生成／Embedding 模型，未重新认证远程数据库或 Temporal Service。

## 决策与剩余范围

- 按用户持续开发授权在既有分支 inline 实现，不重复申请架构批准；代价是共享历史，显式 spec/plan 与测试限定增量。
- 借用已装配 Provider，不新建平行模型客户端；代价是共享自定义 Provider 须支持宿主实际并发。
- 模型改写是 opt-in 检索准备，Temporal 仅 Knowledge；代价是接受前可能重复付费，Temporal Facts 仍待实现。
- 因 review-package 拒绝空提交范围，审查完整工作区 diff 与列出的新文件；代价是审查者必须覆盖清单中的未跟踪文件。
- 增加固定 query-first 方法，保留 dev49 原 recall 字节码／身份；代价是语义排序代码重复、空候选也调用显式改写模型。
- 真实相关性／引用／答案质量另行评测；代价是本轮无法证明实际智能质量。
- 不承诺接受前付费准备恰好一次；代价是中断准备可能重复计费。
- Temporal Facts／自动查询策略／全库索引及更大路线继续待开发；代价是这些组合尚未交付。
- 作者完成最终回归／打包／跨版本验收，独立审查只覆盖源码及122项专项；代价是最终工件验收依赖本记录的作者证据。

自动查询策略、全库事实索引、语义修订、真实质量、其他 Temporal 绑定／共享会话与 H4/H5 仍按剩余清单推进。
