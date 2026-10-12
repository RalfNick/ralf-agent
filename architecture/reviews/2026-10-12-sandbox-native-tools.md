# Dev83 原生 Sandbox 候选验收

本批沿 R13/H4 实现可替换 SandboxProvider、原生有界 DTO、显式本地 Docker
默认、原 SandboxToolSource、异步声明和每 Agent sandbox 绑定。原 Engine／
Temporal History 保持唯一执行权威；原生 FD 租约仅控制一个容器调用的占用。
不增加业务调度器，不把任意自定义 Python Provider 的声明当成隔离证明。

已完成源码任务范围：

- 原生默认十二项真实隔离／生命周期及创建、启动回包丢失测试。
- 原工具通道和默认 Profile 两项真实验收。
- Local 六类和 Temporal 六类审批、重启及已采纳结果恢复，History 回放通过。
- Local／Temporal 单 Agent 取消后保留实际执行，分别维持 Coordinator 和 History
  quiescence；真实停止后才能关闭。冷派发进程实际 SIGKILL、等待退出后查询同一
  运行容器；未启动孤儿容器保留 created 证据，再执行原请求的首次启动。
- Task4 相关 164 项契约回归通过；合并真实组 29 项全部通过，新增 created 场景
  单独通过。重复组不相加当作独立覆盖率。

当前为候选，最终独立审查、全量回归、固定 core／SDK 安装、安装后真实服务、
旧82双向兼容与 Worker 拒绝、22 模板、源码／wheel／sdist 一致门槛尚待完成。
本文件随后按实际结果更新，不据接口或跳过测试宣布能力完成。

默认限制 Linux Docker、local Unix socket、不可变本地镜像、非 root、无网络、
只读 root、无宿主挂载、临时 tmpfs 和有限内存／CPU／PID／并发／输出。
源版本、服务和物理资源固定；model 只能传 argv／timeout。
异常关闭保留实际所有权，类型化失败不会确认业务效果成功。

开放范围：远端沙箱、持久共享工作区、Artifact 传输、外部 Coding Runner、
租约保留治理、完整 R01–R26、真实模型质量与 AgentScope 对等采用验收。
产品不启动 daemon、不拉取镜像；测试仅显式准备本地镜像和本任务资源。
没有使用模型凭据、调用付费模型、推送或发布远端。

详细操作见[指南](../../docs/sandbox.md)，设计与任务边界见
[设计](../../docs/superpowers/specs/2026-10-12-sandbox-native-tools-design.md)和
[计划](../../docs/superpowers/plans/2026-10-12-sandbox-native-tools.md)。

## 独立审查与统一修复

唯一最终只读审查覆盖 d9b5f1a..70582b1。所有发现和八项未处理项在实现修复前
逐项重定级；六项 Important 统一修复，没有启动第二次审查。有效失败复现包括
十二项接口／线程／固定身份回归和一项真实容器误停止；另补拒绝、控制接收者
漂移及并行跨循环回归。修复后相关230项通过（6.61s），真实源码31项通过
（61.55s，零跳过）。这些阶段证据仍需后续完整发布门槛。

| 发现 | 结论与修复 |
| --- | --- |
| I1 未决原生责任提前结束 | Source 向原 ambient ToolExecutionOwner 保留桥接占用；异常／惰性／无效结果必须等待真正停止，停止证据后先释放桥接再排空原线程组 |
| I2 重复 Source 误停止其他调用 | 明确 SandboxExecutionRejected 的 exact bool 未启动契约；默认容量／重复调用／FD租约拒绝撤销未获得的责任，未知派发继续保留 |
| I3 创建回执异常丢失占用 | 在 create 派发前记录原名未知责任；异常回执或暂时查询失败后保留实际线程、槽和FD租约，直到原名身份验证及清理完成 |
| I4 请求投影钩子绕过摘要 | 从原始有界 DTO 使用类方法快照，实际argv和标签摘要来自同一请求 |
| I5 授权列表与身份不一致 | 每次授权／I/O前校验普通 Scope 列表与固定快照一致 |
| I6 控制实现可漂移 | 固定 DockerControl、日志解码和NativeSandboxLease实现，以及实际控制接收者；变更前置拒绝 |

两项 Minor 明确延期：M1 常规CI的Temporal作业尚未接入真实Sandbox组合；本地及
安装后真实服务验收单独执行。M2 Docker info 缺少ServerVersion时仍为KeyError；
拒绝及客户端清理正确，错误类型一致性留后续修复。本统一修复不处理Minor。

## 未处理项的裁决与代价

1. **自定义Provider可以伪造隔离／停止。** 替换端口由可信宿主提供，接口不能认证
   任意Python实现；无效返回已观察到的未决责任按I1保留。代价是合法外形的谎报
   仍需要适配器真实验收，不能据端口声明给出隔离保证。
2. **恶意宿主／daemon／同UID主动替换租约路径或内核逃逸。** 此profile不提供
   管理员或内核漏洞对抗认证；普通Scope和实现漂移已修复。代价是不能承诺防恶意
   宿主或容器逃逸。
3. **同Source并行跨活跃循环。** 明确拒绝；结束原循环后支持关闭恢复，顺序循环
   使用不被当成并行共享。代价是跨循环共享需独立Source或统一宿主。
4. **冷恢复期间累计timeout。** 当前调用／恢复观察使用相对窗口，原生离线期间
   不保证自动停止；业务绝对deadline由原执行治理处理。代价是离线会额外消耗资源，
   原生watchdog仍开放。
5. **control_timeout为整个HTTP绝对上限。** 实际是httpx阶段／无进展超时并另有
   字节限制。代价是持续慢速响应可能长期占线程，关闭保留责任并需重试；绝对
   控制deadline尚未交付。
6. **容器删除后永久exactly-once。** 已采纳结果归原Engine／History；未采纳的
   read_only结果可重试。代价是既有原生调用去重不能推导所有故障窗口永久一次。
7. **租约GC／远程Sandbox／持久工作区／Artifact传输。** 继续列为R13/H4开放项。
   代价是长期保留容量和其他执行环境尚未由本子集解决。
8. **候选全量／安装／旧版门槛。** 修复后必须重新执行固定源码的全部验收；
   候选测试不替代最终成绩。代价是门槛缺失时只能保持候选状态。

旧82Worker的新协议拒绝发生在Workflow构造阶段：History记录
WorkflowTaskFailed，没有可查询RALF状态，且任何Activity／模型／工具都未派发。
需要兼容Worker接管或操作员处理，不能把此拒绝伪报为终态failed Run。
