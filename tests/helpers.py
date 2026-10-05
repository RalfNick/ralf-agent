from ralf_agent.types import ModelResponse, ToolCall


class ScriptedProvider:
    identity = {"kind": "scripted-test", "version": "1"}

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.messages = []

    async def complete(self, messages, tools):
        self.calls += 1
        self.messages.append(messages)
        return next(self.responses)


def tool_response(name="change", arguments=None):
    return ModelResponse(tool_calls=(ToolCall(name, arguments or {"value": 1}),))
