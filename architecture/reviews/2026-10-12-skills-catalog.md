# dev78 子集验收：Skills 目录与受管理加载

基线ac7b87e/dev77；设计／计划本地提交77e82f9，原Engine／History仍唯一执行权威。
首期同步SkillSpec／CatalogPort、不可变Memory、JSON／Markdown File默认、原生read-only Source和声明工厂，
以AgentSpec.tools／原tool_set选择接入六类编排。专用skills角色、完整YAML／异步加载器和Sandbox仍开放。

Task1：公共API55 true RED（2.50s）→161相关通过（5.18s）；Unicode空白／null offset四项true RED（0.38s）→165通过（0.94s），正式165 passed（1.09s）。
Task2：公共File API26 true RED（0.63s）。首轮116通过／7个fixture错误（1.80s）：os.open包装遗漏supports_dir_fd，旧Workspace正确在分配前拒绝，非泄漏；修正fixture后123通过（1.16s）。返回前文件变化两项true RED（0.83s）→125通过（1.17s），正式125 passed（1.22s）。
Task3：Source13 true RED（修正为合法写策略fixture后0.68s）→86通过（0.82s）；真实File处理器在loop取消后保留原FD、Source关闭等待，既有实现通过1项（0.81s），不声称新增RED。配置3 true RED／6非法适配已拒绝（1.26s）→119通过（1.46s）。普通版本非法Unicode空白／257字节／NUL三项true RED（0.77s）：预检过晚留下Store；追加纯检查后新契约120通过（2.50s）。组间重叠。

六类Local审批重启／原结果复用与不授予指令所提工具：7 passed（1.98s）。
真实Temporal native／sequence／graph／team／dynamic／nested、两次Worker重启、重复审批／保存结果／每成员仅一次读／History：6 passed（23.99s），无跳过。普通read-only工具不需PostgreSQL效果日志。
自有Temporal68464／17280仍供本批安装／冻结验收使用，必须等待原会话停止后才能收口。
版本在真实六项通过后才升dev78。正式Task3、安装、旧77兼容、独立审查和冻结全量仍待完成。

判断与代价按顺序：
- 持续授权覆盖重复spec／plan／finish菜单，inline且只本地提交；代价：判断错误须发布前修订，没有远端授权。
- File默认用明确JSON＋Markdown，避免声称部分YAML是完整标准；代价：标准frontmatter需自定义或后续完整解析器。
- 首期同步Port沿原线程所有权；代价：异步／远端加载器协议继续单独交付。
- 先接原普通read工具再补专用skills角色；代价：selector／自动目录阶段仍有独立设计与准入工作。

未调用真实模型、未推送远端，完整R01–R26保持active。前批实际Temporal阻塞原生写取消窗口Minor没有在本批冒充闭环。

CI argument regression: independent shlex probe true RED exit1 because dev77 quoted two test paths as one argument; split them and add new Skills contract/service paths. This is a confirmed CI gate defect, not runtime failure. GREEN check follows; no product tests for simple reversible CI quoting.

Task4 candidate: previous build/venv session results expired after truncation; no inferred exit claim. Fresh build44310 and offline installs25114/18287 actualexit0. Core85061 120PASS3.87s, SDK91769 182PASS3.65s; old77 Local36905/CLI82210 actualexit0 including22 original starters. 268 source/installed/wheel/sdist modules and dev78 metadata match;730 sdist files match;three installed guide examples,560 local links,144 CI args,pip checks,Ruff988 files pass. Initial service79796 and compatibility69982/7977 failed before connection due sandbox PermissionDenied; authorized local-only reruns21008/57882/31831 pending. No product failure or quality inference. Final readonlyreview/full/freeze/stopwait/commit pending.

Task4 actual authorized reruns:21008 actualexit0/read6PASS24.73s zeroSKIP installed six-composition approval/restart/History. 57882 and31831 actualexit0/read old77→78→77 actual Temporal sequential/native original default Session/Turn/receipt/History and one tool call; child Workers terminated and waited by helper. First sandbox-denied runs remain not counted. Sole fresh strongest read-only reviewer dev78_final_readonly_review dispatched; no product mutation while reviewing. Full/freeze/stop original68464/localcommit remain pending.

Final review regrade BEFORE any product fix: sole dev78_final_readonly_review; Critical0/Important4/Minor0. I1 unbound immutable membership, I2 ordinary-data copy hooks/forged evidence, I3 valid explicit Scope declaration rejected, I4 late aggregate loading bound all remain Important by actual user effect. ONE unified TDD fix pass authorized; no re-review.
Final: Ruling: Dedicated skills binding/selectors/automatic Context — deferred as separate role contract; ordinary managed tools delivered — cost if wrong: cannot label complete R01/H4.
Final: Ruling: YAML/frontmatter/recursive discovery — explicit JSON/Markdown default — cost if wrong: standard formats need future full parser.
Final: Ruling: Async/remote catalogs — sync port only — cost if wrong: remote reliability and lifecycle require separate evidence.
Final: Ruling: Associated resources/Workspace grants — text grants no authority — cost if wrong: must configure each resource explicitly.
Final: Ruling: Plugin/scripts/Sandbox/Runner/network permissions — outside catalog data layer — cost if wrong: catalog does not provide isolation or installation.
Final: Ruling: Skills starter — preserve22 existing starters and installed guide — cost if wrong: first use needs guide/config until dedicated template.
Final: Ruling: Windows/non-POSIX — original POSIX file contract — cost if wrong: other OS default needs tested adapter.
Final: Ruling: Real-model quality/full AgentScope/H4/R01–R26 — deterministic runtime proof only — cost if wrong: full goal remains active and quality unproven.
Final: Ruling: dev77 actual blocked native-write cancellation — prior read-independent evidence deferred — cost if wrong: planned write cancellation still requires real-service probe.
Final: Ruling: Malicious adapter/private state/OS revision forgery — trusted adapter boundary, never excuses I1/I2 public validation — cost if wrong: host must trust implementations; no sandbox promise.
Final: Ruling: Public RalfError messages — original deliberate domain-error propagation, unexpected exceptions redacted — cost if wrong: trusted adapter may reveal intentional public details.
Final: Ruling: Final freeze/services stop — pending required gates, not waived — cost if wrong: no acceptance until actual full/package/stop exits read.

Final unified fix pass:29302 actualexit1/read19trueFAIL; complete22 RED below is authoritative, corrected not-yet-reached Temporal fixture private runtime access and added native-hook/partial-page coverage;17073 actualexit1/read22trueFAIL0.99s beforeproductfix. No fixture failure in complete RED. I1 original scoped metadata scan/digest and membership; I2 recursively ordinary finite JSON detachment before comparisons/copy; I3 pure parser vs None-return validator; I4 remaining aggregate byte allowance before each retained body.49892 actualexit0/read204PASS4.24s. Initial candidatefull50914 interrupted actualexit2 before code mutation, NOT counted as finalsuite. Final full and actual source/fresh installed gates pending; no secondreview.
Final: Ruling: first native catalog operation verifies at most1000 metadata entries within its original actual-handler ownership and caches membership perScope — needed to establish custom-port immutable content evidence without new authority — cost if wrong: first read has bounded extra list I/O; public get/page helpers alone cannot prove complete membership without a catalog reference.

Final observed installed:core142PASS3.32s andSDK204PASS4.35s;83172 actualexit0/read7PASS42.52s zeroSKIP (six compositions plus declared explicitScope default). Actual77 compatibility79597/96221 bothexit0 original sequential/native receipts/History/one read, child Workers waited;CLI97572exit0. Local retry8063 pending after documented temporary helper path/stale starter fixture failure; fresh directory retains all prior evidence.268 final source/wheel/sdist/core module hashes andthree installed guideexamples pass. Full50340 remainsrunning; no finalacceptance/localcommit yet.

## Final frozen acceptance

源码全量实际退出0：4757 passed／357 configured skipped（741.54s），配置跳过不计通过。唯一审查Critical0／Important4／Minor0，全部12个Declined在修复前裁定；22项真实RED→GREEN及相关204通过。核心142／SDK204全新安装、安装真实7（42.52s）无跳过；最终源码六类6＋显式Scope1（5.18s）通过（新增fixture曾误用max_steps，已更正原max_decisions，没有产品缺陷声明）。268模块与源码／wheel／sdist／两个安装一致，三个安装示例、148 CI路径通过；旧77双向Local／CLI／Temporal sequential/native恢复与22模板通过。Local临时helper路径和重跑旧starter冲突已用独立目录重新验证，失败日志保留；初始网络沙箱拒绝未计通过。Temporal原会话68464已实际退出0，停止并等待。仅本地提交，不调用模型或推送；完整目标active。

Final source50340 actualexit0/read4757PASS357configuredSKIP741.54s. Skips NOT counted as proof; seven actual service cases independently verified. Final: fixed I1 immutable membership / I2 ordinary snapshot hooks / I3 explicit Scope validator / I4 aggregate loading — tests/test_skill_review.py22 RED→GREEN; complete suite4757PASS357configuredSKIP. All required candidate/final installed/default compatibility/source service evidence observed; original68464 stopped actualexit0. Only documentation closure and rebuild/localcommit/formalTask4/archive remain.
Final: Ruling: formal Task4 command runs204 final installed contracts after already observed full/source/service/compat/package/stop gates — plan gives acceptance classes but no exact final command; this is original task3 set plus22 review regressions — cost if wrong:204 alone is not proof of wholeacceptance, so independent gates remain explicitly recorded.
