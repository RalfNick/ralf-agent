# P3-3 原子任务重复恢复与真实容量边界

日期：2026-10-16。接续本地 `d2a02a8`；仅修复既有公有机械控制，不新增后端、部署、调度器或外部权限。用户已授权P3-3独立推进；P3-2／S2原360秒失败与全部门槛保留。本批不关闭P3-3。

## 发现与最小修复

先纠正上一记录的边界表述：外部SDK新descendant命令仍需原Registry记录和完整祖先校验，但原Parent内部向原child的机械委托已核验原Activity／Scope／source／namespace／held-root／SDK祖先与epoch，直接调用固定child。Coding桥接也沿原证据委托；两者都不另登记全局descendant命令。不需要增加新的后代保护索引。

实际漏洞有两处：

1. 普通公有内部委托使用固定SDK Update ID。SDK重复调用返回缓存结果，不能再次进入原Workflow command handler；原未完成恢复可能不再被唤醒。保持原业务command ID，每次发送fresh SDK Update。
2. Coding公有内部drive把可变child revision放进业务ID；采纳命令会推进revision，恢复重提会制造新命令。改为原owner／child／execution epoch／kind身份，同时采用fresh SDK Update；取消和drive分别有一个原业务身份。

修改两个已有产品文件：`temporal_deployment_execution.py`和`temporal_coding_composition_control.py`。完整原验证和入口／出口检查未减少；取消后drive保留取消，不重开业务。非公有分支保留原命令与SDK ID行为。详细边界见[契约](../specs/temporal-recovery-capacity-contract.md)。

## 离线与安装验证

- 新增5项：最初夹具因lambda参数同名／namespace能力遗漏报错，先纠正夹具；随后5项均以预期原因RED（重复唤醒只有1次或revision变动产生3条命令），产品修复后全部GREEN。使用真实`TemporalRunWorkflow.command`和状态对象，仅模拟SDK去重运输；Provider若被调用立即失败。
- 初次8模块193 passed。最终21个受影响源码模块 **437 passed，零失败／错误／跳过**。首轮扩大回归429 passed／8 failed均为沙箱拒绝测试夹具AF_UNIX bind；授权本机socket后相同21模块437通过，没有修改产品或测试断言。
- 仓库外隔离安装当前wheel，相同21模块 **437 passed，零失败／错误／跳过**。427产品源码／wheel／安装逐字节一致，复制测试及运行前后产品无漂移；隔离解释器导入安装目录，未导入checkout。复用本机已有依赖，无下载。
- 对照原冻结基础wheel，默认Card与普通空工具Temporal publication完整相同；当前安装Worker离线重放保存的原始及续接默认History，使用原记录真实Run ID，输入哈希不变。默认兼容不代表selected／实验性Coding旧History可升级。
- 独立只读审查两个产品diff未发现新增P1／P2；受影响Ruff／格式与Git空白检查通过。没有重复全量基础SDK回归。

## 真实SDK证据：分别记录成功与失败

全部使用已授权本机Temporal服务、原Worker和原确定性Provider，无外部模型API或PostgreSQL调用。不修改服务配置或启动新部署组合。

### 独立helper运输探针通过

源码 **1 passed**，仓库外安装 **1 passed**，分别保存原两条History并离线重放。普通公有图的原child确实由原Parent启动，SDK parent／epoch与原request／admission匹配。在该child等待审批时，经既有内部`_command` helper连续drive三次：三个不同SDK Update被接受，同一业务回执，原`command_recorded`只有一条，工具执行0次。额外以固定SDK Update ID调用两次，History只有一次Update接受，确认原依赖假设。

测试直接调用运输helper，不等于完整外层Activity授权验收；目标是普通公有2 child，**不是原生Coding3／4业务执行验收**。两次都沿原root取消并完成退休；测试owned两个Run、Registry和Worker清理证据齐全。它不证明满容量后的可达性。

### 真实4096容量探针仍失败

该独立探针使用生产`COMMAND_REGISTRY_CAPACITY=4096`，原嵌套Team／Team／Agent树，持有实际Provider，计划填满原Registry后取消原root、核对两个固定后代、实际结束后退休及原History重放。新探针自身整体180秒，Facade观察120秒；不改变S2原360秒或产品期限。

| 运行 | 结果 | 实际边界 |
| --- | --- | --- |
| 首轮，测试并发32 | 1 failed／40.828秒（XML） | 服务每Workflow最多10个in-flight Updates；原Registry History已有221 accepted／completed，最后完整进度批193 |
| 修正测试并发4，4096门槛不变 | **1 failed／14.479秒（XML）** | 服务报`total number of distinct updates ... (2000)`；原Registry History恰有2000 accepted／completed，最后完整进度批1997 |

第二轮是接纳运输／History生命周期的真实缺口：服务先达到2000个不同Update上限，框架4096条逻辑容量未能填满；尚未执行目标满容量root取消、整树停止或退休断言。保护槽的纯状态证据不保证实际服务在此前仍接收新Update。未降低4096、提高服务限制、延长该探针或以状态夹具填充替代实际准入；两次失败保留，集成测试没有改为xfail或删除断言。

两次失败的owned三个Run、Registry终止和Worker关闭证据齐全；这是**测试清理**，不冒称业务退休成功。因第二轮已有明确生命周期原因，不重复相同4096服务运行。

## 制品与证据

独立候选：`dist/p3-delegated-recovery-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`。
SHA256：`183586d360a28c5db9507bbe7dcb74b306f3548476aa691f4a2ab44b57cb34d3`。制品旁保留`verification.json`和`SHA256SUMS`，所有先前不可变wheel未覆盖。

- `/private/tmp/ralf-agent-p3-delegated-20261016/`：源码两次失败XML／日志／progress／Registry History／cleanup，以及源码和安装独立helper成功证据／两条History／replay／cleanup。
- `/private/tmp/ralf-p3-delegated-source-permitted-20261016.xml`：最终源码437项；初次socket拒绝另存`source-final`XML，不覆盖。
- `/private/tmp/ralf-agent-p3-delegated-install-20261016/`：安装437项、隔离导入、427产品哈希、默认对照和原／续接默认History离线重放。

## 兼容与下一步

所选部署source inventory已变化。内部Coding helper也参与实验性Coding组合的实现指纹，因此即使legacy分支行为保持，其完整release指纹仍可改变；旧selected及这些Coding History必须保留原匹配不可变package／Worker。协议整数相同不等于可替换旧Worker。

下一批先固定原History内的必要控制与原回执生命周期契约，再实施最小运输修复。受限Signal＋Query原command receipt是候选，不是本批已交付能力：Signal送达不代表业务接受，缺回执仍未知，必须沿原Registry权限和原epoch，避免新无限字典；Signal也增长History，不承诺无限保留。仅给维护命令增加Signal不能使4096条正常准入变得可达，原失败也揭示正常接纳运输责任；Continue-as-New还会触及固定Registry epoch和全量去重／Session迁移，应另行证明，不能随意切换。

现有unknown Action的首次人工核验可能是唯一恢复入口，不能靠永久拒绝关闭门槛；外部新业务控制允许安全背压。普通scoped Registry和完整所选Temporal／PG／HTTP链仍待。P3-2、P3-3、P3-4／5／A与完整M1均未关闭，只本地提交，不推送。
