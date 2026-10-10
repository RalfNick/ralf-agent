# dev48 H3 HTTP 重排验收

日期：2026-10-10；基线 8c606d7／dev47。沿原能力清单 R17，新增显式 HTTP 适配器，
复用 AsyncReranker／HybridRetriever／KnowledgeStore／Profile 工厂，不新增执行权威。

协议以 [Cohere v2 官方文档](https://docs.cohere.com/v2/reference/rerank)为依据，
不设置商业端点／模型默认，不承诺所有供应商协议兼容。原保序／词项重排及原推荐配置保持。
新增 RerankResponse 只返回原 IDs／分数及明确 search_units；费用缺失未知，不计入执行额度。

已验证：单请求／无重定向／响应上限、索引／数量／分数／计量、UTF-8 输入预检；
并发／取消／实际操作关闭、借用／拥有、失败关闭重试和实现／客户端漂移拒绝。
显式异步 hash+HTTP／semantic+HTTP 配置、JSON／TOML、失败装配 owned 清理。
独立审查发现真实 HTTPX 在传输／响应流释放前设置 closed 标志的两个关闭漏洞。
已以真实 transport 关闭失败、响应读取中取消后全任务取消做 RED→GREEN，
新增独立传输和响应流完成记录，失败／取消保留资源供 `aclose` 重试，借用客户端仍不关闭。
同时验证流关闭异常及 owned 关闭取消／并发关闭；不以 HTTPX 标志作为实际释放证据。
真实回环 HTTP 服务向原 Agent 提供排序证据，来源变化阻止采纳，分支 degrade 不吞重排错误。
真实进程在 model_response_recorded 后退出，恢复审批不重复该 Action 的重排／模型调用；
完成后共2个模型调用、2次重排、1次业务写入。Temporal 原 Context→Model 纯协议接入。

最终专项：项目 `.venv/bin/python` 执行新协议、配置、实际 HTTP／进程、Temporal 端口及原组合，
131 passed；安装到独立目录、在 checkout 外运行 103 项契约通过。
dev47↔dev48 六类默认组合共12次实际审批恢复，准确 Profile／Context／Manifest 身份保持；
semantic-knowledge 共2次双向身份／已接受 Run 恢复（不调用 HTTP），旧 wheel 在建库前拒绝新工厂。
wheel／sdist 使用 `python -m build --no-isolation` 成功，Ruff／格式／空白检查通过。
全量 `.venv/bin/python -m pytest -q`：**3019 passed／92 skipped，522.12秒**。
跳过项仍需相应可选服务／环境验收。本轮新增47项用例。
最终包六个适配器／工厂源文件与当前源码逐字节一致；290个本地文档链接目标存在。
系统 Python 的无 editable 子进程运行因导入失败弃用，
已定位原因，改用仓库 `.venv`，13个受影响的原有 starter／恢复专项通过。

## 决策与局限

- 按用户持续开发授权沿当前分支实现并最终本地提交，省去重复确认；错误成本是共享分支历史。
- 只支持显式 indexed-results HTTP 协议；生成式排序与本地推理后续适配，成本是其他协议需要额外适配器。
- 提交前审查完整工作差异和未跟踪文件；错误成本是遗漏文件，以明确清单及构建安装验证补充。
- owned HTTP 显式持有可重试传输，禁用环境代理／证书覆盖；错误成本是依赖宿主代理／CA的部署需注入 SDK 自管客户端。
- 本轮不判断真实语义／答案质量及全部供应商兼容；错误成本是模型相关性／协议差异仍需独立评测。
- 本轮不判断真实 PG／Qdrant／Temporal 部署；错误成本是部署环境问题仍未知。
- 全量／构建／安装／兼容验收由作者执行，独立审查未复认证；错误成本是作者验证差错，记录实际命令和结果。
- 不审查已移除的解包 sdist 重复目录；错误成本是生成包差异，实际构建与安装单独验证。
- 重排准备沿原检索 I/O 链路，无自动重试，不增加第二套运行账本；准备中断可能重复付费调用。

独立审查两项 Important 均按用户实际影响保留等级，完成一次修复及 RED→GREEN；没有延后 Minor。

本轮不读取历史密钥、不调用真实生成／Embedding／Rerank 模型、不重跑远程数据库／Temporal 服务。
语义／引用质量、全库语义 Facts、索引治理、计费硬上限、H4 隔离与 H5 企业治理仍未交付。
