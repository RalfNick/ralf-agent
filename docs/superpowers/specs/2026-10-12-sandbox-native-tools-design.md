# Native Sandbox tools design

## Intent and authority

Continue R13/H4 under the user's standing request to finish all capabilities, with
replaceable ports, useful defaults, explicit configuration and truthful recovery.
Local commits only; no push. Architectural change, written spec/plan precede code.
The continuous execution instruction supersedes repeated design/plan permission menus.
Dev82 d9b5f1a is complete:5089 passed/386 configured skips; this design starts the next
batch and is not a delivery claim.

Sandbox executes one bounded native command in an isolated environment. Original
Engine/Action/ToolSource owns authorization, approvals, budget and result adoption;
Local/Temporal remain their sole execution authorities. Native container observations
are evidence, not a third RALF Run scheduler. No external DelegatedRunner in this batch.

Alternatives considered: trusted subprocess wrapper fails isolation requirements;
shell-driven Docker wrapper makes client process exit an inadequate stop proof.
Select a local Unix Docker HTTP API adapter using existing httpx, plus structural
custom SandboxProvider implementations. Remote providers remain future adapters.

## Public abstraction

- SandboxRequest(argv, timeout=30): frozen plain argv tuple/list1..64, each ordinary UTF-8
  string without NUL, executable argv[0] absolute container path, total≤65536 UTF-8 bytes;
  exact finite numeric timeout in (0,300]. Never carries image, host paths, credentials,
  resource limits or native container identity supplied by a model.
- SandboxObservation(invocation_id, native_id, state, exit_code=None):
  exact ordinary fields; state=not_found|created|running|stopped|unknown.
  Native ID is lowercase SHA256 or None; only stopped may have ordinaryint exit code.
- SandboxResult(invocation_id, native_id, exit_code, stdout, stderr, truncated,
  timed_out, observation): completed native stopped evidence, matching ID/exit code;
  ordinary UTF-8 output bounded≤16MiB total, exact bool flags. No lazy/custom-copy values.
- SandboxProvider structural port: ordinary fixed identity, async
  run(scope, request, *, invocation_id)->SandboxResult,
  observe(scope, invocation_id)->SandboxObservation,
  stop(scope, invocation_id)->SandboxObservation,
  aclose(wait_timeout=30)->None. Requests run with trusted Scope and host-generated ID;
  ordinary invocation ID nonblankASCII≤128 and Scope fieldUTF8≤512 each.
- SandboxError/Unavailable/IsolationViolation are typed errors; unresolved real work
  prevents successful close (CloseIncomplete). A trusted Python custom provider can lie;
  an interface cannot certify arbitrary code isolation.

DockerSandbox binds version, explicit absolute Unix socket, explicit local immutable
image sha256:<64hex>, API version default1.44, host allowances and selected scope allowlist.
Configuration validates BEFORE socket/image I/O; asynchronous open performs engine/image
admission. No hidden daemon launch, image pull or credentials in product code.
Custom providers retain the same completed-result and lifecycle contract.

## Fixed Docker isolation profile

First default only accepts Linux Docker engine, local Unix socket and installed image.
Pin socket realpath/device/inode, daemon ID/platform, effective API, image identity and
implementation. Image declared Volumes are refused; Entrypoint is replaced by requested
absolute container executable, image health checks disabled; no implicit mounts.
Use UID65534:65534, NetworkDisabled=true/NetworkMode=none, ReadonlyRootfs=true,
CapDrop=ALL, SecurityOpt=no-new-privileges, private PID/IPC, default seccomp required.
Never accept mounts/binds/devices/privileged/hostnetwork/socket forwarding in this profile.
Writable bounded tmpfs /workspace and /tmp only; default32MiB each, workdir/workspace.
Default memory256MiB/swap equal, CPU1, pids64, concurrency4, output1MiB.
Host configure memory64MiB..1GiB, CPU0.25..4, pids1..256, concurrency1..16,
scratch1..64MiB perpath, output1..16MiB, nativecontrol timeout1..30s.
Memory bound includes tmpfs; no persistent workspace or host artifacts in this subset.
Container isolation is a specific tested profile, not a claim of immunity to kernel bugs.

Exact create/start/wait/logs/inspect/kill/remove paths. Stream responses bounded BEFORE JSON
parse; nonTTY logs use strict8-byte Docker multiplex framing; collect bounded stdout/stderr.
Timeout/output overflow/observer cancellation/close requests stop only the owned native ID.
Actual inspect Running=false plus native exit code is required before stopped/result/slot
release. Killing a client request is insufficient. Failed stop/inspect/cleanup retains
ownership; no false successful close or quiescence.

Deterministic native name = prefix+digest(fixedprovideridentity, scope, invocation_id);
labels pin owner/provider/Scope/request digest. A preexisting matching container is queried,
never blindly started again; foreign/mismatched names are refused. Native started/terminal
evidence may be queried after host restart; original accepted Action result stays authority.
Never global prune, arbitrary nativeID delete, or change other containers. Closed provider
rejects new calls and may retry draining/cleanup. Slot covers actual work, not its await Task.
Partial create/start/stop acknowledgments remain unknown unless native query proves outcome.

## Tool lane and per-Agent role

SandboxToolSource exposes one sandbox_run descriptor with argv/timeout only.
Fixed SandboxProvider, configuration and methods captured; original register_tool_source
policy gate/approval and original actual async/thread owner are reused.
Initial native profile has no business/network/host-persistent effects; its tool is
read_only under original effect semantics, with approval defaulttrue, cost1.
This classification applies only to the fixed no-egress/no-mount ephemeral native profile;
custom providers must explicitly declare the same trusted restriction or be refused.
No policy option may turn an unverified provider into an isolation claim.

tools/sandbox-docker async declaration owns provider/source through original BuildContext.
Factories perform pure preflight before local service connection, source registration atomic.
SandboxBindingResource borrows original registered native source tools; pure ref/disabled
intersects already-granted tools and leaves business/Workspace/Skills grants unchanged.
Local/Temporal six member compositions support inherit/ref/disabled via original catalog.
Defaults and22 starters remain byte-identical. Explicit new role publishes protocol1 under
existing recognized admission machinery; exact marker choice must be verified from old
Worker pure validation BEFORE wiring, then actual old82 Worker refusal tested.

## Evidence and scope

TDD pure ordinary input/output/copy/lazy/bounds and resource identity; custom replacement
contract evidence is separate from actual isolation. Actual owned Docker cases prove readonly
root/nonroot/no mounts/no egress/pids/timeout/output bounds/real exit/cleanup and Scope.
Original six Local and six Temporal approval/restart/cancel/close/replay cases; cold native
create/start/query windows and exact original effect/terminal evidence required.
Installed actual tests zeroSKIP; fixed old82 releases/Session/22 starters and pre-I/O new
profile refusal; frozen module/package/docs/CI and final whole-suite evidence.
One strongest fresh readonly reviewer after the batch, all findings/Declined regraded before
one unified trueRED→GREEN Important fix pass; Minors deferred; no second review.
Only owned test containers/services cleaned and their actual exit/wait observed.

Environment: DockerDesktop explicitly started for authorized development; Docker29.0.1,
API1.52(min1.44), Linuxarm64, no images initially. Tests explicitly prepare one tiny pinned
development image; product never pulls. No real model/key needed for Sandbox acceptance.
Container workspace sharing, remote sandbox, artifact transfer, external Runner, fullH4/
R01–R26 and production quality stay open until their separate evidence.

Primary protocol references consulted2026-10-12:
[Docker run](https://docs.docker.com/reference/cli/docker/container/run/),
[container execution](https://docs.docker.com/engine/containers/run/),
[Engine API1.52](https://docs.docker.com/reference/api/engine/version/v1.52/).

DTO wire refinement beforeimplementation: exit codes are exact signed32-bit integers (custom providers may report signal values); each wire decoder rejects extra/missing fields, argv serializes as ordinarylist. Completed-result validator rechecks originalraw fields/observation and configuredtotaloutput UTF8bound≤16MiB without copyhooks. InvocationID grammarASCII letters/digits/underscore/dot/colon/hyphen.

Default implementation refinement beforeproduct: synchronous httpx Unix control I/O runs only in real original ThreadExecutionTracker-owned threads behind async SandboxProvider methods. The actual execution thread remains alive through native inspect/cleanup, including observer/global Task cancellation; close drains original actual threads. This avoids treating client Task completion as native stop. No invented Native thread proof or extra execution authority.

Native dispatch ownership refinement beforeimplementation: default local Docker uses a fixed explicit POSIX lease_root (default task-independent temporary directory per host UID) with an owned secured directory. Nonblocking per-source/Scope/invocation FD flock is acquired before native query/create/start, held through actual stop and exact cleanup, then released. Live duplicates refuse; crashed holders release automatically and cold query may reconcile existing native state. Ordinary files require owner UID, mode0600, one hard link/no symlink; root realpath/device/inode fixed. Lockfiles are retained to avoid unlink/new-inode races; retention/GC remains explicit future governance. This is native resource ownership only, not a new RALF execution authority. Config/native release includes lease_root.

Public default constructor exposes lease_root_path (absolute directory, not a lockfile), matching socket_path and fixed physical resource terminology. The actual lease_root helper returns its root identity; declarations forward this explicit field.

Declaration refinement before factory implementation: tools/sandbox-docker requires version,
socket_path,image; optional lease_root_path,api_version,scopes,memory_bytes,nano_cpus,
pids_limit,max_calls,max_output_bytes,scratch_bytes,control_timeout,max_timeout,prefix,
requires_approval(defaulttrue),cost(default1). Unknown fields rejected in pureprepare;
limits/policy/ToolSpec validated before any native client. Owned provider registered before
aopen, then owned borrowed-provider source, so original reverse cleanup closes source first.
