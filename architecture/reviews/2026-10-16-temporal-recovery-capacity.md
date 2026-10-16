# P3-3 公有 Temporal 根任务的有界保护控制

日期：2026-10-16。接续本地提交`46180da`，解决冻结矩阵中“累计命令容量耗尽不得令已有任务失去必要取消／恢复入口”的一部分；本批不关闭完整容量门槛或P3-3，不重开后置的Coding Session性能专项。

## 复现、根因与修复

原Registry在`len(commands) >= capacity`时拒绝一切新控制。容量1、首次接受并绑定一个公有根之后，首次取消／drive立即被拒绝；SDK每次drive另生成UUID，还会反复消耗普通额度。新增首轮5 failed／1 passed精确复现Registry2／3／4的拒绝，后续SDK固定唤醒身份、Parent重复观察、旧ID冲突分别先RED后修复。

最小修复沿原权威完成：公有Registry满时，每个原held-bound根最多增加一个纯cancel和一个纯drive记录。全Scope幂等检查仍在容量之前，固定原回执，不删除或覆盖旧记录。根首先受普通命令容量约束，因此保护记录不超过`2×capacity`，总命令不超过`3×capacity`。新submit、可变人工控制和descendant不豁免；原部署准入和预算没有改变。

公有SDK复用机械drive命令ID，每次仍发送fresh SDK Update。Parent重复drive恢复原session／memory提示并强制fresh child观察，限公有且未seal；保留原回执、cancelling与stop intent。旧命令可能合法占用该ID：原Registry有界查找可用或已匹配身份，以只读`durable:false`提示返回；SDK仅在真实冲突后重试一次原guard，不覆盖旧命令，不把提示当权限，竞争仍可安全拒绝。完整边界见[契约](../specs/temporal-recovery-capacity-contract.md)。

## 验证

- 最终18个受影响源码模块 **458 passed**；仓库外独立wheel安装同18模块 **458 passed**，均零失败／错误／跳过。新增11项涵盖满容量保护、有限重提、普通／人工背压、Scope／payload／冲突不变性、原回执发现、退休后拒绝新保护、旧ID保留及替代、实际Workflow command handler重复唤醒、原生取消后不重开、Parent停止和seal边界。SDK网络以测试transport替代；不是实际Temporal服务。
- 427产品源码／wheel／安装逐字节一致，运行前后产品及复制测试无漂移，隔离解释器导入来自安装目录，无checkout路径；依赖复用本机已有安装，无下载。
- 原冻结基础wheel与当前独立安装解释器的默认Card、普通空工具Temporal声明完整相同。用当前安装Worker离线重放此前保存的原始及续接默认History；不作旧selected History兼容声明。
- 首次离线重放脚本错误地使用占位Run ID `original-default`，产生Activity ID不匹配。按同一原证据记录的真实Run ID修正，仅重放步骤重跑；没有修改History、产品或重建安装包。一次扩大回归的调用曾引用不存在的测试文件，零测试运行；纠正清单后才取得上述最终结果。
- 独立只读产品审查无新增P1／P2，提出的旧ID冲突已通过RED→GREEN闭环；受影响Ruff／格式及Git空白检查通过。没有重复全量基础SDK回归，没有真实模型、Temporal／PG服务调用，也没有重跑S2性能矩阵。

新候选：`dist/p3-recovery-capacity-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`；SHA256 `08052d871d46d66609a7efdbc4928d7bf8e960789842d71a2140999a9b19db28`。证据目录 `/private/tmp/ralf-agent-p3-recovery-capacity-20261016/`，含安装XML／日志、哈希、默认对照及离线重放记录；制品旁保存verification与SHA256SUMS。此前基础、事件和HTTP控制制品保持不变。

## 版本及尚未完成

修改3个已有产品文件，均已纳入所选发布source inventory。新的实验性selected release指纹发生变化，旧Run／Registry须保留匹配的不可变package／Worker；协议整数2／3／4相同不代表旧Registry具备保护槽。不能用新部署身份代替旧任务恢复或清除原义务。默认对照及默认History重放不替代selected升级／恢复验收。

这只是根控制准入与机械唤醒的实现证据。普通scoped Registry、满容量的descendant控制和可变人工核验／审批仍缺完整契约及验收；根取消已接受不代表后代停止，unknown、效果回执、额度与物理结束继续分别核验。尤其复杂任务若需新descendant控制，仍可能被原累计额度拒绝。未验收的服务组合不列为已支持。

下一批优先统一剩余容量／恢复契约，再补所选真实Temporal服务与安装HTTP控制整链验收；预计先做一个契约与定向验证批次，不预估完整阶段工期。P3-2原360秒失败及剩余矩阵保留，P3-4／5／A依赖不自动解锁。本批关闭阶段门槛数为0，仅本地提交，不推送。
