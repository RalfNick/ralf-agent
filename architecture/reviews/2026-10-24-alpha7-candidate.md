# Alpha 7 独立候选准备与本地验收

日期：2026-10-24。基线 `2d178082282368a901651b4a5fbc39cfa5f84119`。按用户授权纳入该提交的中断清理和文档修复，准备 `relf-agent==0.1.0a7`，不增加功能。完成后仅本地提交，单次跳过钩子，不推送、公开发行、配置账号或触发远端 CI。

## 准备与原包边界

沿用 `relf_agent` 导入、`relf` CLI、原配置／数据／协议身份。产品相对基线只改变版本和生成应用安装提示；不将 a6 原制品或其平台成绩标为 a7。原 a6 两包、整个交付目录、历史 manifest／工作流／发布校验器及原架构 review 在开始前留有 731 个保护文件摘要，结束时逐一复核。

新增 a7 外置 manifest、仅手动暂存／原生门禁／OIDC 发布工作流及固定检查器。共享暂存入口只增加 a7 的独立前缀与新入口校验；历史默认、manifest、检查器、工作流保持。原 311／16／两 starter 不变，新候选增加独立 9 项中断清理阶段，原节点、依赖锁、期限及 Linux 资源条件不降低。

sdist 内 manifest 是构建输入快照，`artifacts={}`；最终两包 SHA、源码输入摘要和本地验收保存在仓库外置清单与交付目录。本文在归档内不自引用最终 SHA。官网固定 `ba1c81f` 的 a6 教程，不随新候选自动升级。

## 验证记录

新发布测试首轮为 **11 failed／14 passed／30 setup errors**：a7 元数据、暂存前缀、工作流和检查器尚未准备，失败记录保留。后续结果在实际完成后追加，不以原 a6 或 `2d17808` 批次通过代签。

本次不运行真实模型或外部服务，不重做 S2／指纹专项；其历史结果继续按原制品／环境引用。新包 Linux／远端 CI、账号与公开安装需要独立后续证据。

## 首轮失败、诊断与复验

- 新候选首轮 11 failed／14 passed／30 setup errors 为元数据、配置和工具尚未准备的 RED；记录保留。
- 首次固定门禁311／16通过，新增中断阶段 `collection_changed`：准备时按收集顺序计算摘要，实际门禁要求排序后摘要。9个节点与断言不变；新增真实 collect-only 反例先失败，再修正 a7 manifest 的排序摘要，最终同阶段9项通过，未改共享执行器和历史 manifest。
- 初次 sdist 附加安装脚本引用不存在的 `test_alpha7_identity.py`，pytest exit4；修正为现有 `test_alpha6_identity.py`（当前元数据断言），原日志保留。
- 首次最终包的附加安装回归为22失败／476通过／2跳过。独立诊断捕获原 broker 的 `listener.bind` 抛 `PermissionError: [Errno 1] Operation not permitted`，确认本机沙箱禁止本地 Unix socket。保持同包、同安装、同测试与期限，允许本地 IPC 后498通过／2跳过；没有产品修复或放宽断言。一次诊断包装改变了 Popen 类型，另一次才成功保留原类并捕获被隐藏的错误；诊断记录均保留，不算产品验收。复验后私有回执脚本漏导入 hashlib 的汇总错误也保留；依据已经成功的原 JUnit／两 starter 输出补生成回执，不重跑或改写测试结果。
- 一次独立只读复审发现首用教程仍安装a6。已同步当前指南、工具安装示例为a7，明确未推送时远端 clone 不能取得新候选；官网固定a6教程保持。修正文档和摘要后重新冻结最终sdist，首轮包与失败作为 preliminary 保存，不能用首轮门禁代替最终同包结果。

最终证据位于 `dist/alpha7-candidate/evidence/`；初始候选与失败位于其中 `preliminary/`。源码503、安装498、57项配置检查互有重叠，不累加为唯一测试总数。安装的两个跳过只属于 PyYAML 可选工作流收集，不进入零跳过的311／16／9固定门禁。本次没有全量SDK、Linux或真实服务的新成绩。

## 本地实际验收（2026-10-24）

| 验证范围 | 本次结果 |
| --- | --- |
| 受影响源码，31 个测试模块 | **503 passed**，零失败／错误／跳过，warnings-as-errors；不是全量 SDK 回归 |
| a7 发布配置与安全反例 | 57 passed，包含真实 pytest 收集与新增中断阶段摘要核对；属于上行范围的子集，不重复相加 |
| 原 wheel，macOS ARM64／Python 3.12.7 | **311 基础＋16 恢复＋9 中断清理**，零失败／错误／跳过；两 starter 各一次业务写入；原阶段与期限不变 |
| sdist 重建后安装，源码 SDK 目录外 | **498 passed／2 skipped**，零失败／错误；跳过仅为最小依赖无 PyYAML 的两工作流模块，源码环境已通过；两 starter 各一次业务写入 |
| 发行与安装身份 | wheel／sdist／源码／重建 wheel 的 **442** 产品文件一致；METADATA、8 个 CLI、LICENSE／NOTICE、`pip check`、Twine 7.0.0 `--strict`、离线发布预检通过 |
| 官网固定 a6 | 25 项、类型检查、14 对双语文档摘要、49 个固定仓库目标与双语离线教程通过；基线 `ba1c81f` 保持，不部署网站 |
| 原制品与历史 | **731** 个预先保护文件摘要一致；a6 原两包、交付目录、旧 manifest／工作流／检查器及历史 review 保留 |

产品相对 `2d17808` 只改两个文件的版本号与安装提示，`runtime_builder.py` 直接保留该提交的修复，不改功能、依赖或 Schema。完整源码回归、真实模型、S2／函数指纹专项未在本轮重跑，也不借历史成绩授予 a7 新包资格。

### 推荐本地原包

目录为 `dist/alpha7-candidate/`；外置 `tools/release_gate_manifest.alpha7.json` 为最终交付清单。仅选以下两份原包，不能上传整个 dist 目录。

| 原包 | SHA256 |
| --- | --- |
| `relf_agent-0.1.0a7-py3-none-any.whl` | `6f4e11f7e1e421dcf31f6085777338fecdefd34248381bd06c8eae3a9f32ea32` |
| `relf_agent-0.1.0a7.tar.gz` | `c6afdb08c69adcb4fe46c32b65d6c0029d3b1179db178cf32fc24da5df323d5b` |

最终外置 manifest SHA256：`41ebadcb3ac263a8b1cded3b0b0edbe9067e2a598caaccecdd9b192d7e0aa7f7`。构建输入清单 SHA256：`81c12eb2555f0cbdaf6cabde859ae641062a7e545ed606b2960d79fb7b33df3c`；包含 2098 个源码输入、990 个测试／示例文件及442个产品文件。来源为基线 `2d178082282368a901651b4a5fbc39cfa5f84119` 加本批维护工作区；**不是某个 Git 提交的逐文件 archive**。最终文档成绩与最终包 SHA 在冻结后追加于这三份记录；归档内仍为准备快照，避免自引用，不代表归档遗漏运行代码。

### 后续外部步骤

a7 的 **Linux ARM64** 与 **原生 AMD64／远端固定门禁**尚未执行，必须使用以上同两包，按 2 CPU／2 GiB／swap0、断网、Python 3.11–3.13 串行独立验收。原生工作流已准备为 `alpha7-release-gate.yml`，暂存、门禁和发布须匹配同一准确提交与 run／attempt；新增9项也必须完整通过。下一步需要推送和远端 CI 授权，本批停在本地提交。

PyPI／TestPyPI 的 `relf-agent` 项目权限、`alpha7-pypi-publish.yml` Trusted Publisher、受保护环境、上传、公开下载后安装均未配置或执行。`publication_ready=false`；没有正式 Tag、推送或公开发布。公开推荐、网站升级和独立采用另行验收。
