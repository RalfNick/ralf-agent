# Dev113：顺序与递归 Temporal Coding 验收登记

状态：所选门槛已验收，随本地提交冻结第二阶段。第二阶段范围由[支持矩阵](../../docs/phase2-support-matrix.md)固定；第一阶段dev99保持冻结，完整R01–R26不因本批完成。

## 实现与审查

Team／Dynamic成员接受Agent、sequence、静态Agent图、Team、Dynamic；既有静态图DTO保持Agent节点。原History逐层管理自己的直接child，SDK实际parent／epoch／namespace、原request／release、cap／depth／revision均固定。祖先准入回溯唯一原Registry；停止采用后代先排空、直接父层采纳、再向根收尾的顺序。PG资源仍只存证据，预算结算、准确效果与物理结束分别检查。

实验发布native6／binding22、composition7／binding23；旧20／21需要immutable dev112 Worker，禁止改标恢复。所有新增纯规则与SDK helper加入手列指纹。默认非Coding发布兼容检查保持；最终安装与历史门槛分开记录。

独立review发现并通过有效RED修复两处：注册只检查直接父而未检查祖先准入，以及父级取消RPC失败会抑制其他已确认后代的清理。注册在guard前后复核祖先／根，关闭保留失败并继续其他义务。复核未发现新的具体P1／P2。深PG原记录测试覆盖fenced资源不消失、祖先采纳失败及原epoch重试；这些SDK夹具不作为真实服务证据。

## 当前已取得的证据

- 纯树／链接／绑定／停止：新增30项，组合状态114项通过；SDK控制新增16项通过，含旧控制组合52项的review修复复验。配置／publication组合449项及状态／connection153项有重叠，不能相加当作独立总量。
- 完整风险回归：632个模块全部覆盖，原结果**10220 passed／704 skipped／2 failed**；395产品源码与资产字节全程未变。两个失败是supervision/resource-safety现行测试仍期待旧20／5；定点更新为22／6，完整两个模块源码8／安装8通过。保留原失败和测试变化，不称原全量绿色，不进行无理由全量重跑。
- 原安装focused为375 passed／1旧publication断言失败，随后上述修订8项安装通过；产品导入origin来自独立site-packages，测试origin来自checkout外installed-check。
- wheel的395产品文件与源码／独立安装逐字节一致，SHA `687c3a76d4f68b069c66e45e8584ac792866abdaffb70cbe7737c1ac4e74f0df`。源码／wheel同一冻结实现，不含私有服务配置。
- immutable dev112原21 Dynamic DAG审批冷恢复1项通过（60.76s）；当前validator拒绝真实原21和伪改22／23。实际原History保存，不在新代码中重新解释旧Run。

主证据目录 `/private/tmp/ralf-agent-dev113-root`。未调用真实模型，不新增质量成绩；第一阶段及dev109有限Coding质量按其原冻结配置复用。

## 实际服务失败与配置区分

专属loopback Temporal／PostgreSQL服务用于新增六项：Team→sequence与Team→Dynamic→Team→sequence，各含审批重启、运行取消、owned关闭；plain步骤禁用ToolSet／Runner，Coding步骤精确注册资源引用。

首次source因sandbox连接权限拒绝，六项未进入业务；权限审核超时记录保留，有界重试获准后执行实际场景。这些不计为业务测试通过。

实际30秒Runner配置首项失败：审批冷重启后已完成prepare／Thread／Turn授权及回执，Tool响应`runner_outcome_unknown`，没有result_candidate。原History证明leaf进入waiting_reconciliation、单attempt、fenced=True、pending_stop=False；清理后leaf取消且physical_stopped=True，原CID移除、实际worker结束。此轮在final断言失败后销schema，原PG行未及时保存，不能事后宣称具有原PG行证据。

仅新增六项改用固定60秒Runner、80秒Activity／drive配置，原案例30／40保持。新独立scope首项Team→sequence审批冷重启通过：两份原History replay、单Action／attempt、native提交2／auth方法3、原容器移除。次项在等候Turn目标窗口时仍使用旧30秒观察期限而失败；capture保存了清理前原History／诊断及PG非敏感字段，原Thread已确认，Turn尚未记录。该等待不是业务截止时间，后续新场景按80秒观察，仍必须达到原两次提交后才执行取消；原失败不删除、不合并为成绩。

该次快照的最终六项固定配置、递归取消／owned关闭、安装包实际验收和服务关闭尚未通过；当前最终结果见下文收口证据。原unknown任务不重新派发，后续测试使用独立参考scope／工作区；源码未因这些期限窗口而修改。

后续固定60配置的顺序成员运行取消通过；三层嵌套审批重启仍失败，原leaf在60秒整体期限后保留unknown，80秒Tool Activity结束未采纳candidate。四份原History、四层诊断／proof及PG非敏感字段在清理前保存；根仍运行、下层保留unknown，assembly关闭没有完整确认。旧测试finally随后停止Workers并删除测试schema／socket，不能将其描述成SDK正确关闭；原失败记录及证据保留。后续故障fixture必须在CloseIncomplete时保留原后端和控制证据，以便有界原配置收尾。

针对这一所选链路阻塞，库存warm测量native约0.006s／composition约0.013s，不能把全部时延归因于反复SHA计算。祖先遍历每层重复查询已验证的current child proof。定点提取完整intent校验，pinned热路径只在本次遍历复用不可变身份；父状态、根准入、原grant仍fresh，cold discovery及关闭时物理证明的新查询保持。RPC次数有效RED后283项受影响检查通过，独立复核未发现新具体漏洞。该次优化后实际性能／嵌套门槛尚待新鲜scope重验；后续完整发布校验优化及最终通过结果见下文。此前全量及wheel证据仅属于优化前快照，该次源码改变的两个helper文件不得沿用“最终字节一致”结论。

优化后独立scope的三层审批重启（attempt05）仍失败，136.48s；固定60／80／观察80未变。Tool Activity实际完成于78.751s，返回`runner_outcome_unknown`；Thread授权在schedule后67.497s才被接受，没有原生业务提交、Thread回执或candidate。四层状态均传播unknown／waiting_reconciliation，physical证明仍false。ControlActivity约0.5–0.6s，排队约6ms，不能宣称RPC减量已改善实际性能。

本次故障fixture在assembly关闭失败后保留原PG schema、socket路径与原配置／四份History／恢复句柄；两原Worker以及gate、broker共四个PID已退出，原CID移除。socket监听FD随测试driver退出，保留路径不意味着监听器仍存活。逻辑运行与容量义务仍未完成，禁止据进程退出宣布关闭成功。私有证据为`source-recursive-attempt05-diagnostics-summary.json`与`source-recursive-attempt05-rescue-handles.json`；完整采集无read failure，未泄露synthetic canary。

优化后wheel SHA为`3698e40b6e44bcb455e7e7669aba2bda25e137968cfc2ca9c27388efbf461568`，395产品文件与源码／独立安装一致；它不代表新增实际服务门槛通过。后续按真实时间线定位Worker内校验成本，当前阶段继续保留未验收状态。

完整发布校验的纯host基准定位到重复Runner深度库存构建：单次校验约97–112ms、重复10次Runner检查与4542次可执行指纹。新增只针对无默认值、闭包、包装器的静态函数的有界CodeType摘要复用；每次比较当前代码和缓存helper，动态配置保持原算法。新增8项覆盖算法逐库存等价、代码／配置／helper漂移；独立review未发现所选范围具体P1／P2。完整Runtime基准当前约67ms，未将其当作实际服务成绩。

CREATE新增helper逐项指纹；当前wheel SHA `3c3b39d8ed794cdd2aeb4f759975e93ef8c9c595dcbc63e63a3caa9c1d66456f`，395产品字节已核对源码／独立安装相等；原3698快照保留用于原运行匹配。受影响源码组合242项、库存／资源191项有重叠；清理源码／安装20项也有重叠，不相加作为全量。清理新增自动回归证实Worker退出不确定也保留恢复资源；原attempt05 fixture快照仍原样登记。固定期限的当前source attempt06／07在六个独立参考scope全部通过：三层审批、两个拓扑各自的运行取消与owned关闭，以及顺序成员审批。18份原History replay、12份原edge证明、每例native提交2／auth3、单Action／attempt、PG效果／物理状态按场景分别核对，有界关闭均有原记录。六个测试schema清理已确认，原失败05的schema／socket路径继续保留。三层审批Tool结果在55.438s内采纳，原60秒业务期限保持。安装包六例也已独立通过，包／测试导入origin来自checkout外的独立安装路径；共36份History重放、24条原边证明、24次native提交及36次auth。准确效果、预算结算和实际停止按各场景分别核对，不将取消的未知效果改为成功。

## 最终阶段收口证据

- 当前冻结源码完整回归：**10234 passed／704配置依赖跳过**，634模块完整覆盖，产品和测试运行前后未变；分组退出码均0。此前10220／704／2的原失败与各快照仍保留，不覆盖或合并为最终成绩。
- 当前wheel与395产品源码／独立安装字节一致，独立安装受影响214项通过；源码和安装的六实际场景使用相同最终60／80配置，18＋18份原History replay均通过。
- 当前三份默认构造（basic／Profile省略／显式false）及原ToolExecution协议在源码／安装与dev112逐字段及规范字节相同；全库存摘要算法等价单测通过，不称重跑了原五份默认构造。
- 实验原05运行继续保留unknown与停止义务；原PG完整物理备份由pg_basebackup取得，pg_verifybackup成功、system_identifier与原集群一致。原Temporal SQLite、socket路径、原3698wheel／395旧安装及原恢复句柄保留；当前validator拒绝该旧快照。该私有备份不作为框架级备份／恢复产品能力。
- 自建服务session1397退出0；原PID29554／29612、精确自有PG容器及56514／56515／56526端口均已核验不存在／关闭，用户Docker平台保留。物理备份与匹配Worker仍在；不据基础设施退出宣称原05逻辑关闭。

最终权威证据：`phase2-final-regression/full-check.json`、`source-recursive-final-six-summary.json`、`installed-static-recursive-final-six-summary.json`、`static-fingerprint-package-provenance.json`、`retained-original-postgres.provenance.json`与`final-cleanup-verification.json`，均在上述私有主目录。完整R01–R26及第三阶段治理、独立采用、对等比较继续开放。

## 收口规则

相应所选门槛通过后才本地提交；不推送。daemon已发送请求的自动负向完成、跨宿主、其他Runner、远程Facts联合索引与复杂模型质量仍保留在长期清单，明确不支持或安全保守处理，不自动阻塞当前冻结矩阵。未知效果及费用不因清理而消失，诊断／原配置恢复与保守人工处置见支持矩阵。
