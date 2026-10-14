# Temporal 有界并行 Coding 图

dev108 已验收有限协议 13／组合版本 2 的有界静态 Agent 图。源码、固定安装、
实际服务和兼容证据见[本批验收](../architecture/reviews/2026-10-14-temporal-parallel-coding.md)，
Team／动态／嵌套、全局容量及真实 Coding 质量保持开放。

沿用 `coding_execution=True, coding_composition=True`，不增加配置开关或依赖。
静态 `GraphWorkflowSpec` 的 `max_concurrency` 受所登记 `TemporalExecutionPolicy`
上限约束；业务节点均为 Agent，仍只委托一层子 Run。

## 并行与资源背压

原生 Runner 实例只能持有一次实际执行。不同 Runner 可以真正并行；同一个
Runner 的节点由原父 History 排队，调用方不需要加锁。授权中已排除的 Coding
工具不占 Runner；不同工具名称指向同一 Runner 时，也只视为一个资源。

父图同时核对实际并行槽和 Runner 占用。一个子 Run 只有尚未启动的明确证明，或
财务结算完成且原物理停止证据为真，才释放占用；财务已结算、物理证明尚未采纳
的子 Run 仍占槽。物理停止但未知的整笔子级额度继续保留。

不同资源使用原 `tools/codex-coding-postgres` 的多工具声明，每个工具拥有独立且
不嵌套的私有根目录。每 Agent 的 Runner 可继承其实际已获授工具，也可用
`BindingSelection.ref(...)` 精确引用已注册资源。完整 SDK／JSON／TOML 声明、
原子 Run 审批和关闭方式沿用[组合接入指南](temporal-coding-composition.md)。

```python
from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, InputMap, ValueRef

workflow = GraphWorkflowSpec(
    "two-coders",
    (
        GraphNode("a", agent=AgentSpec("a", "Implement the first task", tools=("coding_a",))),
        GraphNode("b", agent=AgentSpec("b", "Implement the second task", tools=("coding_b",))),
        GraphNode(
            "join",
            agent=AgentSpec("join", "Check both results", tools=("coding_a",)),
            depends_on=("a", "b"),
            input=InputMap({"a": ValueRef("a"), "b": ValueRef("b")}),
        ),
    ),
    max_concurrency=2,
)
```

工具 `coding_a`／`coding_b` 必须对应各自固定的 Runner，默认示例不会凭工具名称
创建资源。依赖节点只消费原子 Run 已正常采纳、通过输出 Schema 并结算的结果；
native stdout 或普通消息不能替代这些证据。

## 取消和关闭

显式取消保存首次停止意图，不再派发新业务，逐个取得所有原已派发子 Run 的物理
结束证明。一个子 Run 停止、查询或祖先采纳失败时，关闭仍尝试其他身份已验证的
独立子 Run，再汇总 `CloseIncomplete`。接收器、客户端、账本和资源继续保留，
修复原依赖后在同一事件循环重试原 Assembly 的关闭。

每条 PG 资源必须对应原 History 的 Action、完整 native request、effect、SDK epoch
及 Runner。已 fencing 的记录仍参与祖先采纳与最终扫描；`pending_stop=False`
不能替代实际 owner 结束或父级采纳证明。独立 Agent／顺序 Workflow 的所选组合
关闭也复核原取消与物理结束，原 native 执行循环不改变。

## 历史发布和未完成范围

协议 13 发布 `bounded-agent-graph`，不能把 dev107／协议 12 的 serial marker 解释
为新版本。所选发布固定真实实现摘要：旧 12 的运行必须由原匹配 dev107 Worker／
wheel 续接；当前 Worker 不接受旧摘要来假装执行旧实现。默认未选择组合的发布和
协议 11 保持原字节，另做安装兼容与保存 History 重放验证。

本入口只管理同一原父图的槽位和资源占用，尚未提供跨父 Run 的宿主全局 Runner
队列或自动池。跨父任务使用共享 Runner 的容量管理继续作为明确的交付缺口；
不能将本图的背压测试外推到全局调度。

Team／Dynamic 需要持久选择阶段授权、实际 invocation 结束证明和取消后的迟到
响应拒绝；目前继续拒绝。嵌套、直接 Tool 节点及外部 graph patch 也未开放。
跨宿主、Docker create／CID 不确定窗口、专用原生认证与真实 Coding 任务质量
保持独立验收，完整 R01–R26／R13／第二阶段继续进行。

用户授权的 DeepSeek 官方 Responses 端点已通过一次真实连接检查（200、completed、
预期 JSON 输出、实际用量），官方也提供[Codex 接入说明](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)。
该连接检查没有运行受管理 Coding Turn，不能替代原生质量验收。密钥不写入仓库或
发布包，也不修改全局 Codex／Hermes 配置。下一认证集成使用显式专用连接及隔离
凭据能力；不能直接修改当前固定 Profile 绕过控制读回。
