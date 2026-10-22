# 0.1.0a2 本地 Alpha 交付收尾

日期：2026-10-22。用户授权采用包含近期修复的新Alpha，统一版本、wheel／sdist、固定门禁和发布文档，完成本地安装后单次跳过钩子本地提交；不扩功能，不推送、公开发布或触发远端CI。

## 结论与范围

当前推荐本地候选为`0.1.0a2`，目录`dist/alpha2-candidate/`。SDK以`8e09ec7`／dev19为基线，442个产品文件中仅`__init__.py`版本赋值改变，pyproject也仅版本字段改变。依赖、Schema、协议、执行权威与业务门槛未改。

当前源码来源明确是基线加本批发行工作区，不冒称原Git提交已包含a2。`source-inputs.json`固定2,002份声明输入、442产品及964测试／示例输入；网站及其未跟踪工作流／计划排除。后补验收记录属于维护交接，制品仍绑定上述构建快照。

| 最终制品 | SHA256 |
| --- | --- |
| `ralf_agent-0.1.0a2-py3-none-any.whl` | `dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46` |
| `ralf_agent-0.1.0a2.tar.gz` | `8a6be717541117ce8cecf4135ba5442936b3192b9d1967d5c79ca90511a35cc8` |

两包产品与冻结源码一致，sdist包含当前教程、许可证、NOTICE及测试辅助。sdist所含门禁manifest是构建输入快照；最终制品SHA固定于外置manifest，避免自哈希循环。外置manifest的`source_inputs_sha256`为`d0c3ea645e07a4f12606a140c624a06b1284fe8173195e68f91babcfe5526e93`，构建输入manifest摘要为`d21e4c1c6038b08f84acd067d51bdeb1ddf3caee703b4a10c2d7aac25072f079`。交付`gate/`携带原基础门禁、Linux包装器、原依赖锁、最终manifest及历史a1 manifest；源码预检在对应维护checkout执行。

## 本轮实际验证

| 范围 | 实际结果 |
| --- | --- |
| 发布维护测试 | 109通过，零失败／错误／跳过 |
| 最终wheel离线隔离安装基础门禁 | 311通过，显式保留原1项Temporal deselect，零失败／错误／跳过 |
| 最终wheel独立恢复门禁 | 16通过，零失败／错误／跳过 |
| 最终wheel两条starter | 正常审批恢复、业务提交后进程死亡恢复各只写一次 |
| 最终sdist离线重建及安装 | 442产品、METADATA／入口／许可证等值，pip check通过；116安装检查通过，另两starter各只写一次 |
| 本地交接预检 | 返回0、`passed_local_preflight`，复制后两包SHA核对通过，`publication_ready=false` |
| 工程检查 | 全量src／tests／tools Ruff与格式通过，a1两工作流actionlint通过，文档链接和Git空白检查通过 |

平台为macOS ARM64／CPython3.12.7，不声称具备Linux容器的CPU／内存限制。最终原wheel门禁总计161.250秒，完整使用原311／16 node身份、两starter和原17依赖锁，禁止联网补包；安装模块确认来自独立site-packages。sdist重建安装在无SDK源码目录的检查根执行，116项是109维护检查加7项连续示例检查；不将不同范围相加为全量SDK成绩。

sdist重建wheel摘要为`dfac0e38b2a879d8eb0c23dd5889774a0d64860c9ffe1945f9ef945629f95a46`，与交付wheel摘要一致。原安装及重建安装各自取证，不以一次安装替代另一制品验证。原dev19完整离线13,991通过／891跳过、S2同包18/18及原History资格只引用[原记录](2026-10-21-s2-session-parent-hints.md#最终核对与交付边界2026-10-22)；本轮没有重跑S2、函数指纹专项、真实模型或外部服务。

## 原失败、审查与历史保留

新增发布契约先得到5项有效RED，再完成109项维护GREEN。构建前断言曾误以为当前Session测试仍是原a1的校正前字节；实际`8e09ec7`已包含原校正后SHA，故新a2不再重复改写测试，原a1规则逐字节保留。该失败发生在构建前，没有生成包，记录在原closeout根。

独立只读审查发现1项P2：安装文档虽推荐a2，目录／SHA链接仍跳历史a1。首包的实际311／16／2及重建116通过保留，但不作为最终sdist验收。修正锚点后使用新的隔离根导出、构建，并重新完整执行本页的最终两包门禁、预检和重建安装。最终sdist实际含`#当前a2本地交付`；原首包和回执保持在`/private/tmp/ralf-alpha2-closeout-20261022`，最终根为`/private/tmp/ralf-alpha2-final-20261022`。本地交付保存关键前次记录及摘要，不混放两份同名sdist供用户选择。

原a1 wheel／sdist摘要仍为`a736993b941213945ed3309de1fc7ed69e7c5ad5033f69b24ce35b8c1c341aee`／`bdf626bcee84678395b90a9c2b5bd5815a7c14188131b645b7f5ac337229fd63`，原manifest与基线逐字节一致。两个仅手动触发的a1工作流固定checkout至原验收`0b9b6c9682c40285d91994cd831aa93d7e814bf1`，继续使用原a1产品与工具，不能借当前默认a2 manifest处理旧包。没有新增或启动a2远端入口。

## 尚未放行

- 新a2的Linux ARM64与原生AMD64／Python3.11–3.13基础矩阵，及跨平台受影响指纹资格；保持2CPU／2GiB／swap0、串行、门禁容器无网络，不继承原a1成绩。
- 经后续授权的远端CI交接与实际运行；现有a1工作流不是a2入口。
- 发布项目／账号权限、最终源码与Tag、经授权的公开发行及公开安装／审批恢复复验。
- 独立采用、完整M1、R01–R26和企业全范围；S2旧未知异常、旧Worker及原效果义务限制保持。

当前只放行本地候选交接，`publication_ready=false`。证据和精确两包在交付目录，制品不加入Git。完成后只进行单次跳过钩子的本地提交，持久hook配置不改；到远端CI交接边界停止。
