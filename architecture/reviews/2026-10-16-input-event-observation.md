# Waiting-input event observation

## Gate and defect

P3-3 requires durable observation that leaves execution and user controls with the
original authority. Its existing `RunEventSubscription` rejected the legitimate
`waiting_input` snapshot when a follow subscription caught up to committed events.
The iterator raised `ValidationError` and closed instead of waiting for the answer.
This affects both synchronous and native asynchronous readers. Snapshot-only reads
could conceal the defect because they do not inspect live Run status.

This is a compatibility repair to the existing reader, not delivery of the planned
HTTP endpoints. P3-2 remains open; the frozen order and remaining service scope do
not change.

## Change and verification

Add `waiting_input` to the existing allowed status set. It remains nonterminal.
The observer still only calls `events` and `status`; source ownership, Scope and
binding checks, cursor sequencing, bounded pages and cancellation cleanup remain.
No execution, control, persistence or transport protocol changes.

Three RED cases reproduced the rejection: synchronous and asynchronous readers,
and an actual Local Engine with a durable SQLite question. The minimal repair plus
three unknown-status negative cases gives six new checks. The SQLite case catches
up, follows while waiting, disconnects without changing the entire original Run,
closes/reopens the Engine, submits the original answer and consumes the complete
remaining sequence from the same cursor, with exactly one `input_answered` event.
This is actual local storage/restart evidence with a scripted Provider, not a real
model or Temporal/HTTP service test.

Five affected modules: **81 passed**, zero failures/errors/skips, `-Werror`, 5.85s.
Ruff, formatting and whitespace checks pass. Independent read-only review found no
new P1/P2. The independent wheel installation passes all **38 subscription tests**,
zero failures/errors/skips, 1.427s. All imported product modules originate from
the new installation; 424 product files match source/sdist/wheel/site before and
after testing, and all 855 test copies remain unchanged. The full default Profile,
Manifest and orchestration canonical publication matches the frozen baseline;
original and continued saved default Histories replay offline with zero Provider
or service calls. No live continuation or old Coding History replay was performed.

Private evidence: `event-input-check/final-summary.json`; wheel SHA256
`c26394ae51f6f9c400aba9f07d0aac58bef3c4f12d06347af7735c8389d1b5ae`, sdist SHA256
`d3b2e0ccb66613b73c5c8ac0e156633d27b9633179734d92718e4e5311e06bcb`.
This registration follows the build and does not claim current documentation is
byte-identical to its build snapshot. Complete HTTP
reconnection, hosted control, permissions, retention and phase acceptance remain
unverified and must not be inferred from this repair.
