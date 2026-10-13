# dev103：Local 原 Action 的 Coding 委托

本批交付显式 SDK Coding 工具、具体 `CodexCodingRunner`、原 Local Action 准入及
原容器停止／移除。支持根级未绑定 Agent 和顺序 Workflow；不关闭完整 R13、第二
阶段、Coding G1–G8、M1 或全部 R01–R26。dev99 四条已验收参考链路继续冻结。

## 架构和交付范围

- Harness 仍只提出方案；Local 仍是原 Run／Action、审批、预算、控制、终态和
  效果分类的唯一权威。Runner 不推进业务状态，也不能凭 DispatchEnvelope 自行启动。
- 完整一次 Turn 只使用原 Action／attempt／effect key／额度预留。阶段准入在
  原事务中先于 prepare、thread/start、turn/start；句柄先写 RunnerJournal，再由
  原 Run 采纳。丢失回执不重发，冷恢复不追加 Turn 或创建替代环境。
- opt-in `local-10`／delegated protocol 1／SQLite Schema 14 仅在首次原接受事务中
  启用。公共 DelegatedExecutionStore 定义升级、预留回读及有界 pending 查询；
  冷发布和关闭依赖公开端口，不依赖 SQLite 私有扫描。
- 默认环境仍保留并可重启；显式 retire_on_stop 才停止原 CID、核对 PID 0、保存
  retirement intent、移除原 CID、核验 absence、保存 fenced，撤销旧启动 argv。
  停止失败或证明无法保存时仍保留原 Coordinator 和证据接收方。
- 成功须具有原 completed Turn、最终原 Thread 读回、实际容器 fence 和传输关闭。
  有界事件接收保持到关闭，最终排空保留非法原生 peer 请求。输出为空且无产物
  时拒绝候选；产物清单仅记录有限普通文件，不等于 ArtifactStore 发布。
- 注册借用 Runner；Engine 不关闭它。真实线程／Popen 的退出独立于 asyncio Task
  完成，Runner 关闭未确认时返回 CloseIncomplete，不能提前释放原权威。

## 独立审查与问题闭环

同一独立审查者复现并复验五项 P2：完成后 peer 等待被遗漏、空原生候选成功、
自定义 Store 隐藏私有扫描绕过冷关闭、不支持的 Temporal 声明越过模型 I/O、
普通 Schema／参数中的 tool 数据被误作声明。修复分别落实持续接收／最终排空、
公共完成校验、严格公开 pending 端口、提前拒绝、按语义遍历实际声明。

五种原始原生反例均保留 waiting_reconciliation、零候选、原资源 fenced 和实际
owner 0；原 Thread／Turn 总提交次数仍为二。全事件循环取消、持久化 stop 故障、
原 metadata 缺失、根目录缺失及 CID 被替换的额外恢复探针均不能越过关闭门禁。
这些业务测试使用实际子进程和确定性 Docker／API 夹具，未使用真实模型。

完整回归另发现既有 CLI 的 Darwin zombie-group EPERM 竞态。修复只在 EPERM 时
有界重试原 PGID／信号并 poll 回收直接子进程；poll 不充当组退出证明，后续原
信号仍须成功或 ESRCH。持续 EPERM 和其他权限错误保持失败。独立内核反例从
1 failed／40 passed 修复为 41 passed；额外三个实际进程反例与作者 100 次原夹具
通过。不据此增加一般逃逸后继进程或可信 CLI 的沙箱保证。

新建假 Docker 可执行文件冷 shebang 启动在独立 source／installed 配对测量中
超过 0.3 秒。夹具增加无 I/O 的 readiness handshake，断言 executable 字节不变、
无状态／租约／数据库生成。原 0.25／0.3 秒产品调用 deadline、故障与停止证明
断言均不变；同一审查者冻结复验 66 passed／零跳过，未削弱产品边界。

## 会话恢复观察与实际退出的边界

V3 完整回归另遇到远程 Session 恢复后立即断言 busy=false 的原夹具失败。
独立审查在原 `_finish_node` 提交 succeeded 后、返回前设置可控 Event，当前源码
与原 dev102 安装包均得到 wait=succeeded／原 receipt 已核验／零新 I/O，但真实
operation／drive／hosting 尚活跃，Session 正确地保持 busy。释放并等待既有
settled(runtime) 后 busy=false。相关四个公共观察／会话模块与旧版字节相同。
该次原失败日志没有具体活跃位，不追认某个回调为唯一触发原因。

修正限于测试等待实际托管退出；终态、零重复 append／Provider、原 revision 和
最终 busy=false 断言保持。产品纯观察等待及真实退出门禁均不修改。

## 验证登记

本批私有证据目录：
`/private/tmp/ralf-agent-dev103-root-3ird5xup`。

| 检查 | 最终证据 |
| --- | --- |
| 完整源码分片回归 | 8791 passed／634 配置跳过，覆盖全部 556 模块。修正夹具分片最终 2574 passed／59 skipped；其余 V3 通过分片产品／测试字节未变，逐项核对后复用；保留 V3 原失败 |
| 固定 wheel 独立安装 | checkout 外 623 passed／零跳过，88.33 秒；只复制测试／工具／JSON，不复制 Python 产品源码；公开 SDK 与安装 metadata 均为 dev103 |
| 实际普通 Run 兼容 | dev102→103、103→102 同一原数据库均成功，原 manifest／definition／release 相同、默认 Schema 1；显式委托 local-10／Schema 14，原 dev102 在零 Provider 调用前拒绝 |
| 实际安装后的环境 | 同一 coding-mode 连接九项只读控制通过；原容器移除／PID 0、旧 argv 拒绝、同 ID／generation 冷 tombstone、实际 worker 0；auth=false／native task=0 |
| 产品制品一致性 | 362 模块源码／wheel／独立安装相同；旧 346 模块字节保持、13 个旧模块改变、新增三模块；三个包内 Codex JSON 字节保持。源码／wheel／sdist／安装逐文件一致，最终测试及文档亦在 sdist 中核对；证据保留于 package-provenance.json |
| Ruff／格式／空白 | 全部 src／tests／tools Ruff 通过，994 个 Python 文件格式通过；Git 空白通过 |
| 审查闭环 | 同一审查者关闭五项 P2、CLI 退出竞态，并确认两类时序夹具修正保持产品门禁；没有遗留阻断项 |

通过普通根 Agent 的跨版本恢复不代表所有历史编排与 Temporal 已验收；本批 Temporal
只验证不支持的所选 Coding 在模型／工具 I/O 前拒绝，没有真实 History Coding 测试。
上述恢复夹具也不证明原生模型任务质量。最终摘要保留于私有制品／安装／回归报告。固定 wheel SHA-256 为
`a52be7ecea7723f167382b30d13ff765d3f3badae631481cc32d786cee4fa71b`。
634 项跳过不作为实际服务通过；本批未重跑冻结参考模型任务。

保留的先前运行不能计入最终通过：

- 第一轮单进程完整运行因源码仍有修复而中断：1624 passed／34 skipped，退出 2。
- 第二轮并行完整运行：2 failed／8777 passed／634 skipped／3 errors。失败包含
  CLI EPERM、公开 SDK 版本号未更新；三个错误为并行 wheel 构建争用相同目录。
- 第二轮独立安装：1 failed／561 passed，为上述冷夹具命令启动测量。
- 第三轮全量的一个分片：1 failed／2573 passed／59 skipped，为上述终态观察
  早于实际托管退出的会话夹具；其原失败与独立可控边界证据保留。
- 初步兼容比较使用不同数据库路径导致身份不同；保留失败记录，正式比较使用
  同一原数据库。上述失败日志没有删除或追改为通过。

## 实际环境证据和未交付门槛

实际原生固定镜像／版本的有限命令、路径／网络负向检查和整容器停止证据沿用
本阶段明确资产；本批原容器移除、旧 start argv 拒绝及同 ID／generation tombstone
冷核验另有实际 Docker 证明。业务协议夹具不与这些证据合并成模型任务验收。

未读取／挂载宿主认证，未请求原生业务模型；credentials=unavailable、usage=unknown。
仍缺专用认证和真实 Coding 质量、per-Agent Runner 绑定、JSON／TOML 工厂、
图／Team／动态／嵌套和 Temporal History 准入、跨宿主恢复、完整隔离和硬费用上限。
这些继续按[委托契约](../specs/delegated-coding-action-contract.md)验收；
[SDK 使用边界](../../docs/local-coding-delegation.md)提供当前可用组合。
