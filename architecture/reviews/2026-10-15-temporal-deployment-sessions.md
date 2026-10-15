# 部署 Session 集成与收尾验证

日期：2026-10-15。按 [P3-2 固定计划](../../docs/superpowers/plans/2026-10-15-temporal-deployment-sessions.md)收尾，仅本地开发与提交，不推送。S1 普通 Session 功能子集已在 `4fdd5ae`、`8e33b9a` 记录；本批继续接通既定 Coding Session，不引入新编排、适配器或执行权威。

## 当前结论

S2 已实现并交叉审阅，首个真实安装 Agent 两 Turn 验收通过；其余矩阵两个首项仍失败，故障门槛尚未执行，不能标为完成。Temporal＋PostgreSQL、P3-2、第三阶段整体验收继续开放。以下结果来自不同快照，不相加、不称为最终全量；跳过不构成服务或模型验收。

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
| v7 安装验收 | 原失败sequence-json优先复验：1 passed／306.23秒，零失败／错误／跳过。两Turn、四次业务写、原结果采纳、退休／会话发布和安全清理通过；424产品文件前后一致、340已加载安装模块来源已核验；原80／60秒期限不变。其余十二项并行运行 |
| v7 安装相关回归与兼容 | 八模块155 passed／6.52秒，-Werror、零跳过；完整默认发布相等，原／continued History离线重放通过，Provider0／服务0 |
| v6 默认兼容 | 完整默认Profile／identity／Manifest／orchestration等值、原／continued保存History重放通过；Provider0／服务0，无live continuation |
| 测试清理与诊断 | retention32项、Worker异常保留32项分别通过，交叉审阅无阻塞；body与close原异常均保留 |

## 候选与剩余门槛

v5 `s2-advance` 快照1727文件／424产品文件，inventory SHA256：`d530c203d8d4f7826cc915b2184c1be48937934966bafca380aa1bf17ce6ee53`。v6 `s2-origin-reads` 快照1729文件／424产品文件，inventory SHA256：`b935d23c2abae7a156662f0e5c447b2b8f9751a0bf65e02f37875e1e06eaea74`，首个安装 Agent 通过，矩阵首两项失败。v7 `s2-selector-snapshot` 快照1730文件／424产品文件，inventory SHA256：`ef3fc59506253032671f0660a6fbe761d3a4ad93cf40ca0448afa345e67d7826`；155项相关测试通过，安装后优先复验失败的sequence已通过，原十三项集合及原期限保持。源码、wheel、独立安装424产品文件一致；metadata 仍为未发布 `0.1.0.dev120`。

- v5 首个 Agent 两 Turn 已通过；v7 原失败sequence已通过，其余十二项正在两个隔离进程验收；v6 两次首项失败及未运行十项的旧记录保留。
- 验证原审批冷交接、退休回复丢失、显式取消及 effect／native-stop／deployment-end 独立 ACK。
- CONTROL 真正进程死亡后保留原 Turn busy、占位及恢复数据，不制造通用 fence。
- 完成最终安装、约定默认／History 兼容和受影响复验，才判断 S2／P3-2 能否关闭。

结构 native peer 证明 Temporal、PostgreSQL、原生子进程及文件效果协议，不新增真实模型质量或真实 Docker daemon 故障结论。历史真实模型及 Docker 证据按原范围引用；未知义务所需服务与数据继续由原所有者保留。
