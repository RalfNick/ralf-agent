# dev68 Temporal Context 实际读取生命周期验收

状态：本批子集验收通过；基线0917d72/dev67；仅本地提交，不推送远端。
完整 H1/H2/H3/M1、R01–R26、Temporal Profile 装配、企业治理和真实质量继续开放。

## 行为与抽象

- 显式 `context_reads=True`：五类只读阶段 context/plan/read/verify/finalize，固定可替换 `ContextExecutionPort`，默认 `ContextExecutionOwner(max_calls=8)`。
- Owner 独立托管许可等待、实际 async Task、明确桥接的线程和结束 ACK；原 Native History 独占许可／响应／准确结束事实及业务推进。原 Parent/Coordinator 使用原静默门禁，不增加业务状态机。
- 所有已注册数据／客户端保持 borrowed 和原创建循环；注入 Owner 也 borrowed，Runtime 等待并关闭自己的读取入口；默认创建的 Owner owned。
- 线程 Session 元数据通过原 ThreadedMemoryAdapter 跟踪并固定实际 bridge，缓存快照后的元数据仍是真实 I/O。原 dataset_ports 不变。
- 新协议 binding2/context_read_protocol1；默认 False 及旧 save-v1 的 Manifest／请求／重试／History 保持。dev67 对 binding2 在任何 Activity 之前拒绝。
- SDK 绑定原 Workflow UUID／namespace，源身份在 await 前后复核；原响应与实际结束都已采纳才可推进。读额度0，容量是每 Owner 的在途上限，不是全局限额。

## 单次独立审查与修复

Fresh-context Astra 只读审查整批工作区（包括新文件），独立运行125项相关测试通过。没有二次审查。
3项 Important 由14项先失败的回归复现，再修复；相关114项通过：

1. 结束 ACK 后重复派发：原 History 在结束后拒绝新许可观察；SDK 使用新的 Update 观察身份，避免服务缓存的旧 allowed 回执授权新读取。保存原历史许可，不创建无限 Owner tombstone。
2. borrowed 关闭漏掉许可等待：许可等待进入独立 Owner Task；关闭等待它结束，并在许可返回后复核 closing，不能在关闭返回后启动读取。
3. 许可已持久化但观察取消／响应丢失：保留原通知责任并向原 History 解析许可不确定性；全循环取消后的实际线程和通知仍能等待，不能只靠观察 Task.done 确认停止。

Critical／待办 Minor：无。

## 最终证据

Python3.12.7；其余 CI Python 版本本轮未本机执行。

| 验证 | 结果 |
| --- | --- |
| 固定最终源码完整回归 | 3940 passed／306 配置依赖 skipped；498.96s；2378 exit0 |
| 修复后真实服务（源码） | 39 passed；291.05s；9263 exit0 |
| checkout 外干净安装契约 | 241 passed；22.69s；63948 exit0 |
| 干净安装真实服务 | 39 passed；303.78s；26005 exit0 |
| 制品 | 隔离离线构建 wheel/sdist；231个 Python 模块在源码/wheel/sdist/core/完整安装一致；版本与 METADATA 0.1.0.dev68 |
| core-only | 无 SDK/Redis/PG/tokenizer/PDF；原图根／成员两Turn及新读协议、原生 SQLite 保存可运行 |
| 静态检查 | Ruff／format／Git 空白检查通过 |

39项真实服务分别覆盖：七种实际编排普通／managed 两Turn及全部根／子 History replay14项；真实页／后快照元数据线程、取消／server timeout12项；Redis及隔离PG schema4项；每Agent自动规则／模型选择记忆、RAG缓存来源、摘要和SQLite／文件产物5项；独立 Worker kill+wait/restart 原快照和丢失结束通知4项。PG16.15只开自有0700Unixsocket；Temporal CLI1.9.1/server1.32.0；仅本任务localhost17268。没有调用真实模型或认证在线模型质量，没有将306跳过项算作验收。

真实安装 dev67→68→67→68：Local 原审批／Run／Session／准确回执、三个默认配置、21种 starter、原 Artifact 和 typed receipt 身份保持。Temporal default 与 native save-v1 各自 dev67→68→67：原审批／重复命令回执／Turn／结果与 History 重放，一项原 Run 仅一次测试工具执行；旧67拒绝新 binding2，没有 Activity/data/model/tool 派发。

初始 native 兼容 fixture 硬停 Worker，同时观察 Activity 使用默认60s，却要求15/30s内释放；该运行不能算通过。实际诊断之后确认原 Run succeeded/quiescent、Coordinator idle、无重复效果。最终明确2s Activity timeout，正常关闭自有 Worker，等待原 Run 与 Coordinator 双门禁后切换，80612 exit0。仅修正 fixture，没有修改旧协议或用查询隐式恢复。

自有 Temporal68306 与 PostgreSQL37483 均正常 exit0 且 stopped 文件确认；Redis fixture及所有 Worker子进程分别关闭并实际等待。不留测试服务运行。

## 决策及成本（按作出顺序）

1. 注入 Owner borrowed、默认 owned：应用协调共享 Owner 最终关闭；成本是 Runtime 关闭不能推断全局共享资源已关闭。
2. 新协议无效响应记为失败证据并保留门禁，避免清除所有权后的 Workflow-task 重试；成本是使用者检查 Run error／证据，而非依赖采纳异常。旧路径不变。
3. 元数据用原明确 ThreadedMemoryAdapter 桥接、前后核对原同步注册；成本是适配器必须遵守实际线程结束责任。本轮真实服务／漂移测试验证，不搬移 async 客户端。
4. 进程死亡后丢失通知需可信监督方在实际进程／委托工作退出后提交原准确证明；成本是尚需应用监督／人工核实，不支持重启即自动释放，更不证明任意写可重放。
5. 在验收前不提交，所以唯一 reviewer 审查 BASE→工作区及所有新文件；成本是依赖显式审查快照和最终源／制品一致门槛。本批已验证。
6. Reviewer 未认证模型／工具／summary／write／root Session 全生命周期：它们保持原独立契约；成本是 Context drain 不能替代其他关闭责任。
7. Reviewer 对自动进程监督的暂缓再次确认第4项：只验收 kill+wait 后监督恢复；成本是丢失通知仍需要监督介入。
8. Reviewer 将最终完整／安装／core／旧新兼容交还 executor：这些门槛本批实际执行；成本是局部审查通过不能独自构成发布资格。
9. 同一 Owner 不支持多事件循环线程同时使用；支持保留实际工作后的后续循环等待。成本是应用需按循环隔离 Owner 或显式同步，不能把异步客户端搬到其他循环。

## 后续

继续 R04 Temporal 配置装配、其余每 Agent 环境角色、跨权威 Session 租约／治理、索引维护和真实质量。Context 关闭只覆盖声明的五类读取；summary、产物写、业务模型／工具、root Session 读取／保存仍有各自责任。全能力目标保持 active。
