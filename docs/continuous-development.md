# 持续能力开发与验收队列

用户授权：2026-10-10 持续执行直到能力完成；只本地提交，不推送远端。
当前 dev55 已验收本地 POSIX 子集（基线6001fef/dev54）；实际提交 SHA 以 Git 为准。此队列落实既有架构，不新增执行权威。
权威范围：[剩余清单](remaining-work.md) R01–R26、[Harness 架构](../architecture/viewpoints/harness-runtime.md) H1–H5。
历史设计中明确后置的高级 Realtime/TTS、公共插件市场和运行中热迁移保持单独路线图；按需适配器不以数量定义完成。

## 执行与记录

按依赖逐批开发、复现、审查、验证、同步能力文档和本地提交。批次完成后继续下一批。
不把本页的勾选代替验收；每个能力的接口、默认、另一实现、配置、身份／生命周期／恢复和实际证据分别记录。
真实服务、真实模型、外部采用缺证据时保持未验收，继续能独立推进的实现。涉及确实不可逆的外部发布或缺授权才暂停对应动作。
当前批次详见实施记录；上下文压缩后从实际 Git 提交和能力文档恢复位置，避免重复已完成工作。

## 依赖队列

- [ ] H3 计量与数据：R14/R16 可替换 tokenizer、token 分块及输出预留；R18 文件 Artifact；R15 全库语义索引与记忆生命周期；R16 来源／索引生命周期。
- [ ] H1/H2 闭环：R01/R02/R04 Temporal 其余绑定与共享 Session；输入续接、deadline／审批期限及明确移交；公共能力／错误／生命周期组合矩阵。
- [ ] H4 执行环境：R12/R13 Workspace／文件访问、固定 CLI Runner、MCP HTTP／权限、受控 Sandbox、Skills／Coding／首个外部 Runner；R11/R20 受控团队交接。
- [ ] H5 服务治理：R19/R21 单权威多 Process Worker、全局容量与背压；R18/R20/R24 保留／迁移／恢复；R22/R23 Agent Service 与流式观察／基础控制台；R24 企业身份与源 ACL。
- [ ] 横向能力：R05 多协议模型一致性／Gemini工具／路由；R06 媒体；R08 高级节点与合并；R09 数据流工作流；R10 受管理验证；R17 检索／适配／索引；R25 可复用 AdapterContractSuite。
- [ ] R26 质量与 M1：固定最终组合反复实测、分组故障与升级报告、真实服务验证、外部首用，以及同配置 AgentScope/LangGraph 比较。外部采用不由内部测试替代。

## 当前批次

- [x] dev54：TextTokenizer、字节基线、可选 tiktoken、同单位输出预留和 token 分块；字符默认保持。3296/92 全量、127安装包、192模块一致、真实 cl100k_base25块和原回执兼容，见[验收](../architecture/reviews/2026-10-10-tokenization.md)。
- [x] dev55 本地子集：FileArtifactStore 与显式配置，复用 Scope／digest／TTL／读取限额及 namespace 容量；补掉电／原回执／受管理卸载恢复。文件 payload 和耐久 metadata 必须完整确认，缺失／损坏不静默成功；孤儿清理与全局配额另验收。
随后继续上述队列，只有实际验收闭环的项才关闭。

### dev55 进行中（6001fef 后）

SDK／JSON/TOML 配置、真实进程发布窗口／并发容量、Local 图／Team／动态 DAG／嵌套卸载崩溃恢复，以及 Temporal runtime/state 和实际 Worker 装配已通过。独立审查三个 Important（孤儿同步、索引入口别名、实际持有的描述符）均 RED→GREEN 修复。115项初步源码与117项最终安装包契约、193模块一致、独立 core venv 和 dev54↔55 原默认／Run／SQLite引用兼容、21 starter 字节保持通过。最终完整3343/98、最终 wheel117通过；本批次真实 Temporal 服务仍下载，实际 History 不由状态测试替代。详见[实施验收](../architecture/reviews/2026-10-11-file-artifacts.md)。

任务临时目录由 /private/tmp/ralf-agent-dev55-current 指针定位；只有其服务进程确认停止后才能清理。服务下载在 /private/tmp/ralf-agent-dev55-5hg43c2i/temporal/bin，活跃 runner 原会话6304。dev54 临时目录已清理，dist产物保留。批次提交后继续 R15 全库语义索引与记忆生命周期、H4/H1其余主链路。

最终回归已成功结束（3343/98，589.88s），日志 full-suite-final.log；旧首轮亦结束。close 增加 fstat 身份后释放，避免 fd 数值被复用时误关闭其他资源。重新构建安装包并重跑相关门槛已通过。

下一批 R15 优先补有界、可续接的事实枚举，不直接扩大旧 SemanticMemoryStore 候选窗口。原始 Facts 仍是权威；新 scanner 必须覆盖 current/expired 记录、固定 generation、Scope、字节限额、无遗漏 continuation 及版本变化拒绝，默认 memory/SQLite，async/远端独立适配。此端口用于全库派生索引与显式迁移，不能把分页完成当成语义质量或全库索引已交付。随后索引构建／激活和检索前源版本校验仍按 R15/R17 独立闭环。

下一批暂存 tests/protocol 原型位于任务目录 test_fact_scan_next.py／fact_scan_next.py，六项核心缺失功能 RED 已确认；尚未加入源码。dev55 本地提交后转入 dev56，不用原型存在宣称完成。服务及已下载 binary 文件由本线程继续托管，暂不清理该任务目录。
