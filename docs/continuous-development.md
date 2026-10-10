# 持续能力开发与验收队列

用户授权：2026-10-10 持续执行直到能力完成；只本地提交，不推送远端。
当前 dev56 全库索引本地子集已验收（基线ce32d6a/dev55）；实际提交 SHA 以 Git 为准。此队列落实既有架构，不新增执行权威。
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

## 已验收批次

- dev54：可替换Tokenizer、字节基线／可选tiktoken、输出预留与token分块；[验收](../architecture/reviews/2026-10-10-tokenization.md)。
- dev55：POSIX FileArtifactStore、SDK／JSON/TOML与受管理卸载恢复；3343/98、安装117、模块193、core及旧回执兼容。随后官方CLI1.9.1/Server1.32.0的实际Temporal file6＋SQLite6通过；[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。功能cde3966，真实服务补记ce32d6a，仅本地。
- dev56：有界FactScanner、固定snapshot、独立CAS元数据端口、全库构建／accepted embedding／幂等vector／完整active、权威召回和JSON/TOML独立工厂。memory/SQLite/Redis来源，显式HTTP/Qdrant；[验收](../architecture/reviews/2026-10-11-fact-indexing.md)。最终3397/98、安装74、模块197、core与dev55↔56原回执兼容通过。

## dev56 设计与证据

四个实际进程窗口覆盖response保存／vector ACK丢失／page commit／active commit，2次已接受batch与最终4个vector保持。
真实Redis270条、Unicode／大整数／过期、snapshot变化及client+SQLite向量重开；完整ready复用不重复Embedding。
独立review两项P2（DataPort忽略Qdrant物理身份、SQLite大key未截断）已针对RED→GREEN修复。Qdrant新组合HTTP fixture不是实际服务质量。
Scanner是显式宿主枚举，含expired不自动扩张Agent权限；recall是全库排序top256候选分页，不是全库枚举。
默认Hash是离线词项基线，写后显式rebuild；自动增量／修复／GC和真实语义质量均未完成。不关闭整个R15/R17/H3/M1。

## 下一批依赖与主链路

1. R15/R17：PostgreSQL native snapshot／有界scan、真实远端索引组合和全库索引质量；再推进自动增量、信念修订／遗忘与索引生命周期。
2. H1/H2：Temporal其余Facts/Knowledge绑定、共享Session与输入续接；业务deadline／审批期限和移交。
3. H4：Workspace／文件权限与固定CLI Runner，MCP HTTP／受控Sandbox／Skills与首个外部Coding Runner。
4. H5与横向：容量／保留／迁移／服务观察、模型一致性、可复用AdapterContractSuite及真实质量／首用／同场景比较。

缺少服务只阻断相应真实验收，不停止其他能力实现；版本适配不能靠原型或接口声明标完成。
PostgreSQL当前本机未找到initdb/pg_ctl；现有服务依赖测试保持配置跳过。继续寻找可用的隔离服务或推进不依赖该服务的主链路。

## 运行资源交接

当前dev56测试目录由 /private/tmp/ralf-agent-dev56-current 指向 /private/tmp/ralf-agent-dev56-zujg6n38。
full-suite.log确认3397/98，执行会话22663已exit0；所有fixture Redis已正常关闭，无托管中的新服务。
旧dev55目录 /private/tmp/ralf-agent-dev55-5hg43c2i 保留已SHA256校验的官方temporal-cli和验收日志。
旧服务43396与下载6304均已确认结束；SDK默认下载失败后改用官方CLI成功，下一次复用该可执行文件启动新任务状态目录，避免重复下载。
任何清理都先确认任务自有进程结束，不修改其他任务／用户服务。dist保留55／56产物；新功能仅本地提交，禁止push。
