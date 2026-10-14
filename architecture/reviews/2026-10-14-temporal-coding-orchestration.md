# dev110：Temporal Team／Dynamic Coding

本批处理第二阶段已列出的 Team／Dynamic Coding 阻塞，不改变第一阶段 dev99
参考链路或引入第三套执行权威。开发基线为本地提交 `04976b4`。

## 固定实现范围

- 当前选定 native 发布升级为 version 3／binding 16；组合升级为 version 4／binding 17，
  拓扑标识 `bounded-agent-orchestration`。旧选定发布继续要求匹配的不可变 Worker；
  未选定 Coding 的默认发布须逐字节保持。
- 复用原父 History 的 Team 选择、动态计划采纳、校验、replan、预算和 Session。
  支持 static Agent graph、Team 和 Dynamic 的一层直接 Agent 成员；嵌套与 sequence
  成员暂不纳入本批。隐藏 planner／verifier Agent 保持固定且不获 Coding 授权，
  其原子 Run 仍关联并纳入根关闭。
- 调度根据实际声明的成员和有效绑定计算 Runner 资源。Team 队列稳定背压，
  Dynamic 不能使用规划占位节点的 Agent 或节点 ID 代替实际成员。
  子 Run 财务结算和原实际 owner 的物理停止证据同时成立才释放容量。
- child link 保持完整 version 1 字段，规划 revision 为非负数并冻结到原 child request。
  replan 不删除旧 child 的请求、cap、epoch、回执或停止责任；晚到结果不得覆盖新 DAG。
  动态 DAG 仅允许修改 pending 节点，已调度节点不可重绑定；关闭后不接受新修订。
- 原 Registry admission 与 owned close 扩展到三个根类型；仍按原 namespace、
  request／release digest 和 SDK execution epoch 获取、验证和停止原子 Run。

## 验收计划

1. 分别以失败测试验证类型门禁、实际成员绑定、共享 Runner 背压、物理关闭、
   replan／pending patch／旧 revision 证据和取消后禁止调度，再实现。
2. 在实际 Temporal／PostgreSQL 验证 Team、Dynamic、审批冷恢复、运行取消及
   owned close；原 native peer 可用于结构恢复证据，不据此声称真实模型规划质量。
3. 独立审查；冻结后按风险执行受影响及交付检查，构建并在独立安装中复验，
   核对旧发布门禁和未选定默认字节。
4. 记录实际成功、跳过与失败，同步能力文档，仅本地提交，不推送。

## 当前状态

本批直接 Agent 成员的 Team／Dynamic 子集已实现并验收；完整 R13／第二阶段仍开放。跨父容量、不确定
create／CID 窗口、嵌套 Coding 及复杂真实模型任务继续作为第二阶段未关闭项。

## 审查修复与中间证据

独立审查复现两项 P2，均先 RED 后修复：

1. `planning_request` 与 parent completion `source` 仍读可变 diagnostic snapshot。
   selected17 现在只把已冻结 `adopted_result` 送往后续规划／验证，缺少已采纳结果
   明确拒绝；原子 Run 的较新财务／物理诊断仍记录。两个读取入口分别保留失败复现。
2. hidden verifier 结算先到、物理证明后到时，过早 interpret 会误触发父失败。
   现在保留 received proposal，等原全部 children 双重闭环后才新建 interpret Action。
   失败测试与 proof 后成功采纳均验证。

修复前服务验收被明确中断，保留 `11 passed／1 deselected／KeyboardInterrupt`（382.51 秒），
不并入最终交付成绩。原 finally 关闭当前测试的资源后才改产品。首次私有停止脚本
依赖未安装的 psutil 而未执行；随后精确使用系统进程查询定位本批 pytest，SIGINT 完成。
初次 source 格式检查两文件不通过，已仅格式化；全部显式组合指纹前后相同。

旧 immutable dev109 selected15 的真实审批 cold recovery 已通过，当前拒绝其实际
元数据及伪改16／17，业务 I/O 未发生。未选定五种默认构造的 SHA256 仍为
`35004369d4aa8b8b85cc45f59f00fa3f6ee83be8061c20fbf053b99446d03349`。
首个候选 wheel 的385模块／3资产与源及独立安装相等，但它早于两项P2修复，
保留在私有 tested-dist，不能作为最终修复后的包体验收。

## 最终交付证据

| 门槛 | 实际结果与范围 |
| --- | --- |
| 独立审查 | 两项P2已独立关闭；最终56项私有／正式检查通过，全部16 completion纯函数库存和变更拒绝核对；当前审查范围无剩余具体P1／P2 |
| 全量源码 | 610模块分组均返回测试成功：9662 passed／692配置依赖跳过；最终收集10354项与总数相符；没有注入真实模型或外部服务配置 |
| 快照核对 | 产品始终冻结；唯一变动是服务测试 canonical Worker module入口，后来同文件修正owned关闭后的观察方式。完整驱动因测试文件快照变化返回1，原报告保留；最终该模块离线22配置跳过、实际完整场景及定向复验单独核对。不伪称原测试快照未变 |
| 独立安装 | checkout外最终包243项focused通过；src无产品Python，385产品模块／3协议资产与源码及wheel字节一致 |
| 真实服务源码 | Temporal／PG，native、graph、三种默认Team、flat／DAG／managed ModelPlanner、checked Team，以及Team／DAG owned关闭。初次19 passed／2 failed／1 deselected（711.47秒）；两项仅测试误用已关闭Engine，改借用观察入口后定向2 passed（50.22秒）；合计21个独立用例通过 |
| 真实服务安装 | 同一冻结产品、独立队列／Schema／目录并行；初次19 passed／2 failed／1 deselected（719.70秒），同测试问题的定向2 passed（48.47秒）；合计21个独立用例通过。未删失败日志，也不把结果称为一次零失败运行 |
| 恢复内容 | 审批前无native启动，cold Worker续接原Action／digest／SDK epoch，重复submit相同回执，一次attempt／effect／Thread／Turn、认证三次、PG与History核对及重放、原容器fence与credential canary缺失；hidden Planner／Verifier原子停止也核对。native对端为结构化peer，不代表真实模型质量 |
| 旧发布／默认 | immutable dev109 selected15实际审批cold recovery通过；当前拒绝其真实与伪改版本元数据。五个未选定默认构造SHA保持35004369…46d03349，旧History不迁移 |
| 原native实现 | 与最终dev109包相比，10个原生／连接／Local委托模块逐字节相等；dev109真实9/9成绩仍作为该历史固定基线，不新增Temporal模型规划质量成绩 |
| 清理 | 自有Temporal／PG与匿名卷正常退出并独立核对；测试Schema、fake native容器与56个原socket均为空／缺失，Temporal／PG／metrics端口关闭，用户Docker平台保留 |
| 格式与提交 | Ruff、format与Git空白检查通过；本批仅本地提交，不推送 |

最终wheel SHA256：
`a53f003874a38236f3bbfbb9481a25374a7e0091b04df49948fe03984d8e01f3`。
首次候选wheel和失败／中断运行分开保留，不能替换为最终包成绩。

## 下一批

优先补跨父共享Runner容量与不确定create／CID的阻塞窗口，再推进嵌套／sequence
Coding和复杂真实质量；维持原Local／Temporal执行权威、固定配置和原停止责任。
dev99参考链路继续冻结，完整R01–R26目标保持active。
