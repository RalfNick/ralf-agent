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
