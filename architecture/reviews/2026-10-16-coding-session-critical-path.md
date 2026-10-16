# Coding Session 整链成本预算与下一批门槛

最新证据为 `ec0ebe4` 独立安装包的一次原 `graph-sequential-sdk` 两 Turn 验收，仍因原 scenario360 超时失败。下方整链预算基于此前 `31b846a` 的终态工件，不能将两个快照的时间拼接。本文不关闭 S2／P3-2，不改变支持矩阵或任何期限。

## 安全诊断后的原场景复验（2026-10-16）

本批只运行原首项，Tool80／Runner60／approve180／scenario360／first-close60／cleanup40均保持原值，无诊断开关或性能采样。只读取已授权配置中的两个本机服务字段；未调用真实模型，未执行其余十二正常／五故障。425产品／862测试与当前工作区及独立安装一致，运行前后无漂移。

根进程55384已确认exit1：1 failed／0 errors／0 skipped，JUnit suite386.753秒，case386.166秒（均含收尾）。外层360秒取消落在 `scenario → approve → sleep`，不是审批180秒独立超时。本次 `child_control_failed` 安全诊断为0条，上一轮该通用异常没有复现，不能继续将其当作持续超时的根因。

四Tool分别38.020187／38.412823／40.900876／37.940434秒，均SDK Completed、ok:true，候选结果存在，四effect adopted，物理停止正证据且无pending stop。第四Tool于00:26:52.410007Z完成；后Evidence于54.684656Z、Context于58.866625Z、Model于00:27:03.227771Z完成，均ok:true。随后根observe于05.468004Z完成，join注册于05.541057Z调度，10.666764Z返回definition_mismatch，未启动join子任务。

注册跨越超时与关闭：Registry coding-close在00:27:10.355125Z正Completed，根cancel在10.523009Z Accepted，均早于注册拒绝完成；取消时在途CONTROL栈停在原Registry admission Query。该顺序支持关闭后拒绝，不证明关闭前存在独立验证缺陷，也不把瞬时等待栈当作全程耗时归因。初始取消文件mtime只作辅助代理，不当作Temporal事件时间或精确超时触发点。

两Turn各6 start／6 end，全部原Completed ACK为正；Advance分别为succeeded／released和cancelled／released。两root accepted2／retired2／retained0；assembly关闭、Worker退出及安全清理通过，schema未保留、保留原因空。没有完整业务结果文件，**S2仍未通过**。本次未证明性能改善，也不因缺少通用异常而降低原业务成功要求。

同步Runtime指纹pass的设计审查也已停止：同步验证仍会调用组件getter，getter可临时替换helper、命中旧指纹后恢复；仅入口／出口检查无法保留原逐次拒绝行为。将检查放进LRU miss函数也无法防止该函数自身临时替换后污染缓存。未写入产品，未测量该不安全方案。默认与旧History继续沿既定兼容承诺；旧Coding History仍用匹配不可变Worker。

下一步以**完整Tool／CONTROL调用**为成本分析单位，分清同步验证、复制和实际SDK等待的成本；小段Runtime基准不能代替整条调用收益。已有失败证据保留，不重复原场景碰运气，不继续缓存放行或逐个删Query。只有影响当前累计耗时且保留原身份、权限、效果与真实停止责任的变更，才进入下一轮产品验收。

本次终态证据：`/private/tmp/ralf-agent-dev121-session-state/child-diagnostics-normal-terminal-evidence/summary.json`，SHA256 `3b3e26d540b545f648c7d371a85ed3da9eccc57fb2cc0bdf3c26d3665e991377`；34项原输入哈希前后相同。`close-order.json` SHA256 `af24ec603b4730819e106b95f94b45da9d0fa38ee4159d7994282a481f84c6af`。运行工件在 `/private/tmp/ralf-agent-dev121-root/installed-s2-child-diagnostics-normal-sdk`；日志SHA256 `eae62ac7321bb436d3f03e1f940775b4b724fee3ed874d893c9c3e5165eb21ac`。这些临时路径不是公开发行附件，复现仍以仓库中的原测试与外部服务配置要求为准。

## 原场景的墙钟预算

区间按原 History 时间排列；控制 Activity 与工具存在重叠，不能把各 Activity 总时长直接相加。

| 不重叠里程碑区间 | Turn 1（秒） | Turn 2（秒） |
| --- | ---: | ---: |
| submit → root start | 6.335 | 6.601 |
| root → a start | 10.005 | 9.730 |
| a start → Tool A start | 18.159 | 17.847 |
| Tool A | 38.067 | 41.039 |
| Tool A end → b start | 12.999 | 22.360 |
| b start → Tool B start | 12.238 | 17.152 |
| Tool B | 36.222 | 39.339 |
| Tool B end → join start | 16.064 | 未启动 |
| join start → Model start | 5.499 | — |
| join Model | 4.741 | — |
| join Model end → root seal | 9.122 | — |
| Tool B end → failed seal | — | 14.944 |
| seal → positive Advance | 17.345 | 15.511（failed） |

首 Turn 从 submit 到成功 Advance 为 **186.795 秒**；root start 到成功 Advance 为 180.460 秒。首成功 Advance 到第二次 submit 另有 7.978 秒，包含测试端读取和重复提交验证；History 未保存每次 Query 等待，不能全部计入产品执行成本。

root start → Advance 的墙钟覆盖另按类别去重：

| 覆盖类别 | Turn 1（秒） | Turn 2（秒） |
| --- | ---: | ---: |
| Tool | 74.289 | 80.378 |
| Model（不重叠） | 18.066 | 13.000 |
| Context（不重叠） | 0 | 13.203 |
| CONTROL 中未被以上类别覆盖的部分 | 52.928 | 42.457 |
| 未被以上 Activity 覆盖的间隙 | 35.177 | 28.885 |
| 总计 | 180.460 | 177.922 |

第二列总计通向 failed Advance，不能作为第二 Turn 成功耗时。Activity 覆盖也不是 CPU 分摊、网络耗时或因果关键路径归属。

第二 Turn 的 a→b 交接中，首次 b 注册耗时 3.171 秒并返回 `child_control_failed`，随后一次注册耗时 6.616 秒成功。仅有错误码，没有内部异常原因；不能把这次重试当作已定位的独立缺陷。后续若修改注册路径，必须先有内部原因证据。

末 Tool、效果采纳、实际物理停止均成功。第二 Turn 的末 Model 收到原关闭后的 `allowed:false`，返回 `validation_error / dispatched:false`；它不是独立 Provider 失败。两 root 退休、Session 正 ACK、owned 关闭和安全清理通过，仍不能替代两 Turn 业务成功。

## 重复载荷来自哪里

对保存对象按 SDK JSONPlain／Payloads 重新编码，得到了与日志三类告警大小相同的值：

| 保存对象 | JSON 字节 | Payloads 字节 |
| --- | ---: | ---: |
| root deployment proof | 853455 | 853487 |
| 完整 closure | 881714 | 881746 |
| root children | 743910 | 743942 |

这是对象形状和大小的对应，不唯一绑定某一条未记录 method 的 Query 告警。512KiB 是 warning 阈值；这些工件没有证明触发了 2MiB 失败，也不能单凭大小断言它们导致 360 秒超时。

root deployment proof 的 children 占 743910 字节。完整 closure 中有六份相同的 101875 字节 Manifest：root 一份、三个 child physical-stop proof 各一份、两个 native snapshot 的 tool request 各一份，合计 611250 字节。主要重复来自已回灌的完整 child snapshot／物理证据，而不只是 Session intent。

现有 CONTROL `pack_response`／`expand_response` 已能对已知协议字段做无损引用和严格还原。Parent State 采纳时恢复完整对象，后续完整 Query 又展开这些 Manifest。现有 compact node／Registry 投影则缺少完整 physical／ACK／children 事实，不能直接替代树证据。Registry 的大关闭回复发生在 cleanup，不能拿它解释主业务窗口。

## 纯校验原型的决策

源码中的完整 `validate_manifest()` 会经 deployment、native 和直接 composition 入口重复验证同一声明。这与 `_current_manifest()` 的逐层构建不是同一个调用路径：代表性 Runtime 重建中，两次完整 Manifest 入口处理的是未发布 Coding 的中间结果，native 完整校验实际只有一次；不能把三个 composition 入口全部视为三次完整库存验证。

私有 header 拆分原型以四个冷进程 A/B/B/A、相同物理 fixture、每进程 30 次完整 Runtime 验证测量。A 平均 19.321ms，B 平均 19.720ms，未满足预先登记的完整 Runtime 至少降低 10% 的门槛。测量覆盖了完整 Runtime，但拟归并分支未命中其中的 Coding 发布步骤，未测完整已发布 Manifest 的归并路径，也未补齐独立入口防替换检查。**不纳入产品，不据此进入安装、完整回归或真实服务复跑。** 该结果不证明完整公共 Manifest 校验归并无收益，也不允许强行扩大资格条件来制造分支命中。

未来若重开此方向，必须测实际完整请求的同步链并记录分支命中；还必须保留独立的 native／composition 入口及新 helper 指纹复核，防止 no-op、code／defaults／closure／wrapped 替换消除唯一校验。不得加入可由调用者传入的跳过标志或跨请求权限缓存。

## 无损 Query 传输原型：否决（2026-10-16）

按上一批固定范围，用原 closure、deployment proof 和 children 的六个已知 Manifest 字段（children 子对象为五个）做单一私有原型：只复制引用祖先路径，逐原字段验证 Manifest digest，接收端严格验证路径、版本、占位及固定 Manifest，每处恢复独立 JSON 副本。业务字典和原 physical／seal／request 事实保持完整。没有增加产品 Query schema。

预先登记门槛为：每个对象 SDK 字节至少减少40%，完整CPU各不回退、等次数三对象均值至少减少10%。四个冷进程 A/B/B/A，每进程每对象30次；两侧计时都包含完整SDK编码、解码、相同语义／原proof digest及无别名检查，B额外包含完整pack／hydrate。六种路径、缺失、重复、错误Manifest／digest／占位反例均拒绝；输入哈希前后相同。

| 对象 | 原 SDK Payloads 字节 | 去重后字节 | 字节减少 | 完整 CPU 增加 |
| --- | ---: | ---: | ---: | ---: |
| closure | 881746 | 271081 | 69.256% | 9.986% |
| deployment | 853487 | 242747 | 71.558% | 9.619% |
| children | 743942 | 235003 | 68.411% | 6.768% |

等次数汇总完整CPU增加9.013%。结果未满足原门槛，**否决，不增加Query协议，不改变阈值，不为该候选做安装或实际服务复验**。字节下降不代表SDK真实延迟下降；本实验没有测网络或服务，既不证明任何部署中都无收益，也不支持将其纳入当前本机场景。下一步回到同步release验证的整组成本与原注册失败诊断；不把本次否决包装成性能修复。

并行补齐一个已证据确认的诊断缺口：真实CONTROL回调对非RalfError保留原 `child_control_failed` 回执，额外best-effort记录有限静态栈、SDK封装原因白名单码和真实RPC状态。原回执先构造，日志失败不得改变它；不输出请求／Scope／输入、原异常文字、details、args、locals或全路径，不添加History字段或改重试分类。业务取消仍原样传播，已知RalfError仍用原码且不额外记录。该诊断不能追溯解释原已保存的注册失败，也不关闭S2。

诊断修复验收：主RED证明真实CONTROL回调仍返回原错误回执但缺诊断；新增18项全部通过，联合原Session诊断23项通过。最终冻结快照20个受影响模块399 passed／零失败／错误／跳过，51.250秒进程窗口，425产品／862测试无漂移。独立安装7模块157 passed／4.220秒、零失败／错误／跳过；源码／sdist／wheel／site425文件一致，862测试副本前后不变；默认完整Profile／Manifest／编排canonical及原／continued保存History离线重放通过，Provider／服务调用0。独立审查无P1／P2，Ruff／格式／空白检查通过。未复跑原360场景，不能将本诊断视为延迟修复或S2通过。

## 下一批的固定边界

1. 已完成并否决上述完整proof无损传输预算；不重复测量同一候选或扩大Query协议。
2. 保留原完整Query、物理／ACK事实以及SDK epoch／namespace／Scope权威。下一产品候选必须从实际同步验证链的成本出发，先给收益与漂移拒绝证据，再进入安装与真实服务验收。
3. 广义同步Runtime指纹pass已因getter瞬态替换和LRU污染风险停止。下一步分析完整Tool／CONTROL调用的累计成本，不能再将该pass当作已确定的实现方向，也不回到通用getter缓存或缓存helper放行。
4. 产品冻结后只补受影响检查、安装兼容和一次原图原期限验收。S2 通过前，其余十二正常／五故障不解锁，P3-3／4／5／A 保持原清单状态。R01–R26 仍为长期路线图，不将本诊断批当作能力完成。

## 可复核证据

- 原实际终态：`/private/tmp/ralf-agent-dev121-session-sdk/activity-root-normal-terminal-evidence/summary.json`，SHA256 `4c5081b0560e5db2ad88141509e1e7a5378b86a35f0b9925ce8e7e7c21beee4a`；同目录 `input-hashes.json` 覆盖 34 项工件。
- 去重墙钟预算：同目录 `critical-path-budget.json`，SHA256 `7ec286a2f638dfc2bc86454c03d22b3665ec2faf604b9600ef0e9d86ad0d988c`，输入 History 哈希前后不变。
- 载荷字段与编码预算：同目录 `payload-budget.json`，SHA256 `41f2c05eafaab71a2085aa301441c201d17690232a7517d93003d7f67d1959e0`；记录原输入哈希、对象路径、SDK 编码和六处 Manifest 引用，原输入前后不变。
- 私有校验原型：`/private/tmp/ralf-agent-dev121-session-state/manifest-pass-review/upper-bound-result.json`，含四进程计数及作用范围；A／B 各保留独立包和输出。没有修改产品，也不作为恢复或真实服务验收证据。
- 无损wire完整ABBA：`/private/tmp/ralf-agent-dev121-session-sdk/proof-wire-budget/summary.json`，SHA256 `6673b32a9bc30cf1679b46ebcf401fc5bfe6758699fa296268d65d084f6abce9`；预登记 `plan.json` SHA256 `d4ab6807b23ca3fe4f53a20d172a7e801c0b7dc0f22ce9536df29fc3e3a25c63`，原输入／脚本哈希不变。
- 诊断主RED：`/private/tmp/ralf-agent-dev121-session-state/child-control-diagnostics-red.log`，SHA256 `4b3e55c87308e6210517e14411a02592242ecef133164499612373d103c48b00`。最终冻结清单 `/private/tmp/ralf-agent-dev121-root/child-diagnostics-release/frozen-audit.json`，SHA256 `c8f3a605572f3090fc173743ff0c12f084e82a30642b658a9428f1eebf80846a`，同目录 `result.json` 为20模块回归。
- 独立安装摘要：`/private/tmp/ralf-agent-dev121-session-sdk/default-compat-s2-child-control-diagnostics/final-summary.json`，SHA256 `e3237a214990fba3fbea74ba5bc52146b5a68853ab801410f161fe365203afb7`。该安装证据不含真实服务，也不代表旧Coding History跨Worker兼容。
- 业务、关闭和末模型时序详见[上一批原验收记录](2026-10-15-temporal-deployment-sessions.md)。
