# 原 a1 原生 AMD64／远端固定门禁验收

日期：2026-10-20。用户授权暂存原 a1 制品并手动执行固定门禁，维持2CPU／2GiB、Python3.11–3.13串行、原失败和原验收门槛。函数指纹专项及S2继续后置；不公开发布，不增加SDK功能。

## 结论与范围

原`0.1.0a1` wheel／sdist在GitHub Ubuntu24.04原生Linux X64宿主、Docker29.0.1独立daemon中完成Debian12三Python版本的固定基础门禁，每版 **311项基础＋16项恢复＋两条starter通过**。测试零失败／错误／实际跳过／OOM，两例starter业务各只写一次；三个容器停止后移除，实际启动／结束时间严格串行。

| Python | 门禁耗时（秒） | cgroup内存峰值（MiB） | 结果 |
| --- | --- | --- | --- |
| 3.11.17 | 161.088 | 286.81 | 311＋16＋2通过 |
| 3.12.15 | 172.964 | 260.58 | 311＋16＋2通过 |
| 3.13.16 | 175.287 | 262.35 | 311＋16＋2通过 |

实际HostConfig与容器cgroup均匹配：2CPU、内存2147483648字节、额外swap0、`network=none`、pids256；内存峰值包含安装与测试，不是RSS。CPU记录为实际配额，不声称已测CPU使用峰值。耗时只描述本轮维护门禁，不是性能benchmark，更不是S2成绩；原阶段600秒和每容器900秒等待上限未改变。

## 可定位证据

- [暂存run 39361602003](https://github.com/RalfNick/ralf-agent/actions/runs/39361602003)，attempt1，checkout `a2d101a94ba9d302fe1741780c76f6b0967f7f4c`，成功。原包artifact为`ralf-alpha1-original-candidate`，ID `12237472617`。
- [原生门禁run 39362466673](https://github.com/RalfNick/ralf-agent/actions/runs/39362466673)，attempt1，checkout `0b9b6c9682c40285d91994cd831aa93d7e814bf1`，成功。证据artifact为`alpha1-native-amd64-evidence-39362466673-1`，ID `12238191415`，ZIP SHA256 `ecc68b81f66dae5f71cda47436fd03bc9fa2dba57c1d3f37e6ccb9da0af60564`，已与GitHub服务端digest核对。
- 原制品源码仍为`ba7bc467ddaa9bd309435bd9a5a015091911ad62`，维护checkout不冒充原包源码。wheel SHA256 `a736993b941213945ed3309de1fc7ed69e7c5ad5033f69b24ce35b8c1c341aee`，sdist SHA256 `bdf626bcee84678395b90a9c2b5bd5815a7c14188131b645b7f5ac337229fd63`，未重建、覆盖或更换。
- `native-host.json`保存宿主Linux x86_64及daemon Linux x86_64，request保存X64、run／attempt／checkout与输入run ID。实际Docker client／server均29.0.1，按平台inspect能力通过。
- 报告复核原制品、四份工具摘要、442产品与939原始测试／示例树、显式Session校正、六份collection完整node身份、JUnit及两条starter。基础node摘要为`e256798bd6320b827682989458e2bf698aed1bbd2c33c7444d4826e528cd0b70`，恢复node摘要为`d9056e7a4290a7fe3674ef49aaf946bb18f69454db414203a238ce6949f4b42c`。

本地原始证据位于`dist/alpha1-native-remote-20261020/`，包含run／jobs、下载ZIP／服务端digest、解压日志与报告、`native-acceptance.json`、`native-node-identities-verified.json`和清理回执。Actions artifact保留14天，取回的本地副本与摘要单独保留；到期需要重新授权暂存原包，不虚构永久下载地址。

## 本轮失败与最小修正

1. 原工作流job级`env`引用`runner.temp`，两次手动请求均被GitHub以422拒绝，没有启动SDK测试。actionlint复现同一上下文错误，改为runner首个步骤通过`GITHUB_ENV`设置匿名Docker配置路径；语义复验通过。修正提交`23a7d37`，两次拒绝、RED／GREEN与原请求保留。
2. [原生run 39362273382](https://github.com/RalfNick/ralf-agent/actions/runs/39362273382)通过原包预检及Docker准备后，AWS公共注册表拒绝镜像下载：`Data limit exceeded`。该run失败，SDK测试未开始；失败日志和artifact已取回。仅将AMD64镜像传输来源改为Docker Hub官方Python仓库，三个不可变多平台索引摘要保持不变，再单独启动上述成功run；没有改镜像版本、制品、资源或测试门槛。
3. 暂存期间匿名可见性探测取得403，不能据此判断是限流还是草稿可见性，原诊断断言保留为不确定结果。认证API核对草稿`draft=true`、`published_at=null`及无Tag。暂存成功后只删除本次专用草稿ID `417951614`，删除返回204，随后草稿与对应Tag均404；没有将草稿发布为Release。
4. 本地维护命令一次误写不存在的测试文件，未收集测试；保留原日志，改正命令后三个维护模块 **106 passed**。未将命令错误算作SDK失败，未用重试覆盖原记录。

原Session测试仍先按原sdist身份核对，再应用已公开的有界Session空闲观察校正：`b04de6c…`→`46d3eb8…`，前后完整SHA见manifest。原Python3.12测试失败、Docker Hub／其他下载失败均保留；本轮结果不改写为原测试未经校正通过。前12组 **1,533** 份历史文件SHA复核一致。

## 交接与剩余边界

必要CI维护提交`a2d101a`、`23a7d37`、`0b9b6c9`已用核验为RalfNick的账号推送，均保留`[skip ci]`；提交只单次跳过本地钩子，未修改持久钩子配置。已核对这三个提交只有一次手动暂存和两次手动原生run，原宽泛`ci.yml`未启动。没有合并、修改分支保护或公开发行。

本批只形成**所选原a1基础SDK在原生AMD64上的实际远端CI证据**。公开PyPI／Release权限与最终Tag、公开下载／安装复验、外部独立采用仍待后续授权或证据；其他平台、复杂Temporal／Coding、真实模型质量、完整第三阶段及长期路线图不由此关闭。函数指纹专项、S2原失败和360秒门槛继续后置。
