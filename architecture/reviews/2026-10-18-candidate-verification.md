# P3-A 独立候选验证

2026-10-18用户明确允许独立执行候选回归、安装、约定兼容与原服务证据核对，
保留P3-2/S2原360秒失败、全部门槛及第三阶段未完成。这里只调整验收顺序，
不关闭P3-A整体依赖，不增加功能或新的服务矩阵。仅本地提交，不推送。

## 候选与最小修复

原P3-4／P3-5的442产品制品保持不变。本次实际复现两类问题：

1. 原Temporal输入网络夹具缺少SDK识别旧Update-only Worker所需的Registry
   scoped配置、Describe和原epoch固定。原A2A四失败／十二通过、Facade两失败／两通过
   分别保存；夹具补齐观察方法，明确禁止Signal，继续使用真实Run／Registry状态实现。
2. 受影响84项检查随后暴露产品P2：原Parent合法`outcome_unknown`被SDK旧Worker
   状态识别器拒绝，必要取消返回`definition_mismatch`。只将该既有状态加入识别器，
   完整字段、Scope、namespace、workflow类型、原epoch、第二次固定查询和回执校验保持。
   取消不结清未知效果或预算，不证明真实处理器已停止。

最终候选仍是442产品文件（439 Python＋3 JSON），仅一个产品文件变化：
`dist/p3-candidate-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `26546603a6bd9370dfc0bca71f48ecc83310ba3d52a8259fd1847d3a62e61ade`。
相同版本号必须按制品SHA区分，不覆盖旧包，也不把旧425文件全量结果当作本候选回归。

## 本批证据

| 检查 | 结果与实际范围 |
| --- | --- |
| 受影响源码 | 首次十模块123 passed／零跳过；全量暴露夹具缺口后，最终十九模块272 passed／零跳过（15.78秒） |
| 隔离安装 | 首轮126 passed／零跳过（JUnit 11.654秒）；最终测试副本复用同一隔离安装，十九模块与默认Local备份恢复共275 passed／零跳过（JUnit 22.381秒），checkout外site导入 |
| 默认材料与History | 默认Card＋完整普通发布SHA保持`8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`；原与continued两份保存History离线重放通过 |
| 首用 | 独立生成oncall应用，待审批→审批→重复同回执→新进程恢复成功；真实业务只写一次 |
| 同包原服务 | 25 passed／零跳过，JUnit 52.825秒：PG效果清理20、Temporal清理2、HTTP双身份审计2、三阶段备份恢复1；没有新模型或压力专项 |
| 完整离线源码 | 首轮13,341 passed／891 skipped／24 failed（日志2367.12秒），原记录不改；仅补夹具后固定最终输入，第二轮13,374 passed／891 skipped、零失败／错误，JUnit 2224.610秒 |
| 真实不可变旧Worker | 同原任务取消RED→GREEN、重复原回执、未知效果／预算保留与零Signal通过；原SDK三份完整History重放通过。后续旧父级停止未知仍保留，完整脚本失败不计整场通过 |
| 集成审查 | 一次独立代码审查未发现P1／P2；审查不代替完整回归或真实服务 |

安装证据：`/private/tmp/ralf-p3a-candidate-install-20261018`；
服务证据：`/private/tmp/ralf-p3a-candidate-service-20261018`；
完整回归：`/private/tmp/ralf-p3a-candidate-20261018`。
最终输入的回归：`/private/tmp/ralf-p3a-candidate-final-20261018`；
最终安装检查：`/private/tmp/ralf-p3a-candidate-final-install-20261018`。
原失败、原unknown与预算、失败持久数据均保留。连接设置只在私有文件中，不能发布。

## 服务与资源

同包服务使用普通持久Temporal dev server和真实PostgreSQL16；安装测试副本运行，
不是时间跳跃或模型模拟的效果验收。原认证／Scope、效果主回执、重复命令、
History与Registry重放、审批恢复及unknown保留沿原契约验证。
备份恢复仍是受控停写、两次恢复到新空库和新目录，不外推生产HA或任意Schema降级。
服务退出与实际子Worker结束单独核对；仅本批成功自有容器／卷可清理，旧失败资源不动。

源码／wheel／安装的442产品逐项相同。首轮两套副本的930测试输入相同；
后续仅8个夹具文件变化，最终930测试与第二轮源码回归输入一致，20项examples／evals输入也保持，
不把不同测试快照混称同一次运行。`final-audit.json`核对25项XML、两次恢复、自有容器／卷及原服务退出；
连接文件权限为0600，不将凭据放入制品或版本库。

## 首轮全量失败与夹具修复

完整首轮的24失败来自七个测试模块，产品／测试／20项额外输入在该轮前后未变化：

- 11项测试替身缺少必要SDK观察端口，导致原运输绑定拒绝；其中9项维护场景的
  end ACK未能入原History，Owner正确保留义务，关闭继续拒绝。补齐本地旧Worker
  的完整scoped status／Describe／原epoch和显式拒绝Signal，保留原完整Handler与断言。
- 9项直接运行Workflow的测试没有模拟已交付的tool-end-evidence patch事件。
  只为该固定patch补桩，分别覆盖无标记旧History与新History两个分支，原joint6／7、
  timeout／application、unknown及退休后通知断言保持。增加9个参数化用例。
- 4项后续namespace失败来自前序恶意测试污染共享夹具常量。有效RED证明全局UUID
  被改为222…；在原tree夹具中复制namespace，并新增不污染全局的断言，顺序联合恢复。
  没有给后续测试硬编码另一个UUID或降低产品namespace复核。

仅上述夹具修正，没有新产品变化或重新构建wheel。原三模块RED、namespace RED、
各独立GREEN及最终272源码／275安装结果分别保留，不相加改称全量通过。
服务原输入与最终输入的8个变更文件不在四个实际服务测试的25个显式本地依赖中，
见`service-reuse-audit.json`；同包原25项服务证据按其原输入复用，不重复新服务／模型评测。

## 旧Worker窄兼容与保留义务

真实Worker使用不可变基础SDK，旧`1f8efac…`客户端对原Parent的`outcome_unknown`
取消返回`definition_mismatch`，原任务／unknown／预算不变；新候选对**同一原任务**
取得`applied`，重复命令返回原回执，`remote_stop_confirmed=false`。
子级取消后未知效果／预算仍保留，业务calls=1，未向旧History发送任何Signal。

随后原SDK人工核验已将效果日志标为`adopted/operator`，子级reserved／unknown归零、
spent=2，但旧Worker保留`unknown_remote_execution=true`。原Parent最后observe
事件436仍见`remote_stop_confirmed=false`，因此父级cap8继续保留为unknown。
受控handler确实已执行finally，但该旧SDK不采纳外部finally标记作为停止证明；
效果证据不能代替执行停止证据。等待父级quiescent的30秒断言失败如实保留，
没有延长时间、清额度、终止Workflow或把完整脚本标绿。

原匹配Worker离线重放Registry51／Parent442／child37个事件的三份完整History通过，
均零Signal、旧产品未变化。Worker与Temporal进程均正常退出0，持久数据保留。
这证明本次SDK必要取消修复，不声称升级或修复任意旧Worker的后续停止恢复。
证据索引：`/private/tmp/ralf-p3a-legacy-parent-unknown-offline-20261018/evidence-index.json`；
真实RED／GREEN及原失败：
`/private/tmp/ralf-p3a-legacy-parent-unknown-20261018-v2-2533181f`。
首轮因写工具缺少耐久效果日志而在Worker构造拒绝，未开始业务，另保留原目录，
不将该前置夹具失败当作产品RED。

## 收口条件与边界

| 原P3-A要求 | 证据与复用边界 |
| --- | --- |
| 固定候选与安装 | 本批442产品、930测试输入、隔离site与wheel逐字一致；新制品独立目录，旧制品不覆盖 |
| 提交、观察／断连、审批／期限 | 本批oncall首用／审批和真实HTTP双身份场景；原[435产品服务控制](2026-10-16-phase3-control-evidence-audit.md)的断连续接、游标与背压按原制品复用。期限沿原P3-1证据及完整离线回归，不声称本批新增真实期限服务矩阵 |
| 重启、重复控制与恢复 | 本批Local三项备份恢复、真实Temporal／PG两次冷恢复及原命令／回执；旧Worker取消仅按上述窄兼容结论验收 |
| 权限拒绝、安全保留、关闭 | 本批同包HTTP身份审计2、PG20、Temporal2及恢复1；逐项停止／owner／连接／容器证据分开保存 |
| 约定兼容 | 默认Card／完整普通发布不变、两份默认History重放；实验selected只使用匹配不可变SDK／Worker，旧Worker三份History由其原版重放 |
| 原制品证据完整性 | 本批重新核对此前20组`SHA256SUMS`，全部匹配。仅证明原制品字节未变，不把历史失败或未测能力标绿 |
| 完整回归、文档、本地提交 | 本批最终完整无排除源码pytest通过；891项保留原Temporal／PG／Redis／Qdrant／Docker／不可变环境配置依赖原因，见`skip-reasons.json`。最终源码与安装输入固定，文档及制品校验通过，仅本地提交 |
| 第三阶段整体完成 | **未完成。** 独立候选验证不关闭P3-2/S2原依赖和原失败 |

当前候选验证不等于P3-A整体通过。原S2性能及完整所选Session矩阵仍开放，
600秒诊断不替代360秒门槛。实验selected发布仍需匹配不可变SDK／Worker，
未测试任意旧History迁移、新拓扑、真实模型质量或外部开发者采用。
本批独立候选验证已收口：完整回归、隔离安装、约定兼容与未受影响服务证据核对通过，原失败／跳过与旧停止义务均保留。一次产品集成审查无P1／P2，后续仅夹具改动经根因检查与顺序联合验证；Ruff、1374文件格式与空白／凭据检查通过。完成本地提交，不推送。
