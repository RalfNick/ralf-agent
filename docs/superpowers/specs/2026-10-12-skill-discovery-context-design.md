# Skills 目录的自动上下文发现

基线b3cb8ce／dev81，沿R13/H3/H4的已注册Skills目录及原KnowledgeContextPort推进。
目标让开发者无需模型先调用skill_list，也能给首次决策提供相关技能的名称、说明和固定来源；原skill_get继续按已授权工具读取正文。该阶段只交付目录发现，不自动执行正文或激活插件。

## 设计选择

1. 在Harness.prepare隐藏目录I/O会破坏纯提案契约，拒绝。
2. 添加独立Skills状态机重复原Context读取／恢复／预算，拒绝。
3. 显式 `SkillDirectoryRetriever` 经原精确KnowledgeContext实现KnowledgeContextPort，由原Local参考读取和Temporal受管理Context read Action采纳；推荐该方案。它是能力适配器，不把目录伪装成知识文档，不新增数据库或执行权威。

目录发现与模型可调用工具是独立授权：宿主明确配置目录读取Scope／名称allowlist；模型调用skill_get仍受AgentSpec、ToolSet、skills绑定及宿主授权限制。适配器不增加或移除工具。仅将允许目录的metadata放入user级参考块；标注reference_kind=skill-directory、被动参考、不能增加权限。当前Evidence前缀仍有效，不将其提升system instruction。

## 公共契约

纯可替换 `SkillSelector` 具有普通有界JSON identity和同步 `select(query, entries, *, limit) -> list[str]`。默认 `LexicalSkillSelector(version="1")` 使用确定性的名称／说明词项匹配（ASCII词与中文字符双字词），非空查询仅返回正匹配，query=""按名称顺序。按评分降序、名称升序打破平局；不是语义模型或质量保证。limit精确int1..100。输入是已验证完整普通metadata，不提供正文、Catalog或执行句柄；必须返回唯一且在允许集合中的名称，最多limit。同步None/async/generator/contextmanager等配置或返回均拒绝。

`SkillDirectoryRetriever(catalog, *, version, names=None, selector=None, max_entries=1000)`借用固定SkillCatalogPort。catalog/list/get/identity和selector/select/identity在发布固定，await前后与披露前校验。names=None明确允许整个scoped目录；否则精确非空唯一名称集合≤1000。完整分页、total、唯一跨页排序和catalog_digest通过后才能选择。目录超过max_entries失败，不静默截断。实际发现只list，不读取正文get；默认namespace由原KnowledgeContext选择，版本、Scope及allowlist不隐式放宽。

## 默认声明与组合

`knowledge.adapter="skills-directory-file"`配置复用固定JSON+Markdown FileSystemSkillCatalog；`"skills-directory-markdown"`复用FileSkillDocumentCatalog和可选YAML parser。分别复用原file/markdown声明预检，新增version／names／namespace／limit／max_chars／max_entries/selector显式配置；selector首期只lexical，允许SDK自定义。工厂ownedCatalog由原BuildContext登记，Context借用Catalog。Profile base_dir绝对路径固定，Scope allowlist执行前预检。

该组件以原knowledge inherit/ref/disabled选择，为Local原生／顺序／Graph／Team／Dynamic／nested和Temporal对应受管理子Run使用。Skills专用ref仍只选择工具目录；两角色不隐式联动，文档明确。这是独立目录发现能力；后续复合多个Knowledge/Skills源与自动正文加载需要各自设计。原knowledge命名用于原数据采纳端口，不改既有KnowledgeContext实现。

Temporal原Context read协议下将目录I/O、完成响应／实际end均交给原History；默认未启用不改发布。自定义context内部catalog须由固定registration声明实际资源边，支持关闭／身份验证；增加原KnowledgeRegistration的native识别只登记catalog list/get，不开放任意反射。旧81实际Worker的固定发布必须在模型／工具实际I/O前拒绝新组件发布；沿原validate_release，不新增History语义marker。

## 验收与范围

先纯selector／目录适配器真实RED→GREEN：合法选择、无匹配、中文、分页拼接、总量界限、scope/允许names、lazy/customcopyhook/identity或方法漂移、伪造回执、canonical预算与关闭真实handler。
工厂无分配预检、核心无YAML默认JSON、自定义selector、可选markdown及owned/borrowed lifecycle。
Local六类与Temporal六类实际目录发现→模型选择原skill_get→原结果读取，取消／重启／History／source失效／不增加工具权限，源码及固定安装各零SKIP。真实业务工具不执行额外操作。
最终全量、固定包／核心SDK／22默认模板、真实旧81双向默认兼容及实际I/O前新发布拒绝、唯一finalreview及统一Importantfixpass、实际自有服务停止等待、本地提交不推送。完整R01–R26、selector中语义质量、正文自动加载／Sandbox／Runner／治理继续ACTIVE。

## 原生检索和引用格式

原 scoped Knowledge绑定仅接受精确KnowledgeContext，Temporal knowledge_protocol1要求原_knowledge引用格式；不得为Skills复制一套引用或状态协议。采用 `SkillDirectoryRetriever(catalog, *, version, names=None, selector=None, max_entries=1000)`实现原RetrieverPort.retrieve(scope,namespace,RetrievalQuery)/validate(scope,namespace,items)，用原精确 `KnowledgeContext(retriever, namespace="skills", limit=5,max_chars=8000)`装配。所有允许namespace都使用同一已声明目录／names授权，不创建隐式目录范围；namespace选择由原KnowledgeBindingResource限制。无需新增SkillDirectoryContext类。

输出原RetrievedChunk／RetrievalResult，metadata.reference_kind="skill-directory"、name、description、skill_version、catalog_digest、metadata_digest、permissions="none"；text为普通名称+说明参考，不含instructions。document_id为skill名称，chunk_id为digest([catalog_digest,name,metadata])，version精确int1（目录不可变，string技能version在metadata），source_uri="skill:<catalog_digest>/<name>"，expires_at=None，scope/namespace沿原请求。原KnowledgeContext负责预算和原_knowledge引用格式；validate重新读取目录metadata并逐项重建、严格对比，不执行任何正文get。目录注册固定list/get仅用于身份，而实际发现仅list；读取正文仍原模型工具Action。

原KnowledgeRegistration扩展native资源遍历识别SkillDirectoryRetriever及catalog.list/get，保持原knowledge_protocol1和发布的原有效协议。既有scope/source验证、Contextread实际结束和恢复无需新marker；旧81若使用同一通用纯History可以理解同样的引用协议，实际旧Worker的固定runtime因新adapter发布／实现身份不匹配在I/O前拒绝；不要求旧纯state拒绝合法原KnowledgeContextProtocol。默认旧Manifest保持。实际兼容门槛使用真实旧81 Worker+固定默认runtime、新发布request和零模型／工具实际I/O事实，以原validate_release为边界。
