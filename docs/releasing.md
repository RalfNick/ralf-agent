# 预览版本验证与发布

当前推荐 **0.1.0.dev122 的 Local 基础 SDK 本地预览制品**。本批修复 dev121 审查确认的审批、等待、语义绑定、Embedding 与 HTTP 响应边界问题，并修正已有 CI 门禁；不增加后端或编排能力。函数指纹专项、S2、完整第三阶段与 R01–R26 的状态保持。

CI 检查与构建不自动发布到 PyPI／GitHub Release。本轮只生成本地制品，未推送、上传或核验公开发行；历史制品及其证据保留。

## 本轮本地交付

推荐目录为 `dist/basic-sdk-dev122/`：

- `ralf_agent-0.1.0.dev122-py3-none-any.whl`：已验证的安装包。
- `ralf_agent-0.1.0.dev122.tar.gz`：包含源码、测试、文档与连续示例。
- `delivery.json`：精确 SHA、工作区来源和有限验证范围。
- `SHA256SUMS`：目录校验清单。

```bash
cd /ABSOLUTE/PATH/ralf-agent/dist/basic-sdk-dev122
shasum -a 256 -c SHA256SUMS
python -m pip install ./ralf_agent-0.1.0.dev122-py3-none-any.whl
ralf --version
```

版本应为 `0.1.0.dev122`。先按[首用教程](getting-started.md)运行审批／恢复，再按[连续教程](support-journey.md)逐步增加能力。[本批验收](../architecture/reviews/2026-10-19-dev122-review-fixes.md)区分源码、安装、回归和实际服务证据，不将不同范围拼成全量验收。

不同可安装候选使用独立版本和目录，不覆盖 dev121。包版本、Run Release、SQLite Schema 和 Temporal Worker 身份分别管理。**本批 scoped 语义 Facts 资源新增窗口模式身份**，旧任务须保留原匹配环境，不能静默重绑；普通游标资源身份保持。不新增旧 History／函数指纹兼容资格，也不恢复 S2。

以下各段保留对应历史制品的原始范围。

## 历史基础 SDK 制品（dev121）

原目录为 `dist/basic-sdk-dev121/`：

- `ralf_agent-0.1.0.dev121-py3-none-any.whl`：安装用包。
- `ralf_agent-0.1.0.dev121.tar.gz`：包含文档和连续示例的源码包。
- `delivery.json`：精确制品 SHA、源码输入、安装验证和未验收范围。
- `SHA256SUMS`：该目录的文件校验清单。

```bash
cd /ABSOLUTE/PATH/ralf-agent/dist/basic-sdk-dev121
shasum -a 256 -c SHA256SUMS
python -m pip install ./ralf_agent-0.1.0.dev121-py3-none-any.whl
ralf --version
```

`ralf --version` 应为 `0.1.0.dev121`，也可用 `python -m pip show ralf-agent` 核对安装元数据。安装后先按[首用教程](getting-started.md)验证审批与重启，再按[连续工单教程](support-journey.md)增加能力。没有公开发布到 PyPI／GitHub Release，本地提交不等于公开发行。

本候选已完成19模块源码290项、最终wheel独立安装82项及两项原starter审批／进程恢复；精确SHA和限制见[本批验收](../architecture/reviews/2026-10-19-dev121-basic-delivery.md)。这些是分别取证的有限范围，不合并为同次全量通过。

每个推荐的不同可安装版本使用唯一版本号。后续修改使用新的预览版本，不在当前目录覆盖已验证的 wheel；历史 dev120 同版本多候选只作为内部实验记录，通过原目录和 SHA 定位。

包版本、Run Release、SQLite Schema 和 Temporal Worker 身份是不同概念。升级安装不能改写旧 Run：保留旧数据、原组件和匹配 Worker，按[恢复指南](recovery-guide.md)与[备份／回退](framework-backup-restore.md)操作。此包没有执行新的旧 History／函数指纹兼容专项，不能据包版本递增声称所有历史任务可直接续跑；S2 及完整分布式组合仍后置。

以下各段为历史制品证据，不能视为本包同次验证结果。

## 历史基础 SDK 制品（dev120）

本轮交付物放在仓库的 `dist/basic-sdk-b871f61/`：`ralf_agent-0.1.0.dev120-py3-none-any.whl`、`SHA256SUMS` 与 `delivery.json`。这是本地制品，未推送或发布到远端；当前支持范围只以[当前摘要](implementation-status.md#当前交付摘要)为准。

```bash
python -m pip install "/ABSOLUTE/PATH/ralf-agent/dist/basic-sdk-b871f61/ralf_agent-0.1.0.dev120-py3-none-any.whl"
ralf --version
ralf --format text init my-agent
cd my-agent
python -m agent_app --ticket INC-001
```

完整审批与跨进程恢复按[首用教程](getting-started.md)执行；模型与工具定制从[SDK指南](sdk-model-tools.md)开始。安装前在制品目录执行 `shasum -a 256 -c SHA256SUMS` 核对文件；路径及命令由使用者替换为实际位置。

本轮复用固定产品的完整离线源码回归（12,749通过／838配置依赖跳过）、原独立安装62项及其他已登记基础证据；最终wheel已通过隔离安装、版本／入口、starter审批、重复审批、恢复及原命令回读验证，业务只写入一次，结果见 `delivery.json`。wheel与交付记录的SHA-256校验通过。该smoke不改称完整安装矩阵或新的真实模型质量，阶段未验收项保持不变。后续CLI核验便利命令等可选项不进入本轮，现有SDK人工核验可用。

## Temporal 工具结束证据补丁

原 `basic-sdk-b871f61` 制品保留，不替换其哈希。后续发现默认无 `ToolExecutionOwner` 的 Temporal 工具存在P1：超时工具经人工确认效果后，另一个工具成功可能让父任务提前结算。新补丁 `dist/p3-tool-end-20261016/` 的同版本wheel独立校验、安装与验收，细节见[补丁记录](../architecture/reviews/2026-10-16-temporal-unowned-tool-end.md)。该批证据绑定该精确制品，后续增量按各自验收选择；不能只凭 `dev120` 版本号区分。

补丁用 `ralf-unowned-tool-end-evidence-v1` 标记保护新Run，默认Card／普通发布身份保持。无标记旧History为确定性重放保留原行为，**没有自动升级或追溯修复**；重放通过不等于原风险消失。默认Local起步不受本问题影响。无Owner的原工具超时后，即使外部已看到线程退出，没有原History结束回执仍保留义务；没有新增人工清除入口。旧未知Run的安全迁移／处理仍是开放项，不能据本补丁关闭P3-3或P3-5。

## P3-3 scoped 人工恢复增量

后续已验收制品 `dist/p3-scoped-manual-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，SHA256 `4c90e3312f611676e6bc12d126810511621dffe1b2bff6949638766692c417ac`，附 `verification.json`／`SHA256SUMS`。它包含上述新Run结束证据修复，并补原普通Tool在默认scoped满容量后的有限人工核验路径。源码／隔离安装各1,233项及实际SDK图child验收见[本批记录](../architecture/reviews/2026-10-16-temporal-scoped-manual-recovery.md)。默认Local基础制品仍冻结，P3-3／其他阶段未关闭，旧不安全Run未追溯升级；所选实验发布指纹变化后，旧History仍使用原匹配Worker。中间候选与失败包不作为交付物替代此精确制品。

## P3-4 身份与脱敏审计增量

本地制品 `dist/p3-service-audit-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `101e537100f0531e6cc3fdde31713b24ba83969644c0640bc05c63cba5097ba3`，附`verification.json`与`SHA256SUMS`。
原基础／P3-3制品不覆盖。本批默认关闭审计，原Card、普通发布身份及保存默认History兼容通过。
有限源码／安装／实际HTTP证据及4项已复现的原输入夹具失败分别登记于[验收记录](../architecture/reviews/2026-10-18-p3-service-audit.md)。
安全保留和所选远程身份／审计尚未完成；不宣称完整P3-4或强制耐久审计。仅本地提交，不推送／发布。

## P3-4 默认Local保留增量

本地制品 `dist/p3-local-retention-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `068b90130f25dd9a7a3ada5ec7e55d2c5f3cae6831231a938f6eb3622c149111`，附验证及校验清单。
源码／隔离安装各245项通过，旧已安装SDK可读压缩原库；使用限制及证据见[验收记录](../architecture/reviews/2026-10-18-local-retention.md)。
这是显式工作副本逻辑压缩，原动作／效果／幂等与恢复证据不删除，完整P3-4仍开放。
上批审计及HTTP证据仍绑定原439文件wheel，不拼为本440文件同次实际服务验证。

## P3-4 所选远程身份／审计补证

本批没有产品改动或新wheel，继续使用上述440产品的`068b901…`原制品。
实际HTTP／Temporal／PG双身份与审计2项通过，资源授权交集安装52项通过，
原始文件与范围见[验收记录](../architecture/reviews/2026-10-18-temporal-scope-audit.md)。
仅此所选子集补证，完整P3-4的PG安全保留仍待；旧失败及原制品不覆盖。

## 1. 准备版本与兼容说明

1. 同步 `pyproject.toml` 和 `src/ralf_agent/__init__.py` 中的包版本。
2. 更新 [CHANGELOG](../CHANGELOG.md)、[实现清单](implementation-status.md) 和已验证的使用指南。
3. 分别审查包版本、内核 Manifest 身份、SQLite Schema 和命令摘要的兼容性；安全补丁不自动意味着旧 Run 可恢复。
4. 明确列出已支持的 OS／Python、适配器和验证类型。当前 CI 为 Linux、Python 3.11／3.12／3.13；本地开发可在 macOS 验证。

dev6 新增 Harness／Executor 固定身份与接收阶段语义，内核改为 local-4。dev3–dev5 的 local-3 Run 可观察、取消及人工核验，继续需原版本和原配置；不静默迁移。SQLite Schema v1、dev3 起的调用方 submit 摘要保持不变，相同请求可找回旧回执，但不能用新内核续跑。dev1／dev2 历史 submit 摘要重放仍需原版本；自动摘要／Run 迁移尚未交付。

dev9 保留 dev8 默认 Manifest 和缺省 Chat identity。实际制品验证需先安装 dev8 创建任务，再安装 dev9 用原默认工厂重放回执并续跑；同一离线 HTTP fixture 也要验证旧 Chat 配置。启用 Recall／Knowledge／planner／profile、生成参数或流模式会固定新的身份；不能在旧 Run 上静默启用新策略，也不能因同一提交找回回执就忽略配置不匹配。

## 2. 在干净检出中验证

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
git diff --check
python examples/evaluate.py
python -m build
```

使用干净构建目录，确保本次 `dist` 里只有将要发布的版本；不要用 `dist/*` 混入历史 wheel。离线评测检验运行时审批／恢复／业务写入契约，不构成真实模型质量基线。记录源码 commit、测试环境和构建产物 SHA-256。

## 3. 在源码目录外安装 wheel

这里 `/path/to/ralf_agent-0.1.0.dev121-py3-none-any.whl` 是实际构建文件的占位路径。使用新的虚拟环境和源码目录外的临时目录，避免 editable install 或 PYTHONPATH 掩盖打包遗漏。

```bash
python3 -m venv /tmp/ralf-wheel-check
source /tmp/ralf-wheel-check/bin/activate
python -m pip install "/path/to/ralf_agent-0.1.0.dev121-py3-none-any.whl"
python -m pip check
mkdir /tmp/ralf-release-smoke
cd /tmp/ralf-release-smoke
ralf --version
ralf --format text init my-agent
cd my-agent
python -m agent_app --ticket RELEASE-001
```

确认停在 waiting_approval，然后按 [首次使用指南](getting-started.md) 从独立进程 inspect、批准、resume。再重提原命令，核对回执／Run ID 稳定和业务写入没有重复。检查包内包含 starter，生成项目不导入 `examples`。源码包还应包含文档、许可证和测试所需文件。

dev6 制品还需核对 Harness／ToolExecutor／DTO 公开导入、默认与自定义组件身份拒绝恢复，以及两个接收提交后的真实进程故障回归。源码示例使用 [execution_components.py](../examples/execution_components.py)；wheel 不要求包含或导入仓库 examples。保存新／旧内核的拒绝续跑证据，不能只验证一次无故障运行。

dev7 制品还需在源码目录外运行 `ralf init my-knowledge-agent --template rag`，测试中英文来源与无证据拒答，独立进程 resume、原引用版本和 tombstone／TTL 不被启动过程复活。核对 Recall／Knowledge／Vector 的公共导入；两个 RAG 崩溃窗口分别保持原快照及直接采纳已收响应。Embedding 未配置时不产生远程调用。

dev8 制品还需运行 `ralf init my-config-agent --template config`，在只改默认版本后从新进程恢复旧任务，核对原 profile／模型／工具及精确命令回执。补充资源构造／关闭失败重试和真实线程活动时切换拒绝；核对 ExecutionEngine、KnowledgeContextPort、RecallPlanner 与配置 API 的公开导入。配置缺少旧版本时应拒绝续跑，原回执查询不依赖该版本装配。

dev9 制品还需验证三个 HTTP/SSE 协议和 DeepSeek 固定 non-thinking 参数，独立 model 模板的占位/缺凭据拒绝及实际离线 HTTP 配置运行。核对全部公开导入和原 oncall/rag/config 模板字节保持一致。fixture 请求不能记为线上兼容/模型质量成绩；真实付费调用另行执行与记录。

## 4. 人工发布与安装核验

发布者先确认项目名控制权、维护者权限、目标仓库和预览版本号。审查 release notes、许可证、产物清单与摘要后，再通过授权的 PyPI 上传方式或 GitHub Release 界面发布已验证的精确产物；不要把新打包或依赖重新解析视为等同于此前验证的 wheel。

发布后从目标发行入口下载或安装对应版本，在新的虚拟环境中执行同样的 wheel 冒烟与恢复流程。只有这一步通过，README 才能把该 PyPI 安装命令／Release 下载链接列为已验证入口。保留上传记录、产物摘要和安装验证报告；不要把仓库存在等同于发行包可安装。

## 5. 发布后的维护边界

发布说明应注明预览 API、当前能力和升级限制。漏洞处理见 [安全政策](../SECURITY.md)，功能／缺陷贡献见 [贡献指南](../CONTRIBUTING.md)。

变更固定身份或存储格式前，先实现迁移／拒绝策略与真实恢复测试。未知业务效果先核验；回滚程序版本并不自动回滚数据库或远端写入。修复发布不能依赖删除执行日志来获得干净状态。

dev12 制品还需在源码外运行 `ralf init my-parallel --template parallel`，验证历史 Profile 恢复、分支 Session／审批、共享预算与五个崩溃窗口；旧 dev11 native/v1/v2 请求／Manifest 保持精确，dev11 续跑 v3 在派发前拒绝。检查终态资源尚未静止时仍保留 Session 预留，原生授权回调核验不会再次派发。

## P3-3 原Run必要控制增量

制品`dist/p3-run-command-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，SHA256
`185b1d23c5967ba29daad647be9d56f9a3ac36559150dc9ac14d275165c900b2`，附独立
`verification.json`／`SHA256SUMS`。它包含前批修复及本次原Run必要控制运输窄修。
源码／隔离安装各1,272项；相同wheel三个实际SDK场景分别通过，原失败、warning及
各自运行快照详见[验收记录](../architecture/reviews/2026-10-16-temporal-run-command-capacity.md)。
此前12组制品不变。默认Card／普通发布与保存History兼容通过；所选实验指纹变化，
历史所选发布仍需精确匹配Worker。不可变旧Worker只保留原Update兼容路径及其上限，
没有追溯修复或未知义务清除。完整P3-3、原P3-2失败及后续门槛均未关闭。

## P3-3 scoped 人工证明运输增量

制品`dist/p3-manual-transport-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `1d083edf1bcfddf22bdfee71ca2dc58174764424ff98c7177a0b555f62e0f95f`，附
`verification.json`／`SHA256SUMS`。源码／隔离安装各1,316项；同包真实压力和旧manual
Worker兼容分别通过，详见[验收记录](../architecture/reviews/2026-10-16-temporal-scoped-manual-transport.md)。
此前13组制品不变。默认发布／保存History兼容通过；所选实验指纹变化仍要求匹配的
历史Worker。旧manual Worker兼容路径保留其Update上限，没有追溯升级或清除未知义务。
首次结束ACK等剩余生命周期、完整P3-3及P3-2原失败不关闭。


## P3-3 原执行结束运输候选

制品`dist/p3-execution-end-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `9cbea0c142741001ff445ec0179f50195ae1f41e03146a943b81f79c576169f7`，附`verification.json`／`SHA256SUMS`。
源码／独立安装各2,340 passed／6 skipped，434产品一致，默认声明和保存History兼容通过。
它只修复四类原end运输，不增加准入；同包真实Temporal **2 passed／1 failed**，
公有部署后续效果ACK的begin登记仍在2,000 Update上限失败，Owner未排空，不能作为该
组合验收通过的发行。默认Tool压力／重启和旧Worker兼容有通过证据；此前14组冻结
制品不变，实验发布指纹变化仍须匹配历史Worker。原失败及8条失败History重放、完整
P3-3／P3-2门槛见[验收记录](../architecture/reviews/2026-10-16-temporal-execution-end-capacity.md)。
仅本地候选，不推送或发布远端。


## P3-3 公有begin／seal容量修复

制品`dist/p3-deployment-lifecycle-final-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `e71780943d331351aa47192aca83d4278a55ab027b103ba8141c3da564040a67`，附独立校验与
验收JSON。源码／隔离安装各2,381 passed／6 skipped，435产品一致；同包实际3 passed／
21.426秒，原公有普通2满2,000 Run Update后效果ACK、实际结束、封存退休和Owner关闭
通过。两类旧Worker按各自端点验证；旧selected仍需匹配SDK／Worker／replayer，不放宽
当前版本校验。默认配置／保存History及此前15组制品校验通过；旧有限候选与原失败
保持不变。原指纹错误、一次源码组超时与最终复核分开记录，见[验收记录](../architecture/reviews/2026-10-16-temporal-deployment-lifecycle-capacity.md)。
仅该公有恢复子集完成；完整P3-3、P3-2/S2、Registry／Session／native和其他History门槛
继续开放。不推送或发布远端。

### 同一制品的独立HTTP／PG补证

上述435文件制品未重建。其原安装包的HTTP／Temporal／PostgreSQL三场景独立
**3 passed／26.847秒**，受影响离线47项通过，产品／测试输入不变。此前16组制品
及其原验收JSON／SHA256SUMS均保持有效；新证据见[冻结范围核对](../architecture/reviews/2026-10-16-phase3-control-evidence-audit.md)。
这不关闭完整P3-3，也不替代原S2失败、模型质量或外部采用验收。

## P3-3 原Registry退休容量修复

制品 `dist/p3-registry-retirement-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `7a2dc32ab734956b5998bb9cb48d36e575fd60025e6aee9f605560d36cc06cd6`，
附独立 `verification.json`／`SHA256SUMS`。436产品文件与源码／隔离安装一致，安装
2,404 passed／6配置依赖跳过；源码8项socket沙箱失败的原样复验及分批证据单独保留。
相同wheel真实Temporal3 passed／28.621秒，含原Registry满2,000 Update后安全退休、
原Run压力及默认Tool结束，均有重启／History／owned关闭证据。默认发布／保存History
兼容和此前16组制品校验通过。只关闭该根退休子门槛；本批没有新HTTP／PG、模型质量
或native Coding压力验收，历史selected仍用匹配SDK／Worker。完整P3-3／P3-2及后续
门槛保持开放，详见[验收记录](../architecture/reviews/2026-10-18-temporal-registry-retirement-capacity.md)。


## P3-3 公有原Action强人工证明容量修复

制品 `dist/p3-public-manual-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `6dad78871e44f579109838e45a6f8b7cc98ebc1938cc80570532e0a108748e23`，
附独立 `verification.json`／`SHA256SUMS`。437产品文件与源码／隔离安装一致，911测试
输入固定；源码和安装各2,429 passed／6配置依赖跳过。相同wheel真实Temporal
1 passed／127.745秒：原Registry4,096逻辑身份＋2,000 Update后首次强人工核验、
实际结束与效果ACK分别保护额度、原回执、根退休及Worker重启／History重放通过。
使用相同CLI、原服务默认值和新自有数据库，原180秒场景期限保持，服务已关闭。
默认声明／保存History和此前17组制品校验通过。只关闭该恢复子门槛，没有新PG／HTTP、
模型质量或native Coding压力验收。旧selected仍用匹配SDK／Worker，完整P3-3、P3-2原
失败及后续门槛保留；详见[验收记录](../architecture/reviews/2026-10-18-temporal-public-manual-capacity.md)。仅本地提交，不推送或发布远端。


## P3-3 原Coding回执与停止容量修复

制品 `dist/p3-coding-recovery-final-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `62837413eaab1764d00f6ee70ee0565c8f9e00c541eca4992c3988da68ff5426`，
附独立 `verification.json`／`SHA256SUMS`。438产品与源码／隔离安装一致；源码及安装
129模块各2,454 passed／6配置跳过，之后测试夹具增量另验88项（0跳过）。
相同wheel实际Temporal／PG 2 passed／58.684秒，覆盖正常原stop和原单Agent
Coding满2,000 Update后的必要取消／恢复、PG采纳、原stop ACK重启、退休及安全关闭。
源码／安装后的服务及清理夹具修订分开记录，不声称913测试文件跨所有批次不变。
默认发布／保存History与此前18组制品校验通过。原失败及失败服务卷仍保留；正常满容量
续跑的新grant未升级，不外推实际Docker、模型质量、Coding父级压力或完整P3-3。
历史selected使用匹配SDK／Worker；P3-2及后续门槛保持。详见[本批验收](../architecture/reviews/2026-10-18-temporal-coding-recovery-capacity.md)。
仅本地提交，不推送或发布远端。


## P3-3 已封存Coding父级资源关闭修复

制品 `dist/p3-coding-parent-sealed-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `196c9877afe600598f4b29f27c4378d0ed11bf4064579a0f3720eea7734e77dd`，附独立 `verification.json`／`SHA256SUMS`。
438产品及916测试文件在最终源码／隔离安装／实际验证中固定；131模块源码和安装
各2,526 passed／6配置跳过。默认发布和保存原／续接History兼容通过；此前19组制品
校验不变。同包真实Temporal／PG正常及已封存Parent2,000 Update压力2 passed／
171.032秒，原回执、PG采纳、实际停止、退休、Worker重启／History与owned关闭通过；
94项夹具／清理单独通过。失败候选、SDK并发封存drive竞态及失败卷保持；已放弃的
Parent运输候选不作为交付物。最终仅一个产品模块复用原完整只读封存验证，无Parent
协议／业务授权扩展。历史所选发布仍需匹配SDK／Worker，原基础制品不替换。

只关闭已封存原Parent资源关闭子门槛；未封存首次采纳、任意History、实际Docker、
模型质量及完整P3-3／P3-2／后续阶段不由此推定。见[验收记录](../architecture/reviews/2026-10-18-coding-parent-capacity-probe.md)。
下一批仅核对冻结P3-3证据。仅本地提交，不推送或发布远端。


## P3-3 冻结交付门槛收口

2026-10-18 [P3-3证据归并](../architecture/reviews/2026-10-18-p3-3-closeout.md)接受所选
最小服务控制、持久观察、有界背压及原任务必要取消／恢复门槛。运行时代码仍为
`9eb8c35`，复用上述原精确制品，未重建wheel或改写此前的批次验证记录。
20组既有制品校验及原始XML／HTTP结果／Parent和leaf History再次核对通过；
各批次结果不相加冒充单次全绿，不声称最新wheel重跑全部历史服务矩阵。
本批没有新模型或服务调用、全量阶段回归或新的历史selected兼容声明。

当前原包的 `whole_p3_3_complete=false` 仍表示该修复批次单独验收的范围；
新的[P3-3收口审查](../architecture/reviews/2026-10-18-p3-3-closeout.md)是独立的冻结要求
归并结论。P3-2/S2原失败及P3-4／5／A依赖保持，完整第三阶段、R01–R26及企业可用
不由一个门槛推定。仅本地提交，不推送或发布远端。


## P3-A 独立候选验证（2026-10-18）

候选 `dist/p3-candidate-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `26546603a6bd9370dfc0bca71f48ecc83310ba3d52a8259fd1847d3a62e61ade`。
基础交付和此前各包不覆盖；同dev120按SHA区分。442产品仅一处SDK修复：允许
原Update-only Worker的合法`outcome_unknown` Parent接收必要取消，原完整
Scope／namespace／epoch／两次查询及typed回执检查保持。

受影响源码123项、隔离安装126项均零失败／跳过；同包真实PG／Temporal／HTTP与
两次全数据恢复25项通过（52.825秒）。默认发布材料、两份原保存History、
首用审批／重复回执／跨进程恢复通过，业务只写一次。首轮完整回归13,341通过／891跳过／24失败；仅补SDK观察、Workflow patch与namespace隔离夹具后，最终源码272项及安装275项通过。产品未再变化，最终930测试／20额外输入固定，第二轮完整回归13,374通过／891配置跳过、零失败／错误（JUnit 2224.610秒）。制品附`verification.json`、最终与首轮测试输入清单及`SHA256SUMS`，原失败保留。
旧不可变Worker同原任务取消RED→GREEN及零Signal取证通过，三份完整原History
由匹配Worker重放；其原执行停止未知不因人工效果核验清除，完整脚本的后续父级
quiescent等待失败保留。详见[候选记录](../architecture/reviews/2026-10-18-candidate-verification.md)。

用户明确授权独立候选验收。P3-2/S2原360秒失败、P3-A整体及第三阶段未完成保持；
没有新功能矩阵、模型质量或任意History迁移声明。仅本地提交，不推送或发布远端。
