# Alpha 2 原生门禁与公开交付

日期：2026-10-22。用户明确授权继续完成a2原生AMD64／远端固定CI、Temporal指纹单项、公开发行和公开安装核对。此前“到远端／公开边界停止”属于前批授权，本轮已替代；不新增SDK功能，不修改原制品和历史失败。

当前结论：原生门禁、Temporal指纹单项、[GitHub Alpha预发行](https://github.com/RalfNick/ralf-agent/releases/tag/v0.1.0a2)及匿名公开安装已完成。没有重建原包或新增SDK功能。原两包与前批证据分别保留。

## 固定输入与账号

- wheel SHA256：`dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46`。
- sdist SHA256：`8a6be717541117ce8cecf4135ba5442936b3192b9d1967d5c79ca90511a35cc8`。
- 第2版manifest文件SHA：`3ca383ed405745909fa8e84bd40a2b79d2b080dc249cfbc0f96b6d12298cb7da`；SDK442产品和原交付50项摘要不变。
- GitHub默认凭据只在内存使用，经`/user`核验为RalfNick；公开仓库`RalfNick/ralf-agent`具有admin／push权限，初始无Release。没有输出或保存令牌。
- PyPI项目查询404，未配置PyPI发布认证或核验项目控制权。因此本轮采用GitHub预发行，不宣称普通`pip install ralf-agent`可用。

## 暂存与原生AMD64

复用已有暂存函数，按固定a1／a2版本选择各自私有草稿前缀；未知版本及跨版本前缀拒绝，原a1工作流不改。新增a2工作流仅手动触发，固定工具提交`dfb066e111b2ca9cbace7b4c29fb4abdacd04e9b`，原包来源和运行请求提交分别记录。工具更改RED为3失败／12通过，GREEN115通过；工作流RED3失败，相关GREEN118通过，YAML／Ruff／空白检查通过。独立只读审查未发现必须修正的P1／P2。

必要提交`3a92720b63c5ac5aa27edc33a18b8d03396a81ff`经核验RalfNick后快进推送，保留`[skip ci]`，未请求宽泛CI。临时未公开草稿ID420266190仅有原两包；[暂存run39715289979](https://github.com/RalfNick/ralf-agent/actions/runs/39715289979)实际成功，ZIP与原两包摘要、草稿proof均复核。

[原生固定门禁run39715385289](https://github.com/RalfNick/ralf-agent/actions/runs/39715385289)在Ubuntu24.04 X64宿主、原生Linux x86_64 Docker29.0.1中通过。每容器实际2CPU／2GiB、swap0、pids256、`network=none`，Python严格串行；镜像、17依赖锁、原包、311／16完整node身份及第2版测试校正均保持。

| Python | 基础 | 恢复 | starter | 门禁秒数 | cgroup内存峰值MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3.11.17 | 311 | 16 | 2 | 158.439 | 288.33 |
| 3.12.15 | 311 | 16 | 2 | 167.990 | 261.23 |
| 3.13.16 | 311 | 16 | 2 | 172.024 | 262.90 |

实际JUnit零失败／错误／跳过，零OOM，两starter每例业务写入一次。StartedAt／FinishedAt验证串行，三自有容器已移除。取回证据ZIP SHA为`f3c3374cf6de1e9a2ba45204888eb97786f7f82371d2e3905f7af0d1aa141f3a`。不把配置存在或Actions绿灯单独当作验收。

## Temporal指纹单项

原六模块97项中缺依赖的`test_static_and_dynamic_runtime_inventory_digests_keep_original_algorithm`，用同一a2原wheel及原测试，在三个独立ARM64容器中分别执行1项通过、零失败／错误／跳过。保持2CPU／2GiB／swap0／无网络和串行；三容器退出0并移除，峰值319.74／289.26／287.73MiB。

基础17依赖之外，使用固定Temporal1.34.0、protobuf7.36.2、types-protobuf7.35.1.20260906、nexus-rpc1.4.0，下载文件与官方PyPI SHA核对后写入独立哈希锁，容器内仅离线安装。没有连接Temporal服务。每个解释器分别与原摘要算法对照，不承诺不同Python产生相同摘要，不等于任意旧Worker可接管。

该单项与前批最小SDK的96项分别报告，不拼为同一环境97项全绿，也不扩展为全部指纹库存／CONTROL性能／Linux S2资格。原缺依赖失败保留。

## 额外源码回归与原失败

首次额外无筛选回归在受限沙箱中被本地socket／CREATE监督权限拒绝，1136通过／23失败／40跳过／3错误后中断；原日志、JUnit和失败名称保留，不算完整回归。随后在允许本机IPC与进程检查的环境运行相同全量命令，未改产品或测试；最终无筛选源码回归14,003通过／891按原条件跳过，零失败／错误，2442.10秒；与原中断轮分别保存，不拼接通过项。

前次pytest路径下未再发现存活进程；临时防空闲睡眠保护仅绑定新pytest PID，随进程结束，不改全局电源设置。原a1、a2各轮失败及S2未知义务均不删除。

## 公开交付回执

2026-10-22 03:50:51 UTC，RalfNick将本轮草稿420273198公开为`v0.1.0a2`预发行。Tag经原子创建固定`3a92720b63c5ac5aa27edc33a18b8d03396a81ff`，不是移动的分支；最终文档维护不移动Tag或改变原制品。只发布原wheel、sdist及两包`SHA256SUMS`，未上传测试数据库或整个dist。制品冻结来源、Tag验收代码和文档维护提交分别管理。

公开资产ID为wheel664536750、sdist664536798、SHA文件664536897。三者匿名HTTP200，前两包SHA与原制品一致；SHA文件摘要`1ff4d9395de15d0cd6cfc2b83b5596a79b184f21d2e5063e27955a8a071f4fe8`，内容只列原两包。原制品2458个文件的凭据形态和私有文件检查无命中；这不是一般安全审计。

在源码目录外新建macOS ARM64／Python3.12虚拟环境，通过[公开wheel URL](https://github.com/RalfNick/ralf-agent/releases/download/v0.1.0a2/ralf_agent-0.1.0a2-py3-none-any.whl)及SHA片段实际普通pip安装，基础依赖正常从官方PyPI解析，`pip check`、CLI／元数据版本及442产品树一致。未使用GitHub认证或模型密钥，未借用宿主site-packages。实际普通解析的certifi为2026.10.19，与冻结门禁锁2026.10.18分开记录，不能混成同一安装配置。

两条原starter检查复用原sdist测试函数：普通审批恢复及业务写入后进程退出77再恢复均成功；重复提交回到原Run，每例仅一次业务写入。父级维护环境只提供原测试函数，所有应用子进程使用新用户环境；CLI子进程清除凭据／PYTHONPATH。另用该用户环境执行原连续示例Agent、Session、RAG、Memory、Workflow五阶段，各首次成功，重提同命令得到原Run且新增模型调用0。

该公开普通安装成绩不替代冻结Linux依赖矩阵，也不等于真实模型质量。原sdist的本地离线重建与安装116项仍按原SHA引用，不称本轮重建或公开sdist安装的新成绩。

本地原始回执、脚本、官方依赖SHA、原失败和新报告统一追加到`dist/alpha2-public-release-20261022/`，不覆盖原交付或前批追加证据。暂存Actions artifact保留14天，过期复验可从公开入口取得精确原包，核对SHA后按固定工具／锁执行；不能重新构建同版本替代。本轮临时未公开草稿420266190已删除，对应暂存Tag不存在，公开Release保持，未知资源未删除；源码提交3a92720的实际工作流只包含上述两次手动运行，未执行宽泛CI。

完整M1、独立采用、真实模型扩展质量、任意旧Worker、Windows及长期路线图不由本次发行验收。dev18未知异常与旧Coordinator重放限制继续保留，详见[当前验证清单](../../docs/alpha2-validation-status.md)。

最终独立只读审查未发现必须修正的P1／P2；账本完成记录已按实际发布、匿名安装和暂存清理补齐。代码、原包和Tag均不因此改变。
