# Alpha 后续公共契约修复

日期：2026-10-22。基线 `eb62d57`。本批按整体 review 修复现有行为，复用 Harness／Local／Temporal 执行权威；不扩功能、依赖、Schema 或协议，不推送、触发 CI 或公开发布。完成后仅本地提交，按用户授权单次跳过 Git 钩子。

## 修复范围

- 取消：TaskControlBridge 接受原权威合法的 rejected 回执；A2A 同时识别 Local 的 apply_state 与 Temporal 既有 outcome 拒绝格式。终态、稳定 command_id、原回执和幂等关系不变。
- starter：按实际模板输出入口及 seed／check／run、ingest／index／query 顺序，不再给十五种模板统一输出 --ticket。原模块／CLI 参数不变。
- Agent：非空工具须为显式声明 effect 的 ToolRegistry；裸函数列表在创建数据库前清楚拒绝。空列表／元组与省略工具保持兼容，不推断 read_only。
- 检索：固定内置 Lexical／Vector／Hybrid 实际登记的直接来源／索引／Embedding 方法，并在逐次来源读取前后检查，阻断等待期间替换后继续派发其他端口。普通源 CAS 更新及旧来源拒绝保留。该保护不递归追踪任意 Python、客户端内部状态或隔离可信宿主；第三方适配器仍须保证真实后端固定与当前来源回读。

## 验证记录

首轮测试先复现：31 failed／2 passed；另一个 failed-Run 夹具起初抛 ProviderError，被正确标为 waiting_reconciliation，已改用收到非法空输出后的确定性失败，再形成该轮记录。它是夹具选择问题，不改产品错误语义。原 review 的独立复现与历史失败均保留。

初次修复后四模块64 passed，补 Engine 模型前来源拒绝后检索13 passed；独立 review 又发现多块读取间隙，四项竞态先全部失败，再补逐次复核。修正前全量主动中止，707 passed／36 skipped，退出2，不列为完整通过。

最终受影响四模块源码 **69 passed**。从固定维护源码复制到独立临时目录构建测试 wheel，442 个产品文件逐字节相同；在 checkout 外独立 venv 安装，导入路径确认来自该 venv，同四模块 **69 passed**，零失败／错误／跳过。不读取模型密钥或真实服务配置。两个环境独立记录，不相加为138项覆盖。

相邻检索／知识／向量／Embedding的22模块 **316 passed／22配置依赖skipped**。首轮在沙箱内316通过／20跳过／2个本机HTTP夹具端口PermissionError；允许本机IPC后同范围完整重跑得到上述结果，不改测试或服务配置，原错误保留。没有连接真实PostgreSQL／Qdrant或模型，不把跳过项标为验收通过。

全量 Ruff 通过，1,423文件格式检查与 Git 空白检查通过。网站12项测试、14对双语来源核对、48条固定版本仓库路径核对通过；Astro28文件零错误／警告／提示，32页／1925本地链接与资源构建检查通过。九组受影响指南已核对工具注册、扩展和安装含义后更新来源锁；原a1教程代码基线不移动。

完整离线回归 **14,077 passed／891条件skipped／5 failed**，零error，40分32秒，退出1；JUnit与命令结果一致。期间产品／测试代码未变，442产品文件与安装快照逐项一致；环境只保留本机必要变量，移除模型密钥与真实服务配置。**本轮不是全量全绿，也不是发行放行。**

五项失败均来自未修改的Coding子进程测试：

| 测试 | 整轮观察 |
| --- | --- |
| `test_codex_create_supervisor.py::test_success_is_one_exact_same_pid_exec_and_no_host_environment_leak` | 原结束回执cid为空 |
| `test_codex_create_supervisor.py::test_timeout_output_and_eof_require_actual_original_child_end[hold]` | 5秒内未见原子进程启动记录 |
| `test_codex_create_supervisor.py::test_unknown_control_token_does_not_stop_or_unseal_original_cli` | 5秒内未见原子进程启动记录 |
| `test_codex_create_supervisor.py::test_real_worker_exit_keeps_broker_control_and_cold_drain[True]` | Worker就绪后5秒内未见原子进程启动记录 |
| `test_codex_transport_hook.py::test_original_approved_action_uses_subclass_transport_hook_without_duplicate_turn` | Run为waiting_reconciliation，未成功 |

整轮结束后，在相同清洁环境、相同代码和期限下单独执行这五项，**5 passed／18.97秒**。此前两项单独诊断也通过。这说明失败未能在单独执行时复现，**不证明根因或本批完全无回归**；不能拼成14,082项全绿。保留原整轮日志/XML及独立诊断，后续单独定位整轮上下文或宿主时序因素。本批不改Coding产品、夹具、期限或原S2门槛，不扩大修复范围。

私有原始日志位于 `/private/tmp/relf-review-fixes-20261022/`，不纳入发行制品。独立差异复审在逐次读取和安装／门禁入口补正后未发现新的可行动缺陷。

## 发行与历史资格

a3 准备提交 `eb62d57` 此前已按授权推送并保留 [skip ci]；没有执行 a3 远端门禁、上传或公开安装。本批修复仅存在于维护源码，原 a2／a3 包不含这些修复，原 a3 发布推进暂停。源码版本暂保留 a3，但不将当前源码当成原候选，也不在本批冻结新发行制品；测试生成的临时 wheel 仅用于验证。下一次交付必须另起唯一版本和独立 manifest／平台验收，不能覆盖同版本包或修改固定 SHA 放行。

原 a2／a3 包、manifest、验收与失败记录保留。原 dev19 所选 S2 18/18、函数指纹和真实模型证据仍只属于各自原制品／环境；本批不重跑或扩大其资格，不关闭完整 M1、R01–R26 或企业目标。

本批复核原 a2 的50项、a3的76项冻结校验均通过。当前维护源码对原a3两包执行固定预检，返回 `source_product_tree_mismatch`，没有生成放行候选；这是预期拒绝，不是 a3 原制品损坏，也不据此放宽门禁。
