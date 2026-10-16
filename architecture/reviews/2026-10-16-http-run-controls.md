# P3-3 原 Run 的 HTTP 审批、核验与恢复唤醒

日期：2026-10-16。依据用户“允许独立推进 P3-3，保留全部验收门槛”的授权，沿原 A2A 入口补控制链路。不重开性能专项，不更改 P3-2/S2 原 360 秒失败及原 Worker 恢复要求，不自动解锁 P3-4／5／A。

## 交付边界

显式 `enable_run_controls=True` 广告 `urn:ralf:a2a:run-controls:v1`。`tasks/approve` 和 `tasks/reconcile` 复用原同步／原生异步控制端口，核对 Scope、方法绑定和原 durable CommandReceipt；客户端检查命令、Run、类型与记录状态。`tasks/resume` 只向显式宿主 hook 发非持久唤醒，返回原 Task 及 `durable=False` 提示，不伪造持久恢复命令。Local 宿主复用原 root 调度和关闭责任。

四个产品文件发生变化：`a2a.py`、`a2a_controls.py`、`task_controls.py`、`service_lifecycle.py`。没有修改 Engine／Temporal 状态机、发布协议、存储或 Inbox 权威。默认关闭，不增加旧结构端口的必需方法。使用方式见[指南](../../docs/http-run-controls.md)。

## 验证与证据

1. 首批7项在缺少新入口时 RED，随后实现。曾有暂停状态断言失败：测试只 join 旧 `_active` 快照，遗漏完成回调启动的后续 drive；改为在有界期限内 join 实际活跃任务直至排空，没有修改产品状态机或放宽最终状态。最终受影响八个非socket模块 **122 passed**，零失败／错误／跳过。
2. 当前源码真实 loopback HTTP 两模块另一次 **5 passed**，零失败／错误／跳过。包括原事件／取消场景及新增的审批、未知写核验两条独立进程重启路径。恢复使用原 message、Run、Action、命令身份；未知 Action 从原 HTTP 事件取得，不靠测试私查执行库。真实业务库记录每次写尝试，不用业务去重掩盖重复；各路径一次写入，重复控制返回原回执。
3. 初次新增进程测试仅按退出码0断言，出现2项失败。检查已安装 Uvicorn 的 `capture_signals` 后确认它会在 graceful shutdown 后重发 SIGTERM。测试改为要求独立的 `lifespan.shutdown.complete` 正证据：service与Engine均closed、活跃drive为0、真实handler线程为0；同时等到实际子进程退出，允许0或SIGTERM。缺少这份关闭证据仍失败，不以退出码代替停止／关闭。没有为此修改产品。
4. 仓库外新venv安装候选wheel，复制必要测试；事件及控制 **32 passed**，真实HTTP另一次 **5 passed**，均零失败／错误／跳过。427产品文件源码／wheel／安装逐字节一致；产品及复制测试运行前后无漂移。隔离解释器导入来自安装目录，无checkout路径；第三方依赖复用本机已有安装，无下载。
5. 原基础包与候选在独立解释器运行同一无调用脚本，默认Agent Card及普通空工具Temporal发布声明完整相同。仅证明该对照，不外推所有History或选中Coding兼容。原基础制品与事件候选均保持不变。
6. 受影响Ruff、格式及Git空白检查通过；独立只读代码及文档审查无阻塞，核对原权威、回执、关闭、默认兼容及验收限制。没有重复全量基础回归，没有真实模型、Temporal或PG调用。原12,749／838基线仍只适用于原冻结基础快照。

补充用例覆盖：同命令并发、完成后重提、宿主重启后原回执、变更内容冲突、接受审批后唤醒失败再取原回执、真实原业务查询核验、不可查询unknown保留、认证／字段／digest拒绝、关闭期间拒绝、错误远端回执、借用原生异步端口。后者是Local权威的异步适配测试，不是实际Temporal验收。

证据目录 `/private/tmp/ralf-agent-p3-controls-20261016/`；制品目录 `dist/p3-controls-20261016/`，含 `verification.json`／`SHA256SUMS`。wheel SHA256：`272f5a35762b62994df177dfcc67d3b2aaefe171816ec6c6e75caee3b2c2665b`。安装HTTP与非socket分次登记，不相加宣称一次阶段全绿。

## 未关闭与下一批

P3-3仍开放。Inbox容量1的证据不能替代执行权威累计命令容量验收；原 TemporalDeploymentAdmission 的命令容量满时仍会拒绝新的控制命令，已有任务取消／恢复的必要入口需要下一批定向解决。须保留单一权威、旧发布／History兼容责任与原容量门槛，不借本批改成无限队列或一般Registry重构。

随后还需所选真实Temporal／PG宿主的控制与恢复、完整安装服务验收及必要诊断。人工核验需调用方先取得真实业务证据；resume只说明宿主接受唤醒，不保证恢复成功、物理停止或效果闭合。阶段门槛本批关闭数为0，仅本地提交，不推送。
