# Codex Runner 基础组件验收

日期：2026-10-14；基线 `7e530f8`／dev99；交付 dev100，仅本地提交。

## 本批成果

首个 Codex App Server 通信与持久启动证据已实现：固定 0.144.4 生成 Schema 子集，
有界 POSIX stdio 相关请求／原生事件，以及独占 SQLite Thread／Turn 意图和句柄日志。
提交许可先落盘，仅首次阶段推进返回许可；实际接受 Turn 后丢失回执，恢复不产生第二个
Turn。取消意图和空 interrupt 回执分开保留，不生成 Run 终态。

这是第二阶段 R13 的基础子集，**完整 Runner 未交付**。没有 Agent 绑定、配置工厂或
真实 Codex 任务；受限 read/write/test、产物、Local／Temporal 版本化停止门禁及
History／Worker 验收继续开放。Journal 不是执行权威，Harness 不执行新 I/O。

## 验证

- 最终受影响源码四个测试模块：127 passed，零跳过，15.36 秒。
- 固定 wheel 的独立 Python 3.12.7 环境，checkout 外复制原测试，`-I -B`／importlib：
  127 passed，零跳过，16.32 秒；子进程使用同一安装解释器。
- Ruff 检查、八文件格式检查、Git 空白检查通过。原始七份 Schema digest 固定，
  重现输出逐字节一致；未知输入在写输出前拒绝。
- wheel Schema／NOTICE 与 sdist 提取工具检查通过。原有 351 个产品模块逐字节保留，
  新增三个，共 354 个；引擎、默认组件、执行库 schema 与 Temporal Activity 未改。
  这不是重新执行旧 Run／真实 Temporal 兼容测试。

最终 wheel SHA-256：
`d2cf7c32757f2e2efe42c109e109c3834e1ef61cea931863b3dc3de39f1e9b48`。
失败候选、格式固定前候选及日志分别保留；只使用最终固定 wheel 的安装结果。

没有重跑整个框架回归。dev99 的 8397／617 为上一阶段记录，不计入本批结果。
完整回归、部署与兼容门槛在第二阶段集成时执行。

## 独立审查与修复

一次新审查者发现 P1：异步 subprocess 创建尚未完成管道接入时，取消／循环退出可能
丢失真实 PID，退出挂起且子进程心跳继续。作者复现后改为同步 `Popen` 先取得 PID／原始
管道，再接入公开 asyncio 管道接口。取消保持清理所有者，先终止原进程组再排空接入，
信号拒绝保留 PID 并返回可重试关闭未完成。

同一审查者使用原复现及直接循环退出两条独立进程复验，确认 leader 回收、子进程心跳
停止，关闭 P1；四模块 127 项复验通过，没有其他阻塞问题。此前异常窗口及真实 watchdog
记录保留。清理证明仅限本地进程组，不认证逃逸后继、远端效果或 native Turn 全部停止。

## 下一门槛

本地 Docker 已实际启动作为后续验证环境；这不构成 Coding 隔离通过。Linux 原生 CLI、
容器命名空间、网络／文件／凭据隔离和后继停止仍按实际探针验收。协议形状不证明对端
版本或有效权限，普通 workspaceWrite／cwd 不能替代受限 Profile。

真实模型、本地语义模型和四条参考质量结果没有重跑；dev99 阶段证据保持。全 R01–R26、
完整 M1／企业治理和外部采用继续开放。见[使用边界](../../docs/codex-runner-foundation.md)
与[后续计划](../../docs/superpowers/plans/2026-10-13-codex-runner-foundation.md)。
