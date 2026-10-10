# dev54 — tokenizer 计量与分块验收

基线：177bd7d/dev53。范围：R14/R16 的既有 Counter／Chunker 扩展，不新增执行权威。

## 实现与兼容

TextTokenizer 同步 count/prefix/suffix；UTF8ByteTokenizer 为无依赖字节基线，
TiktokenTokenizer 显式接收并复制宿主词表，固定原生版本／摘要／入口。
TokenizerMessageCounter 计量 canonical 消息文本与同单位输出预留；TokenChunker
保持有效 Unicode、完整原文字符位置、窗口／块数／扩展体积限制及原子摄取。
budgeted／managed 工厂增加显式字节计量，SDK 注入任意合规 tokenizer。

原 Counter／字符／段落／budgeted／managed 缺省身份与实际 dev53 wheel 完全一致。
dev53→dev54→dev53 重开原文摄取回执，版本维持1；dev54 token 新回执由真实 dev53 wheel
重读为相同 receipt 与三个块，不重分块、不消费新版本。
无 schema 或 History patch；旧原子权威和租约行为不改。

## TDD 与独立审查

新增40项测试：先观察缺失功能13项失败；另有未覆盖中文的 native pattern、Rust panic、
Unicode 重试中的原生绑定漂移及高重叠 mixed-width 前进失败的独立 RED 复现。
最终40项均通过 warnings-as-errors；实际 memory/SQLite 入库、重复回执／重开、
提交前后进程终止、Local 审批重启一次写，以及 Temporal runtime/state 采纳与预算拒绝有行为证据。

唯一 fresh-context read-only reviewer 审查及100项既有回归／2配置跳过，发现三项：

- 原生 Regex BacktrackLimitExceeded 经 PyO3 BaseException 逃逸：统一原生边界仅转换普通异常与精确 PanicException，保留取消／退出。
- 部分 Unicode decode 重试跳过绑定复核：每次成功 encode/decode 后、最终空裁剪前复核，禁止变化后再调用下一组件。
- 高重叠预算只能重复旧 Unicode 块：去掉当前重叠重试新字符，保留完整覆盖；3个字节宽度复现及8个真实入库／重放组合通过。

审查最后 verdict 中仅第三项尚待修复；上述回归已完成该修复。没有重复派遣第二审查者。

审查排除项的执行者裁定：

1. 实际词表／framing／billing／答案质量：增加 cl100k_base 官方实际资产装配试验，English count及中文／emoji／字面特殊标记25块通过；线上模型、供应商协议完整计量与答案质量仍未验收。
2. 真实 Temporal Worker/History 故障新组合：仅有 runtime/state 证据，明确保持未验收，不用 deepcopy 代替 History replay。
3. PostgreSQL token 摄取 crash：未配置本轮真实PG，沿已有原子协议但不声明实测。
4. 任意宿主纯度／超出 guard 的代码修改：扩展为可信 Python；当前固定 identity/method/native core 有保护，不能当沙箱。
5. 最终全量／wheel／升级门槛：必须由下述实际结果关闭，review 初步回归不代替最终门槛。

## 最终证据

全量回归：3296 passed／92 配置依赖跳过，594.50s；未配置的真实 PG/Qdrant/Temporal 与线上模型不由跳过项验收。
安装 wheel 外部目录：127 passed，warnings-as-errors。
source／wheel／sdist／installed：192个 Python 模块字节完全一致。
独立 core venv 无 tiktoken／pypdf：核心冷导入、typed optional refusal、字节计量、SQLite token 摄取及原回执重放通过；只复制12个实际核心依赖分发包。
Ruff 检查／格式、Git 空白、pip check 通过；12文档308本地链接及15 Python 示例（含合法顶层await）校验。

本批次不声明完整 H3、精确供应商 billing、语义分块或 AgentScope 整体对齐。
下一批沿[持续能力队列](../../docs/continuous-development.md)实现文件 Artifact，再推进执行环境和其余绑定／服务能力。
