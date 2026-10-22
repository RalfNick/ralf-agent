export type DemoPhase =
  | "waiting_approval"
  | "approved"
  | "interrupted"
  | "succeeded";
export type DemoEvent = "approve" | "restart" | "resume" | "reset";
export interface DemoState {
  phase: DemoPhase;
  runState: "waiting_approval" | "running" | "succeeded";
  approved: boolean;
  runId: string;
  actionId: string;
  operationDigest: string;
  hostId: string;
  writes: number;
}
export const initialDemo: DemoState = {
  phase: "waiting_approval",
  runState: "waiting_approval",
  approved: false,
  runId: "run_01J_RALF",
  actionId: "action_change_001",
  operationDigest:
    "55b34230970c26c92d2ac0724204b5ce9d8f16214ab1febc7840321f2ee944ac",
  hostId: "process_01",
  writes: 0,
};
export function transitionDemo(state: DemoState, event: DemoEvent): DemoState {
  if (event === "reset") return { ...initialDemo };
  if (event === "approve" && state.phase === "waiting_approval")
    return { ...state, phase: "approved", runState: "running", approved: true };
  if (event === "restart" && state.phase === "approved")
    return { ...state, phase: "interrupted", hostId: "process_02" };
  if (event === "resume" && state.phase === "interrupted" && state.approved)
    return { ...state, phase: "succeeded", runState: "succeeded", writes: 1 };
  return state;
}
