# dev63 Temporal DecisionPolicy 验收

基线 cb370f9/dev62；2026-10-11。沿 R01/H1 复用纯 Harness prepare/propose、原 Catalog、Model Action 与 History；
host/ref/inherit、九类绑定、具体 DTO、实际请求和模型响应/决策证据、固定方法与原工具描述子集。
原 Schema／授权／审批／limits／CompletionVerifier／记忆仍由原执行权威管理。完整 R01–R26/H1–H5 保持开放。

最终证据：

- 缺少自定义支持23RED/1控制；GREEN138。错配采纳／协议11RED/25控制，原 History 采纳校验后通过。
- 新协议接收旧格式可绕开校验、修改 Native 实例没有显式协议，各自额外RED后闭环。
- 常规 NativeHarness 子类使用 super 被 opaque 捕获拒绝：RED后仅允许编译器零参数 super 闭包，固定 MRO/基类方法；其他捕获不放宽。
- 独立只读审查确认两项P2：Provider 修改准备列表导致原证据变形；直接 __class__.label 读取未固定类状态。
  两项永久RED后冻结派发前证据、拒绝直接类访问；最终195定向通过，包括基类方法漂移、Schema/工具授权/limits。
- 修复直接类访问时，Python3.12 对合法零参数super也使用 LOAD_DEREF，首次修复两项合法继承回归。
  反汇编有效/非法函数并核对官方 opcode 定义，区分隐式 LOAD_SUPER_ATTR 标志；随后195全部通过。
- 实际Service诊断夹具最初误用顶层actions/state，改为官方snapshot字段；不计为产品成功。
  实际SDK采纳时的延迟模块导入警告被复现，改为自包含纯数据判断；14恢复/125.95s及2继承/14.73s通过。
- 全量34418在发现上述定向继承回归后中断并确认exit2，不计验收。冻结源码16服务48723通过/125.73s；最终全量95622通过/485.75s。
- 未调用真实模型；未重新认证远端数据库。本机 Python3.12，其他解释器 CI 未本机重跑。

审查的实际服务、全量、安装/兼容和质量判断由维护者承担，独立纯复现不替代这些门槛。

安装195项/3.11s通过；core-only wheel无Redis/psycopg/Temporal SDK/tiktoken/pypdf，离线索引/原Run恢复、纯Limits/Completion/DecisionPolicy及super继承/Provider输入变更冻结通过。实际62→63→62原默认Run/Manifest/Artifact和21模板一致，旧Worker审批/新Worker重复批准/一次工具/旧Worker重读/History replay通过；旧62Runtime拒绝新增Decisionrelease，0次模型调用。最终安装16实际服务/126.11s通过（25110 exit0）；214模块一致，最终构建归档包含与源码一致的指南／规格／队列／计划／验收文档。自有Service75051已正常停止，exit0且stopped确认。

最终dev63：全量3563 passed/198 skipped（485.75s，95622 exit0）；冻结源码实际16/125.73s、最终安装实际16/126.11s及195契约。214模块、core-only与62→63→62原审批／回执／一次工具兼容通过。独立审查2项P2由2RED→195GREEN闭环，无待办Minor。自有Service75051正常exit0且stopped。未调用真实模型／重验远端数据库；仅本地提交，完整R01–R26继续active。

Ruff、520文件格式检查、Git空白通过；wheel/sdist构建及源码／wheel／sdist／安装214模块与最终文档字节一致。其他Python版本本机未认证，真实模型／外部采用／环境隔离和企业治理保持开放，纯策略不能充当沙箱。
