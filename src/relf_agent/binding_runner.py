"""Pure selection of original borrowed Coding resources; no execution authority."""

from .delegated_coding import CodingToolHandler, registered_coding_tool
from .errors import AuthorizationDenied, DefinitionMismatch, ValidationError
from .tools import ToolRegistry


def pin_runner_binding(runner):
    """Reuse the original finite identity and actual lifecycle method pins."""
    return CodingToolHandler(runner)


def check_runner_binding(runner, pin):
    if type(pin) is not CodingToolHandler or pin.runner is not runner:
        raise DefinitionMismatch("Original Runner binding resource changed")
    return {
        "kind": "runner-binding-resource",
        "version": "1",
        "runner": pin.identity,
        "implementation": pin.implementation_identity,
    }


def runner_registration(runner):
    return check_runner_binding(runner, pin_runner_binding(runner))


def select_runner_tools(registry, names, *, mode="inherit", runner=None):
    """Validate effective grants against one actual original Coding resource."""
    if not isinstance(registry, ToolRegistry):
        raise ValidationError("Runner selection requires the original ToolRegistry")
    if mode not in {"inherit", "ref", "disabled"}:
        raise ValidationError("Runner selection requires inherit, ref or disabled")
    if type(names) not in (tuple, list) or any(type(n) is not str or not n for n in names):
        raise ValidationError("Runner selection requires original tool grants")
    if len(set(names)) != len(names):
        raise ValidationError("Runner selection cannot repeat a tool grant")
    handlers = [
        handler
        for name in names
        if (handler := registered_coding_tool(registry.get(name))) is not None
    ]
    if mode == "disabled":
        if handlers:
            raise AuthorizationDenied("Disabled Runner cannot grant a selected Coding tool")
        return None, None
    if not handlers:
        if mode == "ref":
            raise AuthorizationDenied("Selected Runner has no already-granted Coding tool")
        return None, None
    selected = handlers[0].runner
    if any(handler.runner is not selected for handler in handlers[1:]):
        raise ValidationError("Runner binding requires one unique selected Coding resource")
    if mode == "ref" and runner is not selected:
        raise DefinitionMismatch("Selected Runner differs from the original Coding tool resource")
    return selected, check_runner_binding(selected, handlers[0])
