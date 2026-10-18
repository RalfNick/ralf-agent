# S2：指纹缓存键回调缺口与正确性修复

接续[受限批处理提案](2026-10-18-s2-scoped-validation-and-batch-proposal.md)。预检先发现既有指纹缓存的真实缺口，因此本批暂停分段批处理，只修复缓存输入与原算法拒绝语义。原S2首项360秒、其余十二正常／五故障、效果／预算／停止／关闭及资源保留门槛均不变；没有新增业务能力、权限缓存或观察缓存。

## 复现与边界

`executable_digest`先检查helper，再用CodeType作为LRU键。CodeType可以包含opaque常量；其哈希会执行该常量的`__hash__`。回调在cache miss调用实际digest前暂时替换digest helper的`__code__`，伪helper恢复自身并返回旧摘要。已改变函数因此得到旧指纹，而同一对象的原未缓存算法会拒绝。问题同时存在于plain和primitive-default两条缓存入口；tuple、frozenset和nested CodeType不能只检查顶层。

另一个同根复现：自定义str默认值的元类`__eq__`可欺骗旧`type(value) in primitives`检查；实际默认值哈希再自恢复digest helper，返回已改变函数的旧摘要。这次原算法可以合法编码默认值，正确行为是回退并返回新的原算法摘要。

`isinstance(value, CodeType)`也会读取opaque对象自定义`__class__`；改为exact type identity后拒绝对象，不执行该hook。复现仅证明指纹缓存身份错误，**没有证据证明能绕过Engine全部绑定或授权检查**。

## 最小实现

- 两个LRU入口之前共用有界exact-type树检查，涵盖CodeType的常量、嵌套容器／CodeType、名称与文件元数据、名字元组、整数和bytes字段。检查不hash或比较opaque对象，不调用其`__class__`。
- 不适合缓存的对象和超过检查深度的合法结构走原未缓存算法；不改变python-code-v1摘要内容，不增加组件“已校验”状态。
- 默认参数资格使用type identity，阻止元类相等比较和后续键哈希回调；正常primitive、闭包、wrapper及复杂JSON保留既有行为。
- 新helper按现有机制固定身份、code、defaults、kwdefaults、closure和wrapped，并加入CREATE live inventory。没有重写Engine或新增自证体系。

第一轮15个回归在原实现全部RED；默认值复现另有独立1 RED。随后隔离原c58安装包重现17 failed／零错误／零跳过（含关键词默认值），原失败日志与JUnit归档，避免仅依赖对修改后实现的断言。修复后核心四模块129 passed。第一轮GREEN前8项仅因公共入口原有ValueError归一化改变异常消息而不匹配，修正测试为断言ValidationError类别，不改变产品异常处理。一次独立只读集成审查无阻断发现，独立重跑的三份缓存测试72 passed；后补关键词默认值和live inventory测试由主回归覆盖。

## 完整调用成本：记录代价，不认定提速

复用真实双Runner工厂、BindingCatalog、TemporalRuntime及三个明确绑定的预闭合图节点，保留原SDK形状事实／Query计数／namespace25。四冷进程A/B/B/A、各四次完整CONTROL主体，无profile；A为原c58安装包，B为本次修复源码，各自构建匹配source pin的新发布。

| 块 | 每次完整CONTROL CPU秒 |
| --- | --- |
| A0 | 1.158913 / 1.153069 / 1.150293 / 1.147618 |
| B1 | 1.401993 / 1.377872 / 1.420564 / 1.430065 |
| B2 | 1.405860 / 1.412012 / 1.401890 / 1.387108 |
| A3 | 1.143189 / 1.152488 / 1.149669 / 1.135129 |

合并A中位1.149981秒，B中位1.403927秒，**成本增加22.083%**。正确性检查有实际代价，本批没有提速收益，不通过任何性能门槛。两版本各自完整输出／proof、SDK计数、源与测试及物理夹具不变；source pin不同，不声称跨版本输出字节相同。此夹具不含真实RPC／Runner、外层owned start/end ACK或原顺序业务拓扑，不能外推360秒结果。

工件`/private/tmp/ralf-s2-cache-purity-20261019`；cost summary SHA256 `a1f38aaa1ef5c36d73f85a7bf4d35c5d6f3ed127af028162f364b07097506df0`。所有四进程正常结束，无模型或真实数据服务调用，旧失败服务和资源未动。

## 制品、兼容与验收状态

442产品／931测试文件固定；wheel SHA256 `9d01d2155bbe7b741904f5881cdd29f7383a4980b5b0b904aaff5125c74f29d4`，source与wheel产品字节一致。438模块受影响源码回归 **6469 passed／694配置skipped，零失败／错误，JUnit569.757秒**。独立安装 **517 passed／17配置skipped，零失败／错误，JUnit65.702秒**；source／wheel／site产品字节一致。默认完整材料SHA256 `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`保持，两份原默认History重放、starter审批／重复回执／跨进程恢复及业务写入一次通过。全部442产品／931测试输入前后不变；Ruff、格式和Git空白检查通过。不把旧全量证据算作新候选全量通过。

CREATE实验协议新增helper库存项，不能把新source pin塞进旧Coding History或改写旧证明。旧Coding发布仍需匹配旧不可变Worker；默认非Coding发布／History兼容另行核对。原c58实际360失败和各诊断全部保留，不算新候选成绩。

本批关闭阶段门槛0。S2、P3-2、P3-A整体和剩余17项继续开放；当前不以正确性修复触发无依据360复跑。下一批只在此正确边界上有界验证原固定库存成本，必须先保留拒绝／扩展／恢复契约并证明完整调用收益，再复验原首项。仅本地提交，不推送；完整S2时间仍无可靠估计。
