"""Preserve the latest completion correction and its following evidence atomically."""


def protect_feedback_tail(groups):
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if (
            len(group) >= 2
            and group[0].get("role") == "assistant"
            and not group[0].get("tool_calls")
            and group[1].get("role") == "user"
            and isinstance(group[1].get("content"), str)
            and group[1]["content"].startswith("Completion verification: ")
        ):
            return groups[:index] + [[m for g in groups[index:] for m in g]]
    return groups
