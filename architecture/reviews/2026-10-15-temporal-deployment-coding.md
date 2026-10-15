# Dev120：公共 Temporal Coding 部署验收

日期：2026-10-15。范围：第三阶段批次 2 的既定 Coding 部署子集；仅本地提交，不推送远端。SDK Session coordinator 仍为下一必需交付，批次 2 和完整 R01–R26 未完成。

## 实现与权威

显式公共 deployment3 接通既有 native Agent／顺序、有限图、Team／Dynamic 和递归 Coding 组合，与 ordinary2 共用同地址 Registry 的部署／Scope 根容量。原 Run／Parent History 继续拥有审批、native grant、调度、效果和预算；Registry 核对原树闭合证据后退休根额度，不增加第三套执行状态机。配置和恢复入口见[使用指南](../../docs/temporal-deployment-coding.md)。

所选3使用子事实通知、dirty generation、只读身份投影与紧凑 CONTROL，避免 Parent 自唤醒和重复大载荷。入口／公开出口的完整 Runtime 校验、中间传输与既有 ports、原 Activity claim／SDK 身份核验保留；稳态 read-set 不提供即时 read-auth 撤销。原生写入授权、bootstrap、grant 和业务期限不合并。fresh-owned publication 仅减少中间重复拷贝与验证，最终完整耦合校验保留。

owned 关闭先停止新提交，保留原 receiver、可信原生 stop／观察与退休处理器，等待原调用和资源结束。未知效果、零费用义务和缺失 ACK 不因业务终态或物理停止而清除。原 Tool 冷 fence 必须核对精确 owner、SDK 身份和物理证据；CONTROL／stop／普通 handler 没有通用进程死亡释放许可。

## 验证及证据范围

| 检查 | 结果与解释 |
| --- | --- |
| v30 完整离线回归 | 四个隔离分片重新执行 12651 个唯一节点：11847 passed、804 skipped、0 failed／errors，430.21 秒；无 prior-pass 复用、重复或遗漏。原1679文件快照及四份副本前后不变；跳过不构成服务或模型验收 |
| 后续测试修订 | 产品416文件不变；三个既有测试文件修订及一个新增关闭波次测试另有92项定向通过，6.09秒。不与全量计数相加，也不称新一次完整回归 |
| 原安装 normal 矩阵 | 13 passed、1 failed、0 skipped／errors，1204.19秒。原失败及恢复资料保留 |
| 诊断复现 | v31 单项1 passed，157.67秒；RAISE-only诊断，不计作 normal 验收或性能基线 |
| 修订后安装 normal 复验 | v32 并行 owned-close 单项1 passed，0 skipped／failed／errors，152.70秒；没有 trace／SDKTiming。目标 CID 停止故障实际命中，原4次原生提交未增加，原资源、unknown与关闭证据检查通过 |
| 安装出处 | 源码、wheel、独立安装416产品文件一致；已加载209模块均来自安装路径，无源码 PYTHONPATH。父进程和fixture Worker共用固定解释器及无src测试资产；不是逐子进程运行时采样 |
| 默认兼容 | 不可变dev119安装创建原默认History，由dev120安装Worker重放、续接；Profile／identity／Manifest／orchestration、原epoch／回执／结果与History前缀保持，新增Provider调用0；兼容Worker结束 |

代表性实际门槛由原矩阵13项通过与修订后单项复验分别完成，**不是同一次14项全绿**。范围包括Agent／并行图／递归入口、ordinary2／Coding3共享容量、never-used与递归审批树关闭、四类独立ACK、Tool Turn／candidate冷恢复、释放回复丢失及并行关闭故障恢复。历史13拓扑、真实Docker窗口及其他恢复结果继续按其冻结版本引用，不称在v32全部重测。

## 关闭用例修订与保留义务

原失败正面命中目标停止故障，但解除故障后的恢复调用仍返回 `CloseIncomplete`。后续fixture还释放了Turn gate，不能据其关闭成功断定单纯重试即可。独立确定性回归证明：调用方可加入尚未结束的旧cleanup任务；移除外部故障不会改变该任务已产生的失败，下一次显式关闭才可创建新任务。这不证明原服务失败的唯一因果。

测试按已公开的失败保留／显式重试契约修订：解除故障后最多两次恢复调用，原300秒总期限和每次80秒保持。第一次失败必须再次验证原账本、Client、开放PG、占用额度、未seal和无新增业务；第二次失败仍使测试失败。产品没有新增自动重试、超时或强制释放。

最终两项原物理资源均stopped／fenced／retired且transport closed，Assembly关闭、Worker退出。该故障场景的效果仍unknown：原根1 accepted／1 retained／0 retired，PG schema和恢复History按预期保留，证据错误0。容器退休与部署根额度退休是不同事实。

## 未关闭范围

公共SDK Session-coordinator准入仍拒绝；S1设计及私有纯DTO原型不算交付，也未开启publication4。跨宿主接管、完整服务身份／ACL、保留治理和备份恢复仍按[第三阶段矩阵](../../docs/phase3-support-matrix.md)推进。

结构native peer证明实际Temporal／PG协议、文件效果与生命周期，不新增真实模型质量结论。dev109有限真实质量、后续DeepSeek连接及单次Coding smoke保持原范围；没有本批通用质量、对等框架优势或延迟SLO结论。早期失败资料及未确认义务不因新Scope验证通过而删除。

## 产物核对

离线v30 XML SHA256：`a669db857ce60b54da65e226d7e4dab9a72e1572001177cadaef173a64e596d5`。
安装实际服务使用的v30 wheel SHA256：`9907f50f2382dd4ef754a6f84152a45255fea5684a2854884fcbe957e15f4dff`。
v32 normal安全汇总SHA256：`49d302a95a038e73ecb992bde3878e5c13b275ebce185b085baa7331f749cef6`。

最终文档／metadata重新构建并独立核对416产品字节；其新public inventory、wheel／sdist摘要保存在本地验收记录，不沿用旧wheel摘要冒称最终交付全文逐字一致。原服务与应保留的unknown资料继续由原所有者持有，不宣称全部服务已关闭。
