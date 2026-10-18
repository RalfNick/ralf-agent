# P3-4：双有效身份与最小脱敏审计

2026-10-18用户明确允许独立推进原P3-4，保留S2原失败和全部验收门槛。
本批只交付身份隔离证据与可替换的脱敏观察；完整P3-4、安全保留、P3-5／A仍开放。

## 实现与边界

- 原`authenticate→Scope→engine_for_scope→TaskControlBridge`及资源授权交集保持。
  两个有效调用者在同一原SQLite库、同一ASGI应用中串行路由；原Coordinator仍独占。
  此宿主切换fixture不证明并发多租户或Temporal双身份部署。
- `A2AApplication(..., audit=ServiceAudit(...))`默认关闭，`LocalA2AService`透传。
  固定DTO使用五个分域HMAC引用；正文、工具参数、结果、错误、header/token及游标不入日志。
  默认1000条内存环形缓冲，支持同步宿主sink；资源借用，宿主负责关闭与持久性。
- sink异常、非None／惰性结果和sink自行抛出的CancelledError仅增加失败计数。
  原业务回执与真实调用方取消传播保持；没有新增控制权威或业务重试。
- `rpc_ok`只证明RPC方法返回，不证明响应送达、业务完成、命令耐久接受或审计耐久保存。
  记录在最终reply前产生；进程崩溃可能漏审计。默认缓冲不是合规耐久日志。
  使用、替换和引用缺失条件见[服务审计](../../docs/service-audit.md)。

## 原始验证

制品：`dist/p3-service-audit-20261018/ralf_agent-0.1.0.dev120-py3-none-any.whl`，
SHA256 `101e537100f0531e6cc3fdde31713b24ba83969644c0640bc05c63cba5097ba3`。
原所有制品保持，不因同为dev120替换旧哈希。

| 范围 | 结果与原始位置 |
| --- | --- |
| 审计产品RED | `/private/tmp/p3-audit-red-20261018.log`：公共入口缺失的2个收集错误；补充命令关联／sink取消RED为2失败／12通过，见`p3-audit-command-red-20261018.log` |
| 源码受影响10模块 | **100 passed／2配置依赖skipped**；`/private/tmp/p3-audit-source-final-20261018.xml`，3.199秒（JUnit suite时间） |
| 隔离wheel相同10模块 | **100 passed／2 skipped**；`/private/tmp/ralf-p3-service-audit-install-20261018/installed.xml`，2.943秒 |
| 真实HTTP源码 | 双身份／审计新场景及原查询／容量／审批／未知写／重启控制共**6 passed**；`/private/tmp/p3-audit-http-source-20261018.xml`，13.169秒 |
| 真实HTTP隔离安装 | 同6项**6 passed**；安装目录`installed-http.xml`，12.079秒；不是Temporal／PG矩阵 |
| 原默认兼容 | Card与完整普通Temporal发布材料等值，原材料SHA256 `8b369d886cb117cfb935ac6e9360bcbe8169d3a6630cd545ce09f14ceda42027`；`/private/tmp/p3-audit-default-compat-20261018.json` |
| 原默认History | 原及continued保存History均离线重放通过；安装目录`replay.log`；不是live continuation |

439产品文件在源码／wheel／安装间完全一致，919个Python测试副本一致，哈希清单在隔离安装目录。
新HTTP宿主正常关闭后记录`hosted_closed`、原Engine关闭、drive／thread为空；数据不删除。
真实写入一次，重复控制回执不变；另一有效身份读原Task、持有原cursor和取消均401，原数据库与写入不变。
细粒度ASGI测试还覆盖审批／核验／恢复拒绝以及同请求由原调用者成功执行。

## 失败保留与审查

首轮较广的11模块为111 passed／4 failed（`p3-audit-affected-20261018.xml`）。
4项均为原Temporal输入夹具在Registry view的RPCError，不是本批审计回调失败。
使用`41745ca`原始`a2a.py`及`__init__.py`的独立源码副本重跑输入模块，同4项失败／12通过
（`p3-audit-baseline-clean-20261018.xml`）；原源码和测试复制在`/private/tmp/ralf-p3-audit-baseline-20261018/`。
不把这4项记为通过，也不把过滤后的回归声称完整suite全绿；所选远程验收后续仍需完成。
更早仅替换`__call__`的诊断额外出现异常类型不一致，不作为基线证据，原log保留。

双身份初版fixture漏设审批标记的7失败／1通过也保留，修正后9项通过，不称产品RED。
一次独立review未发现本最小产品入口的P1/P2；其要求的五refs、RPC观察、同步sink时延及耐久性边界已入文档。
受影响Ruff、格式、Git空白检查通过。无真实模型调用，未重跑真实Temporal／PostgreSQL，未推送远端。

## 剩余

安全保留仍缺产品入口，不能用测试schema删除或审计ring覆盖它。
下一批沿原执行权威实现手动、有界、可诊断清理，保护活动树、原效果、幂等与恢复证据；
所选Temporal＋PG身份／审计验证另验。P3-2/S2原360秒失败继续后置／开放，全部门槛不变。
