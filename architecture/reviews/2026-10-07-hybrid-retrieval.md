# dev19 RAG 组合与扩展审查

2026-10-07。用户要求 review 后继续优化。本轮先复现并修复 dev18 扩展回执的块 ID／定位顺序／范围缺口，再交付智能数据 D2。基线为实际 dev18 wheel，未把旧 HEAD 后全部增量算作本轮，已有工作区内容保持。没有提交、推送或发布。

## 架构与实现

EmbeddingProvider 原接口保留，新增显式 OpenAIEmbeddingProvider 和不可变 EmbeddingResponse，支持 float/index 协议、全输入预检、有界批次、usage 和客户端生命周期。Fusion／Reranker 只提出排名／已有 ID，不能替代正文、来源或知识权威。HybridRetriever 借用同一 Store 与命名分支，结构化并行、有界去重／冲突处理、严格／显式降级以及来源的阶段复核。

保留旧配置，新增 sqlite-hybrid、sqlite-hybrid-http、postgres-qdrant-hybrid；资源接入现有 BuildContext 所有权和逆序关闭。没有装配时的 Embedding 或索引请求；只有显式 initialize 会建远程表／collection。第十六种包内 hybrid 模板提供空语料起步、用户文件摄取、显式索引、离线证据查询及恢复。

默认 HashEmbedding／RRF／保序重排不要求外部服务。TokenOverlapReranker 为可选词法基线；HTTP／自定义异步重排明确 opt-in。字符限制不等于真实 token／费用控制；知识回执不确认向量已就绪。在线语义模型兼容和真实质量必须单独验证。

## 独立最终审查与闭环

一次独立最终审查，无 P1，4 个 P2 均用永久复现测试先失败后修复：

| 问题 | 修复 |
| --- | --- |
| Reranker 保留可变 list，最终来源 await 期间能改成重复／未知 ID | 采用前立即冻结成 tuple，后续只使用原快照 |
| 纯同步融合计算期间来源 TTL 到期，异步重排仍收到过期文本 | 融合后、外部重排前回读当前来源并检查 TTL，阻止派发 |
| 可配置输入／响应界限超出规格 | 强制单文本 32768、每批 262144 字符、响应 8MiB 的绝对界限，只能调小 |
| Factory 接受未知融合权重分支，建库后查询才失败 | 装配 preflight 校验 lexical／vector 名字，分配本地或远程资源前拒绝 |

8 个 review 回归 RED→GREEN；修复后相关本地 104 项通过。早期 TDD 还复现错误 Unicode／timeout 溢出与融合修改重排注册的问题，均已修复。没有第二次审查或未闭环 Important 项。

摄取回执补了 3 个错误 ID／乱序／越界回归，相关 53 项通过，原有效回执和首次 pipeline 重放语义保持。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 首轮全量真实服务 | 1573 passed／477.79s，随后增加 8 个 review 回归 |
| 修复后最终全量 | 1581 passed／343.49s；真实临时 PG／Qdrant／Redis／Temporal 与本地 HTTP，-W error |
| 初期 D2 真实组合与边界 | 106 passed／43.68s，含真实 PostgreSQL/Qdrant 与本地 HTTP fixture |
| 工作区外 dev19 wheel | 363 passed／101.81s |
| 可选 SDK 被屏蔽的安装包 | 298 passed／7 expected skips／14.28s；被屏蔽的实际服务明确跳过 |
| 实际 dev18 → dev19 | native／graph／Team／flat／DAG／嵌套回执与恢复通过；原十五份 starter 字典逐字保持 |
| 原生 Temporal History | dev18 wheel 创建 Run／registry History，dev19 重放、原提交／控制回执及继续执行通过 |
| 包与 API | 90 SDK 模块源码／wheel／sdist／安装目录逐字节一致；221 导出可用；基础 2 依赖／6 extras 保持 |
| 静态与指南 | Ruff lint／format、Git 空白、10 份指南相对链接、CI YAML 与依赖最终复核通过 |

真实远程组合检查原子来源摄取、显式索引、两个分支去重、来源回读、删除后旧向量拒绝和固定引用失效。HTTP fixture 明确使用 HashEmbedding 返回向量，证明协议排序／生命周期；不是语义模型 benchmark。取消排空和借用／owned／失败关闭重试、错误／惰性／Scope／预算／注册漂移均有本地回归。

Python 3.12.7 本机验证；其他声明版本保留现有 CI 矩阵，本轮未做多版本本机认证。CI 新增包外 hybrid 模板与实际远程组合测试。临时 PG/Qdrant/Temporal 在全部核验后关闭。

## 仍需完善

D2 的端口与默认链路已交付，真实语义检索／重排、回答及引用质量未得分。真实模型入口没有配置，仍 not_run／0 调用／model_quality=null；离线业务 fixture 8/8、15 次调用保持为集成证据。

D3 token 上下文、大结果引用、摘要、长期记忆提炼，D4 外部采用和对等 benchmark，及企业 ACL、全局容量、清理迁移、沙箱、远程 stop 管理继续独立交付。本轮没有依据宣布完整 M1、企业可用或能力优于 AgentScope／LangGraph。接口和配置示例见[混合检索指南](../../docs/hybrid-retrieval.md)。
