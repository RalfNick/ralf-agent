# Alpha 2 验证与待处理清单

更新：2026-10-22。以`1b72c05`的不可变`0.1.0a2`两包、原dev19专项和本轮追加验证分别判断。运行结果只适用于各自制品、测试集合与平台；不把测试数量换算为框架完成率。

## 当前放行情况

| 事项 | 当前状态 | 证据／下一步 |
| --- | --- | --- |
| a2版本、wheel／sdist、来源及许可证 | 本地已核对 | [本地交付](../architecture/reviews/2026-10-22-alpha2-local-closeout.md)，原两包和50项校验清单保持 |
| macOS ARM64／Python3.12基础SDK | 已按原包验收 | 311基础、16恢复、两starter；sdist离线重建安装116项及另两starter分别通过，不相加为全量 |
| Linux ARM64／Python3.11–3.13基础SDK | 本轮同包复验通过 | 每版311基础＋16恢复＋两starter，零失败／错误／跳过／OOM；原2CPU／2GiB／swap0、串行断网，峰值最高326.48MiB |
| 函数指纹跨Python缓存回归 | 最小SDK的96项在三版本通过 | 六模块原97项中1项需要Temporal可选SDK，原3.11的96通过／1缺依赖失败保留；精确排除该项后另跑96项，不称97项或完整指纹资格通过 |
| 原生Linux AMD64／Python3.11–3.13 | 待验 | 必须是新a2两包的原生报告；原a1成绩不能代替，远端执行先停止 |
| a2远端CI入口与实际运行 | 待授权和交接 | 当前`alpha1-*`手动工作流固定旧提交，只验证a1；a2不能直接使用它们 |
| 项目权限、最终Tag、公开发行与公开安装 | 待核验／未由本轮执行 | 经授权后交付精确原包，再从公开入口安装并验证审批、重复提交与恢复 |
| S2所选Temporal／Coding恢复 | 原dev19同包18/18已通过 | [原验收](../architecture/reviews/2026-10-21-s2-session-parent-hints.md#最终核对与交付边界2026-10-22)；不是a2各平台同次服务验证 |
| 真实模型质量、完整M1与独立采用 | 保留既有有限范围 | 原参考任务按原环境引用；本轮不调用模型、不启动真实Temporal／PG服务，也不扩展长期R01–R26 |

`1b72c05`发行源码已按用户授权推送，保留`[skip ci]`；源码推送不代表上传wheel／sdist、运行远端CI或公开发行。新追加验证不重建或覆盖a2原包。

## 本轮发现与最小处理

首轮Linux 3.11、3.12基础矩阵通过；3.13的基础阶段为310通过／1失败，16恢复和两starter尚未执行。失败用例`test_session_entry_close_only_detaches_from_shared_runtime`在Run成功后立即断言Session空闲。

[Session契约](session-api.md)允许终态Run在宿主或原义务收敛期间仍短暂busy；`AgentRun.wait()`只观察Run，`LocalSessionAuthority`还检查宿主托管Task及原义务。因此该失败属于测试错误假设，不修改SDK或将busy保护删除。当前测试改为在原1秒有界观察内等待原Session空闲，原成功、关闭拒绝和业务断言保持。

原a2 wheel／sdist以及原交付目录的50项校验不改写。原门禁manifest完整保存为`tools/release_gate_manifest.alpha2-original.json`；当前外置manifest增加`gate_revision=2`，先验证原sdist测试树，再只对这一测试文件应用固定before／after SHA和唯一文本替换。原311／16 node身份、17依赖锁、warning-as-error、资源限制和SDK期限保持。原a1历史校正继续独立保存。

新补验使用当前维护checkout或追加证据中的第2版`gate/`，不能用原交付目录中冻结的第1版工具代替。前次a2 macOS成绩仍绑定原manifest；本轮Linux成绩另行记录，原3.13失败不覆盖、不拼分。

三版本纠正后完整重跑，不与首轮成绩拼接。受影响源码128项通过；本地制品预检另行记录，不代替平台成绩。完整记录见[追加验证验收](../architecture/reviews/2026-10-22-alpha2-validation-audit.md)，本地追加证据位于`dist/alpha2-validation-20261022/`。该目录不替换`dist/alpha2-candidate/`。

## 必须保留的未闭环边界

- **dev18并行叶子未知异常：** dev19正式复验未再现，来源仍未确定。保留原异常、Action与未知效果；复现后再定向处理，不以一次成功证明一般传输稳定性。继续限制复杂Coding组合的支持声明。
- **旧Coordinator离线重放：** 原包本身也存在`replay-None`队列身份限制。业务History重放通过不等于任意旧Worker可接管；旧selected任务需匹配不可变组件／Worker，不做静默升级或重派。
- **跨平台指纹资格：** 最小SDK的96项缓存回归不能代替CONTROL性能门槛、全部执行库存、旧Worker兼容或Linux S2。Temporal执行库存摘要的另1项在本轮环境缺可选SDK，仍待匹配环境验证；原Mac／CPython3.12的优化收益仅按原记录引用。
- **离线跳过项：** dev19全量的891项按原条件跳过，没有验收为通过。真实服务、旧SDK环境与组合资格分别按原制品补证，不能靠移除skip或安装一个客户端包完成。
- **首版外能力：** Windows、多模态、一般流式Workflow、跨宿主HA、完整企业身份治理和对等质量比较仍属长期清单，不自动加入本次首版收尾。

## 历史离线跳过项核对

原dev19全量13,991通过／891跳过的JUnit已按真实原因归组；以下互斥计数总和891，不是新a2全量结果，也不抹去原所选服务的独立通过证据。

| 原跳过条件 | 数量 |
| --- | ---: |
| Temporal及含Temporal的组合服务配置 | 701 |
| PostgreSQL，排除上行 | 119 |
| Redis | 25 |
| Docker，排除以上服务组合 | 32 |
| 不可变旧SDK／Worker等外部环境 | 12 |
| Qdrant，排除以上组合 | 2 |

只在需要声明相应组合时按原制品和环境补验；不移除skip或把安装客户端包当成服务验收。

## 停止点

本轮只补本机可执行的离线验证、测试修正和状态文档。新候选原生AMD64／远端CI、账号权限、公开Tag／发行及公开安装需要后续明确授权。所有历史制品、失败、原验收门槛和未知义务保留。
