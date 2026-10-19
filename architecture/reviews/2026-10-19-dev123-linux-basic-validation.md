# dev123：Linux ARM64 基础 SDK 容器验证

日期：2026-10-19。使用本地提交 `c4fe423` 对应的精确 dev123 安装包，只补验证证据，不修改产品或重建制品。函数指纹专项、S2 和原失败继续后置；不推送。

## 环境和方法

- Mac 上 Docker Engine 29.0.1 的 Linux ARM64 容器，官方 Python Debian Bookworm slim 镜像；具体 image ID／RepoDigest 和依赖记录随证据保留。
- 三版本按 3.11 → 3.12 → 3.13 串行执行。每容器 `NanoCpus=2000000000`、Memory／MemorySwap 均为 2147483648；Linux cgroup 同时确认 `cpu.max=200000 100000`、`memory.max=2147483648`、`memory.swap.max=0`。即 2 CPU、2 GiB、无额外 swap。
- wheel SHA256：`240ab4e43be5f677ec59934e1a40553236609d7b7156bdf1ff276482b8efc79d`；原 sdist SHA256：`f4cc62d6fe6f97cdbd33d74baad992e5908c84434883ac42b9c9b5dfbb744e48`。原 `dist/basic-sdk-dev123/` 不覆盖。
- 干净容器先安装最小 SDK 并执行 pip check、包／CLI 版本及 442 个产品文件核对；不安装 Temporal、Redis、PostgreSQL、向量服务或模型运行库。再安装 pytest，记录实际解析依赖。
- 测试仅从原 sdist 提取 tests 和连续教程应用；不提供 src、Git、宿主凭据或 Docker socket。安装后实际断开 bridge 网络；测试数据库和进程在容器 Linux 文件系统中运行。
- 固定 18 模块，共收集 309 项，显式排除一项 Temporal 状态机测试后执行 308 项；三版本的完整用例 ID 清单一致。使用 `-W error`、关闭外部 pytest 插件和缓存，不屏蔽资源警告；不是全量回归。

## 主矩阵结果

| Python | 通过 | 失败 | 错误／跳过 | pytest 秒数 | 容器内存内核高水位 | 每秒采样 CPU 最大值 |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| 3.11.17 | 306 | 2 | 0／0 | 43.384 | 285.46 MiB | 99.54% |
| 3.12.15 | 308 | 0 | 0／0 | 42.486 | 277.77 MiB | 99.56% |
| 3.13.16 | 307 | 1 | 0／0 | 42.138 | 282.70 MiB | 99.53% |

CPU 的 100% 表示一个逻辑核；这里是约一秒间隔的采样最大值，不能当作瞬时峰值。内存高水位来自 cgroup，包含安装、收集、测试、已执行的 starter 及计入容器的文件缓存；各阶段另有采样数据。主矩阵各容器均无 OOM／OOM kill。

数据只描述本批容器，不包含 Docker Desktop 虚拟机、其他容器和 macOS 的整体占用；镜像下载发生在受限容器外。ARM64 Debian 容器结果不能外推 AMD64、原生 Ubuntu、S2 或生产性能。

## 失败证据

### Python 3.11：并行恢复中的 Artifact 调用次数

原 `test_actual_composite_process_death_restores_without_repeating_effects` 的两个 parallel 场景失败，分别位于 context_preparation_response_received 和 context_preparation_adopted 窗口。恢复进程正常退出，Run 均 succeeded，tool=8、summary=4，Artifact.put 调用次数为 2，而测试要求 1。

已从本批自有停止容器复制两项原数据库：各有 8 个不同 effect_key，原 effects 表各键一条；Artifact 库各只有一条内容相同的产物记录。因此现有证据不能直接解释成业务重复写入或两份产物。API 尝试次数与恢复契约的关系仍需核对，原断言失败保留，不改测试获得通过。

### Python 3.13：未关闭 SQLite 连接警告

原 `test_missing_entire_parallel_frame_rejects_surviving_model_evidence` 失败，pytest 捕获到 12 个 SQLite Connection 的 ResourceWarning 并聚合为 PytestUnraisableExceptionWarning。主日志的回收触发位置不是可靠的连接创建位置；需要独立分配追踪归因，不直接归咎于该测试中的框架调用。

独立 `tracemalloc=5` 诊断已确认 12 个连接全部创建于 `tests/test_composite_data_context.py:223`：测试父进程使用 `with sqlite3.connect(...)` 管理事务但未关闭连接，警告在后续 GC 时出现。归因为测试夹具连接生命周期问题；没有屏蔽警告或更改原 wheel，主矩阵的失败仍保留。

## 独立诊断与 starter

主矩阵中 3.12 的原 starter 正常审批与业务提交后崩溃两例均完成跨进程恢复，各业务写入一次。3.11／3.13 的 starter 被主测试失败阻断，安排独立补验，结果分别记录，不改写主矩阵。

补验均使用原镜像和相同 wheel、2 CPU／2 GiB、安装后断网，并且串行执行：

- 3.11 只重跑原两个失败 node：**2 failed／零错误／零跳过**，4.133 秒，仍是 Artifact.put 数量断言；随后两个 starter 均通过，各业务写入一次。
- 3.13 只对原 composite_data_context 模块启用分配追踪：**20 passed／1 failed／零错误／零跳过**，137.762 秒，明确上述 12 个分配来源；随后两个 starter 均通过，各业务写入一次。
- 三版本合计各有两条 starter 的独立通过证据；3.12 来自主矩阵，3.11／3.13 来自补验。不据此把主矩阵失败改写为通过。
- 包含这些诊断在内，所有实际测试容器的内核内存高水位最大为 **286.60 MiB**，仍无 OOM。追踪运行的时间和采样单独保留，不混作无追踪性能结果。

补验顶层原 scope.json 沿用了主矩阵模块模板，3.11 completion 的 purpose 也保留了旧诊断文字。原件不改写，汇总以各版本实际 config／collection／JUnit 为准，并在 `effective-scopes.json` 显式记录有效选择；补验不具备 18 模块覆盖。

## 验证脚本与边界

首轮三个环境均完成最小安装及产品核对，但验证脚本依赖了 pytest 的收集路径格式：`-c /dev/null` 输出缺少文件路径，计数解析失败，且预期 deselection 未生效。该轮未运行业务测试。固定 `--rootdir=/work/checks` 后在新目录重跑，保留原记录；没有修改 wheel、测试断言或产品期限。

独立 3.11 诊断的首次准备另将完整 node ID 当作文件路径，未进入测试；修正验证脚本取文件部分后单独补齐，仍保留原准备失败。这些是验证设施失败，不合并为产品用例失败，也不隐去。

独立只读复核已核对安装输入、308 node 一致性、实际资源上限、严格串行、资源表和两个失败类型。复核提出的补验范围元数据与结果归并问题已按上文明确，不额外改变产品或测试门槛。

本轮**不能将三版本 Linux 基础 SDK 的完整指定清单标为通过**。独立证据目录为 `dist/linux-dev123-arm64-20261019/`：verification.json、effective-scopes.json、各原始日志／JUnit／资源采样、精确镜像／依赖、脚本及两项失败数据库均已保留；SHA256SUMS 定位文件。原 dev123 制品及长期阶段结论保持。

本批共创建 9 个测试容器；原宿主脚本先确认各容器停止，其中成功主矩阵容器已移除，其余容器在归档后仅按原 ID／独占标签清理，结果见 `post-archive-cleanup.json`。不触碰旧资源，官方镜像保留为缓存。本轮无真实模型或外部业务服务调用、无产品改动、无新版本、无推送或公开发布。
