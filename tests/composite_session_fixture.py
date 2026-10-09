import ralf_agent as r


class Provider:
    identity = {"kind": "composite-session-fixture", "version": "1"}

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools):
        self.calls += 1
        if tools and not any(m["role"] == "tool" for m in messages):
            return r.ModelResponse(tool_calls=[r.ToolCall("write", {}, "call")])
        return r.ModelResponse(output="done")


def definitions(tools=()):
    agent = r.AgentSpec("worker", "Answer", tools)
    graph = r.GraphWorkflowSpec("graph", [r.GraphNode("a", agent=agent)])
    return {
        "graph": graph,
        "parallel": r.GraphWorkflowSpec(
            "parallel", [r.GraphNode(n, agent=agent) for n in ("a", "b")], max_concurrency=2
        ),
        "team": r.TeamSpec("team", {"worker": agent}),
        "plan": r.DynamicWorkflowSpec("plan", {"worker": agent}),
        "dag": r.DynamicWorkflowSpec("dag", {"worker": agent}, planner="dag-rule", plan_mode="dag"),
        "nested": r.TeamSpec("outer", {"inner": graph}, child_budget=24),
        "transform": r.GraphWorkflowSpec("copy", [r.GraphNode("copy", transform="identity")]),
    }


def engine(path, *, provider=None, tools=None, **options):
    return r.LocalEngine(
        r.SQLiteStore(path),
        providers={"default": provider or Provider()},
        tools=tools or r.ToolRegistry(),
        **options,
    )


def root_messages(raw, run_id):
    import json

    return [
        json.loads(row[0])
        for row in raw.store.conn.execute(
            "SELECT data FROM memory_session_items WHERE message_id=?", (run_id + ":turn:result",)
        )
    ]
