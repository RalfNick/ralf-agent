# S2 联合发布校验与取消关闭修复

日期：2026-10-20。基线 `e9f8cf1`；仅继续原 S2 整链耗时和取消关闭修复，不增加功能。原失败、原 a1 制品及门槛保持；不推送或公开发布。

## 定位及最小变更

完整 CONTROL 的离线 CPU 诊断确认每次调用重复执行大量指纹 helper 元数据检查及完整材料构造；这不是实际服务整链的 CPU 归因，也不据此推导线上收益。三个隔离原型（扁平库存、绑定校验流水线、分段库存）收益分别 5.572%、3.124%、4.500%，均未达到原 10% 门槛，未进入产品。

最终仅变更两处产品实现：

- 指纹 helper 以原强引用逐字段执行新鲜 `is` 比较，替代每次重建身份元组；继续保留原 CodeType LRU、有界纯代码资格及每次源码／别名检查。补复现发现的字典键回调 P2：外来字符串键可借 `__wrapped__` 查询回调临时替换 digest helper。两项 RED 后，直接核对原字典／键身份，拒绝额外或外来键后才作字典查询；非标准元数据走原无缓存路径。
- 已有 owned Coding 公共部署组装 Context／Tool 前缀时复用现有 `propose`；注册检查、构造器完整校验、最终 Coding／deployment 联合 `publish`、`validate_release` 新鲜固定材料比较及 getter 后复核保留。未新增校验结果缓存、执行权威或替换通用拷贝。非 owned、legacy 和独立 publish 维持原路径。

关闭问题区分产品契约和测试宿主责任：a2.dev2 首轮 CloseIncomplete 出现时原 Worker 尚在，测试宿主随即退出借用 Worker，外层再重试导致 no-poller RPCError。现有 Assembly 会保留未完成的 owned 关闭任务，宿主应在借用 Worker 仍服务时重试。仅修测试宿主：只重试 `CloseIncomplete`，共享原第一轮 **总计 60 秒绝对期限**；其他错误立即传播。原业务 360 秒、外层 cleanup 40 秒以及原 80／60／180 秒工具／Runner／审批期限不变。测试覆盖原 body 异常、递减剩余时间、总期限和不可重试异常；实际取消后关闭结果以本批服务门禁为准。

## 前置证据

原始目录 `/private/tmp/ralf-s2-owned-proposal-20261020`：冷进程 A/B/B/A，各块四次完整 CONTROL，基线／候选各八次。CPU 中位数 **1.3628425 → 1.2093595 秒，减少 11.261976%**，达到原 10% 门槛。SDK 调用计数、各版本完整输出和证明、物理查询及输入不变检查通过。该探针使用实际 Runtime／BindingCatalog 和 SDK 形状的纯端口，不连接 SQL／原生服务／模型；不同版本各自声明的摘要不同，不声称跨版本全部材料字节相同。仅 helper 改写的 5.358% 不单独算性能通过。

一次独立聚焦审查未发现可行动 P1／P2 或 minor；独立相关单测 **183 passed**，另核对字典子类／外来 wrapper 键。它没有运行安装、History、starter、真实服务、原 360 秒门禁或其余 17 项；不把审查结论当作这些验收通过。

## 固定私有制品

`0.1.0a2.dev3`，wheel SHA-256：

```text
2bc793c16cfa671b8d9972ad86827604f147b4f578e2530972bab62a3cea4d2b
```

目录 `/private/tmp/ralf-s2-joint-close-fix-20261020`；442 产品文件、947 测试输入固定，源码／wheel／独立 site 一致。仅第三方依赖复用既有安装，不执行父环境 editable `.pth`；测试进程 `-I` 并验证所有 SDK 模块从本候选 site 导入。该包是本地专项候选，不覆盖 a1，也不继承其平台验收；历史显式源码固定的 Worker 仍须使用匹配原制品恢复，默认发布／原 History 兼容另行核对。

## 实际验收

安装受影响 443 模块首轮 **6502 passed、3 failed、694 配置 skipped，602.83 秒**，全部 417 个已导入 SDK 模块来自本候选 site，442／947 输入不变。三个失败均在旧 Worker 错误保留单测的 `wait_timeout == 60` 断言：新绝对期限传入 `59.999999…`，尚未执行模拟关闭错误。原日志／XML／测试文件完整保留。

仅调整该测试文件的单测边界：Worker body／cleanup 异常保留测试使用一次关闭桩，仍验证原 60 秒参数、原异常对象和两异常并存；真实重试及总期限由新 receiver-close 四项覆盖。产品及 wheel 没有变化。改后一处测试 SHA、其余 946 输入不变和 SDK 来源重新核对，独立安装的两个相关模块 **36 passed、零跳过**。不重复运行未变产品的其余模块，也不把两轮拼接成一次全量全绿；`qualification-result.json` 明确保留原失败和定向复验范围。

默认材料与原输出逐字节相同，按原排除结尾 LF 的约定 SHA 为 `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`；两份原／继续 History 离线重放通过，两条 starter 各只写一次。没有真实模型调用。

### 原 360 秒实际首项：仍失败

固定同一 wheel，按原 `graph-sequential-sdk` 两轮 Session 场景，在新自有 PostgreSQL／真实时间 Temporal 运行：**1 failed、零跳过；JUnit 465.431 秒，pytest 466.37 秒（均含取消收尾）**。第二 Turn 的审批状态 Query 被原整链 360 秒取消；累计 **7 次原生提交、3 次业务写入**，未完成预期四次写入及两 Turn 回执，不计通过。

第一轮总计 60 秒关闭在原 Worker 仍服务时耗尽，等待原 Coding stop task；外层原 40 秒 cleanup 仍 `CloseIncomplete`。首轮错误由本批有界等待报告为 `TimeoutError`，不是已证明关闭成功。两 root 已接受、1 退休、1 保留；Session 关闭未确认／证据不匹配，存在未采纳写入，schema 正确保留。所有借用 Worker 最终退出；本批 Temporal 关闭、PostgreSQL 按原 owner label 校验后停止并保留，旧资源未动。

保留的关闭任务栈为 `composition.close → _close_subtree → _close_child → _fence_leaf → stop → reconcile_history → TemporalCodingAuthority.check → CodingValidation._fresh`；另有原 Context end-ACK 等待生命周期 Query。日志包含 524288 字节告警阈值以上的原协议 Payload 以及 `consistent query buffer is full`。这只能证明原查询链在该时刻未收敛，**不能把全部未归因耗时归为 SDK、网络或该一条 Query**；也不能证明把 Worker 多保留 60 秒已解决生命周期问题。本轮未给实际整链加 profiler，离线 11.262% 不外推为整链收益。

其余十二正常／五故障 **未启动**，`remaining-matrix` 未创建。外层每项 600 秒维护看门狗没有触发，不能取代原 360 秒。S2、P3-2 和 P3-A 整体仍开放；本批闭环的是额外指纹 P2、联合前缀组装成本和测试宿主借用责任，**整链耗时与实际取消关闭尚未修复完成**。

## 可复查证据与后续边界

安全副本 `dist/s2-joint-close-20261020/`（本地忽略目录）保留 wheel、原／定向回归、兼容、CONTROL ABBA、聚焦审查、三个未采纳原型、服务结果及原文件哈希。原始实际导出与服务数据库留在上述受保护临时目录，连接凭据不复制／不提交。`copy-manifest.json` 记录原／副本 SHA，`SHA256SUMS` 可逐项校验。

下一步应以当前固定候选和原 History 复现关闭中的具体 Query／完整调用，区分 Workflow 查询处理、数据转换和本地校验的等待／CPU；先形成有界因果复现，再决定原边界内的修复。不以重复未变场景、继续调局部缓存、跳过新鲜身份检查、已否决的通用克隆／RawValue 或提高期限代替整链修复。本轮不承诺门槛未满足的组合已支持。

## 保留与限制

所有原失败／否决原型和中断诊断保留。a2.dev2 的 Session 关闭未确认／Assembly RPCError、schema 和已停止失败容器不删除；本批使用新自有服务，旧资源不动。原 a1 wheel／sdist 不重建、不覆盖。当前仍不据离线收益或测试宿主修复宣称 S2、P3-2 或第三阶段完成；真实模型质量、独立采用及长期能力范围不变。

提交前检查：9个Python文件的Ruff／格式及Git空白检查通过；607个本地文档链接存在，442产品／947最终测试输入与安装及实际首项保持一致。原a1两包SHA不变；安全副本297项SHA逐项通过，不含连接凭据或原服务数据库。
