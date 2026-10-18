# P3-A 独立候选验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans；独立验证可按既有用户授权并行，共享候选固定。

**Goal:** 验证当前冻结候选的完整离线回归、安装、约定兼容及原服务证据，不将S2后置等同通过。

**Architecture:** 复用当前Local／Temporal唯一执行权威与已验收默认组合，按精确制品复用未受影响证据。
仅修复已复现的验证／SDK阻塞；新候选按实际影响补验，不扩功能矩阵。

**Tech Stack:** 当前442产品、Python3.12、pytest、隔离wheel、原Temporal／PG及不可变旧Worker。

**Spec:** [冻结P3-A](../../phase3-support-matrix.md#固定剩余清单)。2026-10-18用户明确授权“允许独立候选验收，保留S2与阶段未完成”，仅调整顺序，不降低原门槛。仅本地提交，不push。

## Global Constraints

- 基础SDK／dev99／dev113保持冻结；S2原360秒失败及未运行矩阵、P3-A／第三阶段整体未完成保持。
- 不新增后端、拓扑、Runner、平台或质量／对等比较专项；不延长原业务／故障验收期限。
- 失败记录、未确认效果、原额度和实际停止义务保留；只清本批成功资源，旧失败数据不动。
- 完整回归不按排除失败／跳过服务配置伪称全能力通过；没有新变更不重复已有效的模型或服务评测。

## Review Focus

- 旧Worker仅在完整旧status／namespace／类型／原epoch及第二次pinned status后走旧Update；不能泛化失败回退。
- Parent合法outcome_unknown的必要取消不能被错误识别拒绝；取消不清未知效果／预算，也不证明实际停止。
- 网络夹具保持旧Worker行为和真实Run／Registry状态，缺SDK方法不通过放宽产品校验掩盖。
- 候选产品／测试输入在整轮运行前后保持一致；制品变化后不混用前包结果宣称同包全绿。
- 最终候选证据与阶段准入分开，S2原依赖和后置失败不被当前测试数量覆盖。

### Task 1: 已知输入夹具与旧Parent控制阻塞

**Files:** `tests/temporal_agent_fixture.py`、`src/ralf_agent/temporal_command_transport.py`。

- [x] 当前源码复现原A2A输入4失败／12通过，以及Facade输入同因2失败／2通过；原记录保留。
- [x] 夹具只补旧Registry配置观察、SDK describe／原epoch及明确禁止Signals；Run／Registry去重、Scope和原断言保持。
- [x] 受影响84项暴露旧Parent合法outcome_unknown被SDK legacy snapshot识别器拒绝（1失败／83通过）。产品仅加入该既有合法状态，完整shape／Scope／namespace／epoch／两次查询要求不变；10模块123项通过。
- [x] 真实不可变旧Worker同原任务必要取消RED→GREEN，重复回执、unknown／预算和零Signal保持；三份原History由匹配Worker重放。旧执行停止未知不因人工效果核验清除，完整脚本后续等待失败保留；一次集成review无P1／P2。

### Task 2: 固定候选与完整离线回归

**Files:** 当前制品／私有校验清单及原回归结果；不新增产品API。

- [x] 固定442产品、930 Python／JSON测试及必要输入；新目录wheel SHA256为26546603a6bd9370dfc0bca71f48ecc83310ba3d52a8259fd1847d3a62e61ade，不覆盖原包。
- [x] 清除真实模型／远程测试配置的子进程执行一次完整`pytest -q`，不设置排除列表；逐项保留失败／skipped原因，检查输入前后不漂移。
- [x] 真正SDK／数据正确性阻塞按有效RED→最小修复→必要范围复验；最终候选不能以旧425文件全量结果替代。

### Task 3: 隔离安装、兼容及原服务

**Files:** 本地wheel／独立安装、既有服务与默认材料证据。

- [x] 源码／wheel／site全部442产品与两套副本930测试一致；checkout外126项、首用审批／重复原回执／跨进程恢复通过。
- [x] 原Card／完整默认发布SHA及原／continued两份History重放通过；实验selected仍需匹配不可变SDK／Worker。
- [x] 同包真实PG／Temporal／HTTP及原备份恢复25 passed／零跳过（52.825秒）；备份哈希、三个Worker、服务／成功自有资源关闭核对通过。无新模型或压力专项。

### Task 4: 证据核对与本地交付

**Files:** `docs/implementation-status.md`、冻结阶段矩阵、能力／发布说明与本批验收记录。

- [x] 逐项核对P3-A原要求、明确完成／缺证据／后置；S2及阶段未完成不变，当前候选验证不关闭原依赖。
- [x] 一次集成审查、Ruff／格式／空白／凭据检查，必要修复后仅本地提交，不推送。

首轮完整回归固定输入得到13,341 passed／891 skipped／24 failed；七模块夹具缺口及共享namespace污染已有效RED→GREEN修复，产品不变。最终十九模块源码272、隔离安装275零跳过；同包服务25按未受影响输入复用。第二轮完整回归固定最终930测试／20额外输入，13,374 passed／891配置skipped、零失败／错误（JUnit 2224.610秒），产品与输入全程不变。独立候选验证收口；S2／P3-A整体／第三阶段仍未完成。

Pre-flight：Task2消费Task1最终代码，完整运行期间不修改产品或测试；Task3使用相同新wheel。
文档独立核对可并行，真实旧Worker探针在私有独立目录准备，不污染全量回归输入。
