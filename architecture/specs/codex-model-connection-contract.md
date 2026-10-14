# Managed Codex model connection

This batch closes the dedicated authentication prerequisite of phase-two R13/G7,
then tests real Coding quality. It does not close Team/Dynamic selection, global
Runner capacity, cross-host recovery or the complete second phase.

## Composition and authority

- `CodexModelConnection` is nonsecret fixed data: Responses HTTPS endpoint, model,
  credential environment **name**, credential reference and generation. Construction,
  identity, validation and recovery never resolve the credential. Endpoint userinfo,
  query, fragment, embedded authentication and arbitrary native headers are refused.
- The first real configuration uses the already authorized DeepSeek endpoint/model.
  A successful account read is local authentication evidence, not model quality.
- Add a protected transport-construction hook to the concrete Runner. A connected
  Runner overrides that hook and preflight; the original execution loop, grants,
  Thread/Turn/Action identities, journals, cleanup and result adoption stay shared.
  Do not duplicate the business loop or substitute a module-global constructor.
- The original authority admits prepare before credential resolution; cancellation
  is checked before and after authentication. The same namespace and connection
  run control validation, login, barrier, then the original business pump.
- Credentials remain in trusted parent/native process memory. They never enter
  configuration files, Docker Env/argv, identity, Action, History, journal, raw
  exceptions or diagnostics. Python/native RAM is not guaranteed to be zeroized.

## Native preflight

- A separate authenticated transport owns a one-shot exclusive startup phase.
  Generic `request` still refuses account methods; concurrent request/notify and
  repeated login are refused during authentication. No peer request is answered.
- Send exactly API-key `account/login/start`, then `account/read` with
  `refreshToken=false`. Check an initially empty account before login.
- Accept exact login result `{type:apiKey}`, completed notification
  `{loginId:null,success:true,error:null}`, updated notification
  `{authMode:apikey,planType:null}`, and account readback with exact API-key account
  and boolean `requiresOpenaiAuth=true`. Reject unknown fields before projection.
- Exact native 0.144.4 source pins login/read to the exclusive `account-auth`
  queue. The following read response is a barrier for these two login notifications.
  It is not proof that other account traffic can never arrive. Later auth traffic
  fails the connection; never pass it into a business result or diagnostic inbox.
- Distinguish fixed `account/rateLimits/updated` from auth-state traffic. Only in
  the authenticated business phase, validate its exact native 0.144.4 envelope,
  eight-field snapshot and nullable typed variants; discard it. It neither
  modifies execution credits nor enters the business inbox. Bound accepted quota
  updates by the original event limit; unknown fields/types and peer requests fail.
- In that same phase, validate and discard four pure progress notifications:
  `item/agentMessage/delta`, `item/reasoning/textDelta`,
  `item/reasoning/summaryTextDelta`, `item/commandExecution/outputDelta`.
  Fixed exact envelopes, bounded locator/text strings and int64 indices apply;
  accept at most 16,384 such notifications per connection. This prevents token
  bursts displacing terminal evidence; it is not a general `item/*` filter.
  Terminal, errors, item lifecycle, interaction requests and unknown events retain
  original handling. Final content remains original `thread/read`, never a
  concatenation of progress text. Legacy unauthenticated transports are unchanged.
- Remote auth errors, malformed/echoed credentials, timeouts, disconnect and
  cancellation produce only fixed nonsecret errors. The original owner retires
  the entire namespace; incomplete retirement retains original resources for retry.
- Connected profiles retain ephemeral credential storage, fixed binary/image,
  disabled extensions, tool network and protected state. Only nonsecret model
  configuration changes; complete config/origin/layers are read back on this same
  connection. Native builtin filesystem/proc/memory isolation needs actual evidence.

## Publication and compatibility

- Defaults without selected Coding remain byte compatible. A transport hook is
  an actual implementation change: do not claim every old native body is unchanged.
- Publish current selected Temporal Coding as native protocol 2/binding 14;
  current selected bounded composition as version 3/binding 15. Existing option
  names, single execution authority and supported bounded topology are retained.
- Pin the new transport hook and every connected profile/environment/authentication
  helper independently. Old selected releases continue on their immutable matching
  Worker/wheel; current Workers reject old implementation metadata before business.
- Keep the complete per-helper inventory on the Worker and independently recheck
  it before admission. Public Runner identity records its exact algorithm/digest,
  checked against that inventory, so repeated original dispatch and namespace
  bindings fit existing JSON limits. Do not increase journal limits or replace
  per-helper checks with a caller-supplied opaque digest.
- Add explicit connected declarations without changing legacy tool declaration
  fields. SDK, JSON and TOML select the same nonsecret connection contract; borrowed
  and owned closure retain original resource responsibilities.

## Evidence and delivery

The private synthetic native probe already confirms exact notifications, unchanged
config, zero canary in files/inspect/logs, and empty account after a new process in
the same home. It does not prove builtin memory secrecy or remote model quality.

Required: failing wire/admission/leak/cancel tests; connected same-connection native
canary; original Local and Temporal approval/restart/stop recovery; installed app;
fixed real task set and independent oracle with three repetitions; defaults and
matching previous Worker recovery; source/install/build and exact owned cleanup.
Preserve failures and keep incomplete quality gates open. Commit only locally.
