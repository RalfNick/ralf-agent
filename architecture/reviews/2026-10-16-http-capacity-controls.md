# P3-3 验收准备：已有 HTTP 控制与 Inbox 容量

日期：2026-10-16。范围依据为[第三阶段固定清单](../../docs/phase3-support-matrix.md#固定剩余清单)。这是独立测试准备，不启动新服务能力建设，也不跳过 P3-2 的依赖。

## 门槛与结果

P3-3 要求容量耗尽不能使已有任务失去必要控制入口。本次只验证其中既有 Local A2A HTTP＋SQLite Inbox 的路径：

1. 将已有 Inbox 的 `max_entries` 配置为 1，接受一个消息，等待原异步模型调用实际开始。
2. 新消息被拒绝，未创建第二条 Run 或消息回执。
3. 同一原消息重提返回原 Task；原消息回执和 Task 查询仍可用。
4. 取消请求到达原执行权威。模型调用尚未实际结束时为 `cancelling`，不能将控制回执当作实际结束。
5. 测试进程显式释放原调用后，原 Task 成为 `canceled`；按原消息继续查询和重提仍是同一 Task。SQLite 中只有一条 Run、一条 Inbox 回执。

两项真实 loopback HTTP 测试均通过，包括原有任务提交／去重／查询／取消用例。服务在独立子进程运行，退出时等待进程结束；未连接外部模型或数据库服务。

## 变更与证据

- 运行时代码、公开接口、默认配置和包版本均未改变；只为既有测试服务添加容量参数、跨进程调用结束信号及一项测试。
- 受影响源码测试：`test_a2a.py`、`test_a2a_async.py`、`test_a2a_http.py`、`test_task_controls.py`、`test_service_lifecycle.py`，**39 passed，0 failed／error／skip**。
- 原基础交付 wheel `ralf_agent-0.1.0.dev120-py3-none-any.whl` 的独立安装：复制两份 HTTP 测试文件到仓库外，用安装解释器运行，**2 passed，0 failed／error／skip**。导入路径不含源码目录，425 产品文件与基础交付逐字节一致；源码产品文件验证前后也一致。
- 结果及日志：`/private/tmp/ralf-agent-http-capacity-20261016/`，含 `result.json`、源码／安装 JUnit XML、日志及安装隔离信息。
- 首次沙箱尝试因本机监听权限拒绝而未运行；授权 loopback 后，新增夹具曾永久阻塞 Provider 却要求立即取消完成，产生一次超时。修正夹具为显式释放实际调用，没有修改产品取消语义。失败不作为产品缺陷或通过证据。
- 两份变更测试的 Ruff、格式检查及 Git 空白检查通过。产品无变化，复用基础交付的完整离线回归，不重新运行整个阶段。

## 尚未验收

本次 Inbox 容量证据不覆盖 Temporal Registry 或其他执行权威的累计命令容量，不证明这些容量耗尽后的控制／恢复入口。HTTP 审批、效果核验／恢复、持久事件游标和完整服务治理仍按原清单待交付；P3-3 没有关闭。

S2 Coding Session 原 360 秒失败、Temporal＋PostgreSQL 集成及其余第三阶段门槛保持原状态。性能专项继续后置，不重复微调。下一步先核对既有 Temporal＋PostgreSQL 的验收设施与缺口，预计一个证据核对批次；不预估完整阶段完成时间，不新增部署组合。
