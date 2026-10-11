# dev71 Temporal 启动预检验收

基线 ef711f4/dev70；完整 R01–R26/H1–H5/M1 保持开放。

## 行为与审查

Host 在 namespace RPC、Client／route 和启动 Task 固定前，验证原 Engine 超时、实际安装 SDK 字段、普通 Worker 标量、cache／slot／poll／tuner 组合及全部版本 build_id。拒绝后可以在原 Host 纠正重试。字典浅复制；复杂 SDK 对象仍借用并委托构造。原执行权威、默认发布与直接 Engine 行为保持。

唯一独立只读审查发现 3 项 Important，无 Critical；统一修复：严格超时不读取调用方 `__class__`，保留 SDK 合法零 poll ratio／队列 rate，提前验证 nullable 字符串 identity。新增 8 项复现 RED／46 pass → 136 相关 GREEN（3.70s）；安装包同组 136 pass（2.82s）。无第二次审查。

## 已读取证据与剩余门槛

- 前期：缺模块 35 RED → 88 GREEN；惰性 build_id 1 RED → Task1 89 GREEN（4.14s）；Host 无 I/O 计数 9 RED → 119 GREEN（3.08s）。
- 独立核心安装：98 pass／38 缺可选 SDK 跳过（2.21s）；跳过不计为 SDK 验收。
- 修复后源码／安装服务组合各 7 pass／3 缺 PostgreSQL 跳过（21.45s／21.00s）；其中 1 项离线模块。必需源码 7 pass（20.30s）／安装包 7 pass（21.03s），无跳过。
- 实际 SDK 零队列 rate 能合法启动，但会抑制活动执行；使用独立队列只验构造，正常速率再验执行／原回执／重启／History。首次把零速率用于业务执行的测试失败是配置语义，不是放宽执行成功条件。
- 实际旧70→新71→旧70：Local 审批、typed Session、原 Manifest／artifact、21 starter；Temporal 默认审批和 native save-v1 Session／Turn／原回执／History 均通过，每个业务只调用一次工具。
- 242 模块源码／冻结／wheel／sdist／两个独立安装环境一致；METADATA 为 dev71，两环境 pip check 通过。
- 11 文档 502 本地链接存在、CI YAML 解析、Ruff／格式／Git 空白通过。

最终冻结全量：4114 passed／329 配置跳过（624.34s），已读取 runner 80839 exit0。自有 Temporal runner 2758 已停止、等待 exit0 并检查 stopped 标记；未启 Redis/PostgreSQL，未调用真实模型，未推送。最终 sdist 的 644 项当前文档／测试／包配置逐字节复核通过，repository CI 按既有 MANIFEST 不打入 sdist；CI 在仓库中单独解析验证。记录与实现一并仅本地提交。

## 执行裁决（按记录顺序）

1. implement already authorized R04 pure configuration-refusal architecture continuously with inline writing-plans/executing-plans, without repeat skill spec/plan/finish approval menus — human says continue until allcapabilities and explicitly no interruption; this is existing documented startup flow refinement — cost if wrong: design detail may need changing before final acceptance; no irreversible publication.
2. worker rich objects/callback semantics stay SDK-delegated; this batch promises known names/common primitive constraints only — pure validation cannot execute user executors/plugins to prove their semantics — cost if wrong: validly named rich objects may still fail SDK construction after namespace lookup, explicitly documented instead of falsely closing all SDK validation.
3. same final-local-commit order uses explicit BASEef711f4→WORKTREE review package (commit range empty) — review actual tracked/untracked implementation before final acceptance/localcommit — cost if wrong: later edits still require regression/frozen gates, not reviewer certification.
4. plan blanket positive rates/ratio changes to field-specific SDK-compatible bounds — ordinary valid zero poll ratio/task-queue rate must remain usable — cost if wrong: SDK version-specific differences require later compatibility work.
5. arbitrary executor/runner/tuner/interceptor/callback/plugin semantics remain delegated — pure preflight must not execute them — cost if wrong: rich configuration can fail after namespace RPC.
6. plugins may alter registration/configuration during SDK construction, no blanket semantic guarantee — original Host bindings stay owned but plugin behavior is SDK responsibility — cost if wrong: unsupported plugin combinations need explicit adapters.
7. internal poller objects and nested borrowed object mutations remain outside shallow snapshot — only dictionaries and scalar fields are detached/checked — cost if wrong: caller mutation may affect rich SDK construction.
8. deployment_config/build-id combination remains SDK-delegated complex configuration — cannot verify arbitrary object behavior in pure preflight — cost if wrong: configuration may fail after namespace I/O.
9. older official SDK historical matrix is not certified by synthetic signature probes — current installed SDK and explicit known-name refusal evidence only — cost if wrong: older versions may need version-specific support.
10. live service/install/frozen-full/old70 compatibility remain executor gates, not reviewer claims — complete them before delivery — cost if wrong: deployment regression could escape offline review.
11. live model quality/independent scheduler/global capacity/full R01–R26 remain open — startup option validation adds no such capability — cost if wrong: users must consult capability status before deployment.

## Deferred minors

极端 cache 整数宽度及非正规 worker rate 可在 namespace RPC 后被 SDK 拒绝；本批按低频边界延后，不宣称所有合法名称数值都能通过 SDK 构造。
