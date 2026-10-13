# dev104：Runner 绑定、声明装配和关闭归属

本批将有限 Local Coding 委托接入每 Agent 可选 Runner 绑定和 JSON／TOML 工厂。
支持根级 Agent 与顺序 Workflow，一个 Profile 可声明 1–16 个独立资源；原 Harness
只提出方案，原 Local Engine／Run／Action 继续拥有审批、预算、阶段准入和终态。
dev99 四条参考业务链路冻结，不重复下载模型或扩大既有质量结论。
完整 R01–R26、Coding G1–G8 和第二阶段仍开放。

## 实现与范围

- 可选 `runner` 只在显式声明时进入 Descriptor 3；缺省保留 Descriptor 1／2 原字节。
  联合发布使用 `local-bindings-18`／`runner_binding_protocol=1`。`inherit` 从有效工具
  中选唯一实际资源；`ref` 必须与已授予工具的原对象一致；`disabled` 拒绝有效 Coding
  工具。角色不能扩大工具权限，不能接受资源 selector。
- `tools/codex-coding` 异步工厂先纯校验全部声明与引用，再检查私有物理路径，随后
  按 journal／Runner 登记 owned 资源。`runner/registered-tool` 只借用原工具资源。
  不自动发现 Docker、下载镜像、注入认证或启动容器。默认 Registry 的 POSIX 导入保持
  惰性；借用自定义工具可同步装配，内置拥有资源须 `abuild`／`aclose`。
- 原 Action 的 manifest、attempt、reservation、审批及请求固定到实际 step。
  发布／冷恢复复核原生命周期方法与具体物理依赖；回执丢失仍不得追加 Turn。
- owned 清理在第一次 await 前隔离原 Engine，阻止直接或借用客户端继续 submit／drive
  及新原生业务 grant；只有原权威接收既有停止证据。多个待停止资源先全部确认，再
  逆序清理 Runner／日志、关闭 Engine。停止失败、清理故障或调用方取消保留原
  Coordinator／账本／重试 handle，不能用替代 Run 或资源跳过停止。
- 图／Team／动态／嵌套与 Temporal Runner 尚未接入。原 Temporal 入口及直接模型
  Activity 均拒绝显式 Runner descriptor，不静默忽略 optional role。

## 开发与独立审查

绑定、声明工厂、Local 生命周期三个独立切片并行开发，root 统一集成和固定版本。
作者保留有效 RED：绑定／选择／聚合、工厂纯预检与物理别名、关闭隔离、具体依赖
漂移及 Temporal 无 I/O 拒绝；故障与恢复断言未通过放宽产品 deadline 修正。

独立审查在同一上下文复验具体物理替换和 original Engine 清理窗口。最终正确
`.venv` 环境中新增五模块 101 passed，原 Runner／默认兼容 26 passed；另外两个
真实 SQLite／实际子进程、确定性原生 peer 的双资源冷恢复探针通过。第一资源完成
后重建全部对象，再恢复第二资源；正常完成和 Turn 回执丢失后冷取消均保留原
request／attempt，每资源恰好一次 Thread／Turn 提交。该结果为协议与生命周期
证据，不是实际原生模型质量或任意下游恰好执行一次保证。

一次集成检查 1 failed／172 passed 为旧 bound-Agent 断言期待 `root unbound`。
新契约在缺少显式 Runner 时拒绝 `explicit Runner binding`；只更新该错误匹配，
保留 Team／Dynamic 原拒绝和零模型调用断言。独立审查确认，恢复相关三模块
57 passed；没有产品修改。审查者最早使用 system Python 的导入失败及私有探针
fixture 导入启动错误保留，最终验收使用 repo `.venv` 或固定 wheel 独立安装。

## 最终验证登记

私有证据目录：`/private/tmp/ralf-agent-dev104-root`。
独立审查：`/private/tmp/ralf-agent-dev104-independent-review.md`。

| 检查 | 最终证据 |
| --- | --- |
| 完整源码集成 | 最终输入覆盖全部 561 测试模块，8892 passed／634 配置依赖跳过。首次完整分片 8890 passed／2 failed／634 skipped；原 Runner 模块在静止环境 24 passed，其他未改模块逐项 SHA-256 核对后复用 |
| 固定 wheel 安装 | checkout 外 792 passed／零跳过，109.22 秒；只复制测试／工具／JSON，不复制 Python 产品源码；SDK 与安装 metadata 均为 dev104 |
| 旧 Run 兼容 | 源码与独立安装各 9 个同数据库阶段通过：dev103↔104 普通 Run 原 manifest／definition／release／Schema 1 相同；新 schema3／local-bindings-18／Schema14 原 Run 被旧103在零模型 I/O前拒绝，随后由104续跑原 Run |
| 文档实例 | SDK／JSON／TOML Profile 身份一致；固定安装的绑定 Agent 与两资源 sequence 成功。离线 Provider 未请求 Coding 工具；不作为原生业务质量 |
| 制品一致性 | 364 产品模块源码／wheel／安装一致，旧352模块字节保持、10旧模块改变、2新模块；三份 Codex JSON 及原生 Runner／环境／协议／日志／委托工具保持 dev103 字节。最终 sdist 另核对全部产品／测试／本批文档 |
| 静态与独立审查 | Ruff／1001 Python 文件格式／Git 空白通过；同一审查者复验实际资源与关闭隔离、原恢复探针、旧版本和完整回归故障证据，无支持范围内遗留阻断项 |

固定 wheel SHA-256：`7695fab4a9ae90880dbd0d3471d315f2dde7d119ab6ac751e8b80c868aef33e8`。
最终统计与每项输入哈希保留在 `final-check.json`／`full-manifest.json`。

首次完整分片的两项失败均位于原 `test_codex_runner.py` 的 late_auth_close／empty。
保留 SQLite 和启动日志证明两例没有 Thread／Turn 准入或原生业务提交；原 attempt、
unknown 效果和原容器 fence 保持。第一例在准备阶段结束；第二例已有 prepare 但日志仅
intent，最初异常被清理失败遮蔽，无法断言唯一的超时位置。独立审查认为证据与提交前
调度／deadline 路径相符，未发现新产品缺陷。保持原 1.5 秒 deadline、产品及夹具字节，
全量进程结束后只重跑原受影响模块得到 24 passed；未删除失败或重复完整回归以取最好结果。


实际服务配置跳过不作为服务通过。本批没有调用真实模型或原生认证、没有启动真实
Docker／PG／Temporal 服务。原生控制、容器停止／移除、旧 start argv 失效与同资源
冷 tombstone 的有限实际证据沿用 dev103；对应原生实现与三份包内 JSON 按 SHA-256
确认未变，不能将其合并成新的业务 Coding 或 Temporal History 验收。

## 关闭与剩余门槛

本批关闭有限 Local G1 的绑定／声明／资源所有权入口；原 root／sequence 的恢复和
原执行权威保持。完整 G1 的旧 Worker／全部组合、G3／G5 的复杂父级及 Temporal
History／PG 采纳、G7 专用原生认证、G8 真实重复任务仍开放。下一批先沿原父子 Run
协议补复杂 Local 组合，不创建第二套调度或状态机，再实现独立 Temporal 准入。

使用方法及边界见[配置指南](../../docs/coding-profiles.md)、
[原 Action 指南](../../docs/local-coding-delegation.md)和
[完整委托门槛](../specs/delegated-coding-action-contract.md)。
