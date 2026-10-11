# Temporal startup option preflight

Baseline ef711f4/dev70. Continues authorized R04/H5 and the documented startup-options Minor; full R01–R26 remains active. Local commit only, no push.

The existing Host startup should refuse invalid ordinary configuration before namespace/description RPCs, binding a Client, creating Engines or starting Workers. It reuses original SDK/History authorities and default Profile/queue identities.

Engine options accept only activity_timeout and drive_timeout in Host dictionaries. Host requires exact built-in int/float values, refusing subclasses before user arithmetic. The numeric non-bool finite (0,86400] seconds rule is shared with TemporalEngine rather than copied; direct Engine constructors retain their existing numeric subclass behavior. Original direct Engine constructors, defaults60/120 and manifests remain unchanged.

Worker field names are checked against the actually installed Worker constructor's explicit parameters without constructing Worker. Host-owned client/task_queue/runtime/activity_owner/workflows/activities fields cannot be overridden. Common primitive integer capacities, booleans, field-specific finite rates/ratio values (worker rate positive; task-queue rate and poll ratio nonnegative), nullable string identity and nonnegative timedelta values receive pure validation. Nullable capacity/rate fields preserve None. The installed SDK floor and defaults remain unchanged. Known rich SDK objects/callbacks still belong to SDK validation; this change does not claim every SDK object's semantics can be validated without construction.

Explicit build_id must equal every hosted assembly's original release digest before the first RPC. Default build_id remains independently supplied by the existing Worker factory. Tuner and explicit slot caps conflict as the SDK states; cached workflow capacity and explicit workflow slots/polls honor the installed SDK's documented minimum. Unknown newer fields in older installed SDK refuse without RPC, rather than silently dropping them.

Validation precedes Host's retained startup task and mutable startup state, so a pure refusal leaves it available for correction/retry on the original loop. Validation must not run caller callbacks, constructors, executors or network operations. Failures are ValidationError or DefinitionMismatch, never accidental TypeError for unknown names. Existing cancellation/fatal/shared-drain behavior remains unchanged.

Acceptance: RED→GREEN unknown Engine/Worker keys, reserved roles, timeout bool/NaN/infinity/zero/over-limit, common primitive bounds/cross-field constraints and build_id conflict; zero namespace RPC/Workers/start-task/Client mutation on refusal; corrected options retry; minimal no-SDK behavior; original Host lifecycle/routing and direct Engine compatibility; installed behavior, one final read-only whole-batch review, full/package/docs and local commit. No live model quality or global capacity guarantee.
