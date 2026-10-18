# S2：完整 Activity 生命周期的成本归因

沿[恢复计划](../../docs/superpowers/plans/2026-10-18-s2-resume.md)继续`bb8a2ae`，本批仅补前批未测的外层owned Activity与结束回调成本，不增加能力或组合。原图首项360秒、Tool80／Runner60／审批180／first-close60／cleanup40保持；其余十二正常／五故障仍依赖原首项通过。仅本地提交，不推送。

## 固定输入与监控边界

沿用442产品wheel `c58a3b00000893cba6d79d447699e786d9b22633a95256207f69ae5eeb40a982`和930测试文件；产品与测试不修改，不套用旧候选全项目回归结论。独立安装已有379通过／17配置跳过，受影响372模块5607通过／638配置跳过，默认材料与两份原History、starter一次写入恢复按[原记录](2026-10-18-s2-runner-binding-cost.md)复用。

私有CPython monitoring只观测函数边界：完整deployment包装、原生命周期begin／ended、ContextExecutionOwner的execute／invoke／notify、Tool与CONTROL主体、Session控制和Runtime发布复核。原方法、请求、结果及Workflow状态机不替换，Workflow内回调跳过，不记录载荷或凭证。诊断使用本批新普通持久Temporal／PG16服务和原结构peer，不调用真实模型，不代表原生Docker或模型任务质量。

inclusive CPU包含同Task内的被观测子调用，不能跨层相加；exclusive CPU扣除这些子调用，也不包括未被观测的其他Task或进程。Wall包含等待和并发工作。诊断有监控开销，不能直接作为性能验收，也不能把跨运行总时差当作改进。每次核对输入、安装路径和自有关闭；失败容器停止保留，旧失败资源不动。

## 首轮监控失效与修正

首轮诊断原360秒仍超时，1 failed／零跳过，JUnit397.042秒含收尾；四Tool成功、4业务写入，2 roots退休，Session／Assembly与Worker关闭通过，原正删除证明允许本批schema清理，导出与Temporal持久数据、已停止失败容器保留。工件`/private/tmp/ralf-s2-outer-monitor-live-20261018`；只读业务／History审计SHA256 `a03db1fc5f6385c54c6ae5704c96fcde3288f64ee56136d0fb21211f4fe2c9bd`。

**首轮CPU归因不可用。** 监控记录27处`running_stack_mismatch`及27个残留running frame，虽然函数开始／结束计数配平，仍不能据此使用inclusive／exclusive成本表。原`activity-monitor.json`及其SHA256 `3bf13a73a1744a8d6904ba3b3179966a9463829a417c47b979ae52ea49d3e32b`保留，另写`quality.json`明确拒绝归因。

原因是按code／Task维护的递归栈无法区分同code异步调用的暂停与恢复。真实宿主Runtime向所选Runtime委托时会递归调用`complete_model`等同一实现。四层递归await独立稳定复现4处栈错误（RED），不是产品运行故障。监控器改用事件实际Python frame身份；递归、异常、取消、多Task、跨Task续接和线程自检96事件，零异常／残留，exclusive CPU152.200毫秒、进程CPU153.186毫秒。完整真实Runtime的SDK形状CONTROL主体再验证148事件、零异常／残留；106744字节Manifest、原SDK次数与完整证明、结果摘要`8a3c72d0971261e5a3e34534787d89c7da1362c9354f5db938d313b16ede81f4`保持。该主体没有外层真实RPC，不能代替下一轮服务诊断。

## 修正后诊断

同包原360秒诊断仍超时，**1 failed／零错误／零跳过，JUnit396.842秒含收尾**。76856次监控事件，开始／结束配平，零栈异常／残留，所有exclusive非负且不大于相应inclusive，exclusive合计不超过进程CPU。监控器源文件哈希在服务启动前固定；442产品／930测试及安装文件前后保持。工件`/private/tmp/ralf-s2-outer-monitor-v2-live-20261018`：原监控SHA256 `572e1dea5740837430727963b1b97da71a7b5e885a2c52e06f1030577e80e777`，质量通过后的`cost-summary.json` SHA256 `c803f3ae11d87688902e254945d4b546583990d7c5f8004db6f33468f2812deb`。

按Activity类型汇总被选边界的exclusive CPU；包含其原Owner子Task和已完成结束回调，不把inclusive重叠值相加：

| Activity | 调用数 | 被选边界CPU（秒） | 其中发布复核CPU（秒） |
| --- | ---: | ---: | ---: |
| CONTROL | 36 | 61.037 | 39.226 |
| Session CONTROL | 13 | 31.569 | 21.510 |
| Tool | 4 | 28.593 | 24.070 |
| deployment release | 8 | 11.282 | 6.240 |
| model | 9 | 8.138 | 5.079 |
| Session deployment verify | 7 | 7.450 | 7.450 |
| deployment admission | 7 | 4.278 | 4.107 |
| context | 4 | 3.561 | 2.085 |
| evidence | 4 | 3.177 | 2.187 |
| Activity以外 | — | 5.102 | 4.860 |

`validate_release`6000次，inclusive118.506秒；其中同函数递归会重叠，不能再加清单重建。去重后的发布复核为其exclusive17.494秒加`_current_manifest`5911次／exclusive99.320秒，约116.815秒。四个Tool各自的被选边界CPU在6.870–7.363秒，不能把35.6–40.7秒Tool wall全归给工具主体CPU。

原普通deployment生命周期begin的57次inclusive CPU共0.033秒；ended的57次共2.329秒；Owner结束通知78次共4.841秒。这些inclusive数值仍有嵌套，**不是可相加的剩余耗时，也不能解释全部超时**。本次进程CPU344.268秒，而所有被选边界exclusive合计164.187秒，尚有约180.081秒未归因；它可能包含未选SDK／Workflow／序列化及监控成本，不能从现有数据断言具体占比。已补齐外层生命周期这一遗漏，但未完成全进程归因，不据此新增产品优化。

四Tool均`ok=true`，业务写入4次；2个accepted roots均retired、零retained，Session／Assembly关闭与Worker退出通过。原fixture在正删除证明下清理本批schema，导出、Temporal持久文件及已停止失败容器保留，旧资源未动；只读History审计SHA256 `7c0b628c367cc8f77b00e3b82737445030f59e37e6b4d6f7e2e3e47e01296bb9`。原门槛未通过，不能启动剩余17项。

## 同一原History的只读Query检查

为收窄未捕获CPU，使用上述第一根原History（SHA256 `056f315873933b9bbc1645e7d3295801fd6b381cb26e9a8b2f6ae0d0fddfe83b`），在SDK Replayer完成原History后、原缓存驱逐前，执行两轮各五个原`view`查询。生命周期／结束观察使用History内实际Signal的完整原envelope，Scope／namespace／epoch保持；零服务／模型调用，不替换RALF方法。普通status、diagnostics、deployment_admission及两类观察均成功，两轮结果摘要分别相同，观察缓存数量和History文件不变。

首个私有探针误把合法status的`error: null`当成错误，SDK驱逐回调报错但Replayer返回；该次零查询不作有效证据。修正探针的响应判定，并显式捕获驱逐探针异常、要求十查询完整通过，避免把Replayer返回等同于测量成功。修正后工件`/private/tmp/ralf-s2-offline-query-cost-v2-20261018`，summary SHA256 `cb1d53ae36070755f2fbad473b37c194c189156e7a6b81ff10585058b067c5d5`。

在带cProfile／线程CPU计时的这个有限样本中，status及两种观察约0.4–0.6毫秒；diagnostics响应883034字节，约66–68毫秒；deployment_admission响应888165字节，约85–86毫秒，大响应的主要被采样自耗时为`copy.deepcopy`相关函数。剖析开销会放大细粒度复制成本，且该样本是完成后的第一根状态，不是原运行期间的所有Query／Update次数，因此**不能外推这两类Query解释了约180秒缺口，不能据此恢复已否决的通用快速复制或Query压缩**。

## 当前结论与下一步

本批只有诊断证据和文档变化，无新产品候选，也不重复未变化代码的全量回归。已排除“把Tool wall直接当主体CPU”和“仅凭外层结束回调推断唯一瓶颈”的依据，仍需在原SDK Workflow activation／载荷转换等未捕获边界补齐归因，或证明某个具体改动有完整调用收益，之后才允许下一次产品修改与原首项复验。S2及P3-2／P3-A整体未完成，原失败／360秒及剩余矩阵全部保留。
