# dev58 Temporal Facts 绑定与召回验收

基线6c69cb8/dev57，用户授权持续开发与仅本地提交、不推送。范围为原执行权威中的 Facts 读链路；完整 R01–R26/H1–H5 目标保持，未关闭全部能力。

## 实现

TemporalRuntime显式 Facts backend／纯 recall planner／MemoryRecallPolicy，FactsBindingResource namespace allowlist、每 Agent inherit/ref/disabled。
复用原 Context Activity 与 temporal-3 History，新增 opt-in facts_protocol=1；默认-off temporal-1/2/3 manifest不变。
原生、顺序及图/Team/动态DAG/嵌套实际Agent沿原子树绑定，不创建Local权威或第三套状态机。
来源Facts/Knowledge/recall receipt分开，普通与managed finalize公共采纳固定原字段、digest和预算。
多页预先分配总量并保持query，拒绝snapshot变化、循环cursor及重复记录；Facts版本/值/TTL在新模型前复核。
原生SQLite路径/connection、Redis client/pool/prefix/address/DB、PG connection/address固定，不公开密码；SDK资源borrowed。
最后Facts await在History admission前，期间取消不能派发模型；已采纳模型响应保留历史效果，不因新事实重跑。
Worker继续显式SDK工厂；未宣称自动Temporal RuntimeProfile装配、共享Session或Knowledge selector。

## 复现、审查与服务

原生/managed最初4项RED：Temporal拒绝Facts binding；实现后范围、恢复和新派发前来源变更通过。
只读review复现3项P2：远程实际资源未固定、多页query破坏cursor、finalize可重分类来源。
均修复并有定向测试；复核41 passed、未发现新增P1/P2。额外unknown protocol和普通采纳分类RED→GREEN。
纯状态与原Temporal相关回归229 passed/70未配置服务跳过；安装实际wheel、源码目录外94项通过。

复用此前SHA256验证的官方Temporal CLI1.9.1/Server1.32.0，SDK1.34.0，独立任务数据库。
12个新增真实Worker-kill组合通过：native/sequence/graph/team/dynamic-DAG/nested × plain/managed。
原生在安全read意图期间退出；多成员在下一read前退出，前一已采纳成员不再召回/调用模型，后续保持原namespace。
原始History replay通过。源码12项76.50s，安装wheel目录外12项74.96s。
原有binding4和managed-context/artifact12共16项通过（147.40s），保留file/SQLite与取消覆盖。

服务验证期间修复两处实际沙箱问题：selector校验调用外部数据模块导致重复Scope类型；纯Facts证据模块在Workflow加载后导入触发warnings-as-errors。
现在selector校验是Workflow纯JSON，证据模块预加载并加入passthrough；未关闭sandbox或警告检查。
初始在model Activity挂起时kill得到未知模型失败，保留该正确语义；最终恢复测试选择可重试read窗口，没有新增模型重试。
早期服务失败/中断与修改期间的旧进程结果不作为成功验收。仅最终stable/installed/原组合日志计入。

真实任务Redis和官方PG16.15（复用已验证源码构建，仅0700 Unix socket）另验证async scoped recall、TTL排除、Unicode、大整数文本、snapshot restore、stale拒绝与PG物理connection替换拒绝。
这是Activity/state与实际数据库组合，不是跨机器Temporal部署、嵌入模型质量或所有数据库矩阵。
两个服务runner已正常stop/exit0；PG stopped=0，Temporal stopped marker确认。fixture Redis由自身finally关闭。

## 发布与门槛

wheel/sdist构建、200个source/wheel/sdist/installed Python模块逐字节一致。
独立Python3.12 core-only venv无redis/psycopg/temporalio/tokenizer/pdf；配置离线全库索引、Agent引用、原Run恢复和Temporal纯注册通过。
真实57→58→57默认Run/Manifest、SQLiteArtifact和21starter比较通过；temporal-1/2/3 default-off manifest亦逐字段相同。
CI显式纳入新Facts与原绑定/压缩实际服务测试，但未运行远端CI或发布。

首次全量在源码版本更新前已加载dev57，最终1 failed/3416 passed/119 skipped（483.48s），唯一失败为SDK版本与当前pyproject dev58不一致。
已固定代码与版本，最终全量58529已exit0：3417 passed/119 skipped（577.74s），-W error启用。119项为未配置PG/Temporal/Qdrant等服务组合；上述实际服务专项证据独立记录，不能替代全部部署矩阵。更早受限沙箱端口错误的中断不算通过。
Ruff、724文件格式检查、Git空白检查通过。只有默认读取/恢复子集验收，不关闭整体目标。

日志与脚本保留在任务目录 /private/tmp/ralf-agent-dev58-7f724wa1，pointer /private/tmp/ralf-agent-dev58-current。
未调用真实模型，不宣称语义质量或AgentScope/LangGraph对等能力胜出。
下一依赖是Temporal Knowledge namespace/源视图，再推进Session/其他绑定与索引生命周期及H4/H5；完整H1/H3/M1/R01–R26仍未完成。
