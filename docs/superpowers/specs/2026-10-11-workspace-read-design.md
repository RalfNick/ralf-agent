# Read-only Workspace Port Design

## Intent and position

The user wants each capability to have a replaceable public contract, useful defaults,
declarative assembly and recovery evidence, continuing locally without pushing.
This architectural increment implements the R13/H4 file-read foundation. It preserves
ToolSource, Action, PolicyGate, Local and Temporal History as the execution authorities.
It does not enable the currently refused `Agent.workspace` binding role or code execution.

Three approaches were considered: arbitrary path tools lack a stable host boundary;
a container implementation conflates workspace data with Sandbox isolation; an explicit
read-only WorkspacePort supplies a small replaceable boundary. Choose the third.

## Public contract and defaults

`WorkspacePort` has a finite JSON `identity` and synchronous methods:

- `stat(scope: Scope, path: str) -> dict`;
- `list(scope: Scope, directory: str = "", *, max_entries: int = 100) -> dict`;
- `read_text(scope: Scope, path: str, *, max_bytes: int = 1048576) -> dict`;
- `close() -> None`.

`FileSystemWorkspace(root, *, version, scopes=(Scope(),))` uses an existing host-selected
POSIX directory. `InMemoryWorkspace(files=None, *, version, scopes=(Scope(),))` takes a
copied mapping of relative UTF-8 paths to text. No dependency or automatic Context read
is added. Scope is a trusted host allowance, not authentication. Only listed exact
workspace/principal pairs are allowed. Scope.workspace is not a physical path.

Paths are canonical forward-slash relative UTF-8 strings, maximum4096 encoded bytes
and128 components. No absolute path, empty file path, dot/parent component, empty
component, NUL, backslash or ASCII control character/DEL is accepted. Empty directory selects
the root. `.git` and `.ralf` components are protected case-insensitively; listing omits
these entries, with an independently bounded scan of `max_entries+3` raw entries.
Caller entry bound is an ordinary integer1..1000; text byte bound1..16777216.

`stat` returns `{path,kind,size,version}`; directories have kind `directory`, size null.
`list` returns `{path,entries}`, entries sorted by path using that same record format;
if more than the visible bound or raw scan bound exists it refuses, never truncates
silently. `read_text` returns `{path,text,bytes,sha256,version}`. Empty UTF-8 text is
valid; embedded NUL/invalid UTF-8 refuses; other UTF8-decodable binary is not universally classified. `version` is an opaque file metadata revision,
not a write receipt or a promise of atomicity against malicious concurrent writers.
Every output is detached finite JSON. Missing/unsafe/oversized actual data raises
sanitized `WorkspaceError`; bad caller/configuration raises `ValidationError`, a
forbidden Scope raises `AuthorizationDenied`, changed pinned resources raise
`DefinitionMismatch`. OS errors and absolute host paths are not returned.

Memory accepts at most4096 files,16MiB per file,64MiB total UTF-8 data, rejects file/
directory prefix conflicts, derives directories, and never mutates caller mappings.
Both defaults implement the same visible path/Scope/bound/error contract.

## File ownership and source validation

Capture the host path string once; lexical normalization must not erase a final symlink.
Validate original root entry against the opened FD before accepting initialization.
Normalize the trusted host root once to an absolute real path; reject a symlink root
at initialization. Pin root device/inode and one owned directory FD. Identity includes
kind/version/behavior version, allowed Scopes, root path digest and device/inode;
there is no implicit UUID file creation, migration or managed SQLite metadata.
Reconstructing the same physical root restores the same identity; replacement/moving
a root requires explicit reconfiguration, not silent attachment to an old Run.

All operation paths traverse from the root FD, with FD-relative opens, O_NOFOLLOW,
O_DIRECTORY for intermediate directories and O_NONBLOCK for files. Reject symlink,
non-regular/special files, hard-linked regular files and cross-device descendants.
Validate normalized root UTF8/4096-byte allowance before allocation; all post-allocation
initialization lies within exception-safe cleanup. Check the full canonical root
address chain without following newly introduced ancestor symlinks before/after work, each opened ancestor against its parent
entry, and leaf metadata before/after stat/read/list. Never return a value if ordinary
replacement or modification is observed. Bounded `max_bytes+1` read detects growth;
FDs close in finally, including errors. A directory moved after opening cannot silently
return evidence after post-validation fails. These checks are a read policy under a
trusted filesystem, not a process sandbox or a global filesystem transaction.

Operations hold an independent synchronized active count. `close` forbids new calls;
if a synchronous operation still runs it raises WorkspaceError retaining the root FD;
retry after true exit closes it. It never releases an in-use FD because an awaiter died.
Unsupported platforms refuse before allocating resources.

## Original managed tool integration

`WorkspaceToolSource(workspace, *, version, max_entries=100, max_bytes=1048576)` borrows
any compatible WorkspacePort. It supplies `workspace_stat`, `workspace_list`, and
`workspace_read_text` descriptors; the latter two use the fixed host caps, never an
untrusted per-call limit. Schema accepts only path/directory strings. Source identity
pins the port identity/behavior/caps; output is revalidated for canonical JSON and
identity after await. Host policies may require approval or cost, but only read_only,
with no effect key/reconciler. The original registration function enforces optional
pure validate_tool_policy(descriptor,policy) synchronously, with None as the only
completed return, before publishing handlers. Per-Agent existing tool_set can restrict the three names.
Custom ports must maintain the same contract; opaque port identity does not authenticate
the custom implementation or sandbox its Python code.

The source uses the original ThreadExecutionTracker both for itself and the ambient
handler. Queued cancellation withdraws work; running cancellation retains both owners
until the actual port method exits, even when the original event loop is closed.
`aclose` forbids new calls and drains actual handlers, but does not close its borrowed
port. The async factory owns the port before the source; reverse cleanup drains the
source before closing the port, including partial allocation failures.

`tools/workspace-read` config is exactly `{root,version}` plus optional `scopes`,
`max_entries`, `max_bytes`, `prefix`, `requires_approval`, `cost`. Explicit Scopes are
list1..256 of exact `{workspace,principal}` objects with no duplicates. Ordinary
boolean/integer fields and every other structural check occur before I/O; relative
host root joins existing assembly `context.base_dir` lexically before port normalization.
Absent scopes uses the trusted assembly context.scope; explicit scopes remain fixed.
The assembly Scope must be included before allocating the port; SDK custom ports
remain responsible for their declared caller contract. Pure preflight performs
no mkdir/stat/open. Local sync build refuses async factory before Store creation.
Both Local and Temporal original async factories can assemble it. InMemory or a
custom port is available through SDK injection/registered host factories.

## Acceptance and open work

Actual POSIX tests cover traversal, Scope, symlink/hardlink/FIFO/device, root and
ancestor replacement, file mutation, caps, copied outputs and retryable close. Original
managed lifetime tests cover running/queued cancellation, closed loops and resource
cleanup. Local Graph/native restart, scope refusal and changing file content after
accepted tool evidence; actual Temporal approval/restart/History replay for FS and
Memory ports; frozen source/wheel/install/core and dev74 compatibility are required.
Version stays74 until required actual authority proof. One fresh read-only final
review, one unified Important RED→GREEN pass, frozen gates and local commit only.

Writes need cross-process exclusive leases plus intent/receipt/unknown-effect protocols;
CAS alone is insufficient. Agent.workspace binding/views, staged file context, Skills,
container/remote Sandbox, delegated Coding Runner, directory streaming and enterprise
file ACL remain open. A read-only root does not prove R13/H4 or full R01–R26 completion.

Rejected path/content inputs are length-checked before encoding or splitting; memory UTF8 encoding uses bounded chunks and remaining-total allowance. Custom text output is bounded before JSON copying. Source registers ownership under its admission lock for direct and ambient calls. Unicode C1 path/root controls remain the recorded deferred Minor, outside the current ASCII/DEL refusal.
