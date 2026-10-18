# S2：原Runner绑定复核与实测成本

从`004f5d6`继续原S2恢复计划，不扩大能力或组合。原Tool80／Runner60／approve180／scenario360／first-close60／cleanup40及13正常／5故障门槛保持；前批失败和数据保留。原360首项通过前不执行剩余17项，本批只本地提交、不推送。

## 具体问题与最小修改

真实版本的完整CONTROL transport主体剖析显示，BindingCatalog解析Runner时先检查原pin、丢弃返回注册，再构造临时CodingToolHandler及重复检查。这既有成本，也可在额外identity getter中换成另一个同类实例的方法，并由临时pin采纳。另一个复现是第二次所有权getter在方法检查后替换receiver。原12例中8失败／4既有通过；复用原pin的当次完整注册，保留原身份摘要比较、Scope及selector限制、返回记录深拷贝。

复核中发现仅移动getter顺序会允许“先替换、由getter恢复”隐藏漂移，四个负例RED。因此保留getter前方法检查，并补getter后复核。一次独立审查另发现getter能改变identity，简单复用会丢失旧临时注册发现该变化的机会；三字段／两时机回归3RED／3既有通过。最终check保留入口identity及方法检查，读取所有权后再查原identity与方法绑定。没有缓存执行权、放宽资源身份、少读SDK或修改效果／停止采纳。

另一处只将runner_journal_state两个逐字符禁用字符扫描替换为同范围的stdlib正则搜索：handle仍拒绝控制字符与surrogate；JSON值仍允许转义控制字符并拒绝surrogate。exact类型、结构／节点／深度、有限数值及UTF-8字节界限、canonical序列化和复制保持。新增字符边界用例在修改前56通过；遍历1112064个有效Unicode码点及4128个拒绝输入，对旧隔离安装与新实现得到同一序列化SHA256：`8829b2532d5aadc714254209080d2421fe0203988ca692a8cae7f2e8fd75dac0`。这不是此前已否决的JSON快速复制。

## 成对完整主体测量

使用真实TemporalRuntime、两Runner工厂／BindingCatalog和当前原State构造；相同物理配置、测试构造输入，SDK仍为明确的进程内形状端口。没有替换Runtime或验证方法，无原生、SQL、真实服务或模型写入。每次完整验证expected proof、canonical输出、Query／Describe／namespace／History次数；结果摘要均为`8a3c72d0971261e5a3e34534787d89c7da1362c9354f5db938d313b16ede81f4`。

| 测量 | 旧73435cc…安装 | 最终审查修复后 |
| --- | --- | --- |
| profile两次CPU（秒） | 2.362／2.335 | 2.173／2.202 |
| 四次无profile CPU（秒） | 1.081347／1.066303／1.075801／1.095166 | 1.042439／1.014102／1.030326／1.067335 |
| 无profile中位数（秒） | 1.078574 | 1.036383 |

这一轮完整主体中位CPU约少3.9%，收益有限，不能外推原360通过。外层owned start／end ACK、真实RPC等待及完整Tool／Session整链不由这组主体测量覆盖；profile本身会放大Python字符循环成本，不能用较大的profile差异代替无profile结果。两版manifest均106744字节；Scope、bootstrap／fresh读取和全部原proof要求保持。基线及审查后工件分别为`/private/tmp/ralf-s2-control-pair-baseline-20261018`、`/private/tmp/ralf-s2-control-pair-reviewed-20261018`，summary SHA256为`3b71b2770e275b922e5bb229d1ad030bd3ba2fd72a64fa170efaf620d5a20635`及`c6bb6e7a833b8c5759898badec138646eea24764a24349aa983a585bcbe112ad`。

## 候选与验收状态

最终候选wheel SHA256 `c58a3b00000893cba6d79d447699e786d9b22633a95256207f69ae5eeb40a982`，442产品／930测试文件。受影响三个模块126 passed／17远程服务配置skipped。最终372模块扩大回归5607 passed／638配置skipped（432.17秒），源码与测试哈希未变。最终隔离安装379 passed／17配置skipped；source／wheel／site逐文件一致，默认材料摘要`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`不变，原History及continued History replay通过，starter审批／重复审批／新进程恢复仅一次业务写入。工件分别为`/private/tmp/ralf-s2-runner-ready-regression-20261018`及`/private/tmp/ralf-s2-runner-ready-install-20261018`；这不是旧候选的全项目回归。

此前同一产品的两次372模块回归分别5603 passed／638配置skipped／1 failed（436.60及474.190秒），不能合并为一次全绿。失败分别是原生取消测试在peer未开始Thread时耗尽观察轮询，以及认证故障测试在peer尚未进入预期故障阶段前被120毫秒请求期限终止。隔离注入200毫秒认证启动延迟、1.6秒原生启动延迟分别稳定复现，两者均在原请求配置内；最初非授权环境的Unix broker拒绝属于无效环境对照，保留日志，不归因于产品回归。

只为测试补开始观察前的就绪条件：认证peer握手发生在原120毫秒认证请求计时前；取消测试先在既有3秒fixture界限内观察首次Thread，再启动原300×5毫秒第二帧轮询。增加三个慢启动用例，15项相关检查通过。Runner原3秒请求、取消／退休断言和S2全部门槛不变；默认原生fixture生成内容与旧版逐字节一致，SHA256 `61e733ffa2339d2807239da53908214f8fcfeda61bb1d6a9d815ef41a9ff86ef`。最终完整回归使用固定后的测试输入，实际S2服务测试未改；产品包仍为上述c58a3b…。

审查前两个候选分别因读取前检查、读取后identity检查不足而废弃，未进入实际S2验收；其回归主动中断、日志和制品保留，不算最终候选通过。第一次中断还触发pytest tmp_path teardown的StashKey KeyError，明确属于主动中断结果，不当作产品缺陷或全绿。单次独立审查P2的修复按RED→GREEN验证，不另起多轮功能开发。

## 原360秒实测与剩余缺口

上述最终包在普通持久Temporal／PG16上独立执行原`graph-sequential-sdk`，没有CPU监控、并行回归或期限调整。结果 **1 failed／零跳过，JUnit 396.272秒（含收尾）**；360秒看门狗在第二Turn的`system.approve(..., all_steps=True)`轮询中取消。四个Tool Activity均`ok=true`，wall依次39.659／37.730／37.979／40.081秒；原生提交8次、业务写入4次。第四Tool完成后仍有必要的效果采纳、上下文／模型和父级收尾，不能把业务写入完成当作Turn成功。

保存History显示第四Tool结束于`13:26:06.034421Z`，随后效果证据Activity通过；第二Turn最终模型Activity返回`validation_error`，取消时栈同时显示原Session祖先查询仍在执行。第一Turn父级History从`13:20:24.862166Z`到`13:23:16.380621Z`，第二Turn从`13:23:41.874569Z`到`13:26:33.060994Z`；这不是CPU剖析，不能从这些wall数值判定某个校验是唯一瓶颈，也不能拿跨运行的总时差宣称性能提升。

本次原清理证明完整：2个accepted roots均retired、零retained roots，Session／Assembly关闭及Worker退出通过；原fixture在正删除证明下删除本批schema，效果／Runner／History导出保留。本批失败容器已停止并保留，Temporal持久文件保留，旧失败资源未动。工件`/private/tmp/ralf-s2-runner-ready-live-20261018`，原JUnit／result／shutdown／cleanup及History保留；只读`terminal-audit.json` SHA256为`9cfcf6af33da253a269dc40a802e012679678c4321500d87a38629be4f533bfd`。354个已加载RALF模块均核对来自该安装包。

**S2仍开放，原其余十二正常／五故障未启动。** 已完成的是绑定正确性修复、有限成本改善和同包回归／安装，未关闭360秒性能门槛。下一批先补完整Tool与外层owned CONTROL start／end的累计成本归因，再选择有整链收益证据的最小修复；停止仅凭局部热点继续微调或盲目重跑。不引入通用缓存、快速复制、弱化身份验证或新能力，不把本轮当成第三阶段完成。
