# Alpha 2 追加验证与待处理核对

日期：2026-10-22。任务是补齐既有优化的本地证据和状态说明，不新增SDK功能、不连接模型或业务服务、不推送、不触发远端CI、不公开发行。

## 结论与范围

原`1b72c05`发行源码已推送；当前维护增量与下面追加证据尚未推送。当前推荐仍是原`0.1.0a2`不可变wheel／sdist，不同版本、不同平台、测试集合及服务成绩分别判断。

本轮补齐Linux ARM64／Python3.11–3.13基础门禁，发现并修正一个Session测试竞态；SDK产品442文件及原两包均未改动。函数指纹最小SDK缓存回归的96项另行在三版本通过；需要Temporal可选SDK的另1项在该环境未验收。原生AMD64／a2远端CI和公开交付继续开放。

原交付在`dist/alpha2-candidate/`，追加证据在`dist/alpha2-validation-20261022/`。原目录50项SHA校验通过；追加目录有独立摘要，不覆盖原证据。

## 不可变输入与门禁修订

| 输入 | SHA256 |
| --- | --- |
| a2 wheel | `dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46` |
| a2 sdist | `8a6be717541117ce8cecf4135ba5442936b3192b9d1967d5c79ca90511a35cc8` |
| 原第1版外置manifest | `f8396887f5d010e1052fc56bb9951aa518276269322361304004435af679bbd0` |
| 本轮第2版外置manifest | `3ca383ed405745909fa8e84bd40a2b79d2b080dc249cfbc0f96b6d12298cb7da` |
| 原sdist内Session测试 | `46d3eb8b57f8422fe84a7f59c09fcc17c8354b0e87b8e9846ba14171928fd40e` |
| 本轮Session测试校正后 | `b930481bfca0935ef9cf50d71109aa76819401f780324f5bcdd061083a4cc3ce` |

第1版manifest逐字节保存在`tools/release_gate_manifest.alpha2-original.json`。第2版仅增加修订来源及一个有before／after SHA和唯一文本替换的测试校正规则；原制品、442产品树、964文件原测试输入树、311／16完整node身份、17依赖锁、缓存镜像、warning-as-error和资源限制保持。

原sdist仍先按原SHA和原测试树验证，再应用该显式校正。原sdist内的构建前manifest不能替代最终外置manifest；原交付`gate/`继续冻结为第1版。当前补验使用维护checkout或追加证据的第2版`gate/`，不以重建同版本包实现修复。

## 首轮失败与原因

原第1版ARM64矩阵：3.11和3.12各311基础＋16恢复及两starter通过；3.13基础310通过／1失败，恢复与starter没有执行。失败用例是`test_session_entry_close_only_detaches_from_shared_runtime`：Run成功后立即要求Session不busy。

[Session契约](../../docs/session-api.md)允许Run已终态、Session仍因宿主托管Task或未收敛义务短暂busy。`AgentRun.wait()`观察Run终态；`LocalSessionAuthority`还负责会话准入。这是测试假设错误，不是SDK未释放资源的证据。测试改为在1秒有界观察内等待同一Session空闲，原成功、关闭拒绝和其他断言保留；不删除busy保护，不延长业务或S2期限。

两项新增门禁回归先得到2项有效RED，修正manifest与归档后，受影响四模块共128项通过、零失败／错误／跳过。首轮报告与RED／GREEN日志均独立保存。

## 第2版同包完整复验

三版本按顺序完整重跑，不拼接首轮通过项。全部使用原缓存Debian12镜像、原锁定依赖和同一a2两包；每容器实际2CPU、2GiB、swap0、pids256、`network=none`。CPU记录是配额，不声称CPU使用峰值；内存取cgroup峰值。每个容器退出0、无OOM，按自有标签核对后移除；不停止其他容器。

| Python | 基础 | 恢复 | starter | 整次门禁秒数 | 内存峰值MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.11.17 | 311 | 16 | 2 | 70.087 | 326.48 |
| 3.12.15 | 311 | 16 | 2 | 71.098 | 293.80 |
| 3.13.16 | 311 | 16 | 2 | 73.309 | 295.17 |

三版本JUnit零失败／错误／跳过；两starter每例业务写入一次。实际StartedAt／FinishedAt证实串行。原3.13失败保留，这些成绩明确绑定第2版校正，不称原测试未经校正通过。

复验命令使用当前第2版维护工具，输出目录须不存在：

```bash
.venv/bin/python tools/run_release_gate_linux.py \
  --wheel dist/alpha2-candidate/ralf_agent-0.1.0a2-py3-none-any.whl \
  --sdist dist/alpha2-candidate/ralf_agent-0.1.0a2.tar.gz \
  --wheelhouse dist/release-gate-20261019/wheelhouse \
  --output /ABS/new-a2-linux-arm64-evidence
```

门禁不下载镜像或依赖。Mac3.12原311／16／2、sdist离线重建安装116项与另两starter仍按[原交付](2026-10-22-alpha2-local-closeout.md)单独引用，不换算成全平台全量。

## 函数指纹缓存的独立限定复查

初选六模块97项，在基础17依赖环境的Linux3.11为96通过／1失败。失败是`test_static_and_dynamic_runtime_inventory_digests_keep_original_algorithm`导入`temporalio`时缺少可选SDK；不是摘要不匹配。原报告保留，未在门禁内联网补包。

对该环境可执行的96项另建明确集合，精确排除上面单一node，node身份SHA为`bdde52e8b20f98dbee308078c902c2bc4be150c6bdb604eb01f76e06345e15cb`。集合与排除理由、两个独立执行脚本、原97项尝试和新报告均归档。三版本重新离线安装原a2 wheel并独立验证：

| Python | 通过 | 失败／错误／跳过 | 内存峰值MiB |
| --- | ---: | --- | ---: |
| 3.11.17 | 96 | 0／0／0 | 206.77 |
| 3.12.15 | 96 | 0／0／0 | 183.62 |
| 3.13.16 | 96 | 0／0／0 | 188.99 |

相同2CPU／2GiB／swap0／无网络、严格串行，三容器退出0且移除。该子集检查缓存摘要、默认值、纯度及辅助函数身份等，不并入311／16门禁；不验收那1项Temporal执行库存、完整指纹集合、Linux CONTROL性能、旧Worker接管或Linux S2。原Mac／CPython3.12优化收益只按原记录引用。

## 其他证据与剩余事项

本轮本地制品预检返回`passed_local_preflight`、442产品／版本／许可证／复制后摘要正确，`publication_ready=false`。其`spec_sha256`是规范JSON摘要，区别于上表manifest文件字节SHA。它不代替安装或平台测试。

原dev19全量的891项条件跳过已从JUnit逐条归组：Temporal及其组合701、排除Temporal的PostgreSQL119、Redis25、排除以上的Docker32、旧SDK／Worker等外部环境12、Qdrant2。总数891；不是本轮a2全量。原所选真实服务通过证据仍保留，不能把这些skip改写为通过或都当成新缺陷。

仍需处理的事项和先后顺序：

1. **a2原生AMD64与远端固定门禁：** 新a2尚无三Python版本原生报告。当前`alpha1-*`手动入口固定旧提交和原a1包，不能直接用于a2；先准备明确交接，经授权再上传原包和执行，不自动触发。
2. **公开交付：** 核对仓库／包项目权限、最终源码／Tag和精确包SHA；经授权发行后，从公开入口验证安装、审批、重复提交及恢复。源码已推送不等于制品公开。
3. **适配范围的独立补证：** 上述Temporal指纹库存单项需匹配可选SDK环境；完整M1、真实模型扩展质量和外部采用按各自证据验收，不为凑数扩展首版范围。
4. **保留已知限制：** dev18并行未知异常来源未确定；旧Coordinator的`replay-None`限制和匹配不可变Worker要求保留。原S2所选18/18已闭环，不因补文档而重开或冒称新平台已验收。

当前不重跑真实S2／模型／远程数据库、不扩大功能、不清除未知义务。公开发行和上述外部证据仍未完成；详细状态见[当前验证清单](../../docs/alpha2-validation-status.md)。
