# Alpha 3 本地发行与 PyPI 准备验收

日期：2026-10-22。用户授权准备 `0.1.0a3` 新品牌、PyPI 元数据、手动发行工作流、相关测试和本地安装；完成后单次跳过钩子本地提交，不推送、触发远端 CI、配置账号或公开发布。不扩展 SDK 功能，a2 原包和历史失败保留。

## 验收范围

本批独立构建新的 wheel／sdist，SDK 产品仅版本赋值不同。发行名、导入、CLI、运行依赖、存储和执行身份保持。a3 外置 manifest、构建输入快照与交付目录分别固定，a2 默认 manifest 和历史工作流不切换为 a3。

最终推荐制品位于 `dist/alpha3-candidate/`，来源父提交 `01f49b1069347ab5fa01fccfcb41a05dce8f8c3b` 加本批逐文件固定工作区，不声称父提交已包含a3。最终构建输入为2028文件、442产品、968测试输入；验收后的维护记录允许追加，不回写原sdist快照。

| 原包 | SHA256 |
| --- | --- |
| `ralf_agent-0.1.0a3-py3-none-any.whl` | `f896e548ce26ba0d2e171d56f232ad818b32a2db1c50ed87d10dafe04ddd860d` |
| `ralf_agent-0.1.0a3.tar.gz` | `1983effb0479af60fcc5227202f40c40c50a9f110bfe693c6d4911e80d2dcfbc` |

最终外置manifest SHA为`54f6f06c8a272e34b683c7bbbf44bee1870cdac4bda2ce9c4546ea29b4169ea5`；构建输入manifest SHA为`f36c29abdfd852a6343df3be844ee02e984a5ad9b9e9d038d48157b26bfaad58`；来源回执SHA为`b24f72dc2ec6b48f01b9555bf3c40457fa0f15a638df398893842aa598caeebb`。SDK逐文件对照a2，仅`__init__.py`中的版本赋值变化，其余441产品字节一致，运行依赖及许可证不变。

## 实际本地结果

| 范围 | 结果 |
| --- | --- |
| 发行工具、工作流、包展示与原a2维护契约 | 源码159通过，零失败／错误／跳过；YAML、嵌入Python及Bash语法核对 |
| 最终两包安装门禁 | macOS15.6.1／ARM64／CPython3.12.7；原17依赖离线哈希锁，311基础＋16恢复通过，零失败／错误／跳过；151.434秒 |
| 原wheel两starter | 审批／崩溃恢复各通过，每case只写一次业务 |
| 最终sdist独立重建安装 | 离线重建；442产品、METADATA／入口／许可证一致；独立安装155通过、零失败／错误／跳过；两starter各一写 |
| 连续示例 | Agent／Session／RAG／Facts／Workflow五阶段成功；重提相同命令取回同Run和结果，新增模型调用0；Session下一Turn读取前史 |
| 发行格式与元数据 | Twine7.0.0对最终两包`check --strict`通过；新品牌／新仓库、Apache-2.0／LICENSE／NOTICE、README绝对链接和不失真的发行状态另核对 |
| 网站 | Node25.6.1；12测试、14组双语来源；Astro28文件0错误／警告／提示；32页面、28搜索索引页面、1925本地链接／资源；原a1教程基线不变 |
| 工程与原证据 | Ruff检查及1420文件格式检查、Git空白检查通过；a2交付50项、公开交付249项、追加验证248项摘要分别匹配 |

各范围有重叠，不相加为全量或同包服务矩阵。本批未重跑全项目14k回归，没有调用真实模型、启动真实Temporal／PostgreSQL或Linux容器；没有远端CI、账号配置或上传。

## 审查、失败与处理

独立只读审查未确认P1/P2。两项非阻塞问题在冻结前补齐：发布检查器不再把已核验的原生门禁／远端CI写入`pending_external`；新增仅替代网络读取的CLI组合测试，实际执行来源、报告、文件和预检，验证四类拒绝不会暴露可上传candidate。回执断言先1失败／4通过，最小修正后同一5case及最终159项通过。

首轮构建后，最终Ruff检查发现新增测试共享夹具的导入触发I001／F811；修正为模块绑定后全仓Ruff通过。该首轮sdist SHA为`f705accaf673c06d08ab554a40ec391175da34ad5899232c9e56bd6b1ff729a2`，其通过的局部安装报告仍保留，但该源码包未放行，不推荐、不用于上传。随后从修正输入重新构建并按相同门禁完整复验最终两包，未拼接两轮成绩；两轮wheel字节恰好相同，不据此复用sdist资格。

网站初次来源锁检查按设计拒绝5组受影响页面；核对双方语言及来源后更新锁，教程仍固定原a1。首次Astro同步试图写全局telemetry配置被沙箱拒绝；保留原日志，仅对重验进程设置`ASTRO_TELEMETRY_DISABLED=1`，不改全局配置，原网站检查和构建通过。上述记录及未放行构建保存在交付证据中，不覆盖历史。

## 未执行的外部步骤

原a2默认manifest及历史工作流逐字节保留；新a3必须显式选择新manifest。三条新工作流只手动触发，Action固定40位提交，checkout为dispatch的不可变SHA。PyPI流程核对同仓库ID／同SHA／准确run与attempt、三版原生报告、资源和容器移除、工具及原包摘要；跨job转交后再次核对两文件集合和SHA，发布job不checkout或重建，只在所选环境内申请OIDC。

尚未验收a3的Linux ARM64／原生AMD64三Python平台；保持2CPU／2GiB／swap0、串行断网和原node身份。需要先完成获准的平台复验、必要推送、账号／Publisher配置、TestPyPI演练、正式上传和公开安装核对，不以工作流存在或a2成绩代签。账号字段和人工核对步骤见[PyPI指南](../../docs/pypi-publishing.md)。最终本地提交由Git记录及交付`local-commit.json`核对，不推送、创建Tag或公开发布。

## 保留的历史边界

a2 GitHub Release／Tag／两包、原失败、S2 dev19 的 18/18、既有指纹和真实模型成绩均按原制品保留。a3 本批不连接真实模型或服务，不恢复旧未知义务，不获得新的旧 Worker／跨平台 S2／完整 M1 资格。
