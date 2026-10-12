# dev82 被动 Skill 目录与自动上下文验收

基线b3cb8ce／dev81；Task1 66a3080，Task2 c1aa9c9。完整R01–R26继续ACTIVE，仅本地提交。

纯可替换SkillSelector／确定性词项与中文bigram默认选择，借用原SkillCatalogPort的SkillDirectoryRetriever，输出原Knowledge DTO。原KnowledgeContext／每Agent Knowledge资源／Local Run与Temporal History保持唯一采纳和执行权威。metadata permissions=none，正文仍由原授权skill_get Action读取。完整目录有界、Scope／names限制、来源版本和方法身份固定、线程／文件guard由原owner管理。

源码相关153 passed（10.22s）；真实Temporal8 passed（52.18s）零跳过。六类Agent／sequence／Graph／Team／Dynamic／nested在首次模型决策前提供目录，原审批工具读取正文，重启／重复命令／重复审批与History重放；另两项实际File metadata读取阻塞、取消后保留root FD、CloseIncomplete、真实结束释放、重新Worker查询原cancelled且零模型调用。

前两次实际取消失败是测试夹具在Worker关闭后查询，以及共享默认Scope让CommandRegistry指向已关闭旧队列；已使用唯一Scope并在原队列重启Worker，未放宽终态／FD／无模型断言。

固定修复包核心155项（9.86s）／SDK271项（14.72s）、真实源码8项（56.74s）／安装8项（79.48s）零跳过；281模块源码／冻结／wheel／sdist／core／SDK字节相同，核心guide无SDK／YAML实际运行。旧81与新82 Local／CLI／Temporal／nativeSession双向恢复、22模板相同及旧Worker新发布业务I/O前拒绝再次通过；自有拒绝Worker实际exit0并等待。171 CI参数、13变更文档466本地链接通过。原自有Temporal启动进程实际exit0并等待；完整固定源码5089 passed／386配置跳过（845.08s (0:14:05)）。本子集最终验收通过；整体能力目标继续开放。无新模型调用、密钥操作或远端推送。语义Skill选择、自动正文激活、插件／Sandbox／Runner和真实质量继续开放。

唯一fresh Astra只读审查独立57项通过；三项Important（非法页递归复制、raw DTO拷贝伪造、默认查询候选不兼容）在全部finding／八项Declined定级后统一处理。10项有效失败与1项已有成功（1.89s）在产品修复前读取；初步相关74项通过（2.35s），最终完整／安装验证仍待完成。没有第二review，新Minor无延期。

## 裁定与成本

以下保留本批所有裁定原顺序及错误成本；本批没有新增延期Minor。

- Ruling: user continuouscompleteallcapabilities/localcommits/no push authorizes nextwrittenarchitecturalbatch inline withoutrepeatapproval/spec/planmenu — preserveoriginaldesignandhonestsubsetdelivery — costifwrong: revisebeforeexternalrelease, no externalmutation.
- Ruling: implementpassiveSkillsdirectory discovery throughnativeRetriever+exactKnowledgeContext, nothiddenHarnessIO or thirdSkillsstateauthority — originalKnowledge binding/protocol requiresnativeDTOandversionint, alreadysupportsrawmetadata — costifwrong: independentknowledge/skillsroleconfiguration mustbeexplained; metadataonlynotautomaticbody/pluginactivation.
- Ruling: directoryreadScope/names is explicittrustedKnowledgecapability; toolskill_getstillseparateoriginalAgent/ToolSet/skills/hostauthorization — discoverycannotgranttools — costifwrong: usermustconfigurebothreadreferenceandtoolpermission; no silentprivilegeexpansion.
- Ruling: old81HistorymayunderstandsameoriginalKnowledgeContextProtocol; requireactualoldWorkerfixedrelease refusalbeforemodel/toolIOratherthannewbindingmarker — no newHistoryprogressionorDTOneeded — costifwrong: actualcompatprobe mustprovefixedruntimepreIO, notActivityscheduleabsence.
- Task1 expandedpure153PASS6.54s aftertrueRED36651 2FAIL31PASS Unicode/depth. boundedfixed_identity validates4096values/depth16/64kUTF8 BEFORE_plain, no customcopyhooks. Found originalmemory_call syncinline oncoordinator (notthreadbridge); spec assumedwrong. Ruling: nativeSkillcatalog reads use explicitoriginal ThreadExecutionTracker/currentgroup bridge asSkillToolSource does, notmemory_call — actualfilelistI/O mustnotblockobserver orlosehandlerownership — costifwrong: customcatalogmustthreadsafe asoriginalSkillToolSourcecontract; borrowednativeFD closeguard retained. Actualthreadtest43264 trueRED beforebridge, nowgroupretest running; no sourceget/bodyIO.
- Final: Ruling: I1 Important retained — malformed entire page must be bounded/exact BEFORE recursive detachment, not only skills/total; otherwise custom adapter can exhaust eventloop. Cost if wrong: stricter malformed response rejection, original validpages unchanged.
- Final: Ruling: I2 Important retained — raw native DTO source fields must be checked before asdict/deepcopy; scalar subclass can forge expected text while actual differs. Cost if wrong: broken adapters reject rather than disclose forged evidence; valid Chunk/RetrievedChunk remains compatible.
- Final: Ruling: I3 Important retained — original QueryTransformRetriever default128 and union256 must compose with native SkillDirectoryRetriever; reconcile candidate cap256 with pure selector max100 using min(limit,100), validate union≤256. Cost if wrong: candidate recall max100 per query documented, no global Query wrapper/default/History change.
- Final: Ruling: Semantic ranking/recall/multilingual — preserve explicit lexical baseline/no qualityclaim; futureR13/R26 evaluation. Cost if wrong: deterministic matching may miss usefulSkills, clearly open.
- Final: Ruling: Automatic instructions/plugins/Sandbox/Runner — keep separate originalauthorizedskill_get and futurecapabilities. Cost if wrong: fullH4 incomplete, no falsegrant/isolationclaim.
- Final: Ruling: MultipleKnowledge/Skills/Hybrid — separatemultisource design remainsopen; I3 singlewrapper compositionfixednow. Cost if wrong: usersneed explicit oneKnowledge source or customadapter.
- Final: Ruling: ArbitraryPython getter/method — trustedportsnot sandbox; malformed returneddata I1/I2 fixednow. Cost if wrong: hostextension can execute arbitrarycode, no isolationclaim.
- Final: Ruling: UnrelatedhistoricalAPI malformed inputs — constrainonepass to new directory publicboundary and originalDTO/wrappercompat, do not unrelatedrewrite. Cost if wrong: oldAPI hardening remains futurebatch.
- Final: Ruling: Build/install/full/old81/shutdown — retainmandatoryactualfinal gates; candidate core144/SDK260/actual8/old81compat alreadypassed but rerun frozenfixedpackage; full notyetstarted. Cost if wrong: no finaldeliveryclaimuntilfixedactualevidence.
- Final: Ruling: OverallR01–R26 — wholegoalACTIVE, do not markallcompletefrombatch. Cost if wrong: sustained roadmap remains unfinished.
- Final: Ruling: Olddocheading/compressedwording — unrelatedhistoricaleditorial cleanup deferred, lateststatushonestandAPIexplicit. Cost if wrong: historical notesrequire careful reading; no changedbehavior.

完整回归首次误在沙箱内启动，HTTP／Redis绑定失败，及一次并行build与安装夹具冲突均记录为执行器错误；固定代码以正确本地服务权限、串行build条件完成最终完整回归，未放宽断言。
