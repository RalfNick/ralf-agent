# dev117：Temporal 部署准入的 History 基础

日期：2026-10-14；前序本地提交 `40c2277`／dev116。[第三阶段支持矩阵](../../docs/phase3-support-matrix.md)的批次 2 仍开放。本批完成原 CommandRegistry 的内部登记与身份固定，不交付可直接启用的 Temporal 部署容量控制。

## 实现和独立审查

原 `ralf.temporal.commands.v1` Workflow 增加显式部署模式，不增加 EffectJournal 或业务调度权威。Registry 地址仅依赖部署身份；所选根地址纳入部署、Scope 和命令，避免多个部署指向同一 Run。首次完整策略与 namespace 固定，命令按 Scope 区分；新提交在一个无 await 的原 History Update 中登记命令与根额度。容量拒绝不产生身份；满额时原重复命令仍返回原登记回执，合法控制命令不占新根槽位。累计命令记录上限与活跃根限制分开。

登记根请求、首次 Manifest、namespace 和 proof digest 后，可以固定不可替代的 epoch 字符串。**当前绑定只登记调用方提交的身份，不证明该业务 Run 已真实启动或已通过 SDK 身份验证。** 登记回执保持 `not_applied`，与业务回执分开。查询只返回当前 Scope 的根定位及汇总计数，不泄露其他 Scope 的命令、Run 或 principal。返回值脱离原记录，修改返回值不会修改 History。

独立审查确认原子登记、固定身份和 Scope 隔离的结构；发现外层初始化 envelope 可为 dict 子类或产生原始 TypeError。补充四项 RED 后，在读取字段前要求 plain dict，转为明确拒绝。另发现显式 policy／namespace 都为 None 会落入默认模式，补充 RED 后明确拒绝。实际 Worker 在严格警告模式暴露准入模块延迟导入；通过既有 `imports_passed_through` 预加载修复，没有抑制警告。

默认 scoped Registry 路径保持原回执和行为。部署模式拒绝尚未接通的 Coding composition 路径。公共 Temporal Engine／Profile 仍维持已有预检拒绝；没有加入释放、TTL、强制驱逐或凭空清除未知义务的接口。

## 最终证据范围

| 验证 | 结果与含义 |
| --- | --- |
| 状态测试先行 | 28 项初始 RED；扩展发现 malformed kind 的 TypeError 后修复。最终 42 项状态测试通过 |
| Workflow 测试先行与修复 | 初始 15 项 RED；显式空值 1 failed／7 passed；外层类型 4 项 RED；最终 23 项通过 |
| 受影响源码 | 492 passed，零失败／错误／跳过；21 个选定模块，严格警告模式 |
| 独立安装 | 同一 492 passed，零失败／错误／跳过；仓库外安装，实际导入独立 site-packages |
| 最终真实源码服务 | 3 passed，零警告／跳过，8.98 秒 |
| 最终真实安装服务 | 相同 3 passed，零警告／跳过，6.05 秒 |
| 产品固定 | 403 个产品文件在源码、wheel 与安装中逐字节一致；wheel SHA256 `af5048a41099ebb5067fd7d567971c706c66e6511d1d1ac9460eac322a0731b8` |
| 默认发布兼容 | 不可变 dev116 的完整默认 Temporal Profile、Manifest、orchestration release 与当前 canonical JSON 相等 |
| 默认原 History | 原不可变 dev116 Worker 生成 History；当前 Worker 重放并续接，原查询与重复回执相等，两个 Worker 均结束 |
| 实验性 Worker | 原 dev116 完整 Coding publication 由匹配旧安装接受；当前 composition／native source 门禁明确拒绝，旧选定业务仍需原 Worker |

三个服务场景覆盖：多客户端、三个实际 Worker（两个原队列，一个变更队列）、多个 Scope 的总限额与 Scope 限额；满额重复、别名移动、合法控制和跨 Scope 拒绝，以及不能替代的身份；原 Worker 缺席时 Update 等待且原槽位保留，随后新 Worker 从原 History 继续并重放。六份源码／安装的所选 History 均重放，实际业务 Run、Agent／Parent 子孙调度、效果及安全释放均未在这些场景验收。

服务测试编写期间实现已并行到达，因此没有把其初次沙箱连接 PermissionDenied 当成实现 RED。服务 RED 是隔离原 HEAD Registry 的事后复现（原初始化 KeyError 后 Update 超时），只证明旧实现不支持新模式。严格警告实际复现为 1 failed／2 deselected、18.15 秒，最终严格模式两套均通过。缺少可选 SDK 的导入边界模拟发现服务测试在收集时直接导入 SDK Workflow，造成 1 项 collection error；移到实际 Worker 工厂并为 Workflow 单元测试声明可选依赖，随后收集与测试恢复，核心安装不被该测试强制添加 Temporal 依赖。这是导入边界模拟，不是另一套核心 wheel 安装。默认发布探针初次直接比较 Python tuple 与解析后的 JSON list 导致夹具断言失败；改用 canonical JSON 比较，无产品兼容缺陷。早期失败、警告和最终报告分别保留。

本批运行受影响检查，没有重跑完整阶段回归、远端 CI、PG 或真实模型。CI 增加源码与安装的独立服务入口，其配置存在不代表远端已执行。dev99／dev113 等历史质量与阶段证据只沿用原冻结范围。

## 生命周期与剩余必需门槛

测试只使用本批专用 Temporal 服务和私有数据库，没有操作其他服务。测试 Registry 的终止是测试清理，**不是产品准入释放**。源码与安装共六个测试 Registry 均终止，所选 Worker 均退出；原默认兼容 Registry 也按测试身份终止。专用服务在最终验收后关闭，私有数据与报告保留以供核对，不代表框架备份恢复能力交付。

私有目录 `/private/tmp/ralf-agent-dev117-root` 保存源码／安装 JUnit、六份 History／观察及 Worker 清理、固定文件清单、package provenance、默认发布／原 History 兼容、原实验性 Worker 拒绝与服务关闭记录。子进程服务验收不继承模型密钥；本批没有模型调用。

下一交付必须把该登记协议接入公共 SDK／Profile、原 Run／Parent 的业务 Activities 门禁和原子孙根身份，验证真实 SDK namespace UUID／原 epoch／发布，而非只相信传入字符串。还需不确定启动的持久恢复、原业务回执，以及原 History 的终态／零金额预留／未知效果／辅助写入／实际处理器和物理停止证明闭合后的安全释放。释放失败继续占位并能恢复；旧 scoped 部署的纳入或明确空部署前提需验证。以上仍是批次 2 必需门槛，不因本基础测试通过而删去。

预计下一交付包含执行接入和恢复／释放两部分，工作量高于本批纯登记协议；验收后才继续托管观察与服务控制。完整 R01–R26 与通用 AgentScope 对齐仍未完成。本批仅本地提交，不推送远端。
