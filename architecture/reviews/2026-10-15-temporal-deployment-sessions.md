# 部署 Session 集成与收尾验证

日期：2026-10-15。按 [P3-2 固定计划](../../docs/superpowers/plans/2026-10-15-temporal-deployment-sessions.md)收尾，仅本地开发与提交，不推送。S1 普通 Session 功能子集已在 `4fdd5ae`、`8e33b9a` 记录；本批继续接通既定 Coding Session，不引入新编排、适配器或执行权威。

## 当前结论

S2 已实现并交叉审阅，既往 Agent／sequence 两 Turn 有通过证据；最新 v13 安装候选的 graph-sequential 首门槛仍失败，其余十二项未运行，故障门槛尚未执行，不能标为完成。两个原 Tool Activity 均完成，当前失败点仍为整图审批辅助等待超时；后续 Session 收尾出现已证实的2MiB消息硬拒绝，schema 按证据保留。当前仅为本地预览，Temporal＋PostgreSQL、P3-2、第三阶段整体验收继续开放。以下结果来自不同快照，不相加、不称为最终全量；跳过不构成服务或模型验收。

## 实现边界

- 显式 Session＋部署准入＋Coding 使用 publication4／Registry4，旧默认选择保持。同地址不兼容 Registry 拒绝，不换地址规避容量。
- native6／binding22、composition7／binding23 请求与库存形状保持。实际 SDK parent 是原 Session coordinator，业务 lineage 不把它计作业务父节点或根额度。
- 原 intent、首次信封、Scope、namespace、原始／首个／当前 epoch 关联真实 SDK 证据。Registry 管准入和退休，原 Run／Parent History 管业务、预算和效果，Session History 管串行 Turn 与发布。
- owned 关闭先完成 Coding 物理收尾、Session 排空、原调用及退休，再退出 Worker。未知效果、缺 ACK 或 CONTROL 进程死亡不因终态而清除。
- 测试资源清理只读原 SDK History，复用原 Session 状态规则验证调用结束、正退休及关闭证据；缺证据保留原资源。

## 分快照证据

| 检查 | 结果与限制 |
| --- | --- |
| 首轮受影响 Temporal 回归 | `s2-first`：3226 passed／584 skipped，138.59秒；232模块，冻结源文件前后不变，未启真实服务或模型 |
| 配置与 Registry | 170 passed；所选组合、原 Coding admission 索引及普通4隔离 |
| 生命周期与 bridge | 124 passed；原 stop、scoped close、真实配置版本及 owned 接收责任 |
| ancestry／compact | 220 passed；旁置 origin、真实 SDK parent、Registry 配置与业务 lineage |
| 第一轮安装 Agent | 1 failed，Session 激活延迟导入纯 Coding inventory，未进入业务执行；失败与原 History 保留 |
| 沙箱修复 | 初始加载预载纯 inventory；native6／22、composition7／23 激活 RED→GREEN，98项定向通过，未扩大 sandbox 权限 |
| 第二轮安装 Agent | `s2-sandbox`：1 failed／222.51秒；原工具进入 waiting_reconciliation，保留未知效果、占位和恢复数据；其余十二种组合未启动 |
| 计时复现 | 同一安装产品及现有脱敏计时夹具复现握手期限问题，部分 preflight 已回应、未提交业务 Turn；不作正常验收 |
| 原生相邻校验修复 | publication3 专用优化遗漏 Coding4，造成重复 fresh；RED→14项通过，相关本机进程回归217项通过，普通4仍隔离 |
| 只读集合校验修复 | 完整组件检查放在 SDK 读取集合入口／出口；逐 await 原 pins、全部7次事实读取保留；此快照读取顺序不变。43项通过，模拟组件漂移均阻止返回授权 |
| 离线 CPU 测量 | 完整 native factory、零延迟 SDK 形状读取：174.82→39.60毫秒，约4.42倍；不代表端到端延迟或线上吞吐 |
| 退休与发布补齐 | Coding4 的 release closure、Parent CONTROL 和 Session Advance 仍有普通／旧3分流遗漏，已分别补齐；定向153、51、94项分别通过。v3／v4实际失败均保留，v4已正退休但未发布，不能据此当作完整Turn通过 |
| v4 受影响回归 | 3272 passed／589 skipped，137.97秒；239模块。后续v5只改Session Advance，因此不冒称v5全量 |
| v5 安装相关回归 | 589 passed／241 skipped，37.35秒；63模块、340已加载模块来自独立安装路径，424产品文件前后一致 |
| v5 实际 Agent | 1 passed／215.995秒，零失败／错误／跳过；两Turn、两次业务写入、四次原生提交，审批／重复命令、原父身份、退休和会话发布通过。清理证据成立，测试schema已安全删除 |
| v5 默认兼容 | 完整默认Profile／identity／Manifest／orchestration与原快照相等；保存的原／continued History重放通过，Provider0／服务调用0，未重跑live continuation |
| v5 组合矩阵 | 两个隔离进程各首项失败：顺序工具80秒超时；Dynamic-flat 的完整 Session origin 被旧 metadata1 子调用校验拒绝。各自后五项未运行，不能称十二项已完成 |
| 子调用身份修复 | 完整 metadata2 复用原纯 Session origin 校验，业务 lineage、Scope、namespace、原父身份保持；RED→GREEN，117项定向通过，Parent sandbox 激活无延迟导入 |
| Coding4 只读并发 | 首批四项独立 SDK 读取并发，全部七项事实、Start／queue 校验、最终 CURRENT describe→namespace 与完整入口／出口保持。失败和取消等待读取全部结束；13项定向、120项相关回归分别通过，双人审阅无阻塞，不提高原期限或缓存权限 |
| v6 受影响回归 | 3313 passed／589 skipped，137.25秒；242个Temporal测试文件。全部1729个冻结文件前后哈希一致，未启外部服务或模型，skip不作服务验收 |
| v6 实际 Agent | 1 passed／184.12秒，零失败／错误／跳过；两Turn及原身份／效果／退休／发布断言通过。424个产品文件前后一致，340已加载模块来自独立安装；其余矩阵首两项失败，后续十项未运行 |
| v6 组合矩阵 | 两进程各首项失败：sequence-json 363.42秒、dynamic-flat-toml 510.42秒，后续十项未运行。原生业务提交分别4／2次，但后一个动作缺最终结果候选；原Activity完成返回tool_error，无ActivityTimedOut。关闭失败及原未知效果／schema保留，不计完整Turn通过 |
| v6 隔离计时复现 | 相同安装产品，sequence单项281.95秒失败。测试native响应毫秒级，重复SDK校验在请求之间占用较多时间。第二个native执行的首个SDK读取至取消相隔60.0069秒，吻合原Runner60秒期限，取消发生在原adopt的fresh校验内；此证据属于该计时复现，不反推其他运行的具体异常。诊断不作正常验收，未修改产品期限或放宽授权 |
| 同步 selector 复制定位 | 原真实167KB intent：selector重复6次完整复制，command／intent查询各8次；每同步方法复用一次隔离快照后分别1／2／2次，CPU中位约4.64→1.03、5.95→1.65、6.04→1.53毫秒。此为局部CPU测量，不等于服务延迟或完整链路通过；全部字段校验、隔离语义及SDK读取保持 |
| v7 安装验收 | 原失败sequence-json优先复验：1 passed／306.23秒，零失败／错误／跳过。两Turn、四次业务写、原结果采纳、退休／会话发布和安全清理通过；424产品文件前后一致、340已加载安装模块来源已核验；原80／60秒期限不变。其余矩阵Agent单项通过；graph-sequential失败、dynamic-flat失败，后续九项未运行 |
| v7 图失败定位 | first child原Tool在80.004秒发生真实SDK超时；thread／turn／terminal观察已记录，原final-read／candidate缺失、effect仍dispatched，后续approve180秒是下游等待失败。未知效果与schema保留 |
| v7 动态失败定位 | 两Turn的Tool均成功、两effect已adopted、两root已退休；第二次首次Session observer持久返回session_control_failed且ACK完整，未发布。原身份显式重试得到正Advance／发布并安全清理；不是native预算／2MiB拒绝。底层异常未保存，继续定向诊断 |
| v7 observer 诊断尝试 | 相同安装产品的单项脱敏PY_UNWIND探针505.07秒失败，停在approve，未取得目标observer底层异常；不作正常验收，不据此判新根因 |
| 原启动握手优化 | 仅selected Coding4在initialize／initialized后并发固定8项独立只读请求，每请求保留原fresh校验；全部成功后才校验完整profile／进入业务，失败／取消先排空。RED→265项相关检查通过，原3／普通4／Local仍串行；实际性能与组合待验 |
| observer可诊断性 | 原错误返回与ACK不变，增加有界脱敏异常类型／RPC状态／静态位置日志；不记录消息、参数、locals、payload。71项相关检查通过，日志handler失败不改变原业务／ACK，实际异常仍待捕获 |
| v8 安装首门槛 | `installed-s2-preflight-sdk`：graph-sequential 1 failed／369.12秒，零错误／跳过；其余十二项未运行。424产品文件前后一致、340已加载模块来自独立安装；失败与原恢复资料保留 |
| v8 图失败定位 | 原Tool发生80.002秒真实SDK Activity超时，turn receipt距执行开始77.20秒；无terminal observation／result candidate，effect仍dispatched、根额度保留。prepared→thread grant为21.686秒，未显示相较v7加速，不能据此宣称并发握手改善实际性能 |
| v8 安装定向与离线兼容 | 安装后两个新增测试模块14 passed／1.87秒，-Werror。默认发布canonical SHA256为`9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，与原快照相等；原／continued History离线重放通过，Provider0／服务0，不代表live continuation或组合验收 |
| v9 最小origin合并 | 仅删除`CodingValidation._fresh`首轮重复origin校验两行，保留bootstrap、集合末尾完整七项事实及实际Query／Update／SQL／native I/O双边验证，无缓存。RED为3 failed／5 passed；相关检查93 passed／4.24秒，另一次独立复核84 passed／5.04秒，不相加为全量或服务通过 |
| v9 安装首门槛 | graph-sequential 1 failed／365.94秒；其余十二项未运行，故障场景未执行。424产品文件前后无漂移、340已加载安装模块来源已核验；原Tool在80.002156秒真实SDK Activity超时，terminal observation为75.92秒，无result candidate，effect仍dispatched、额度及恢复资料保留。局部时间变化不代表完整链路通过 |
| v9 observer日志 | 脱敏日志捕获`RPCError／CANCELLED`，位置为`control.operation:113`：begin之后、body之前的第二次validate，经verification早期gather进入_namespace。此为独立observer读取失败证据，不是主Tool超时的已证根因，也不是成功Advance采用失败 |
| v9 安装定向与离线兼容 | 安装检查22 passed／2.57秒，-Werror；默认canonical等值，原／continued History离线重放通过，Provider0／服务0。各项与真实首门槛失败分别记录，不称v9已验收 |
| v9 受影响回归 | 245个Temporal模块：3355 passed／589 skipped／2 failed，143.94秒，冻结产品源码前后不变。两项失败为相邻native测试保留了旧的内部origin次数预期；测试修订为明确断言bootstrap加实际Query前后验证，并与新origin测试同次22 passed／3.33秒。产品未因此改动，不将两次运行拼为一次完整绿色回归；589跳过不作实际服务验收 |
| v7 安装相关回归与兼容 | 八模块155 passed／6.52秒，-Werror、零跳过；完整默认发布相等，原／continued History离线重放通过，Provider0／服务0 |
| v6 默认兼容 | 完整默认Profile／identity／Manifest／orchestration等值、原／continued保存History重放通过；Provider0／服务0，无live continuation |
| 测试清理与诊断 | retention32项、Worker异常保留32项分别通过，交叉审阅无阻塞；body与close原异常均保留 |

## 候选与剩余门槛

v14 `frozen-candidate121-s2-control-body-codec`冻结于本地`91a7837`：1740文件／424产品，inventory `583fdcbed44e21f1ed9e669189d4ab36099e1717da3be78c289e8de8cf5d5150`，wheel SHA256 `0b96f87e073fb400da065b5eedb38cee2d76e23b33b734d4be8f5953db03a316`。独立安装新增两模块37 passed／6.70秒（-Werror、零失败／错误／跳过）；source／wheel／site及841份测试副本前后字节一致，默认完整canonical仍为`9df90a99df2c298ab2b2bf8aad0b7d907d2670e2c5247055c81cfe1afa475fbd`，原／continued保存History离线Replayer通过，Provider0／服务0，不代表live continuation。

v14实际graph-sequential仍1 failed／308.83秒，零错误／跳过，424产品及测试前后无漂移、339已加载模块来自独立安装。主异常是approve辅助等待180秒超时，两个Tool分别53.223301秒／60.000258秒完成且`ok:true`，均有原result_candidate／stop收据。父release Activity约29.17秒后返回`deployment_release_failed`，原root退休未确认。owned关闭先CloseIncomplete，Worker退出后重试为RPCError／Timeout expired；最终cleanup为schema_retained、deletion_allowed:false，保留pending Registry Update、未确认退休／Session关闭及原证据，不能称清理完成。其余十二项正常组合与五项故障未运行。

v14保存的Session History只有5次call_start／5次call_end：两register原body分别212144／212496字节，其余三observe为160字节的pending结果；最后end在13:45:42.742924 UTC，之后为wake Signals，没有大结果observe完成。全部保存History编码标记为0，无PAYLOADS_TOO_LARGE；故本次没有命中编码正向路径，不能据错误未复现关闭2MiB实际服务门槛。源码及安装codec证据继续有效，服务证据仍待。

主流程结构定位来自独立的v13原History：首次批准13:14:58.178至父观察最终子成功13:18:00.169共181.991秒，两Tool合计127.831465秒，中间交接40.901435秒。父12次observe累计83.750秒，部分与Tool重叠，不与Tool耗时直接相加。源码下界为每observe三轮fresh至少39项事实、四轮完整root proof至少52项，合计至少91次SDK事实读取；12次至少1092项，不含其余bootstrap、physical及namespace读取。Query不入History，这不是实测RPC总数。下一项将固定child epoch的Coding4 observe中相邻的只读describe与完整校验归为一组；前置execute.validate_activity、bridge前完整bootstrap／fresh、末轮校验及其他模式保持。审阅未发现该重排跨过grant／Update，但仍须RED→GREEN和安装实际验证，不据此预判主超时已解决。

该有限重排已实现：仅exact整数版本4、observe及原SDK proof中的固定child epoch，将describe前的一次validator.validate移至其后的既有完整校验集合，三轮变两轮；constructor固定资源／源码／Activity／请求及完整Runtime检查保持。最前execute.validate_activity仍完整完成才发只读describe，DTO核对后必须完成bootstrap＋fresh才进入bridge，末轮不变；register／cancel／recover、epochNone及旧3路径保持。真实CodingValidation（非伪造validator返回）的主RED为3轮及旧顺序，修复后相关六模块同次115 passed／6.97秒，-Werror、零失败／错误／跳过；含during-describe Runtime／namespace／父子epoch及SDK端口漂移在bridge前拒绝和其他模式／旧3对照。独立源码审查、Ruff、格式与空白检查通过；该增量尚未冻结安装或运行实际门槛，不从读取预算减少推导真实延迟或关闭成功。下一批只复验原图首门槛，单次服务检查此前约5分钟；通过后才运行剩余十二项及五项故障，缺陷修复耗时不作确定承诺。

当前有界修复只针对v13取消后另行暴露的2MiB恢复传输限制：exact Coding4且原body大于512KiB时，将canonical JSON经zlib/base64编码到exact版本信封，整个信封至多1MiB，解压至多原8MiB加1字节探测；尺寸、摘要、canonical、EOF及尾随数据全部校验，禁止无界flush或截断。结束确认Update与Activity返回两处均使用该编码；State先解码再按原digest及完整语义校验记账，Workflow先解码再校验ACK并处理结果。原Update ID、semantic digest、冷恢复body和ACK保持；普通4及小结果保持raw，旧raw仍接收。新增四个codec源码绑定沿原factory／validation前后检查，await中替换会被拒绝。新wire需匹配不可变Worker，不能宣称旧Worker可直接热接续新编码。

这项修复的主RED分别为codec API缺失、合法大Advance的end_call／Workflow尚未解码，以及codec源码替换未被原pins拒绝。最终相关八模块同次191 passed／10.79秒，`-Werror`、零失败／错误／跳过；覆盖原合法2,097,693字节body（合法submission仍小于1MiB）、重复ACK、冷状态恢复、Scope／摘要篡改不改账本、两处wire输出及SDK sandbox runtime激活。代码审查与Ruff／格式／空白检查通过。本轮不启动新的服务矩阵，安装及真实服务payload复验仍待；该源码结果不证明解决180秒审批等待或owned关闭。P3-2／S2保持开放，原十三项正常矩阵及五项故障门槛不删减。

后续性能修复仅针对 P3-2 的原期限阻塞。v9 的计时诊断与正常验收分开：首次探针因 Python 的非局部 monitoring event 配置错误在业务前失败，未取得 CPU 证据；修正并完成离线探针检查后，固定图诊断仍失败（396.11秒），不能计为通过。有效的首 owner 至次 owner 前采样窗口为84.722秒，不冒称完整 Activity 边界：目标函数 exclusive CPU 合计28.291秒，其中 Manifest 重建15.893秒、Runner root检查6.158秒；原生九项回应合计0.092879秒。SDK交叠区间66.226秒与CPU重叠，不相加；原函数pins均未变，探针错误为0。

已完成两项最小修复并待冻结实际复验：plain Runner 连续调用同一 root 检查时合并一次，Connected 的不同 override 与 base 保持独立；Session 校验仅在两份 intent 的 canonical digest 相同时共享本次快照，每次仍重算完整 wire hash，不同 canonical 的数值键输入保留原双快照校验。原七项 SDK 事实、逐 await pins、独立 Runtime 检查和期限均保持。定向证据分别为 registration RED 4失败／2通过→6通过、相关218通过；snapshot RED 9失败／7通过→相关137通过、最终16通过；最终两项及相邻边界同次63通过／4.99秒。各次检查不拼为当前全量，不代表实际图场景已通过。

v10 `frozen-candidate121-s2-root-snapshot` 已完成冻结与安装：1735文件／424产品，inventory `6ad18433fd38dd6170f08fc11089a5e838eb35737e45f519aec015578b923451`。源码／wheel／site 字节一致，安装定向30通过／3.86秒，默认完整canonical及原／continued History离线重放通过，Provider0／服务0。实际 graph-sequential 仍为1失败／364.31秒，但失败阶段已改变：两个原Tool分别71.409541秒、76.865328秒正常完成，均返回`ok: true`并采纳原result candidate，没有原80秒Activity超时。首次Turn的approve辅助等待在180秒处超时并发出原取消，第二Tool随后完成；第二Turn未执行，不能算完整图或Session验收。后续关闭也未完成，缺少最终cleanup报告，不声明资源清理或恢复已通过。源码／wheel／site／测试前后无漂移，340个已加载模块来自安装。

v11 候选仅合并显式 Coding4 callback 内重复的完整发布校验：外层固定 Manifest 入口／出口独立检查、bootstrap、公开 validate／permission、SessionControlValidation 的全部七项 SDK 事实及完整检查保持，资源／源码／请求／Activity pins 仍逐边界核对。主回归使用真实 Session verifier，warm callback 重建次数 RED 为11次、修复后5次；不是缓存 SDK 事实或权限。相关五模块75通过／3.58秒；加入边界回归后的同次六模块91通过／4.89秒，Ruff／格式／空白检查通过。独立审查无阻塞。实际首门槛结果另列，未通过不进入其余组合与五项故障门槛，不以局部计数代替验收。

v11 `frozen-candidate121-s2-aggregate-readset`：1736文件／424产品，inventory `a285a49afd978230142244e4f949447b21e529b88d1d83c7ae1e37eecc281efb`。源码／wheel／site一致；安装后四模块46通过／3.54秒，零失败／错误／跳过；默认完整 canonical 与原值相等，原及 continued 保存 History 离线重放通过，Provider0／服务0，不代表 live continuation。产品与837份测试副本前后无漂移，导入均来自独立安装。

v11 实际 graph-sequential：1失败／333.35秒，零错误／跳过；其余十二项及五项故障未运行。424产品／原测试前后无漂移，340已加载模块来自安装。只读原 History 核对两个 Tool 分别56.530649秒、57.576230秒完成，均有`ok:true`与原result candidate；第一 Tool完成到第二 Tool开始间隔41.476033秒。第二 child 的实际结束证明完成后开始 plain join 注册，随后180秒审批辅助等待失败并触发清理取消；join 注册结果为definition_mismatch。Root最后seal为cancelled，Registry释放该完整cancelled证书，不能登记Turn成功。owned关闭仍为CloseIncomplete，清理报告因session_evidence_invalid保留schema，Worker已退出；不声称清理通过，也不删除恢复资料。

下一项已定位的结构性重复在 observer：`_CheckedClient` 每次读取后运行完整 Session 校验，而嵌套 `validate_session_origin` 又把同一带校验客户端作为其七项验证的传输层，每项读取再次触发原校验，额外放大约49次事实读取。优先审查仅固定原 SDK 传输、继续执行原七项验证的最小修复，不增加紧凑投影、缓存权限或调大期限；该源码发现不单独证明已解决实际失败。

v12 候选仅在相同 Runtime／完整 intent 的 exact `_CheckedClient` 和 exact `SessionControlValidation` 场景固定原 SDK transport，仍构造独立 verifier 读取七项事实，并携带原 Activity info。原 outer 完整检查及 wrapper／transport／info／Runtime／完整 intent 在 await 后复核，不信任 outer.validate 返回值；其他 wrapper 与不匹配调用保留原路径，不新增协议或投影。真实读取计数 RED 为1失败／1通过（56次／7次），修复后同次四模块65通过／2.98秒；另一次原六模块88通过／3.47秒，分别记录不相加。新增11项包含七类读取中漂移、伪造 outer 回执及外部 subclass 旧路径，独立审查与 Ruff／格式／空白检查通过。实际 observer 耗时和整图／收尾门槛仍待安装候选验证。

v12 `frozen-candidate121-s2-origin-transport`：1737文件／424产品，inventory `2509ad148a65efdf7fc9644f20a61c3e6a0989d07bed1258d6e6afd63c96b3c5`。源码／wheel／site一致，安装后四模块49通过／3.41秒，零失败／错误／跳过，424产品及838份测试副本前后无漂移；导入来自独立安装。默认完整canonical及原／continued保存History离线重放通过，Provider0／服务0，实际图门槛另行记录。

v12 实际 graph-sequential：1失败／268.17秒，零错误／跳过，原180秒审批辅助等待仍超时，其余十二项及五项故障未执行。两个原 Tool Activity 都完成，但不是完整 Turn／会话通过；424产品与测试前后无漂移，339已加载模块来自安装。owned Coding 关闭先返回CloseIncomplete，Worker退出后的清理重试出现RPCError（task queue近期无poller）；最终报告Worker已退出，但root退休、scoped Session关闭与Session证据均未确认，schema保留。不能用总耗时缩短证明observer性能或收尾改善；该候选的正常图与关闭仍未验收。后续先按原History定位两个Tool之间及汇合注册的实际关键路径，再做有依据的最小修复。

v13 收尾候选针对上述主路径共用的 `_public_start_binding`：仅 exact Coding4 将首轮重复 Session 读取改为 await 前 detached 的完整预期身份，保留原启动记录／namespace 只读查询与末轮完整七项事实及结果比对。中间不发送 grant／Update／业务写，也不返回正 proof；普通 Session4 保持原两轮，旧3与默认路径保持。不增加跨层上下文、事实缓存或新执行权威。真实主计数 RED 1失败（14项事实）→GREEN（7项）；同次四模块91通过／2.27秒，另一次六模块153通过／2.64秒，各次不相加；独立审查与 Ruff／格式／空白检查通过。安装兼容、实际整图与收尾仍待该冻结候选验证。

v13 `frozen-candidate121-s2-terminal-start-binding`：1738文件／424产品，inventory `0228db22aeefbea9d77e88626e4dd999e60312fb8956b73b67969b237b1f1e7a`。源码／wheel／site一致，安装后五模块57通过／3.78秒，零失败／错误／跳过；424产品与839份测试副本前后无漂移，导入均来自独立安装。默认完整canonical及原／continued保存History离线重放通过，Provider0／服务0，不代表live continuation或实际图通过。

v13 实际 graph-sequential：1失败／343.10秒，零错误／跳过；其余十二项及五项故障未运行。两个原Tool分别65.926138秒、61.905327秒完成，均`ok:true`且有原result candidate；不能由局部读取计数推导真实加速。180秒审批辅助等待在第二child收尾观察期间超时，尚未注册join。取消后约1.09秒才收到该child的succeeded／physical_stopped:true观察；整Turn未通过。424产品及测试前后无漂移，340已加载模块来自安装；owned关闭仍CloseIncomplete、Worker已退出、schema保留。

v13 收尾载荷另有独立证据：原Root取消于13:17:59.080015 UTC，Registry正退休于13:18:10.636168；随后Session的observe已记录call_start，但无call_end接受／Activity完成。原Session History事件188／191的WORKFLOW_TASK_FAILED原因为PAYLOADS_TOO_LARGE，SDK日志消息体2121093字节超过2097152上限23941字节。该错误晚于审批超时，不能用来解释主等待失败。源码关联到`session_deployment_call_end.body_result`中的完整Advance证据，失败入参未进入History，具体Update和大字段仍为关联推断，不能写成已捕获的完整失败载荷。后续优先修复该真实证据传输门槛，完整原生逐请求fresh契约保持；不实施跳过单帧动态事实的preflight批量例外。

v5 `s2-advance` 快照1727文件／424产品文件，inventory SHA256：`d530c203d8d4f7826cc915b2184c1be48937934966bafca380aa1bf17ce6ee53`。v6 `s2-origin-reads` 快照1729文件／424产品文件，inventory SHA256：`b935d23c2abae7a156662f0e5c447b2b8f9751a0bf65e02f37875e1e06eaea74`，首个安装 Agent 通过，矩阵首两项失败。v7 `s2-selector-snapshot` 快照1730文件／424产品文件，inventory SHA256：`ef3fc59506253032671f0660a6fbe761d3a4ad93cf40ca0448afa345e67d7826`；155项相关测试通过，安装后优先复验失败的sequence已通过，原十三项集合及原期限保持。源码、wheel、独立安装424产品文件一致；metadata 仍为未发布 `0.1.0.dev120`。

v8 `frozen-candidate121-s2-preflight-observer` 快照1732文件／424产品文件，inventory SHA256：`ee5f60a4930791029e44c84af770ad0effa87580ac930ec152052726025be093`。该快照的安装失败、定向测试及离线兼容分别记录如上，不与旧快照结果相加；其记录时最小origin合并尚未验证。

v9 `frozen-candidate121-s2-terminal-origin` 快照1733文件／424产品文件，inventory SHA256：`bf084f2053d67a26dafd82d1f4a0b8a8717f0ac099c4dd7755115c860c8ecda7`。最小origin合并的单测、安装兼容与真实Graph失败证据分别如上，不能拼接不同快照为通过。

- 最新v9 graph-sequential首门槛失败，其余十二项未运行；v5／v7已通过的独立Agent／sequence与各版失败记录均保留，不推导当前十三项集合已通过。下一步针对同步CPU与SDK排队测量定位，不增加协议或放宽原期限。
- 验证原审批冷交接、退休回复丢失、显式取消及 effect／native-stop／deployment-end 独立 ACK。
- CONTROL 真正进程死亡后保留原 Turn busy、占位及恢复数据，不制造通用 fence。
- 完成最终安装、约定默认／History 兼容和受影响复验，才判断 S2／P3-2 能否关闭。

结构 native peer 证明 Temporal、PostgreSQL、原生子进程及文件效果协议，不新增真实模型质量或真实 Docker daemon 故障结论。历史真实模型及 Docker 证据按原范围引用；未知义务所需服务与数据继续由原所有者保留。
