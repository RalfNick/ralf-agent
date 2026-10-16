# Temporal 根 Runtime 的注册回调重入修复

本批修复一次 release 校验返回前未复核绑定的P2问题，不是性能优化。P3-2/S2原360秒验收仍未通过；旧包独立600秒诊断与本修复分开，见[整链记录](2026-10-16-coding-session-critical-path.md)。

## 问题与修复

真实 `TemporalRuntime` 的 Context identity getter可以在 `_current_manifest()` 中将已检查的 BindingCatalog／Provider／Context 换成内容相同的新实例，或改变Provider方法。原声明仍相同，首次 `validate_release()` 成功，下一次才发现原对象或方法pin已变化。最小复现不调用模型、工具或服务；它证明单次校验的返回契约缺口，不证明已发生未授权业务写入。

保留全部原前置校验和完整Manifest重建。将已有能力对象及方法检查放入 `validate_release()` 的局部函数，在原位置及公开返回值复制之后复核。局部函数没有新增可替换的公开／类级入口，其嵌套code由原 `validate_release` 可执行指纹覆盖；没有新增权限缓存、跳过参数或执行权威。

出口复核本身也可能读取 `validate_request` 等descriptor，因此不能将再次调用getter当作最终证据。修复在调用这些回调前记录本次静态descriptor及函数code／wrapped链，出口通过 `inspect.getattr_static` 复核，不执行descriptor。覆盖普通函数、绑定方法、staticmethod／classmethod、property以及原 `_binding` 已支持的async-callable类型级 `__call__`。静态遍历以seen集合处理重复与环，比较使用对象身份。最后直接检查Provider注册表、Catalog原条目及已有构造期owner pins，拒绝最后一个getter造成的对象或方法漂移。

原selected-host委托路径、调用方expected Manifest验证、各SDK／PG／native I/O两侧独立校验和实际停止／ACK义务保持。该改动不声称能验证任意Python私有状态或隐藏业务配置；组件仍需履行自身identity和纯注册契约。新代码没有在真实服务运行中验收，不能引用旧包600秒结果代替。

## 验证

- 主RED：四种注册回调变更均首次未抛 `DefinitionMismatch`，4 failed／2 passed；额外出口getter变更实例／code的RED为2 failed，async-callable code变更的RED为1 failed。失败均为行为断言，非构造或收集错误。
- 最终新增10项覆盖上述拒绝、实例方法别名、合法不变getter及返回值隔离；与原binding isolation联合17 passed。
- 冻结32个相关模块628 passed／69.48秒，零失败／错误／跳过。425产品／863测试前后不变；独立审查在本次声明的支持边界内无新增P1／P2。
- 独立构建、安装后10模块171 passed／18.25秒，零失败／错误／跳过；425产品source／sdist／wheel／site逐字节相等，863测试副本无漂移，导入来源全部为新安装。
- 默认完整Profile／Manifest／编排canonical等值，原与continued默认History离线重放通过，兼容检查Provider调用0；没有真实模型、服务或native业务调用。旧Coding History仍用匹配不可变Worker，不用新指纹强行重放。

只执行本次影响范围的检查，不将其表述为完整项目回归或阶段验收。Ruff、格式和Git空白检查另在提交前执行。

## 证据

- 原安装最小复现：`/private/tmp/ralf-agent-dev121-session-sdk/release-reentrant-red/result.json`，SHA256 `88f42530655973be0cf4e178b01dcfe2f4d9a883b7218bba77e16f0596b68648`；同目录 `tests/` 保存RED日志和XML。
- 产品 `temporal_activities.py` SHA256 `5941b252cace9504f1d9c5e66a7eb3450e76843a5b83880ad80dc2455b607bc9`；新测试SHA256 `a5637f65b0782eaf4715966edceb0bd142f8ccefde7cdc2ed024f4f89b6a48f1`。
- 冻结清单：`/private/tmp/ralf-agent-dev121-root/release-binding-guard-release/frozen-audit.json`，SHA256 `93152b32da313cfe89ea952cef54357ceb6cc4c92f4e57197f9b50bd622064f2`；同目录 `focused.xml`、`result.json` 保存628项结果。
- 独立安装汇总：`/private/tmp/ralf-agent-dev121-session-sdk/default-compat-s2-release-binding-guard/final-summary.json`，SHA256 `da09d4cde4f528c0ea723838227299382326dfb4f28d6dc63dd8064104988ffa`。
- wheel SHA256 `681da9f94004696af56f1c4c6aae65185dd04282463407489b67d020ac52f831`，sdist SHA256 `e4e310c8f418ae93543d313a5bf94c0b02e016138c0bec4c2c47247ab152bf49`。这些路径是本机可复核工件，不是公开发行附件。
