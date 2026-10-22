import test from "node:test";
import assert from "node:assert/strict";
import { initialDemo, transitionDemo } from "../src/lib/demo.ts";
import { siteMetadata, localeHref } from "../src/lib/site.ts";

test("approval survives a simulated restart and resumes the original operation once", () => {
  const approved = transitionDemo(initialDemo, "approve");
  assert.equal(approved.phase, "approved");
  assert.equal(approved.runState, "running");
  const restarted = transitionDemo(approved, "restart");
  assert.equal(restarted.phase, "interrupted");
  assert.equal(restarted.approved, true);
  assert.equal(restarted.runState, "running");
  const completed = transitionDemo(restarted, "resume");
  assert.equal(completed.phase, "succeeded");
  assert.equal(completed.runState, "succeeded");
  assert.equal(completed.runId, "run_01J_RALF");
  assert.equal(completed.writes, 1);
  assert.deepEqual(transitionDemo(completed, "resume"), completed);
  assert.deepEqual(transitionDemo(completed, "reset"), initialDemo);
});

test("restarting changes the illustrative host while keeping the approved operation identity", () => {
  const approved = transitionDemo(initialDemo, "approve");
  const restarted = transitionDemo(approved, "restart");
  assert.equal(initialDemo.runState, "waiting_approval");
  assert.equal(initialDemo.hostId, "process_01");
  assert.equal(restarted.hostId, "process_02");
  assert.equal(restarted.actionId, "action_change_001");
  assert.equal(restarted.operationDigest, initialDemo.operationDigest);
  assert.equal(restarted.actionId, approved.actionId);
  assert.equal(restarted.writes, 0);
  assert.equal(transitionDemo(restarted, "approve"), restarted);
});

test("the demonstration cannot resume or restart before approval", () => {
  assert.deepEqual(transitionDemo(initialDemo, "resume"), initialDemo);
  assert.deepEqual(transitionDemo(initialDemo, "restart"), initialDemo);
});

test("private previews cannot emit a fabricated public canonical", () => {
  assert.deepEqual(siteMetadata(undefined, "/zh/"), { indexable: false });
  assert.throws(() => siteMetadata("javascript:alert(1)", "/zh/"));
  assert.throws(() => siteMetadata("https://example.org/subpath", "/zh/"));
  assert.deepEqual(
    siteMetadata("https://ralf.example.org/", "/en/docs/quickstart/"),
    {
      indexable: true,
      canonical: "https://ralf.example.org/en/docs/quickstart/",
      origin: "https://ralf.example.org",
    },
  );
});

test("switching language preserves the current documentation page", () => {
  assert.equal(localeHref("/zh/docs/recovery/", "en"), "/en/docs/recovery/");
  assert.equal(
    localeHref("/en/docs/models-tools/", "zh"),
    "/zh/docs/models-tools/",
  );
  assert.equal(localeHref("/", "en"), "/en/");
});
