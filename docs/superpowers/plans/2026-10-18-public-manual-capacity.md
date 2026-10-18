# Public original Action proof at Registry Update exhaustion

Existing P3-3 recovery only. The immutable 436-file `6af901f` wheel reproduced
**1 failed / 124.292s** at 4096 logical commands and exactly 2000 accepted/completed
Registry Updates. SDK manual fallback failed at the second reserve with the
server's distinct-Update limit. One genuine write and a live handler remained;
original cleanup and owned-service shutdown completed. Evidence:
`/private/tmp/ralf-agent-p3-public-manual-probe-20261018/`.

1. Add failing tests for a fixed strong-manual observation on the original public
   Registry. The ordinary refusal remains the prerequisite; no new descendant
   exemption, control slot or business authority.
2. Reuse the complete asynchronous `Registry.reserve` handler, preserving original
   prepare, SDK `manual_control` verification, post-await epoch/capacity check,
   Action slot commit, original `guard` post-check and `_control_result` validation.
3. Bound observations to 64 with no pending eviction and 2 MiB envelopes. Bind
   Scope, namespace UUID, policy, command, target/Action payload and Registry epoch.
   Timeout/lost response/cancellation never authorize Update fallback.
4. Pin the new source and Worker callable inventory; keep historical selected
   deployments on matching SDK/Worker. Verify stable defaults/saved History,
   affected regression, isolated wheel, original combined actual capacity case,
   duplicate control, physical end, ACK, retirement and owned lifecycle.
5. Update current evidence and commit locally only. Full P3-3/P3-2 and later gates
   remain open; do not infer native Coding pressure or model quality.

## Execution record

- Boundary RED: 15 failures with the absent transport module; GREEN: 15 passed.
- Initial integration: 91 passed / 2 failed because old fake handles lacked the
  SDK epoch/observation API; corrected doubles, production checks unchanged.
  Final targeted integration: 118 passed.
- Source affected 127 modules: 2,429 passed / 6 configuration skips / 89.645s.
- Isolated wheel, same modules: 2,429 passed / 6 configuration skips / 90.712s.
  All 437 product / 911 test inputs fixed; default publication and original/
  continued saved default History compatibility verified.
- Independent read-only review: no actionable P1/P2; no services run by reviewer.
- Same installed wheel's actual combined 4,096/2,000 acceptance: 1 passed /
  127.745s; original deadlines, physical-end/ACK/retirement, restart/original
  receipt and History assertions passed. Owned service shut down; seventeen prior
  artifact checksum sets unchanged. Only this recovery subgate closes.
- Evidence and final gate scope are recorded in the
  [batch review](../../../architecture/reviews/2026-10-18-temporal-public-manual-capacity.md).
