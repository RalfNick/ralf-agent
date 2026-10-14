# dev109：受管理 Codex 模型连接验收

本批关闭第二阶段的专用 Responses 连接前置缺口，并验收一个有限真实 Coding 基线。
保持纯 Harness 与原 Local／Temporal 单一执行权威；完整 R13、第二阶段和 R01–R26
继续开放。第一阶段 dev99 四条参考链路保持冻结，没有重新运行其线上评测。

## 交付与公共契约

- `CodexModelConnection` 固定非敏感 endpoint／model／凭证环境变量名称、引用与代际。
  默认 `EnvironmentCodingCredentials` 延迟读取可信宿主环境；SDK 可替换借用 source。
  构造、配置加载、identity、冷核验和关闭不解析凭证。
- 原 Runner 增加 `_make_transport` 构造钩子；connected Runner 只扩展启动控制／认证，
  复用原业务执行循环、Action、attempt、审批、预算、Thread／Turn 和 namespace 清理。
  `tools/codex-coding-connected`／`codex-coding-connected-postgres` 提供 SDK／JSON／TOML。
- 同一个原生连接校验完整配置、初始空账户、一次 API-key login、两条精确通知和
  read barrier。账户认证是本地证据；远端兼容与任务质量另行验证。认证／远端错误
  不保存原始正文，晚到认证请求／通知仍拒绝。
- 已认证业务阶段，按固定 0.144.4 协议校验并丢弃额度通知和四类纯进度片段。
  额度不修改执行 credits，进度不构造结果；保留终态、错误和交互处理。进度上限
  16,384，最终内容仍取原 `thread/read`；旧未认证 transport 不变。
- 完整逐 helper／安全常量库存保留在 Worker 并独立复核；公开 identity 仅携带
  精确算法与库存 digest，仍核对公开值，避免原请求重复库存超过既有 JSON 限额。
  没有放宽通用 callable fingerprint、journal 大小或编译器闭包规则。

当前选定 native protocol 2／binding 14、静态组合 version 3／binding 15。
图拓扑范围未扩大；旧选定发布需要其匹配 immutable Worker，不能伪改版本号迁移。
本批确实修改了原 `_execute` 的 transport 构造，不能声称旧 117 个 native body 全部未变。

## 阻塞问题与失败证据

1. 全量 helper identity 重复进入准备 binding，真实 PG 最小重现为 65,952 字节，
   超过原 65,536 字节上限，认证和业务均尚未开始。改为有独立核对的有界公开 digest；
   本地与真实 History／PG 恢复通过。随后发现公开 digest 可被篡改而私有库存仍匹配，
   增加公开算法／digest 精确对应检查；源测试和独立 RED→GREEN 均保留。
2. 对全部 `account/*` 的拒绝遗漏合法额度通知。有限 typed quota 验证修复后，
   后续真实行号 trace 证明还存在先发生的 256 项事件 inbox 溢出；早期“仅额度导致”
   的归因不完整，已修正。精确纯进度过滤的 2,000 项真实 stdio 洪峰复现通过，
   终态／错误／peer request 与严格认证防线保留；不扩大队列或静默忽略未知事件。
3. 初始真实 smoke 驱动错用 `generate`，在模型／原生业务前失败；后续原配置及
   诊断配置的 unknown/fenced 失败全部保留，均不并入最终冻结质量评分。
4. 原 sandbox 下广泛检查出现本地 HTTP／Redis 权限错误并中断：22 failed、
   3168 passed、69 skipped、7 errors，保留该日志，不视为成功。安装首次也保留
   1 failed／2046 passed／429 skipped／1 error。冷恢复测试遗漏固定 timeout
   跟随改为读取原 identity；其与 Redis 启动权限问题的定向安装复验 2 项通过。

fixture deadline 采用 8 秒，cold restore 复用原值；真实服务 fixture 沿用已有 30／40 秒
界限并保持原 receiver 存活直到 owned close。没有修改生产 60 秒上限来提高模型成绩。
source identity 漂移可阻断 stop receipt 采纳：物理 namespace 已结束，原 owner 和
`cancelling` 保留，修复原依赖后重试关闭；这是保守边界，不静默释放原责任。

## 最终验证

| 范围 | 实际结果与限制 |
| --- | --- |
| 全模块分组回归 | 607 个模块，9552 passed／675 配置依赖 skipped；五组执行返回成功，构建 fixture 串行，未注入线上模型密钥或外部服务配置 |
| 冻结核对 | 产品快照不变；唯一变动是集成测试 Worker path helper 与新增旧发布 gate。变动模块最终复验 5 配置跳过，当前全收集 10,227 项与分组总数相符；真实服务另有实际证据，不伪称原测试快照未变 |
| 独立安装 | checkout 外，`src` 无产品 Python。首次成功的 2046 项与两个失败的定向 GREEN 合计 2048 成功；429 配置跳过。新增服务 gate 在实际服务证据中验证 |
| 真实服务源码／安装 | Temporal＋PG：binding14/15 × 审批后冷 Worker／运行中取消，源码四项与最终安装四项通过；原 Action/attempt/effect/epoch、一次 Thread/Turn、认证三次、fence、History replay 与无 canary 持久化均核对；native peer 为结构化假服务，不据此声称真实模型质量 |
| 旧发布兼容 | immutable dev108 selected13 双 Agent 图实际 approval_restart 通过；当前安装拒绝其真实13元数据及伪改14/15，在资源／业务前停止。旧 Histories 未改写 |
| 独立审查 | 最终 requested scope 无剩余具体 P1/P2；106 项 focused 复验，不与全回归重复加总 |
| 默认／包体 | 未选 Coding 的五种固定默认构造与 dev107/dev108 逐字节一致，SHA256 `35004369d4aa8b8b85cc45f59f00fa3f6ee83be8061c20fbf053b99446d03349`；385 产品模块，原378模块保留，source／wheel／installed 产品字节相等 |
| 格式与清理 | Ruff、format、Git 空白检查通过；源与安装两组自有 Temporal、PG 容器／匿名卷／ports／schemas／sockets 已精确清理。15 个真实模型试验原 CID 独立核对缺失，前后 Docker 服务健康 |

独立原生 canary 对照完整配置与认证消息确认没有落盘。原生 sandbox CLI 的 protected
文件、proc／process_vm_readv／ptrace 拒绝，以及固定版本 builtin filesystem helper
源码审计分别保存；unsandboxed same-UID Docker-exec 基线能打开 PID1 内存，所以
不把 cap-drop 或源审计描述成任意操作／漏洞下的全局内存保密证明。RAM 不保证零化。

## 固定真实质量基线

[冻结任务](../../evals/coding-cases.json) SHA256：
`4bcb3037efd1e744edb471fe4bd45a702c8282c551c489d50bb249b422b66e8b`。
三个任务为 signed decimal add、nonblank line count、validated CSV total，每项三次。
模型连接为 `https://api.deepseek.com`／请求型号 `deepseek-flash`／reasoning `low`，
原 Runner 60 秒；outer dispatch 固定，不评价模型工具选择或自主规划。

已安装测试 wheel SHA256：
`8997483ac84d3916ebe13fba4a610852485a525d6022007e5669a75cccfcbbc1`。
原生 0.144.4，镜像
`sha256:0a38a968acc4f11ab75cfd4b65a1c2f1982a18bfc27d9fb0dc1045bef5e79d43`。
最终 SDK 基线 **9/9** 次成功，78 项独立 oracle 检查通过；oracle 使用另一批禁网、
read-only、cap-drop、非 root、限制时间／内存／输出的容器，仅挂载工作区与固定输入。
宿主不执行生成代码，所有 oracle 容器精确删除。原 native Action 各一次 attempt，
最终线程回读、候选采纳和原资源 fence 都通过。

[脱敏结果](../../evals/results/deepseek-coding-dev109.json)记录全部输入案例对应的检查、
原状态、限制和耗时。893 个持久文件全部在原扫描范围内，最大约 4.36 MB，没有发现
实际凭证。用量／费用保持 unknown，耗时包含验证与 oracle，不作为性能比较。
文档整理后的 metadata-only 重建可复用该证据，前提是全部385模块及原生 JSON 资产
逐字节核对相等；模型试验的原 wheel hash 独立保留，不替换成未测的新 hash。

该结果只验收三类有限 POSIX 编码任务。复杂仓库／多语言／长流程、真实 Temporal
模型任务、企业凭证代理、外部首次采用和跨框架优势尚未验收；不关闭完整 G7／R13。

## 下一批

优先按既有原父 History 的持久选择边界补齐 Temporal Team／Dynamic Coding，随后
关闭跨父容量与不确定 create/CID 窗口等阻塞项。避免重复第一阶段四链路或新增非阻塞
适配器。完整能力目标继续 active，本批仅本地提交，不推送远端。
