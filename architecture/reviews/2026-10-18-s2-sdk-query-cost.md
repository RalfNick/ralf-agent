# S2：SDK 边界与只读响应原型

沿[恢复计划](../../docs/superpowers/plans/2026-10-18-s2-resume.md)和[前批成本缺口](2026-10-18-s2-owned-activity-cost.md)继续。当前产品仍为442文件的c58a3b…安装包，930测试未改；本批无产品候选或能力扩展。原Tool80／Runner60／审批180／scenario360／first-close60／cleanup40及首项→其余十二正常／五故障的顺序不变。仅本地提交，不推送。

## 测量质量与原服务结果

增加SDK Workflow activation、DataConverter／PayloadConverter，以及事件循环Handle和线程池入口边界。同步SDK activation运行嵌套Workflow事件循环时，按Task分组会重复计算CPU；独立同步外层／五次内部事件循环自检稳定RED。改为真实frame／物理线程栈，保留异步暂停恢复、递归、异常、取消、跨Task及线程自检：146事件，exclusive308.529毫秒／进程309.582毫秒，零异常／残留。

同一原History（SHA256 `056f315873933b9bbc1645e7d3295801fd6b381cb26e9a8b2f6ae0d0fddfe83b`）重放及十个只读Query通过，4780监控事件零异常／残留，SDK activation确实命中，捕获约96%该离线样本进程CPU。各响应摘要与原记录一致，观察缓存数量与History不变；工件`/private/tmp/ralf-s2-sdk-offline-query-20261018`，summary SHA256 `721149073b6641c3641ee6db082476a1c2075c9d3f0dcfaea8434e27228db6c0`。

随后只在本批新普通持久Temporal／PG16上执行原360秒诊断，无其他CPU测试并行。**1 failed／零错误／零跳过，JUnit432.636秒含收尾**，业务原360仍超时，关闭另报RPCError。四Tool均ok、业务写入4次；2 roots均退休，但Session关闭与Session证据未确认，Assembly关闭不成功，原fixture保留schema。原History／业务／效果导出、Temporal持久文件及已停止的失败容器保留，旧资源未动。未监控c58原首项的关闭曾通过，不把本次监控下关闭失败直接当作新产品回归，也不隐去本次失败。

工件`/private/tmp/ralf-s2-sdk-monitor-live-20261018`。监控1016564事件，所有开始／结束配平、exclusive非负且不大于inclusive、零异常／残留；源文件哈希启动前固定，产品／安装／测试前后核对不变。raw monitor SHA256 `4e41924754dd1a327c31c422fcbef0fb7d8d4b9d740e5ef8d93bcc4a3721c64e`；cost-summary SHA256 `3038258423d9e7cf9e01aa708c17d55c742be47077c8bd7ddc0b5e2628cbafa2`；只读终态审计SHA256 `29ecf72c0e465fe18055f84ff8b63bca554341feb59ea683b45c7b6ccae979d4`。

## 未归因部分已收窄

本次进程CPU351.789秒，选定边界exclusive捕获323.983秒，约92.1%。以下各行互不重叠，不相加inclusive；它们含监控开销，不是无监控吞吐或验收成绩：

| CPU归属 | 秒 |
| --- | ---: |
| 已选RALF Activity边界 | 164.432 |
| Workflow activation内事件循环回调 | 101.771 |
| 主事件循环其余回调 | 45.612 |
| 其余Workflow activation边界 | 5.678 |
| DataConverter／PayloadConverter | 5.611 |
| 线程池其余部分 | 0.879 |
| 未捕获 | 27.806 |

18929次Workflow内部Handle回调与268265次主事件循环Handle回调分别按其实际父边界区分；9094次SDK activation也包含查询处理。**Workflow内部回调包含RALF状态／查询逻辑，不代表101.771秒都是SDK自身开销。** 转换栈5.611秒不能解释原约180秒全部缺口；下一步应定位具体查询／状态逻辑及完整调用收益，不能直接修改SDK或继续仅优化Runtime指纹。

## 隔离只读编码原型

根据前批实际大Query样本，仅在`/private/tmp/ralf-s2-query-wire-prototype-20261018/source/ralf_agent`的隔离源码副本试验SDK原生`RawValue`／`Payload`：准入查询先构造并验证原完整proof，再由默认SDK JSON converter同步编码为独立Payload。普通State `view`仍走原detached，SDK查询的自定义Converter设计为原路径回退；当前仓库代码和已安装c58包不修改。没有通用deepcopy替换、数据删减、压缩协议或缓存。

它与此前已否决的通用JSON克隆／Manifest去重不是同一个实现，但**现有正向证据仍不足以证明拒绝语义与扩展契约等价**。此前600层exact dict的deepcopy拒绝、custom／subclass回调次序、资源边界和自定义Converter等必须继续核对，不得用新名称绕过旧反例。只读旧History查询成功也不证明不同source-pinned Worker可以接管旧Coding Run。

同一原第一根History完成后、驱逐前的两轮各五个完整Query，响应结果摘要及确定性protobuf Payload字节SHA均与c58基线相同。profile下准入查询约82毫秒→20毫秒，但该差值放大了细粒度复制成本，不能作收益结论。

另以四个独立进程按A／B／B／A运行，A为原安装、B为隔离副本；各进程四轮五种Query，**不启用cProfile**，计时覆盖原完整SDK query activation及响应编码，载荷解码和摘要核对在计时外。80个响应的结果／Payload字节均相同，History与观察缓存数量保持，零外部服务／模型调用。准入查询八个A样本CPU中位14.996毫秒、八个B样本8.593毫秒，约减少42.7%；完整五查询等次数集合也保留原其他路径。包导入路径分别核对为原安装／隔离副本，没有替换运行方法。

ABBA工件为`/private/tmp/ralf-s2-query-wire-unprofile-{0-baseline,1-prototype,2-prototype,3-baseline}-20261018`；汇总`/private/tmp/ralf-s2-query-wire-prototype-20261018/abba-summary.json` SHA256 `ef93dda1e844767980a6cb43e6681076cf8bfab60524cc03a93ee66b6759c312`。这是单个已完成根的默认Converter查询证据；没有当前活跃Query种类频数，也没有完整Tool／CONTROL或真实服务提速证据，不能外推原360通过。

## 独立复核：原型否决

只读独立审查复现一个合法扩展契约反例：Worker通过现有`worker_options`接受Workflow拦截器；`WorkflowInboundInterceptor.handle_query`在`await next`之后、SDK编码之前可以读取原返回字典。只检查`result["scope"]`的审计拦截器在基线成功，在原型因返回`RawValue`抛`TypeError`。默认Converter资格检查不能证明没有拦截器，也不能改变拦截器的原返回类型契约。因此**否决该原型，不继续添加特例guard，不进入产品**；80个相同字节的正向结果和42.7%的单Query样本收益不能覆盖此反例。

复现使用真实`TemporalRunState`、原初始化及SDK拦截器，仅提供离线默认Converter上下文；没有注入私有State、服务或模型调用。主任务再次执行复现，基线为dict成功、原型为TypeError。脚本与结果保留于`/private/tmp/ralf-sdk-wire-independent-review-YDeSOl`，SHA256分别为`eeb6522ece5dc585f9a1ed94169e4da5f23754547eac7e8ba5bfd47e190ab002`、`cc2f355e495a9fb0d463932808879b7b89e26ba00891b1fbd234f01b673ab626`。这不是实际服务或完整History的拦截器验收声明。

同时独立确认600层exact dict可经canonical及默认SDK编码，而原deepcopy抛`RecursionError`；但本次合法State构造路径493层即先拒绝，**未证明600层反例可成为已接受History**。它只说明默认编码不能普遍替代原复制拒绝域，不把它冒充本次实际History回归。未发现默认内建树同步编码期间的具体别名泄漏；source pin接管边界保持原规则。

## 后续边界

本批关闭的S2阶段门槛为0，原失败与剩余17项全部保留。当前产品仍为c58a3b…，没有新发行包或功能扩展。后续仅接受保持原字典、拦截器、复制拒绝、Scope及source pin契约的方案，并在完整Tool／CONTROL调用证明收益后才进入产品；不重试该RawValue候选或重复无变化的原360。SDK主循环45.612秒与未捕获27.806秒仍是明确的归因缺口，不将这些剩余成本改称已完成。
