# dev86 端到端任务评测：已验收子集

前置已提交基线为 dev85 `3d053a5`。本批仅本地开发与提交，不推送。
长期 R01–R26／H1–H5／M1／企业与目标场景对齐保持开放。

## 交付与边界

- RAG 复用 IngestionCoordinator、SQLite Knowledge/Vector、Hybrid、KnowledgeContext、版本2推荐Runtime和原生Agent。八类冻结来源，正确答案与实际来源分别评分。
- 引用证据以最终模型 Action snapshot/request 和 digest 为准。与候选精确匹配，截断时仅还原可见 value.text；metadata、隐藏候选和压缩记录不替代原文。
- Plan／Team复用版本2推荐Harness及原受管理researcher/writer。独立库存、查询／计算回执和前序实际请求评分；显式researcher输出Schema让对象和原生HTTP JSON文本在公共完成边界统一。
- Provider及Embedding真实方法／身份固定；宿主借用客户端不关闭。显式索引是准备任务，恢复工厂仅重开库和索引，不重做摄取、索引或模型调用。
- SDK、安装包内CLI、独立生成／Embedding配置、repeat summary、来源化usage和私有0600证据。单文本Adapter cap不能保证任意第三方内部HTTP重试或硬费用。

## 当前证据

Task1：67项oracle RED缺模块→GREEN；覆盖命名空间、版本、digest、伪造正文、隐藏展示、JSON重复字段和拒绝／缺证据。
Task2：18项实际链路 RED→GREEN；新增错误／召回独立评分2项RED→GREEN、原方法变化／用户请求冒充引用2项RED→GREEN，取消与实际os._exit仅观察恢复通过。
Task3：初始14项RED→21项GREEN；两类编排原Provider方法固定新增2项有效RED，统一固定Wrapper后纳入回归。
CLI：36项RED→GREEN；原生HTTP生成／Embedding组合和关闭测试发现researcher JSON字符串契约缺口；Root复现2项RED，增加输出Schema后2项GREEN。

统一修复完成：独立review的2项Important／1项Minor均有效RED复现后修复。单调用timeout不限制整链观察；已知tools=False在派发前not_run；真实子进程使用被测包路径，安装时不指向checkout。源码定向161 passed（33.80s），独立核心wheel安装同组161 passed（33.61s，-W error）。核心无Temporal／Redis／PDF／tokenizer extra。

源码实际CLI三次重复：RAG24/24、24模型调用／54单文本Embedding调用；Plan15/15、51模型调用；Team15/15、51模型调用。安装后实际三种CLI：RAG8/8（8模型／18Embedding）、Plan5/5及Team5/5（各17模型）。安装SDK文档例子输出(16,10)。均离线且model_quality/semantic_quality为null。

8类原默认Profile身份及2类Harness请求在旧85／源码86／核心安装86字节一致。真实旧85→源码86→安装86→旧85的同一原Plan Run回执／完整快照保持。298模块源码／wheel／sdist／核心安装一致，冻结hash不变。

最终完整源码5681 passed／447配置跳过（830.34s），退出0。Ruff／格式／Git空白检查通过。构建和最终源码／wheel／sdist／安装及Manifest载荷一致校验列入本批制品记录；配置跳过不算真实服务验收。
本批尚未调用真实外部模型／Embedding或重跑Redis／PostgreSQL／Qdrant／Temporal服务；没有实际模型质量与对等成绩。

## 后续

继续完整配置的重复真实模型任务、记忆及长上下文事实保留，Temporal对应链路与多窗口崩溃验收，再推进独立首次采用与服务治理。
dev83 M1真实Temporal Sandbox CI及M2 ServerVersion错误分类延期保持，本批不关闭。

## 设计判断与代价

Embedding上限按单文本Adapter调用计量；原通用端口不能保证第三方内部HTTP次数或硬费用，错误推断会低估费用。引用只接受已支持来源协议的最终可见原文；自定义投影需提供相应来源协议后才能评分，否则可能拒绝合法但无法核实的引用。两项均不改变执行协议。

本轮无新增延期Minor，独立review三项已修复。完整目标保持active，仅本地提交。
