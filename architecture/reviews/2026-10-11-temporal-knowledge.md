# dev59 Temporal Knowledge 绑定验收

基线3a2408b/dev58。用户授权持续完成能力清单，仅本地提交，不推送。
范围为原 Context History 的 scoped Knowledge；完整 R01–R26/H1–H5 继续开放。

## 实现与审查

KnowledgeBindingResource namespace allowlist 与每 Agent inherit/ref/disabled，原子树投影覆盖实际 Agent。
新增 opt-in knowledge_protocol=1；具体 namespace 与原资源写入 effective manifest。
纯 source adoption 固定 Scope／namespace／版本／文本摘要，普通与 managed 保持 Facts/Knowledge 分类。
原生组合树、方法、实际 SQLite／PG 连接／地址及 HTTP 客户端固定；最后来源 await 在 admission 前。
旧 raw/global 发布不新增字段；不新增执行权威，不自动装配 Temporal Profile 或共享 Session。

最初 scoped native/managed 与 sequence 四项因 selector 被拒绝而 RED；实现后 GREEN。
独立只读 review 发现2项P2：HTTPModelProvider._client方法误当实例、SQLite地址未进入新发布。
三项复现先确认失败后修复；review复核20 passed、未发现新增P1/P2。
Facts/Knowledge共存增加2项，当前相关29 passed；纯采纳、来源变化、取消、非法Scope/selector/protocol和恢复另有回归。

## 验证状态

源码实际 Temporal12：native/sequence/graph/team/dynamicDAG/nested × ordinary/managed，Worker在安全Context读取窗口kill后重启；已完成成员不重复模型／检索，原namespace沿子树保留。98.94s。
安装实际 Temporal12从checkout之外运行，相同矩阵82.94s；每项实际History replay通过。官方CLI1.9.1／Server1.32.0，SDK1.34.0，临时任务磁盘。
安装独立契约63 passed（3.47s），202源码/wheel/sdist/安装模块字节一致。
实际PostgreSQL16.15普通/managed Activity/state探针：namespace、Unicode／大整数文本、TTL、来源恢复、变化阻断及connection替换拒绝通过。此为真实DB+Activity证据，非跨机Temporal部署。
独立core-only Python3.12 venv使用已留存基础依赖和实际wheel，无redis/psycopg/temporalio/tiktoken/pypdf；离线索引/Agent/原Run、纯Knowledge注册/采纳通过，不宣称Service运行。
实际安装58→59→58：默认Run/Manifest/SQLite artifact与21 starters保持；temporal-1/2/3 default与raw Knowledge manifests相同；实际58在接受前拒绝新Knowledge namespace selector。
既有真实Temporal回归28 passed（222.73s）：Facts12、绑定4、managed context12。
本轮自有PG runner68836已exit0、stopped=0；Temporal runner97489已exit0，temporal-official/stopped确认。所有实际Workers由fixture关闭。
最终完整3436 passed／131未配置服务跳过（467.01s），-W error，执行66357 exit0；Ruff、格式与Git空白检查通过。
最终构建重新包含当前指南／验收／能力队列，sdist文档及202模块一致性单独校验；实际提交SHA以Git为准，仅本地，不推送。
未完成项不标通过；本轮没有调用真实模型，语义／任务质量仍未验收。
