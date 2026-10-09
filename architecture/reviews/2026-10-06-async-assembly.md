# dev13 异步装配与资源生命周期审查

日期：2026-10-06。范围：保留当前 dev12 契约修复，增加异步组件创建与 owned 客户端清理。依据[设计](../../docs/superpowers/specs/2026-10-06-async-assembly-design.md)与[实施计划](../../docs/superpowers/plans/2026-10-06-async-assembly.md)。

## 架构与实际交付

ComponentRegistry.register_async 与 RuntimeBuilder.abuild 为 Provider、记忆、知识、工具等可注册组件提供显式异步工厂；validator 保持同步。同步 build 不隐式等待，在创建 Store 前拒绝异步选择。BuildContext.own/own_async 处理显式归属的客户端，借用资源仍由应用负责。

RuntimeInstance 的同步接口保持，增加 async with/aclose。生命周期抽到 runtime_lifecycle.py，与注册、配置和执行事务分离；原 runtime_builder 的公开导入路径保留。正常 Engine 先排空真实线程、完成同步 close，再逆序清理附属客户端。失败与取消保留实际清理 Task/资源；重复关闭不重复清理已完成资源。

循环亲和性在 drive/排空/关闭前检查，包括缓存的方法；异步关闭开始后禁止新公开操作。Store/Coordinator 与 LocalEngine 权威仍同步，不能把客户端清理接口当作分布式执行后端。local-4、Schema/ExecutionStore v1、合法请求身份和默认声明保持。

包内 async starter 使用真实 httpx.AsyncClient 与离线 MockTransport。可编辑 TOML Profile，旧任务解析保留的原 Profile，重提返回原回执；演示没有网络请求或模型费用。模板使用应用 async 入口，尚无通用 AsyncProfiledEngine/CLI 异步运行路由。

## 一次独立审查与修复

由独立只读 gpt-6-astra/high 执行，未修改源文件；发现两个 P2，均额外复现后一次修复，没有请求第二轮审查。

| 问题 | 修复与证据 |
| --- | --- |
| 被拒绝的部分 Engine 有有效 close，但无效同步 wait_for_threads 阻止清理，真实租约永久保留 | 构造失败句柄标记为部分 owner，直接通过同步 close 的权威门槛清理；正常实例仍要求 async 排空并返回 None。缺失/无效排空两种真实 LocalEngine 包装均释放租约和客户端 |
| 外层 aclose 取消后，资源 aclose 重入所属 Runtime，等待自己的保留 Task 而死锁 | Runtime 与 BuildContext 在等待前识别当前 Task 的资源归属并拒绝自重入；两种入口均只执行一次实际清理，后续关闭能完成 |

两项新增复现首次运行为 2 failed/1 passed；修复后针对性组合 113 passed。回归继续覆盖外层取消、双重构造取消、无效完成值、失败重试、缓存调用、真实同步线程、错误事件循环及默认兼容。

## 验证证据

- Python 3.12/macOS，项目虚拟环境，`pytest -q -W error`：**1018 passed in 88.78s**；比修复后的 dev12 新增 28 项。审查前 1015 项通过，审查后的三个用例增加了被拒绝 Engine 与两种自重入入口覆盖。
- 针对性组合：**113 passed in 13.71s**。初始 system-Python 的两个生成应用失败来自子解释器缺少安装包，随后在项目环境及真实 wheel 下验证。
- 仓库外实际 wheel 的生命周期/契约测试：**92 passed in 1.33s**，无仓库 PYTHONPATH。真实 dev12→dev13 原生/v3 任务保留恢复前记录、原回执、合法 Session 和节点诊断。
- 实际 dev13 安装包验证 async starter 的执行、重放、重启、真实客户端关闭；全部 **118** 公共名称可导入，原七个 starter 字典逐项内容相同。
- wheel/sdist 使用既有依赖、无隔离构建；**39 个 SDK 模块**与源码、wheel、sdist 和安装副本逐字节一致。项目 editable 版本/元数据均为 dev13，pip check 通过。
- Ruff check、format --check 与 Git diff --check 通过；**53** 文档、**297** 本地链接、**28** Python／**36** shell／**2** TOML 代码块通过链接/语法检查。离线运行时评测 **3/3** 通过，每个案例业务写入一次；这些结果不属于真实 AI 任务质量基线。

## 明确未交付

异步生命周期减少远程适配器的接入障碍，但没有提供 Redis/PostgreSQL/托管向量数据库实现。动态 Plan、多 Agent/ChildRun、流式数据链路、沙箱、分布式权威、真实模型与竞品对等 benchmark 仍是独立工作。完整 M1、AgentScope/LangChain/LangGraph 能力对齐和特有能力优势仍按原验收目标判断。本轮未运行 Python 3.11/3.13 CI，也未推送或发布预览包。
