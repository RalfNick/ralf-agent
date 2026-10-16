# P3-3 原Registry同步预留运输修复

日期：2026-10-16。接续本地`1c18555`，对应P3-3“容量耗尽后必要控制仍可达”的一个具体缺口：每个普通预留占用一个SDK Update，在4096业务额度之前先触服务2000 distinct Update上限。本批仍不关闭完整P3-3，不改变P3-2／S2原360秒失败、任何容量或业务期限。

## 边界与实现

新增一个内部模块`temporal_reservation_transport.py`，仅实现原公有Registry2／3／4、无descendant的七类同步reserve运输。原Signal调用原`commands.reserve`，Query读取同观察／Scope／完整请求digest的原结果。64项有界运输观察缓存可逐出，原业务身份、首次信封与回执不可删除。Signal送达不是接受；未处理／逐出保持unknown，SDK30秒等待及调用方取消只结束观察。重试保持业务命令ID，使用新观察；先前拒绝不永久钉死未来重试。

Signal和Query各自执行原epoch与权威校验。旧Worker必须在发送前返回明确识别的观察形状；不认识则拒绝，不自动降级Update。后代控制仍沿原Activity完整取证，其他Update和`session_*`首次预留保持原路径；没有新执行权威、部署、队列或Continue-as-New。详见[契约](../specs/temporal-recovery-capacity-contract.md)。

初次共享helper分支过宽，真实Session调用者也被切到不支持的运输：扩大回归发现5项Session失败，明确增加七类kind限定后闭环。这是产品回归，不归为fake-only差异。新增测试初版还错误使用满容量保护不允许的任意drive ID，已改为合法cancel；一项额外夹具把未绑定root的原ValidationError误写为DefinitionMismatch，按实际原契约修正，未放松拒绝／重试断言。

## 已取得的验证

- 新增首轮10 RED，修复后12项离线测试覆盖真实Workflow／State的处理前unknown、稳定业务身份、64逐出后同命令恢复、Scope／namespace／descendant／初始化epoch拒绝、观察ID冲突、旧Worker预检、调用方取消，以及原拒绝后的新观察重试。仅SDK网络边界以fake替换。
- 34个受影响源码模块 **806 passed，零失败／错误／跳过**。保留初次6失败XML：5项上述Session回归和1项夹具错误；最终相同清单通过。只开放本机Unix socket供既有测试夹具使用，没有真实服务／模型环境变量。
- 短实际SDK诊断 **1 passed**：同一原嵌套Team／Team／Agent树8条预留，Query／Signal实际RPC计时，原取消、物理结束、退休、3条History离线重放及owned清理通过；没有外部模型API或PG。8次Signal中位3.05ms，16次Query中位6.11ms，两次回执Query分别约1.014／0.975秒，其余未见长期RPC停滞。不是完整容量或一般性能基线。

## 真实容量：保留所有失败

前批raw Update路径在并发4时遇原History2000 accepted／completed上限，记录不变。本批复用原生产4096、原180秒、原嵌套树、持有实际Provider、取消后代／实际结束再退休／重复回执／History与owned清理断言；原raw Update用例仍保留。

首次Signal候选、夹具并发4：**1 failed，185.29秒（pytest）**，原180整体期限。最后完整批621，原History625 Signals／183个已完成WorkflowTasks，只有2个原Update接受／完成；没有Update2000拒绝。调度至开始中位11.48ms、开始至完成中位6.53ms，相邻WorkflowTask间隔中位1.14秒；不能将间隔误当Worker计算成本。尚未填满4096，因此未运行目标满容量树停止／退休断言。owned3Run、Registry和Worker已安全测试清理，不当业务退休成功。

首轮还观察到新模块在Workflow加载后导入的sandbox warning，后续移到现有passed-through初始化导入；没有据此宣称吞吐问题已解决。首轮428产品源码已逐字节匹配原`product-before.json`保留在证据目录`capacity-v1-source/`，不能拿后续源码冒充其匹配Worker。

短诊断后，仅Signal专用夹具改为每批32，低于64观察缓存；每批全部回执返回后再开始下一批，不滚动无限fan-out。原并发4不是冻结SLO，而是为raw Update每Workflow10个in-flight限制选择的夹具值；raw路径仍4。4096、180及全部业务／恢复断言不变。结果只覆盖该并发范围，不声称单次延迟改善或任意并发可用。

第二轮源码Signal并发32：**1 failed，170.172秒（XML）**，已由原权威确认4096条，之后新submit确实拒绝，但夹具错误要求SDK通用拒绝文本包含`capacity`。该消息并非稳定契约；修正为原ValidationError／code，并补充拒绝后4096命令及held-root1不变，没有删除拒绝断言。

第三轮隔离安装、同并发32：**1 failed，171.292秒（XML）**，已确认4096及新拒绝／原权威不变；首次原root cancel已返回持久回执，但夹具读取`remote_stop_confirmed`时KeyError。只读保存原3条History核实：原模型Activity发生StartToClose超时，原root取消回执确为`{"rejected":true,"reason":"too_late"}`。`system.facade(timeout=120)`实际指定Activity期限，不是观察超时；填充约160秒后业务已失败，不能把正确的过晚拒绝当取消成功，也不能放松停止字段断言。3条原History及原Registry重放／owned清理证据保留。

随后仅Signal夹具每批48，仍低于64缓存且逐批gather；保留120秒Activity期限、180秒整体期限、4096及全部原停止／退休断言，并增加取消前root必须仍`running`的检查。每批32／4不是用户冻结SLO，而是该压力夹具的运输并发选择；本记录不据此宣称单次延迟改善或任意并发可用。若48仍不能满足实际活动窗口，不继续搜索并发参数。

第四轮隔离安装、并发48：**1 passed／126.286秒（XML），零失败／错误／跳过**。4096个原Registry命令全部确认；新submit拒绝且命令4096／held-root1不变；原root仍running时接受保护取消，命令变4097；两个原SDK epoch固定后代取消；实际Provider尚未结束时保留根额度且无seal；实际结束后才退休归零；原重复取消回执相同，工具调用0次。三个Run／Parent History及原Registry History离线重放，owned3Run／Registry／Worker清理通过。原120秒Activity和180秒整体期限均未调整。

这是**公有普通2、同一嵌套树、Signal同步预留并发48**的整链证据，不是原生Coding3／4、所有并发或所有History生命周期验收。没有重新跑一轮源码完整4096；最终整链由隔离安装包执行，产品与当前源码逐字节相同。其他三次失败及其不同夹具／源码范围不被该结果覆盖。

隔离wheel同34模块 **806 passed**，428产品源码／wheel／安装一致；默认Card、普通Temporal声明与原冻结基础包完整相同，保存的原／续接默认History使用原Run ID离线重放通过。安装离线回归期间复制测试未变化；为本次服务复验，之后只同步一个服务夹具文件并单独保留旧文件及前后哈希，不冒称整个复制测试目录始终不变。独立只读审查已纠正漏查Session调用者的初次判断，七类限定及原Session回归现已通过；最终受影响静态检查与本地链接检查通过。

## 制品与证据

本候选`dist/p3-reservation-20261016/ralf_agent-0.1.0.dev120-py3-none-any.whl`，SHA256 `caa821f3380befdf130a35478dd49ced54ee518098ed38ac3f453a7dbf07edf3`；旁存`verification.json`及`SHA256SUMS`。此前基础／事件／控制／根保护／子任务恢复的五批不可变制品校验有效，没有覆盖。

- `/private/tmp/ralf-agent-p3-reservation-20261016/`保存首轮6失败／最终806源码XML、三个容量失败与最终安装成功XML／日志／progress／cleanup／Registry History、短RPC诊断及首轮428产品源码快照。
- `installed-capacity-failed-histories/summary.json`及原三条History记录120秒StartToClose及原`too_late`回执；`installed-capacity-v4/`含最终`capacity-result.json`、原三个Run／Parent History和Registry History。
- `/private/tmp/ralf-agent-p3-reservation-install-20261016/`含隔离安装806项、产品／测试哈希、默认对照及保存默认History重放，旧服务夹具另存；后续仅一个服务文件更新，前后哈希登记在verification中。

本批验证一次实际所选容量取消／退休路径，完整阶段关闭数仍为0。不重复基础SDK全量回归，无外部模型／PG调用，无新质量／外部采用结论。

## 剩余与兼容责任

新模块纳入公有source inventory，所选实验release指纹变化。旧selected及受影响实验性Coding History仍需匹配原不可变package／Worker；默认对照及默认保存History不能替代其升级验收。正常根预留之外的Registry／Run Update、人工未知效果核验、外部后代与普通scoped Registry仍有各自生命周期责任。不能从这一运输修复推出无限History、完整企业可用或P3-3完成。

只本地提交，不推送；后续先根据本批真实结果处理同一必要可用性问题，不扩大冻结范围。
