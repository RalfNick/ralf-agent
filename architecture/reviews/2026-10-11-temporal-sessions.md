# dev60 Temporal History Session 验收

基线d548012/dev59。用户持续授权完整能力开发，仅本地提交，不推送。
范围为 H2c3 History Conversation／Turn；完整 R01–R26/H1–H5 保持开放。

## 实现与审查

协调 Workflow 只保存 Session 绑定、Turn／启动意图与 Conversation；原 Run/Parent
独占业务 Action、审批、预算和效果恢复。实际 Namespace UUID 与可信 Scope 固定资源；
端点别名不产生另一占用。原命令稳定重放、忙碌拒绝、空闲 CAS；默认关闭协议保持。
普通／managed Conversation 为独立 sourced reference，不替换本轮 Knowledge/Facts 查询。
根及已启动后代的原请求／发布／静默／hold／ACK 证据分别确认后才释放。

最初缺 enable_sessions 两项 RED 后实现 GREEN。额外 rebind 非法队列／timeout 三项
RED 后增加统一固定绑定验证。纯 nested Team→Team→Native 永久回归覆盖缺失／外来证据、
deferred ACK、未静默与原证据释放。Model/Context/managed 公共边界校验原 Conversation。
独立只读 review 先发现2项P2：open在全局guard前创建导致失败请求固定绑定；await期间
可变输入导致注册身份与接受内容分裂。两项分别 RED→GREEN；冻结完整声明、先reserve再create，
Describe也纳入原RPC托管。永久 caller cancel/close/输入冻结回归通过。
最后兼容审查确认第三项P2：基础 Session kernel1 在普通 Knowledge 复验等待期间取消仍披露模型。
Session发布显式包含 history-1 admission，协议验证强制门槛；原定位／请求摘要与现有一次授权贯通。
直接已取消及 source await 期间取消两项回归保持 Provider 零调用。第四项P2由入口收尾复现：无效冷定义／超长command先reserve/start导致Workflow ID被失败初始化占用。
Describe只在NOT_FOUND后执行冷绑定预检，其他RPC错误传播；长度校验与冻结声明早于登记／启动。
两个RED→GREEN和旧Provider消失仍重放原open的永久回归通过。竞态冷读取仍由Service唯一启动及原绑定收束。
四项P2均修复；最终review无未解决P1/P2。

## 验证状态

源码真实恢复12项：native/sequence/graph/team/dynamicDAG/nested × ordinary/managed，
首Turn完成、第二Turn安全Context读取kill Worker、新Worker接续原Turn，已采纳成员不重复；
Session／首Run／第二Run实际History replay。初版132.76s；最终 Session15与既有 Knowledge12共27 passed/208.89s。
基础Session及 native/graph 审批、busy稳定回执、重复审批、alias重连、CAS与旧Ref共3项通过。
最终安装包从checkout之外运行相同 Session15，151.48s；100独立契约6.04s。
207 Python模块源码/wheel/sdist/安装一致；独立core-only venv不含SDK/Redis/PG/tokenizer/pdf，
离线配置索引／原Agent/Run和纯Session/Run/Conversation/admission均通过，不宣称core支持Service。
实际59→60→59默认Run/Manifest/SQLiteArtifact及21 starter保持；temporal-1/2/3与raw Knowledge默认Manifest相同。
实际安装59无SessionWorkflow，原Worker complete_model对新发布明确拒绝且零Provider调用；
旧纯Manifest读取器允许未知字段，不能称它主动拒绝。官方CLI1.9.1/Server1.32.0、SDK1.34.0。
本轮自有Temporal runner6062已exit0；temporal-official/stopped确认，所有fixture Worker均退出。
一次审批组合等待误用普通paused返回，改为 terminal_only 后重验；未改变业务状态推进。
两次开发服务测试因复用已停止测试队列而主动停止，保留日志；独立Scope／Session之后验证。
受限环境全量因local socket被拒主动停止；允许回环服务的最终全量单独记录。

前次全量3463 passed/146 skipped（493.67s）通过；冷入口预检新增三项后重新完整验收，最终结果另记。
冻结冷入口补丁后：源码实际Session3/6.83s，最终安装Session15/147.90s，安装契约103/9.81s均通过。
补验自有Service runner35988已exit0、stopped确认；第一次重开保留stop标记而立即正常退出，确认后清除任务标记再启动。
这些与此前原执行状态机矩阵27项分别记录，源码/安装的运行路径与派发均有最终证据。
最终全量3466 passed/146未配置服务跳过（536.83s），-W error，47316 exit0；
Ruff／504文件格式／Git空白检查通过。最终文档与sdist再构建并校验；207模块跨源码/wheel/sdist/安装一致。
未提供完整证据前不称全部能力验收。未调用真实模型，不宣称语义质量、跨机部署或外部采用。

## 仍未交付

Temporal 外置 Redis/PG Session 数据与准确保存回执、其他 binding 角色、自动Profile、
FIFO／send_input／移交、跨执行后端协调、迁移／Continue-As-New／保留／全局容量，
H4环境、H5治理和完整H1/H2/H3/M1继续开放。History容量上限不是长期运行治理。
