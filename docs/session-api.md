# Durable Local Sessions — dev39 / H2b1–H2b4b

H2b1 provides durable native/sequence conversations; H2b2 adds colocated Local
Graph (including parallel and direct transform nodes), Team, Dynamic linear-plan/DAG
and nested definitions with existing capability bindings. Colocated Session and execution records share the same SQLite connection and
Coordinator. H2b4a adds receipt-backed remote data for native/sequence Turns;
H2b4b adds explicit remote composite root conversations; Temporal shared Sessions remain unsupported. H2b3 adds host-authorized
composite root namespaces. Temporal stateless entry has a separate delivered subset.

## Open and continue

```python
from ralf_agent import Agent

# model is an explicitly configured Provider. No model call occurs when opening.
async with Agent(model=model, db_path=".ralf/runs.sqlite") as agent:
    session = await agent.open_session("customer-42", command_id="open-42")
    first = await session.run("My order is 123", command_id="turn-1", wait_timeout=10)
    second = await session.run("What was the order?", command_id="turn-2", wait_timeout=10)
    print(second.snapshot.state, second.snapshot.result)
    ref = session.ref.to_dict()
```

`run` returns WaitResult; use submit for AgentRun with `.turn` (TurnAdmission).
Each accepted Turn has a stable turn_id, increasing turn_seq, original binding
revision, input digest and RunRef. Coordination also fixes the Runtime authority_locator; reconnect with the original locator, not an unregistered alias. Duplicate command_id returns the exact original
Turn/receipt. Reusing it with changed input/budget/ref conflicts. History is read
through the existing Session/context ports; this does not claim real recall quality.

Shared Runtime uses `await agent.open_session(...)` or
`await runtime.open_session(AgentHarness(definition), session_id, command_id=...)`.
`runtime.attach_session(SessionRef.from_dict(ref))` observes the existing route.
Attach/status/turns do not resume work. Use the original RunRef and explicit
resume/approve/cancel/reconcile; human control is not a new Turn.

## Busy, binding and rebind

```python
from ralf_agent import SessionBusy

try:
    run = await session.submit("Next request", command_id="next-1")
except SessionBusy as busy:
    original = runtime.attach(busy.run_ref)
    print(await original.pending())
```

Busy rejects durably with the original RunRef and `.receipt`; replaying that same
command stays rejected after the blocker completes. A new attempt uses a new ID.
Busy does not create a second Run or increment seq. Reject receipts identify the
rejected proposed Run; its original blocker is `busy.run_ref`.

Opening fixes the declaration and resolved manifest. Moved defaults never silently
upgrade existing Sessions. Original receipt replay precedes current model resolution;
new input with missing original components refuses; successfully resolved changed manifests produce durable binding rejection receipts. Restore them or rebind
explicitly while idle:

```python
updated = await session.rebind(
    new_definition,
    expected_binding_revision=session.ref.binding_revision,
    command_id="rebind-1",
)
```

Rebind is a durable CAS, retaining old declarations/receipts and affecting future
Turns only. Use the returned entry/ref; a stale handle cannot submit a new Turn,
but its accepted command still replays and its history remains observable.
Changing resource/namespace requires a new Session/explicit branch, not rebind.
Idle native↔composite rebind is supported on the same actual conversation address.

## Composite conversations

```python
from ralf_agent import AgentSpec, GraphNode, GraphWorkflowSpec, Runtime

# engine is a configured LocalEngine with its colocated SQLiteMemory default.
async with Runtime(engine, owned=True) as runtime:
    graph = GraphWorkflowSpec("support", [GraphNode("answer", agent=AgentSpec("a", "Help"))])
    session = await runtime.create_agent(graph).open_session("customer", command_id="open")
    run = await session.submit("Investigate this issue", command_id="one", budget=64)
    result = await run.wait(wait_timeout=10)
    print(result.snapshot.state, result.snapshot.result)
```

The default root conversation uses plain host SQLiteMemory on the execution
connection. An explicit host resource may select an allowed root namespace.
Child bindings remain selected independently. Team/nested child Runs and parallel
graph nodes retain their existing isolated Session addresses; sequential graph
nodes retain their existing shared Session address. Intermediate messages can
therefore coexist with the root final message for sequential graphs.

Before composite success, the existing execution transaction appends one root
assistant message with `task` equal to the original Turn input and `content` equal
to the final composite result. Its stable ID is `run_id + ':turn:result'`.
Actual saved-content confirmation, a `session_turn_result_committed` event and Run
success commit together. Save or commit failure rolls them back; previously
committed child/tool evidence survives. Cancelled/failed Turns invent no final
message. This records whole-turn results; it does not rewrite later member inputs
or establish model recall quality. Use explicit context/bindings for application
history semantics.

### Authorized root namespaces

```python
from ralf_agent import LocalEngine, Runtime, SessionBindingResource, SQLiteMemory, SQLiteStore

store = SQLiteStore(".ralf/runs.sqlite")
memory = SQLiteMemory(store)
resource = SessionBindingResource(
    memory, namespaces=(None, "support", "sales"), default_namespace="support"
)
engine = LocalEngine(
    store, providers={"default": model}, tools=tools, conversation_resource=resource
)
async with Runtime(engine, owned=True) as runtime:
    agent = runtime.create_agent(graph)
    support = await agent.open_session("customer", namespace="support", command_id="support")
    sales = await agent.open_session("customer", namespace="sales", command_id="sales")
```

`model`, `tools` and `graph` are application-configured. Omission uses the host
resource default; explicit None selects None if authorized. The option is
composite-only; native/sequence retain existing leaf Session bindings.
The borrowed resource must be SessionBindingResource with actual colocated
SQLiteMemory; remote/foreign connections refuse. The Engine owner manages its
actual Store connection. SDK/factory and dev37 Profile JSON/TOML assembly are supported.
Use `components.conversation_resource` with `adapter="colocated-session"` and
`config={"namespaces": ["support", "sales"], "default_namespace": "support"}`.
The built-in factory borrows the existing execution connection; it accepts no path
or backend declaration. Validation precedes Store creation; building alone leaves
schema1, while a valid configured composite open enables4.

```python
from ralf_agent import Runtime, load_catalog

catalog = load_catalog("runtime.toml")
async with Runtime.from_profile(catalog.default, ".ralf/runs.sqlite") as runtime:
    session = await runtime.create_agent(graph).open_session("customer", command_id="open")
    result = await session.run("Question", command_id="one", budget=64)
```

Use `await Runtime.afrom_profile(...)` for async factories. `ComponentRegistry`
accepts explicit sync/async factories for this kind; their resources obey the
existing owned/borrowed lifecycle and actual colocated validation. New declarations
are rejected by old SDKs; absent-component Profile1/2 identities stay unchanged.

`ralf init my-sessions --template sessions` creates an offline installed example.
Its run command returns an immutable reference containing the original Turn and
Profile identity. Resume resolves that original Profile, validates the persisted
Turn and reconnects without another submission. Pure status uses the scoped
read-only reader and works with unavailable model configuration. Retain original
Profiles and code for recovery; reference files are not an execution authority.

Binding revisions fix resource identity, allowlist/default and selected namespace.
Each configured composite Run independently records that original descriptor in
the same Turn admission transaction, including an explicit None selection. Missing
or inconsistent admission evidence refuses dispatch and final save; upgrading a
database to schema4 does not reinterpret its genuine legacy Turns.
Changes prevent new dispatch on that original release; restore configuration or
explicitly rebind while idle on the same address. Original command replay and
pure observations retain original references/evidence.

The parent Session ID is the canonical storage key, for example
`ralf-session-v1:["support","customer"]`. Members derive their existing addresses
from that ID so same-ID roots cannot share node history across namespaces.
Explicit member namespace bindings remain independent. Default None IDs remain
original. Storage namespaces under trusted Scope do not supply enterprise identity
or resource ACL.

SQLite COMMIT failures are handled inside the rollback boundary. If rollback
itself fails, the Store preserves the original error and refuses further use;
close/reopen and restore original references for recovery. Uncommitted state cannot
be used as successful completion evidence.

## What occupies the Session

Approval, nonterminal intent, actual handlers/threads and unknown tool writes keep
the lane busy through close/restart. Composite occupancy walks original parent/child
records (4096 identities,16 levels), verifies ownership and includes graph frame
lifecycle. A terminal parent alone cannot release active/unknown descendants.
A succeeded Turn also requires confirmed final Session append matching the
original result/message_id. Failed
before successful result intent need not invent an assistant message.

`await session.status()` is a pure evidence-based eligibility observation;
`await session.turns(after=0, limit=100)` returns up to1000 ordered records.
The latest owner pointer advances atomically on the next explicit admission/rebind,
not on a timer or observation. Run state, real execution quiescence, save confirmation
and unknown effects are separate conditions. No queue or TTL lease is supplied.
Explicit resume/evidence controls may wake the original authority's terminal
housekeeping to adopt child evidence and mark quiescence. Observation remains
pure; terminal maintenance never reopens a cancelled parent or reexecutes effects.

Session entry close only detaches. Shared Runtime and existing RunHandles retain
H2a ownership/observation behavior. After Runtime close, use original code/components,
SQLite file and explicit SessionRef/RunRef reconnect; no new defaults or dispatch
are chosen by queries. Port/factory implementations must finish synchronously
inside the owning execution transaction. Mutation methods return None, save evidence is an actual bool, and read methods return concrete finite JSON data; deferred results are rejected without entering them.

## Resource safety and schema versions

SessionKey fixes trusted workspace/principal, canonical physical resource digest,
namespace and ID. Only SQLiteMemory sharing the actual execution connection is
allowed, optionally through an authorized SessionView. All sequence steps share
one namespace; composite root selection uses a host allowlist. Address aliases
cannot register separate routes. Raw submit is
refused on registered addresses even while idle; explicit Turn admission holds
the scoped permit and original acceptance transaction.

The first valid native/sequence Session open enables schema2. The first successful
default composite open or idle rebind enables schema3. Configured conversation
descriptors atomically enable schema4. Ordinary databases stay schema1. Readers
support1/2/3/4; dev31 and earlier refuse2, dev34 and earlier refuse3, and dev35 and
earlier refuse4 before execution. Busy/mismatched/failed admission does not upgrade.
Preparation never downgrades4.
This is an explicit opt-in one-way compatibility boundary: keep upgraded code for
an activated database, or use a separate schema1 database for old executors.
Failed first acceptance rolls back activation. There is no automatic downgrade.

`SessionAdmissionStore` is an optional, replaceable authority-bound port; custom
stores expose create_session_admission and must share the real transaction owner,
backend identity, raw-route protection, legacy query and save evidence. This does
not make arbitrary database adapters or independent Redis/PG coordinators compatible.
Composite support additionally advertises exact integer `session_admission_version=2`
or3 on the ExecutionStore and implements the optional
`ralf_agent.session_ports.CompositeSessionAdmissionStore.prepare_composites()->None`.
It must complete in the owning transaction and preserve monotonic activation and
rollback. The original port remains compatible; lazy or foreign-owner extensions
refuse before acceptance. Atomic SQLiteMemory append returns a positive completed
revision and must have actual saved-data evidence, rather than merely acknowledge.
Configured conversations additionally require exact marker3 and the optional
`ConversationSessionAdmissionStore.prepare_conversations()->None`. Schema4 is a
semantic compatibility fence for original-resource validation; base tables/DTOs
remain unchanged. Marker2 retains default composite support.

Shared remote routing/admission, durable FIFO,
input continuation, deadline, handoff, Temporal shared Sessions and full H2b remain separate
capabilities in the [remaining checklist](remaining-work.md).

## 远程持久会话：dev38／H2b4a

原生 Agent／顺序 Workflow 可通过已有 SessionBindingResource 和绑定目录使用
RedisMemory／PostgresMemory。它们保存会话数据；Local SQLite Coordinator
仍独占 Run、Turn、审批和预算的执行权威。异步客户端用 RuntimeBuilder.abuild
装配，或按既有 owned/borrowed 生命周期创建：

```python
from ralf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingSelection,
    SessionBindingResource,
)

# backend is an initialized RedisMemory or PostgresMemory; catalog and engine
# use the same trusted Scope. The caller owns this borrowed async backend.
catalog.register(
    "session",
    "history",
    "1",
    SessionBindingResource(backend, namespaces=("support",), default_namespace="support"),
)
definition = AgentDefinition(
    AgentSpec("support", "Help the user"),
    AgentBindingDescriptor(session=BindingSelection.ref("history", "1")),
)
agent = runtime.create_agent(definition)
session = await agent.open_session("customer", command_id="open")
run = await session.submit("Help me", command_id="one")
result = await run.wait(wait_timeout=10)
if result.snapshot.state == "waiting_reconciliation":
    print(await run.pending())
    await run.resume()  # original output and stable message ID; no business-tool replay
    result = await run.wait(wait_timeout=10, terminal_only=True)
```

所有顺序步骤必须使用同一后端、namespace 和回执协议。为了阻止不真实的
backend_id 别名绕过准入，同一 Scope 内已登记的远程物理会话地址会保守阻断
其他后端的直接提交。独立存储需要不同 namespace 或 Session ID。此规则只
覆盖同一执行权威，不能在两个独立 Coordinator 之间共享可写会话。

保存分为原 Run 日志中的意图、派发和核验回执；append 返回的 revision
本身不能确认成功。连接失败、CAS 冲突或未得到有效回执会暂停为
waiting_reconciliation，每次显式恢复最多尝试一次保存。先按原 message_id
查询；已保存且内容匹配时只补记回执，不重新追加，也不重跑模型／工具。

取消后的未知保存仍占用 Session；终态的显式 resume 只查询已有保存意图，
不追加新消息，也不把 cancelled/failed 改成 succeeded。status/turns 只读
原权威证据，不检查远程当前可用性或数据保留情况。保存到远程和提交本地
终态不是跨库原子事务：取消或本地提交失败时，远程可能已保存一条观察消息。

自定义后端需声明精确整数 session_receipt_version=1，并实现
inspect_message(scope, physical_session_id, message_id)。返回完整有限 JSON：
scope、session_id、message_id、当前 revision，以及 None 或包含正整数
revision 和原 message 的 receipt。查询必须是同一原子快照且按消息 ID
有界读取；SessionView 负责授权 namespace 投影和返回校验。原 read/append
接口和默认 colocated 路径保持兼容。

成功接受远程 Session 首次原子启用语义 schema5；dev37 及更早代码拒绝
此数据库。未使用该能力的 schema1/2/3/4 不升级。自定义 admission Store
需声明 session_admission_version=4，并提供同步、同事务完成的
prepare_remote_sessions 与 remote_owner 扩展。dev39 接通远程复合根会话；完整 H2b 仍缺跨权威租约、耐久 FIFO、输入续接及业务 deadline。

## 远程复合根会话：dev39／H2b4b

Local Graph（串行／并行／直接转换）、Team、动态 Plan／DAG 和嵌套流程
可使用显式 conversation_resource 的 receipt-v1 后端。根会话与成员绑定
独立：成员保留原有工具、上下文及会话；根最终消息记录原任务、最终结果和
复合定义名称。默认 SQLite 的原子保存保持原行为。

```python
from ralf_agent import Runtime, SessionBindingResource

# backend is an initialized receipt-v1 Session port. Caller owns this borrowed client.
engine.conversation_resource = SessionBindingResource(
    backend, namespaces=("support", "research"), default_namespace="support"
)
async with Runtime(engine, owned=True) as runtime:
    agent = runtime.create_agent(graph_or_team_or_dynamic_definition)
    session = await agent.open_session("customer", command_id="open")
    run = await session.submit("Investigate", command_id="one", budget=128)
    result = await run.wait(wait_timeout=10)
    if result.snapshot.state == "waiting_reconciliation":
        print(await run.pending())
        await run.resume()
        result = await run.wait(wait_timeout=10, terminal_only=True)
```

既有 session-resource 工厂也可配置宿主根资源，沿用异步客户端的 owned
生命周期和环境变量引用：

```toml
schema_version = 1
[default]
name = "app"
version = "1"
[[profiles]]
name = "app"
version = "1"
[profiles.providers.default]
adapter = "offline-echo"
[profiles.components.conversation_resource]
adapter = "session-resource"
[profiles.components.conversation_resource.config]
namespaces = ["support", "research"]
default_namespace = "support"
[profiles.components.conversation_resource.config.backend]
adapter = "redis"
[profiles.components.conversation_resource.config.backend.config]
url_env = "RALF_REDIS_URL"
backend_id = "app-conversations"
prefix = "ralf-conversations"
```

使用 await Runtime.afrom_profile(load_catalog(path).default, db_path)；同步
工厂在创建数据库前拒绝远程异步客户端。PostgreSQL 使用同一 backend 槽，
adapter="postgres"，config 包含 dsn_env、backend_id 及按需 initialize。

最终结果由原 Interpreter／Team Policy／Plan Verifier 采纳，先在原 Run
记录保存意图和独立 workflow/orchestration 标记，再执行远程保存。未确认
时保留该结果；重启恢复直接保存／核验，不再次选择计划、调用验证器或子 Agent。
原 Run 仍独占成功提交，远程写入和本地提交之间没有跨库事务。

message_id 固定为 run_id + ':turn:result'；终态 resume 只查询原意图。
未知保存／实际后代／工作线程仍占用会话，取消／失败不会被升级为成功。
Session status/turns/pending 只读持久证据。idle native↔composite rebind
可以复用同一真实远程地址和 namespace，原绑定修订与历史继续可观察。

首次成功接受该能力原子启用 schema6，dev38 及更早版本拒绝读取。自定义
admission Store 声明 session_admission_version=5 并实现同步同事务
prepare_remote_composites；仍包含原 schema5 native 及 colocated 扩展。
没有启用的新数据库保留原 schema1–5。跨权威会话租约、Temporal 绑定／
共享会话、耐久 FIFO、输入续接、业务 deadline 和完整 H2 继续待交付。
