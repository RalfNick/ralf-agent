# 函数指纹与 S2 恢复验证

日期：2026-10-20。用户明确选择“现在恢复两项验证”，撤销此前两项专项的后置安排。保留全部原失败、原360秒首项及十三种正常／五项故障矩阵；不推送、不公开发布。原a1制品及原生AMD64基础SDK验收保持独立，不因专项恢复而重建或替换。

## 当前结论与制品边界

基线`e5ea4cf`，指纹实现与此前正确性修复`af9a32c`相同。本轮发现并修复已有helper元数据结构相等回调P2；身份键优化被否决，最终候选保留原两个CodeType LRU、摘要算法和未缓存回退，仅对精确不可变CodeType的完整纯度判定作有界复用。没有缓存权限、Scope、组件解析、发布验证通过或执行状态；Harness／Local／Temporal执行权威不变。

正确性候选`0.1.0a2.dev1`完成所选安装回归与兼容，但真实S2原360秒首项失败。最终有界候选`0.1.0a2.dev2`完成所选指纹资格／安装／兼容，但S2首项仍失败；两者均为本机私有候选，不能套用原a1的Linux／AMD64门禁，也不替换原a1包。不新增模型、存储、编排或平台能力。

## 被否决的私有身份键优化

隔离目录`/private/tmp/ralf-s2-identity-code-key-resume-20261020`，旧目录和失败均保留。

- wrapped相等回调／bases元组地址复用共4项有效RED，身份前缀和强引用修正后155 passed。首次完整ABBA下降11.742%，但输入被随后独立审查拒绝，不能作为最终收益。
- 审查发现helper CodeType比较可运行元数据相等回调；主执行者在原基线和候选均复现`_cacheable_constant`改码后返回并缓存`foreign`。补guard自身、helper代码和默认值4项RED，修正后159 passed。此为指纹缓存边界P2，不是Engine全部授权绕过证明。
- 安全修正后的完整ABBA仅下降3.410%；分离强引用与整数签名后仅8.168%，均未达原10%门槛。拒绝身份键类、新LRU键和miss内纯度检查方案，未进入产品；其负例“额外一次miss”允许也没有进入产品测试。
- 私有源回归曾以PYTHONPATH运行；两个`-I`冷Worker加载原editable安装造成源声明不匹配。该输入同时被审查否决，核对精确PID后SIGINT退出：884 passed／31配置skipped／2 failed。原失败保留，不修改期望摘要；后续改用匹配wheel隔离安装。最初测试缺少子进程参数的无效RED也保留，与有效RED分开。

## 已有P2修复与 a2.dev1

helper签名仅比较整数身份，另持有原对象强引用；guard函数／代码直接`is`，不让CodeType、默认值或wrapped的结构相等回调参与guard判断。新增14项负例先14项有效RED，再与原129项合计143 passed。保留原纯度扫描位置、两缓存计数和回退语义。

独立wheel SHA256 `b26b65170c0cf39a47f68fcb372b19ad7855647938c4eb2062b6d520132f3074`；442产品／943测试与示例输入固定，源码／wheel／安装字节相同。CPython3.12.7／Mac ARM64，独立venv共享已安装第三方依赖路径但不执行父site的editable .pth：439受影响模块 **6486 passed／694配置skipped／0失败错误**，632.82秒；417个已加载SDK模块确认来自安装目录。不是全项目／跨平台／真实模型验收。

默认发布材料SHA仍为`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`，原／continued两份默认History离线重放通过，两条原starter分别一次业务写入。默认材料不变不意味着所选Coding发布源身份相同；旧selected任务须保留匹配组件和Worker，不能静默改绑。

原`graph-sequential-sdk`真实Temporal／PostgreSQL首项 **1 failed**，JUnit390.564秒（pytest391.43秒含收尾）。原360秒取消发生在第二Turn审批等待；6次native提交、3次业务提交。两root均退休、Session／Assembly关闭、Worker退出和正证明schema清理完成。自有Temporal关闭、PG停止并保留失败容器；旧资源未动。外层600秒维护看门狗未触发，Tool80／Runner60／approve180／scenario360／first-close60／cleanup40均未修改。其余十二正常／五故障 **未启动**。结构peer及实际子进程不等于真实模型或Docker执行质量。

原始证据位于`/private/tmp/ralf-s2-helper-metadata-fix-20261020`，服务连接私密文件不进入交付或Git。

## 最后一次有界纯代码试验

`/private/tmp/ralf-s2-pure-code-proof-20261020`仅复用exact不可变代码树已通过的纯度判定。稳定单元素list发布copy-on-write精确dict；整数地址键必须同时满足代码对象`is`一致，强引用防地址复用，每个快照最多1024项，满时重新建立快照。并发覆盖只丢缓存项；不引入锁、threading运行时访问或I/O。新helper及cache cell身份进入guard，helper进入live CREATE inventory，源文件仍受source inventory覆盖。

7项有效RED／1项原有行为通过后，8项新增边界加143项原检查共151 passed。纳入产品后增加新helper库存漂移用例，所选核心 **152 passed／18.46秒**；最初误写测试文件名的无测试运行保留为命令错误，不算产品失败或通过。

以已修复P2的a2.dev1为基线，完整冷进程A/B/B/A各4次CONTROL，中位CPU **1.5538645→1.303055秒，下降16.141%**，达到原10%门槛。各版本SDK计数、完整输出与各自proof一致，输入前后未变，无SQL／native／服务／模型调用。只证明该CONTROL主体成本，不外推Tool、outer owned ACK或整链性能。

一次最终聚焦只读审查未发现P1／P2或小问题，独立10项边界／inventory检查通过。覆盖身份、强引用、并发有界、opaque拒绝、helper漂移与source pin；静态未见Temporal sandbox／确定性新增问题。未以审查替代安装、History replay、实际sandbox、其他Python或真实S2验证；并发测试不穷举调度，同调用跨线程改码、主动篡改私有缓存和任意host破坏不在本轮隔离承诺内。

## a2.dev2 验收（所选指纹通过，S2未通过）

独立wheel SHA256 `20f0f7b35cfbe1b974ef35bce221c494bd5e5cbc7b3b7bf92061534d9ad8653e`；442产品／944测试与示例输入固定，源码／wheel／安装字节相同。隔离安装440受影响模块 **6495 passed／694配置skipped／零失败错误**，606.15秒；417个已加载SDK模块全部来自安装目录，产品与测试输入未变。默认输出与a2.dev1逐字节相同、排除末尾LF后的原摘要8b369d…保持，两份默认History离线重放和两条原starter各一次写入通过。最初维护脚本误按含LF文件摘要比较，断言失败已保留；仅修正工具口径，未改产品或基线。同一候选独立运行原360秒首项，结果如下。

S2／P3-2和第三阶段整体仍未关闭。原本机网络安全请求的来源仍未核实，本次恢复授权不构成对其来源的判断。未运行Git钩子、推送或公开发布。

原`graph-sequential-sdk` **1 failed／0跳过，JUnit432.140秒、pytest432.88秒（含收尾）**。原360秒取消发生于第二Turn审批Update，初始错误为`WorkflowUpdateRPCTimeoutOrCancelledError`；随关闭产生`ExceptionGroup`，不能丢失初始失败。最终6次native提交、3次业务提交；两root均退休、Worker退出，但Session关闭未确认、证据核对为`EvidenceMismatch`，Assembly关闭报`RPCError`。清理规则正确拒绝删除，原schema、Temporal数据库、导出及已停止失败PG容器全部保留。两个root退休不等于Session／Assembly已安全关闭。

自有服务的最终只读核验确认标签匹配、PG停止及Temporal shutdown完成；旧资源不动。外层维护看门狗未触发。产品／测试输入及所有原期限未变；其余十二正常／五故障 **未启动**。本轮没有证据将关闭失败归因于新的纯度缓存，也没有证据将它视为独立已修复问题；不从单次结果推导性能回退或提速。

## 交付与剩余门槛

本批仅修复已有P2并复用不可变纯度判定，未扩功能。本轮所选函数指纹资格（Mac ARM64／CPython3.12.7、原摘要语义、负例／缓存有界、安装回归及约定兼容）通过；其他Python／平台不套用原a1结果。最终候选不作为S2已支持组合公开推荐。

安全证据副本见仓库内`dist/s2-fingerprint-resume-20261020/README.md`及`SHA256SUMS`；包含两份独立wheel、各自回归／兼容／S2回执、失败和试验记录。完整live导出及数据库留在上述受保护原目录，交付副本排除连接私密文件；若日志需脱敏，原／副本哈希分别记录，不覆盖原文件。该目录不加入Git或上传。

S2／P3-2／P3-A整体继续开放，并未重新后置。剩余为原首项整链耗时和取消后的Session关闭证据，然后才能进入其余17项。按原有界试验约束，本轮不再做下一轮局部缓存微调或无变化重试；下一次产品改动须先定位完整调用成本／关闭失败，并保持原Scope、fresh校验、效果和停止义务。默认a1范围、长期R01–R26和真实模型质量各自独立；未推送或公开发布。
