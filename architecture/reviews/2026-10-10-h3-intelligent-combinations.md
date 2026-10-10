# dev47 H3 智能数据与编排组合验收

日期：2026-10-10。基线：adbc328／dev46。此轮在既有开发分支完成用户授权的
能力文档同步、H3 默认组合、扩展接口与恢复验证；仅本地提交，不推送。

## 实现与架构边界

- 先修正当前能力表的 Local 十类／Temporal 五类绑定、自动记忆与上下文范围；
  保留明确标为历史的 dev9／dev21／dev37 记录，README 首段同步当前版本。
- 新增 ReferenceSelector、OverlapReferenceSelector 和 opt-in RelevantDataContext，
  同步纯策略选择原索引，Knowledge 顺序与原来源不变；摘要 fallback／finish 消费保存的选择。
  非法／惰性返回、参数修改、身份／方法变化被拒绝。选择只排序有界召回候选。
- 七个版本 `1` Profile；新增 semantic-knowledge／memory-recall／plan-and-execute／team。
  语义组合要求显式 HTTP Embedding 与 async 工厂，复用 SQLite Hybrid／RRF／来源回读。
  原三个 Profile 和 ManagedDataContext 默认身份保持；owned 资源由原 Builder 生命周期关闭。
- recommended_harness 返回原 AgentHarness／DynamicWorkflowSpec／TeamSpec；默认规则 Plan／
  固定 Supervisor 成员不提供自主搜索或业务 oracle。自定义、嵌套、原绑定路径、额度、审批、
  取消与子 Run 权威不变。显式 model Planner 仍通过受管理无工具子 Agent。

## 行为证据

- HTTP Embedding 夹具使用确定性同义词向量，通过真实回环 HTTP／SQLite 索引／Hybrid
  找回无共同词项的证据，传入实际 Agent；重启保留索引，来源更新后拒绝旧版本。
  此夹具不是实际 Embedding 模型或语义质量测试。
- Facts 在有限上下文下相关排序，JSON／TOML Profile roundtrip、异步装配预检与 owned 关闭。
- 默认 Team／Plan 通过 Runtime 托管与重连；自定义及嵌套成员的原 Provider 绑定、
  审批重启／重复审批保持，业务写入恰好一次（此测试场景，不是任意外部副作用保证）。
- parallel／Team／dynamic-DAG／nested 的摘要 response_received／adopted 八个
  `os._exit(77)` 恢复窗口：每例 8 tool／4 summary／1 artifact，不重复调用。
- 新上下文与 Temporal 纯 Activity／History 原 temporal-2 协议集成；无真实服务验证。

最终 dev47 wheel 在仓库外安装后 **75 契约通过**；两个离线示例成功。
dev46→47 与 dev47→46 的原三个 Profile 共六项审批恢复通过，Profile／Context／Manifest
精确相等，重复审批和 drive 均只产生一次业务写入。wheel／sdist 构建通过。
最终完整回归 **2972 passed／92 skipped**（519.07 秒）。跳过项依赖可选服务设置；本轮未重新配置真实服务。Ruff、格式和 Git 空白检查通过，修改文档的 300 个本地链接均可解析。旧 dev46 在创建执行数据库前拒绝新 relevant-data 工厂。

## 独立审查及修复

一次新上下文只读审查发现三项 Important；七项复现测试先失败，再在新增实现内修复：

1. RelevantDataContext 的 Session 不再提前调用最后消息摘录，完整轮次／原生 task-result
   交给原预算器；assembly／summary finish 与超过预算的近期完整轮次均有覆盖。
2. 普通 Fact 按 key／value 评分，观察事实仍排除生成的来源键与 Run 元数据。
3. 正相关 Facts 与 Knowledge 从 Fact 开始交替，保留 Knowledge 相对语义顺序；零相关 Facts 最后补入。

当前文档中的 Temporal 绑定／模型压缩／自动卸载矛盾也按用户的文档同步目标修正。
作者按采用效果将该文档项提高为验收问题；历史记录保留。无延后 Minor。
修复专项 **52 passed**（含八个进程退出）；最终安装测试包含新增八项召回回归及两项失败装配清理。

## 决策与局限

1. 依据用户持续开发及最终本地提交授权，沿现有功能分支执行，省去重复设计／实施确认；
   错误成本是共享分支历史，采用明确规格、差异审查和验收记录约束范围。
2. 使用新增 opt-in 上下文／Profile，保留旧版本 `1` 默认；错误成本是使用者需要主动选择新组合。
3. 在最终提交前审查完整工作区差异及未跟踪文件；review-package 脚本仅接受已提交范围，
   此轮用明确文件清单生成等价包。错误成本是遗漏未提交文件，已完整收集跟踪／未跟踪差异。
4. 混合来源默认先选正相关 Fact 再交替 Knowledge，保留 Session 和 Knowledge 相对排名；
   错误成本是词项事实可能先于更好的语义证据，宿主可替换 selector。

审查明确未裁定的事项由作者逐项保留边界：

- 真实生成／Embedding、引用和业务正确性：夹具只证明接线；成本是质量仍未知。
- 真实 Temporal／远程部署：本轮仅协议测试，不沿用为新服务实测；成本是部署组合仍可能出现缺陷。
- 全库语义 Facts／自动索引／记忆修订：保持有界候选及显式索引；成本是应用仍需自行接入或等待后续能力。
- 隐藏 selector I/O 隔离：可信宿主 Python 扩展，不能声称隔离；成本是不可信插件需要 H4 环境。
- flat RulePlanner 依赖：保持原语义，依赖输出选择 DAG／自定义 Planner；成本是应用要显式选择编排形式。
- 最终回归／安装／兼容证据：作者在本地提交前完成；缺失证据会阻止宣告完成。

本轮不读取历史密钥，不运行真实模型或 PostgreSQL／Qdrant／Temporal 服务。
完整语义记忆召回、自由合成／修订／遗忘、语义重排、业务完成验证、真实任务／引用质量、
自动索引治理、H4 环境隔离及 H5 企业治理继续开放；不能宣布完整 H3／M1 完成或超越 AgentScope。
