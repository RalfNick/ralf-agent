# S2：实际查询种类与已发布 Manifest 验证成本

延续[原门槛恢复计划](../../docs/superpowers/plans/2026-10-18-s2-resume.md)及[SDK 成本证据](2026-10-18-s2-sdk-query-cost.md)。产品仍为442文件的c58a3b…安装包，930测试未变。本批无产品／测试修改，无新制品、执行权威、协议或支持范围。原Tool80／Runner60／审批180／scenario360／first-close60／cleanup40不变；其余十二正常／五故障仍由首项通过解锁。仅本地提交，不推送。

## 有效性与实际结果

私有CPython探针保留真实frame／物理线程栈，仅观察三类RALF外层Activity及SDK Query／Update／Signal入口。查询参数只导出有限静态kind标签，不记录Query ID、请求、头或异常文字；沿用的Activity记录仍含原执行关联ID。没有方法包装、源文件改写或产品缓存。146事件自检exclusive334.254ms／进程335.520ms，零异常／残留；同一原History十查询的五类标签各命中两次，完整响应及History保持，记账配平。

在本批全新普通持久Temporal／PG16上执行原360秒诊断，无其他CPU测试并行：**1 failed／零错误／零跳过，JUnit436.204秒含收尾**。三Tool均ok，分别39.493311／37.553983／42.892484秒，业务写入3次；2 roots中1退休、1保留，Session关闭未确认、Assembly关闭不成功。原fixture保留schema，原因包含root_retirement_unconfirmed、scoped_session_close_unconfirmed、session_evidence_invalid。已核对本批PG容器停止、Temporal shutdown终态；失败容器、schema、History／业务导出与Temporal文件保留，旧资源未动。前批同包无监控四Tool／完整关闭证据不覆盖本次失败，也不把本次监控结果单独认定为新产品回归。

工件`/private/tmp/ralf-s2-sdk-query-mix-live-20261018`。25,212监控事件全部开始／结束配平、exclusive非负且不大于inclusive，零异常／残留；源／安装／测试哈希前后不变。进程CPU324.333秒，本探针仅覆盖选定入口，不复用前批92.1%覆盖率。raw monitor SHA256 `77c972b457b639c1b5e721cb1e803346f1fa9c5d9aa214db0a350560125d5046`，query summary SHA256 `30ac4afb57ba136cd4e5afc8ef33f19be6a723a565b4b563b11e4c9bbc7751d7`，终态审计SHA256 `256588f7f4820e615b827750202159108a9f143e93a289a285cf2a90b158d0c6`。

## 实际热点已改变优化优先级

8,007次Query处理器exclusive CPU合计74.664秒；包括业务与收尾，不包含SDK响应编码、网络或Core耗时，各Query墙钟可能重叠，不能相加为关键路径。相同kind可来自Run、Parent或Registry，本探针未分别采样它们的实时频数。

| Query kind | 次数 | 处理器CPU秒 |
| --- | ---: | ---: |
| deployment_coding_validation | 1164 | 58.733 |
| deployment_admission | 485 | 3.441 |
| deployment_session_command | 881 | 2.426 |
| deployment_session_intent | 874 | 2.316 |
| deployment_session_root | 433 | 2.085 |
| deployment_closure | 53 | 1.822 |
| diagnostics | 36 | 0.071 |
| 其余（含有限other桶） | 其余 | 其余 |

因此已否决RawValue原型所针对的准入查询不是本样本主要CPU来源；即使单Query局部收益可重现，也不能外推原360通过。当前具体热点是compact Coding validation，而非仅大响应字节数。

## 原 History 的有界离线拆分

原第一根已完成History继续按原SDK／restrictions重放；新增node-basic／node-edge两个只读Query，两轮共14个响应成功、摘要相同，原History及观察缓存数量不变。Profile逐行检查无负值、self不大于cumulative且sum-self在窗口内。其节点样本分别重复3／5次部署Protocol验证及483／805次executable_digest；这些是该节点样本的计数，profile秒数含开销，不能乘以1164或外推所有Registry调用。

直接在原Registry保存History首次出现held-bound根的原State采样两次Query，不修改任何根或History。先把正常activation返回值原样保存，另送query-only activation并只消费Query响应；继续把原activation completion交给Replayer。最终完整重放通过，原SDK命令字节、Registry完整数据字典及外层commands数据前后相同。未启用cProfile；两次完整Query线程CPU为108.163／107.592ms，响应仅922B且摘要相同。这是单个原held根的离线样本，不是真实频数、SDK网络或无监控整链成绩。summary SHA256 `fca319a7bd3e1cff8368fcbc791ec7fd5f0a175dc22506924fa11330ab4498e7`。

另一次同位置原State仅开启PY_START计数，完整重放、状态／命令字节及响应摘要同样保持，两轮计数一致：

| 每次 held Registry Query | 调用次数 |
| --- | ---: |
| validate_manifest | 1 |
| validate_bindings | 3 |
| validate_descriptor／reject_runner_descriptor | 各27 |
| coding_enabled | 33 |
| Coding validate_protocol | 36 |
| composition validate_protocol／implementation／_fingerprints | 各37 |
| executable_digest | 5928 |

计数钩子有额外开销，本次只用计数，不把其时间当作无profile成绩。summary SHA256 `f8e3442c073f4932c3f3e7191da22a24f08bb4890edb05d44a50ee6a8cda18cb`。以上离线探针无服务、模型、SQL或原生Runner调用；不覆盖完整Tool／CONTROL，也不证明新的优化方案已安全。

## 失效诊断保留

Registry退役根的cProfile有13个负累计行，相关函数耗时全部撤回；不能用其表面调用栈分摊58.733秒。首次held探针把原activation completion变量覆盖为Query响应，完整重放未证明；已按完整参数核对自有PID50276，SIGINT未退出后SIGTERM终止（exit143），文件保留。修正返回类型后，空cProfile对象的Stats构造TypeError由独立小例复现，去除未启用的Profile及其Stats读取后，最终受30秒独立离线看门狗保护的探针成功。该30秒只约束私有诊断，不改任何产品／S2期限。失效目录及quality-rejected文件保持，不以成功覆盖失败。

## 下一步的固定范围

本批关闭阶段门槛0；S2及剩余17项开放。新的依据支持优先审查**已发布Manifest完整验证内**的重复Protocol／绑定校验，避免再次测未命中该分支的中间Runtime并据此推断收益。独立native／composition入口、helper code／defaults／closure／wrapped漂移拒绝及每个I/O两侧的身份／权限／效果／真实停止检查必须保留；不是授权跨请求缓存、广义指纹pass、删除校验或放宽期限。

任何下一候选仍须先以完整已发布调用证明命中及收益，并用原负例证明拒绝／扩展等价，再进入产品、安装及原首项。不得将5928次相似工作全部视为可删，也不把一次Query的108ms等同整条Tool／CONTROL成本。没有新候选时不重跑同包原360或扩大矩阵。
