# SDK Model and Tool Foundation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline.

**Goal:** Deliver dev22 model/tool defaults and reusable compatibility checks
within the approved first roadmap phase, preserving local-only development.

**Architecture:** Additive Provider/factory and ToolRegistry convenience methods;
existing managed Runs own compatibility execution. No changes to execution authority.

**Tech stack:** Python3.11+, existing httpx/jsonschema; no new base dependencies.

Spec: [SDK model/tools](../specs/2026-10-08-sdk-model-tools.md).

## Task 1 — native Responses
- [x] RED actual HTTP request/response, tool continuation and approval restart,
  SSE/final agreement, status/error/refusal, capability and configuration tests.
- [x] Implement model_responses.py conversion/Provider, responses_stream.py
  semantic stream state and runtime_builder openai-responses factory.
Produces ModelProvider/StreamingModelProvider through existing ModelResponse and
ModelCapabilities. Consumes plain text/function messages, immutable config and
HTTPModelProvider lifecycle. Default native providers/identities stay unchanged.

## Task 2 — typed Python tools
- [x] RED schema types/defaults/postponed annotations, forbidden lazy evaluation,
  explicit Schema, context injection, async/approval/restart, callable identity.
- [x] Implement tool_schema.py pure inference and tool_functions.py immutable
  bridge; add ToolRegistry.register_function/tool. Validate before registration.
Produces existing ToolSpec/RegisteredTool and (arguments,context) callable. Consumes
Python signature and explicit metadata; no authorization inferred from annotations.

## Task 3 — model conformance defaults
- [x] RED not_run, selected scenarios, managed budgets/tool evidence, sanitized
  reports, caller ownership and bounded failed models.
- [x] Implement model_compatibility.py over existing evaluation/Engine ports,
  optional CLI and independent offline starter with typed read-only tool.
Consumes Task1 Provider and Task2 ToolRegistry; records actual Runs without tools
outside the fixed suite or claiming general task quality. No live calls this turn.

## Task 4 — review and distribution gates
- [x] Public exports/version/docs/current capability matrix and roadmap evidence.
- [x] One fresh whole-increment reviewer; Important/Critical RED→GREEN in one pass.
- [x] Full actual services, installed wheel, optional imports blocked, actualdev21
  native/local/History/template compatibility, build/lint/format/links/secret exclusion.
- [x] Stop owned temporary services, retain local records, no remote commit/push.

## Review focus

Model history correlation, unsupported continuation, SSE output consistency and
ordering, Schema defaults/JSON bool types, context spoofing, callable identity,
annotation evaluation and unsafe defaults. Probe limits/unknown usage/secret-safe
reports, no auto-paid calls, actual receiver evidence, ownership and baseline
recovery. Plan and features do not claim completed AgentScope parity.
