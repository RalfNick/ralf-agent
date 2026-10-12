# 原生 Workspace 写入的真实 Temporal 生命周期验收

基线 `11581df`／dev80，沿 R13/R19/R21 和原 Run／Action／Runner 契约推进。
补齐 dev77 延期的实际原生写入取消、关闭和第二 owner 租约窗口证据。
本阶段复用原 FD、WriteJournal、Source2、WorkerExecutionOwner、Temporal History 和 PostgreSQL EffectJournal；
不增加执行权威，不把 SDK Task 取消当作真实线程结束。

## 场景与责任

自有本地 Temporal／PostgreSQL，显式 Agent、顺序、Graph、Team、Dynamic、嵌套六种原定义。
只允许对测试临时根的 `note` 写入，首次审批后在真实 `os.replace` 前阻塞原 handler。
观测线程实际开始，重复原审批，提交显式 Run 取消，并尝试以零等待关闭 Assembly。
未退出时关闭必须报告 `CloseIncomplete`、原 Root FD／租约保持，第二原生 owner 不得取得该根。
关闭后的原 Engine 不接受业务推进；观测使用原 Client／Scope／原 History。
未实际退出的线程不能被记为已停止；可见业务取消与真实静止证据分别记录，不允许取消后的成功或新成员业务派发。

释放原阻塞点后，必须看到真实 handler 返回／线程结束，再排空原实际调用及原结束通知，关闭 Worker 与 owned 资源。
实际退出后第二 owner 才能打开原根，查询同一稳定效果键的原本地回执；不得通过重放原写处理器找回结果。
原文件效果最多一次。重新装配原 Profile／Worker，只查询或核验原取消／未知效果，保持原取消结果和稳定回执、固定发布。
History replay 必须通过。记录业务状态、quiescent、未知效果和实际结束各自证据；发现矛盾先写失败复现再修正，不自行放宽验收条件。

## 测试边界

真实服务用显式配置选择，普通无服务测试可跳过，但本批必要源码／安装服务验收必须零跳过。
阻塞仅匹配测试根的 `note` 原生 replace，不影响 SDK／pytest 其他文件操作。
线程阻塞最多30秒、事件启动等待15秒、单场景90秒；finally 始终释放阻塞并关闭所有原 Assembly。
自有服务限回环及临时 Unix socket，原启动进程实际停止并等待退出；不启动 Docker 服务、下载镜像或调用模型。
保持原 JSON／工具／默认发布和22 starter，真实旧 dev80 双向兼容证明不可用源码模拟替代。

## 交付判定

这是已交付原生写能力的实际运行与恢复门槛；优先复用已有实现。
若测试直接通过，增加证据及可重复测试；若失败，在同一阶段按实际问题修复原层职责并固定协议兼容边界。
本批另外允许独立处理 dev80 两项文档 Minor：明确默认 YAML merge key 限制，并恢复历史 dev79 段落标题；它们不改解析行为。
产品保持 dev80，所有必要实际场景通过后才升级 dev81。全量／全新安装／固定源码包及旧兼容门槛继续沿原流程验收。
Sandbox／Runner／selector／自动目录阶段／治理／真实质量仍是后续能力，完整 R01–R26 保持 ACTIVE。
