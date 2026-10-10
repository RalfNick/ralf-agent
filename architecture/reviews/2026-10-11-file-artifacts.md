# dev55 — 文件 Artifact 验收

基线：6001fef/dev54。范围：R18 与既有受管理卸载，不新增执行权威。
状态：本地 POSIX 文件后端子集完成验收；真实 Temporal file Worker/History 尚未验收。

## 实现与兼容

FileArtifactStore 复用原 ArtifactStore／引用：正文为有界 canonical JSON 文件，
元数据为 bounded SQLite receipt index；POSIX flock 串行化协作客户端。
固定根、实际持有的描述符、索引入口与原组件；发布先同步正文与目录，再确认索引。
重复值保留原引用，丢失正文可由同一 put 重建；损坏、别名、漂移不静默成功。
JSON/TOML sync/async 工厂可显式替换；默认 SQLite、字符计量、Run／History schema 不变。
Runtime 所有资源按原账本关闭，SDK 注入由宿主管理。

实际 dev54→dev55→dev54 wheel 验证 budgeted／managed-summary／managed-data 的
原 Manifest、Context 身份、Run ID 与 SQLite Artifact 引用完全一致。
21种 starter 文件树在 dev54/dev55 字节完全一致；旧 wheel 在建库前拒绝新 file 声明。

## TDD 与独立审查

新增行为覆盖正文重开、丢失／损坏／别名、共享容量、根与索引固定、
JSON/TOML 两种装配及 owned 关闭、真实进程四个发布窗口、实际三进程容量，
Local 图／Team／动态 DAG／嵌套在 Artifact commit 与上下文响应两窗口的崩溃重启。
业务工具8次、摘要4次、Artifact写1次保持，不由重启重复写入。
Temporal runtime/state 重开复用原阶段及真实 Worker 装配的发布身份稳定。

唯一 fresh-context read-only reviewer 初步69项通过，提出三个 Important，无 Critical/Minor：

- 孤儿重复 put 未同步已存在正文／目录：实际 rename 后 os._exit，重开观察 SQL COMMIT 前缺 fsync 的 RED；修复为核验、同步正文与根后提交元数据。
- 根内索引软链接可指向外部数据库：构造前根相对 O_NOFOLLOW 创建／检查，绑定入口 inode；拒绝外部目标且不创建外部 DB 的 RED→GREEN。
- 锁路径正确但持有描述符可被替换：固定目录／锁实际描述符与 inode，关闭只释放 original owned FD；两项替换及两项原生 FD 复用 RED→GREEN，借用 FD 仍可使用。

三个意见已逐项落实，六项针对回归通过，没有重新派遣第二审查者。
本地正文／索引身份的保护针对可信宿主组件漂移与协作客户端；不是恶意宿主／OS沙箱。

审查排除项裁定：硬件掉电认证与 NFS/cloud 不属于本地 POSIX 子集；磁盘 quota、孤儿 GC、
引用保留不属于本次交付且仍在 R18；真实 Temporal 服务及最终打包门槛按独立证据验收。

## 验证证据

- 文件／通用 Artifact／受管理上下文／Temporal state：首轮115 passed；新增两项原生 FD 复用回归通过，最终全量覆盖。
- 源码外实际安装最终 wheel：117 passed，26.94s；source/wheel/sdist/installed 的193个 Python 模块字节一致。
- 独立 core venv，只有12个核心依赖分发包，无 temporalio/pypdf/tiktoken：冷导入、文件原引用重放、容量／读取限额、async 配置和 owned 关闭通过。
- Ruff、格式、Git 空白与 pip check 通过；9份相关文档340个本地链接及4个Python示例校验。
- 完整最终回归：3343 passed／98配置依赖跳过，589.88s；原生 FD 复用最后修复后重新运行。首轮3341/98只是中间检查点。
- 真实 Temporal：本批次服务下载进程仍在运行，尚未取得地址，新增6项 Worker/History 测试未实跑。

范围详见[文件指南](../../docs/file-artifacts.md)与[持续队列](../../docs/continuous-development.md)。
不声明完整 H3/M1、分布式文件存储、GC／硬磁盘配额或 AgentScope 整体对齐。
