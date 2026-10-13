# dev102：保留 Coding 环境与共享启动证据

本批新增具体 `DockerCodingEnvironment`、借用原 `PostgresEffectJournal` 的
`PostgresRunnerJournal` 和 Local／PG 共用纯阶段规则。范围是环境资源与耐久证据
基础；原 Action／Local／Temporal 准入、fence 与 History 尚未集成。R13、第二
阶段和完整 G3／G5／G7／G8 保持开放，dev99 四条参考链路继续冻结。

## 实现与有限实际证据

- 保留原 container ID／generation、workspace／session state、私有元数据和独占
  lease，使用固定已有镜像与专用空 Docker 配置，拒绝静默导入或替换环境。
- 真实线程／Popen 拥有有界 Docker 命令；停止后重新 inspect 原 ID，关闭不删除
  容器／状态，停止失败保留 lease。冷重开保留同 ID／generation 和 workspace。
- 实际准备、控制读回、受限原生命令读写／负向路径和存活 setsid 后继的整容器
  停止已提供证据；停止后的心跳稳定观察仅为有限 0.4 秒。
- PG 将原 dispatch intent 与启动记录同事务保存，绑定完整原 envelope；相关
  检查覆盖独立连接、容量、回滚、原效果阻塞与重开。共享纯规则保持提交无回执
  不重发，取消意图不解释为实际停止，关闭视图不关闭借用的原 owner。

私有环境汇总：`/private/tmp/ralf-agent-dev102-environment-final/summary.json`。
原过早退出探针保留在 `/private/tmp/ralf-agent-dev102-environment`，心跳夹具采样
时序修正记录为 `premature-heartbeat-assertion.json`，不删除失败历史。
PG 先前日志：`/private/tmp/ralf-agent-dev102-root-DtoaDD/pg-tests.log`，34 passed／
零跳过，包含纯边界与实际数据库检查；该结果不是下述 P1 修复后的最终验收。

## 审查与最终检查登记

独立审查确认两项问题：

- P1：失败的 Runner.initialize 修改借用原 owner 的 schema routing。实际两 schema
  复现使同一 envelope 两次获得 `execute=True`。修复以私有 staging 保存路由，在
  原 owner mutex 内跨事务提交后发布；metadata 失败／初始化取消不污染借用 owner。同一审查者
  实际独立 schema failure 与 commit mutex 探针复验通过。
- P2：全事件循环 cancel-all 可结束 asyncio 包装 Task，而真实线程／Docker 命令
  仍活跃。已补实际 worker tracker drain；同一审查者以 cancel-all／aclose 与实际
  Popen 额外探针复验通过。future.done() 不算退出，剩余 P1／P2 为零。

一次错误 system Python 全量运行被中断：**29 failed／927 passed／34 skipped／
1 error**。导入环境不正确及 loopback 限制使该运行无效，不作为已接受产品回归，
也不删除失败或并入有效受影响结果。本批验证目标是正确环境下的受影响检查。

| 检查 | 最终证据 |
| --- | --- |
| 固定源码受影响验证 | 最终 301 passed／零跳过，34.65 秒；含 PG 39 项检查，其中 17 个实际服务案例 |
| 固定 wheel 独立安装 | checkout 外独立安装同 301 passed／零跳过，33.33 秒；只复制测试、工具及 JSON 资产，未复制 Python 产品源码 |
| 实际环境与共享 PG 修复复验 | 有限环境汇总及上述同一审查者实际探针通过；不代表原 History 已接入 |
| dev101 模块／启动记录与制品一致 | 359 产品模块与源码／wheel／独立安装一致；旧 355 模块字节保持，仅 runner_journal.py 提取共用规则、新增三模块；三个包内 JSON 字节保持，原启动记录身份与阶段测试通过 |
| Ruff／格式／空白 | 七个受影响 Python 文件 Ruff／格式与 Git 空白检查通过 |
| P1／P2 修复审查闭环 | 同一审查者复验通过，剩余 P1／P2 为零 |

独立安装的实际产品环境完成九项无模型控制查询、原容器整容器停止和同 ID／
generation 冷重新连接，关闭后实际 worker 计数为零。模块来源位于本批独立
site-packages；安装记录保留在私有 `native-installed-probe.json`。固定 wheel 摘要和
源码／sdist／安装逐模块证据保留在同批 `package-provenance.json`，不覆盖先前制品。
本批未重新运行旧业务 Run 的跨版本恢复、完整框架回归或真实 Temporal History；
模块字节与启动阶段兼容检查不能替代这些未运行门槛。

## 未关闭的门禁

原始 `docker start` argv 仍可重启已停原容器。lease、generation 和 stopped 状态
未撤销已取得的启动参数，不能声称旧 grant 失效。容器停止与原生 Turn 终态、效果
分类、原 authority 采纳须独立接通；共享 PG 不代替 History 审批／控制权威。

本批 `execution_admitted=false`，未请求模型／provider／auth，未读取宿主认证或
执行业务 Turn，未下载资产或重跑冻结 dev99 评测。控制配置和有限命令拒绝不证明
builtin read／apply_patch、凭据边界、全部工具隔离或专用原生认证。继续按
[委托集成契约](../specs/delegated-coding-action-contract.md)推进；接口与边界见
[环境／日志指南](../../docs/codex-coding-environment.md)。
