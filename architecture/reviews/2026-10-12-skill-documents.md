# dev80 标准 Skill 文档接入子集验收

基线 `3de04c2`／dev79；遵循 R01/R13、H3/H4 原设计。
只交付纯同步可替换解析器、可选 YAML 默认、固定显式文件目录和已有 tools／Skills 绑定装配。
原 Local／Temporal History 仍是唯一执行权威；Source1、绑定 protocol1、默认 JSON／22 starter 保留。

[设计](../../docs/superpowers/specs/2026-10-12-skill-documents-design.md)、
[计划](../../docs/superpowers/plans/2026-10-12-skill-documents.md)、
[指南](../../docs/skill-documents.md)。
参考 [Agent Skills 格式](https://agentskills.io/specification) 和用户指定本地 AgentScope 的
`src/agentscope/skill/_local_loader.py`；采用明确文档格式，保留原版本冻结，未引入目录扫描／mtime刷新。

## 交付边界

- `ParsedSkillDocument`／`SkillDocumentParser`／`YamlSkillDocumentParser`：描述数据与普通有限身份，原 SkillSpec 名称／版本契约。
- 完整安全 YAML 有可选 PyYAML 依赖，缺失时打开文件前拒绝；核心导入和自定义解析器可无 YAML 使用。
- frontmatter／事件／深度／别名及展开量均有界；拒绝重复键、惰性返回值、复制钩子、循环、不安全标签和无效普通类型。
- `FileSkillDocumentCatalog` 使用原 Workspace FD／Scope／真实处理器关闭门禁和前后版本复核；借用解析器、拥有文件资源，原 JSON 默认无改动。
- `tools/skills-markdown` 默认声明复用原资源账本、read-only Source 和每 Agent 授权交集。`allowed-tools` 不扩大实际权限。

## 目前证据

Task1 缺失公共 API 60项真实RED；原生／目录旧契约143项通过。
Task2 初始26项／扩展34项RED，相关162项通过（1.72s），正式162项（1.17s）。
Task3 默认配置缺失4项RED；修正两处测试夹具 API 名称后19项通过（3.82s），相关282项（8.19s）。
自查新增别名展开复现1项RED，相关283项通过（8.75s）；非法身份漂移复现1项RED，修复正式验证待记录。
自有真实 Temporal 服务17282：六类 Agent／顺序／Graph／Team／Dynamic／嵌套原审批、Worker重启、重复审批、保存读结果与History回放6项通过（33.61s），零跳过。

独立审查、最终全量、全新 core／SDK 安装、源码／wheel／sdist一致、实际旧79恢复／默认22模板、安装服务和服务退出门槛待验收。
未执行真实模型或推送。以上是交付子集，完整 R01–R26、AgentScope 全面对齐与企业质量门槛仍开放。

## Rulings（实施裁定）

1. 连续原授权按书面设计／计划执行，不重复审批菜单；误判代价为发布前修订，无远端动作。
2. 使用维护中的可选 PyYAML 完整解析；误判代价为 YAML 使用者增加可选依赖，原核心 JSON 不受影响。
3. 首期明确 paths／冻结文件而非递归／mtime刷新；误判代价为自动发现另行建设。
4. 保留 RALF ASCII 名称和有限容量、明确较窄配置；误判代价为 Unicode／扩展字段另定义契约或自定义解析器。
5. 别名展开在普通 JSON 复制前有4096值／64KiB标量容量；误判代价为高复用但过量的 YAML 明确拒绝。

## 未完成能力与延期项

自动 Context 目录阶段、目录 selector／资源视图、异步／远程解析、递归发现、脚本资源、Sandbox／Runner及真实规划／RAG／记忆质量不由本批完成。
dev77 的实际 Temporal 原生阻塞写取消／关闭／第二 owner 租约窗口仍为延期证据项；dev76 live drift 错误分类 Minor 仍未闭环。

## 唯一独立审查与裁定（修复前）

Astra/high全新只读审查：0 Critical／3 Important／2 Minor，针对117项通过（4.30s）。
I1：公开元数据在容量检查前递归复制；I2：自定义解析正文在循环结束后才检查容量；
I3：外层精确类型未完整复核内层SkillSpec／描述元数据。按实际影响均保持Important，进入一次统一TDD修复。
M1：YAML merge keys与完整安全YAML描述存在差异；M2：历史dev79段落标题被标为dev80。
均保持Minor并延期，本批不修改、不复审。候选门槛仍待最终证据。

十二项Declined已逐项在修复前裁定：

- Native YAML alias explosion：Retain bounded_header before JSON detachment; separate public construction is I1；误判代价：Native scalar limits remain a narrower YAML profile。
- Unsafe YAML construction/keys/cycles/events：Retain SafeLoader/event/mapping checks and passing evidence；误判代价：Unsupported extensions require explicit versioned changes。
- Lazy parser results：Retain pre-root sync checks and exact completed-result adoption；误判代价：Pure parser authors must complete synchronous results。
- Raw-file aggregate capacity：Retain original read remaining cap; parsed output expansion enters I2；误判代价：Raw and parsed capacities must be maintained independently。
- Parser identity/method drift：Retain explicit identity and executable fingerprint; hidden state is app version responsibility；误判代价：Unversioned hidden changes are outside verifiable contract。
- File/root drift/aliases：Retain original FD-relative revision checks before/after snapshots；误判代价：Mutable files must be published as new resources。
- Root FD lifetime/cleanup：Retain actual handler guard and borrowed parser lifecycle；误判代价：Failed close remains retriable and holds original resources。
- Scope/allowed-tools privilege：Retain host Scope and original read-only grants; metadata grants nothing；误判代价：Actual business privileges require separate registration。
- Execution protocol/authority：Retain original Source1/Skills protocol/Local/History; no new state authority；误判代价：No automatic Context or scripts provided here。
- Core import requiring PyYAML：Retain lazy optional import and typed pre-root refusal; fresh core gate required；误判代价：Default YAML users must install optional dependency。
- Existing JSON/starters：Retain original code paths, require actual old79/22-template proof；误判代价：Diff inspection alone is not compatibility evidence。
- Incomplete final acceptance：Keep candidate pending and run all specified final gates；误判代价：No complete-framework or release claims before evidence。

## 最终修复与安装／真实服务证据（全量尚在运行）

所有3项Important在全部裁定之后进行一次统一TDD：14项真实RED（1.35s）→相关298项GREEN（9.06s）。
公开描述元数据先验证固定浅层形状与字符串容量再复制；原文件和解析正文分别计量64MiB，超限前停止继续解析；
精确返回对象也重新验证／分离所有SkillSpec字段及有界描述JSON。无第二次审查，2项Minor保留。

全新核心wheel无PyYAML：35项通过／14项明确未选择（1.25s），独立自定义解析器指南通过并验证yaml模块不存在。
全新SDK含PyYAML6.0.3／Temporal：359项通过（13.83s）。这些组相互重叠，不累计为全量数。
最终源码真实6项（39.39s）／安装真实6项（32.66s）无跳过；Agent／顺序／Graph／Team／Dynamic／嵌套保持原审批、Worker重启和History恢复。
272模块冻结源码／wheel／sdist／core／SDK一致，751份sdist文档／测试／示例／配置逐字一致，160项CI独立argv路径有效。
安装指南执行通过。真实旧79↔80 Local／CLI／Temporal顺序／原生Session双向恢复与22 starter字节验证通过；业务效果仍各一次。
原自有服务26862实际退出0、停止并等待确认。最终全量回归仍在进行；文档收口将重新构建检查包载荷。

## 最终冻结验收

全量48416实际退出0并读取：4954 passed／370 configured skipped（713.55s）；跳过项不计通过。
全部Important经一次14项RED→相关298项GREEN后，全量保持通过。唯一独立审查0 Critical／3 Important／2 Minor；无第二审查。
全部18项Rulings（六项实施裁定与十二项Declined）已收集；额外第六项裁定：审查使用明确基线、gitstatus/diff和候选未跟踪文件，因为实现尚未提交；误判代价为文件遗漏，因此最终全量及逐字包载荷验收不可省略。

核心35／SDK359、源码真实6／安装真实6、旧79双向恢复／22模板、272模块一致及原自有服务实际退出0均已通过。
正式Task4与文档收口sdist重建另记录。仅本地提交，无模型或push。
M1 YAML merge keys支持／描述、M2历史dev79段落标题误标dev80，均作为Minor延期，本批不修改。
dev77原生写实际取消／关闭／租约证据仍独立延期；完整R01–R26目标保持ACTIVE，不将本子集当作全框架完成。

正式Task4在本地实现提交7a861d7之后执行全新SDK安装契约：359项通过，实际命令由原task-done保存，范围a9f8334..7a861d7。所有计划复选项完成。文档收口sdist重建再次验载荷；本计划独有SDD账本移入本批临时存档，其他计划账本保留。
