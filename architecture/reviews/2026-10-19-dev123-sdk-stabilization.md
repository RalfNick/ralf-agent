# dev123：基础 SDK 适配器一致性与组合验收

日期：2026-10-19。基线为已本地提交的 `746b6b6`／dev122；本批是其后的 dev123 工作区候选。复用已有能力，不新增后端、编排、公共协议或运行依赖。函数指纹专项和 S2 继续后置。

## 变更与扩展边界

六处消费者复用现有 `ports.is_async_callable`：基础 ExecutionEngine 的 drive／wait_for_threads、ToolSource、MCPTransport.request、MemoryPipeline.extractor、ManagedDataContext Artifact，以及 Facts 索引维护的生成／CAS 操作。不再将合法的 `async def __call__` 对象误判为同步组件。

不修改公共判断函数本身、函数身份实现、流式生成器规则、线程桥或具体 vendor 客户端。原组件身份、工具授权、返回值采纳、来源固定、所有权与关闭检查保持；Local／Temporal 仍分别是唯一执行权威。

| 已有组合 | 新行为测试的证据 |
| --- | --- |
| Engine／A2A | 异步 callable 的 drive／排空完成实际任务，owned 服务关闭 |
| ToolSource | 审批暂停后关闭并重开 Local 权威；原提交／重复批准保持回执，实际业务调用一次 |
| MCP | 异步 callable 请求完成发现、固定 Schema 的工具调用与结果返回 |
| 自动记忆 | 异步 callable 提炼器保存有来源的 Facts，重复归并不再次请求模型桩 |
| 上下文／Artifact | 异步 callable 的 put／get 完成真实大结果卸载，模型接收投影，原始值保存在 Artifact |
| Facts 索引维护 | 结构化异步生成端口及原 CAS catalog 完成维护；重复回执不再 Embedding，实际召回可用 |

异步专用端口的负例在调用前拒绝同步 coroutine 工厂。Artifact 原本支持成组同步或异步端口，其负例仅证明同步 put／异步 get 的混合模式拒绝；不声称所有同步 Artifact 返回值均能预先识别。现有 memory_call 等待行为保持。

## 使用文档与门禁

- 连续教程保留同一工单逐步增加 Agent、Session、RAG、Facts、Workflow 的路径；恢复指南增加按现象／错误码定位的表格，使用已有命令，不新增诊断接口。
- 扩展指南明确异步 callable 的适用范围，以及 Artifact、流式、线程桥与 vendor 的边界。不把“可替换”解释为任意 Facade 或数据库客户端均可直接替换。
- CI 增加安装后执行本批组合测试的一步，复用本 job 的 session-contracts/tests；已核对涉及的测试路径和 job 内复制前提。没有新 CI 服务或平台。

## 验证记录

环境：macOS ARM64、Python 3.12.7。以下分别取证，有重叠，不相加为唯一用例数或全量通过：

- 新组合测试 RED：**6 failed／5 passed**，对应六处异步形状误拒绝；最小修复后 **11 passed**。
- 最终受影响源码：21 模块 **379 passed，零失败／错误／跳过**，JUnit 129.613 秒。包含审批／Session／上下文、RAG／Facts、Workflow／Team 和绑定恢复。
- checkout 外隔离安装：9 模块 **160 passed，零失败／错误／跳过**，JUnit 15.119 秒；不含 src/，清空 PYTHONPATH，依赖复用本机已安装库，无下载。
- 同一安装环境独立执行 CI 新适配器步骤：**11 passed，零失败／错误／跳过**。这是本机执行相同命令，未宣称 GitHub Actions 已运行。
- 安装 starter 的正常审批与业务提交后崩溃两例均完成跨进程恢复，各业务写入一次。安装连续教程覆盖五阶段、原命令重提和 Session 第二轮读取；仅为内部演练，未验收外部独立采用。
- 包元数据、运行时与 CLI 版本均为 `0.1.0.dev123`，pip check 通过；442 个产品文件的源码／wheel／安装结果一致。最终源码包另核对这些产品、测试和连续示例输入。
- 产品修复的独立只读审查未发现 P1／P2；其新模块 11 项和既有模块 85 项通过。Artifact 负例的证据口径已按上述范围限定。文档收口审查另发现 Session 忙碌与绑定错误指引混同（P2）及 CI 数量口径不明（P3），已分别拆开恢复动作、删除固定数量；CI 新步骤依赖和本地文档链接成立。
- 全仓 Ruff、1,384 文件格式检查与 Git 空白检查通过。

## 所选实际服务

对**同一已安装 wheel**运行现有三个模块：test_postgres_effect_retention、test_temporal_retention_service、test_a2a_temporal_scope_audit_service。结果 **24 passed，零失败／错误／跳过**，JUnit 39.434 秒。

使用缓存的 PostgreSQL 16 镜像和 Temporal CLI 1.9.1／Server 1.32.0；新建本批独占服务，不下载、不调用真实模型。覆盖原封存树下冗余效果证据清理、实际 DELETE 后校验失败回滚、冷 SDK 原回执、原 History 重放、HTTP 双身份越权拒绝、脱敏审计以及审批／未知写恢复。具体断言沿用原测试，不增加服务功能或降低期限。

测试 HTTP 宿主与 Worker 由原测试关闭；外层 Temporal 已 shutdown，PostgreSQL 已停止并删除本批自有容器，旧资源未触碰。shutdown.json 随本地制品保存；连接与测试口令仅留在私有临时目录，不进入制品或仓库。这是所选门禁的安装后真实服务证据，不是全部分布式组合、生产灾备或新历史兼容资格。

## 推荐制品与未验收范围

独立目录 `dist/basic-sdk-dev123/` 不覆盖 dev122／dev121。已测试 wheel 的 SHA256：`240ab4e43be5f677ec59934e1a40553236609d7b7156bdf1ff276482b8efc79d`。delivery.json、产品输入清单和 SHA256SUMS 定位精确制品及验证记录。最终 sdist 在文档收口后单独构建，保留已测试 wheel，不重新替换。文件校验用于制品定位，不是函数指纹资格验证。

未运行全量套件、真实模型质量评测、函数指纹专项、S2 或额外旧 History 兼容专项。既有服务中的原任务重放不扩称全部历史兼容。原 S2 失败、剩余矩阵、完整第三阶段和长期 R01–R26 状态保持。仅本地提交，不推送或公开发布。
