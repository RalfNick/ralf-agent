# S2：Scope 校验合并原型及下一步受限批处理

接续[实际查询与已发布校验证据](2026-10-18-s2-query-mix-and-published-validation.md)。当前产品仍为442文件的c58a3b…，930测试未修改。本批未构建新包、未重复服务验收，也未运行其余十二正常／五故障。所有原期限与已失败记录保持；S2／P3-2及阶段整体验收仍开放，仅本地提交、不推送。

## Scope 合并实验：不进入产品

本批仅在隔离源码副本修改两文件：`validate_request`试验可选Scope，在plain Coding4绑定请求中以最终完整Scope验证替代末端重复的无Scope验证；Registry提交仍以固定Scope检查结束，custom／alias等Python输入保留原路径。未缓存授权、效果或SDK观察结果，也没有删除独立`validate_bindings`入口。普通无Scope调用保持原行为。

先写私有测试，正确wire输入上的原实现为**2个预期RED／2个既有拒绝与回退GREEN**；原型四项通过，验证结果及输入不变、输出隔离、foreign context Scope拒绝、自定义dict维持原三次路径。首轮测试夹具缺command_id导致4项KeyError，另一次request仍含Python tuple而误作wire输入导致未命中；两者均不是产品缺陷，修正夹具后才确认RED。这四项不能证明全部helper漂移、恢复或兼容契约。

完整CONTROL成本夹具从现有真实双Runner工厂、BindingCatalog及TemporalRuntime构建同源发布；三个预闭合图节点使用两个明确Runner绑定和一个disabled绑定。保留原全部SDK形状事实、namespace25、原Query计数和完整结果／proof检查，写入0；没有替换产品方法或后补允许标记。它仍是并行预闭合图及SDK形状端口，**不是原顺序实际场景、外层owned start/end ACK或真实RPC／Runner成绩**。源输入、测试及物理夹具前后不变，每个版本用自身新发布生成完整证明，不把不同source pin装进旧History。

预先固定四冷进程A/B/B/A、各四个完整调用、无cProfile，并要求完整调用CPU中位至少减少10%。各块保留全部样本：

| 块 | 每次完整CONTROL CPU秒 | 块中位秒 |
| --- | --- | ---: |
| A0 | 1.380055 / 1.399401 / 1.370150 / 1.215954 | 1.375103 |
| B1 | 1.397816 / 1.326613 / 1.323144 / 1.252377 | 1.324879 |
| B2 | 1.317512 / 1.333709 / 1.311180 / 1.311148 | 1.314346 |
| A3 | 1.362348 / 1.338942 / 1.354252 / 1.371852 | 1.358300 |

合并A中位1.366249秒、B中位1.320328秒，约减少**3.361%**，未达到10%。另一次完整调用仅计数确认Scope参数／合并分支各命中2次，所有相关plain guard均返回True，避免把未命中当作优化成绩。计数运行不作时间依据。SDK读取计数跨A/B一致，各自完整结果与当前发布证明一致；未声称不同source pin的输出字节相同。

因此**否决当前原型，不增加Scope API、不迁移测试至产品、不构建包或复跑原360**。工件`/private/tmp/ralf-s2-scoped-submission-prototype-20261018`及`/private/tmp/ralf-s2-scoped-control-{A0,B1,B2,A3,B-count}-20261018`；summary SHA256 `bd540c17e3de9c9561d785e0d9a55e84b9a409bc380d419ce0460c81ddccc291`。原型两文件与测试仅保留为私有失败证据，仓库产品不采用。

## 架构判断与有界下一步

已有三个局部方向未同时满足成本与契约：完整proof传输去重增加完整CPU、RawValue破坏合法Query拦截器、此次Scope合并不足完整调用门槛。依据实际held Registry的5928次函数指纹检查，下一步先验证**固定代码库存内的纯对象分段批处理**，不继续堆叠角色、复制或传输微调。

这个方向尚未实现或证明可行，不引入新执行权威、业务能力或平台。拟仅在现有`_fingerprints`遍历中，严格证明没有Python用户回调的连续片段内复用helper完整性复核；独立`executable_digest`、原python-code-v1输出与既有有界纯代码LRU保持。**不新增Manifest、权限或SDK观察缓存，不跨请求复用组件／校验器已通过的标记；静态代码结果复用仍需逐次拒绝代码与helper漂移。不使用ContextVar通用pass，不允许调用方传入跳过标志。**

进入任何产品候选前必须关闭下列问题：

1. **源解析与别名。** 实际SDK Sandbox与host均核对；只允许可证明无回调的普通模块、类descriptor和原Python函数。不能提前解析所有目标后无条件复用；遇到import／getter／复杂项／fallback后，丢弃本段并从当前别名重新解析，保留中途alias替换拒绝。
2. **完整纯度。** 在LRU key计算或`isinstance`可能触发自定义`__class__`之前，验证完整code常量树及defaults／kwdefaults／closure／wrapped；不以最终unknown拒绝代替此前无回调证明。初期可明确拒绝快路资格并走原完整入口，不扩大支持范围。
3. **miss与污染。** 不把cache miss当作无回调。miss必须结束guard复用区间并重新检查helpers与后续源别名；helper临时替换、code／defaults／closure／wrapped漂移及可能LRU污染须由具体RED证明拒绝，不能只在最终出口检查。
4. **独立入口与所有权。** 新helper及其调用方独立pin自身依赖，拒绝helper整体替换或no-op；缓存只能产生原不可变指纹，输出dict依然新建。默认非Coding、自定义对象、旧匹配Worker恢复与I/O两侧权限／Scope／namespace／epoch／效果／预算／真实停止检查保持原契约。
5. **完整收益与恢复。** 先在真实已发布、明确绑定的完整CONTROL或Tool调用证明命中、拒绝等价及至少10%该调用CPU收益；再做受影响回归、独立安装、默认及约定History兼容、原360首项。首项通过前不解锁原17项；局部收益、样本变更或跳过都不关闭S2。

预计先用一个有界验证批次决定这条路径能否成立；证明失败即不实现，不以新名称复活旧广义pass。原360与后续故障矩阵完成时间目前仍不能可靠估计。本批关闭阶段门槛0，现有可交付基础SDK继续保持冻结。
