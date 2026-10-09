"""Pure team selection; delegation and effect ownership belong to LocalEngine."""

from .errors import ValidationError
from .orchestration_types import ChildCall, TeamSelection


class SequentialTeam:
    identity = {"kind": "sequential-team", "version": "1"}

    def select(self, request):
        for member in request.members:
            if member not in request.results:
                return TeamSelection(
                    [
                        ChildCall(
                            member,
                            member,
                            {
                                "task": request.task,
                                "results": request.results,
                            },
                        )
                    ]
                )
        return TeamSelection(done=True, result=request.results[request.members[-1]])


class RouterTeam:
    identity = {"kind": "router-team", "version": "1"}

    def select(self, request):
        field = request.config.get("route_field", "route")
        routes = request.config.get("routes")
        if (
            not isinstance(field, str)
            or not isinstance(routes, dict)
            or not isinstance(request.task, dict)
        ):
            raise ValidationError("Router requires a task object and explicit routes")
        route = request.task.get(field)
        member = routes.get(route) if isinstance(route, str) else None
        if member not in request.members:
            raise ValidationError("Route does not name an allowed team member")
        if member in request.results:
            return TeamSelection(done=True, result=request.results[member])
        return TeamSelection([ChildCall(member, member, request.task)])


class SupervisorTeam:
    identity = {"kind": "supervisor-team", "version": "1"}

    def select(self, request):
        supervisor = request.config.get("supervisor")
        if supervisor not in request.members:
            raise ValidationError("Configure a registered supervisor member")
        workers = [name for name in request.members if name != supervisor]
        missing = [name for name in workers if name not in request.results]
        if missing:
            return TeamSelection([ChildCall(name, name, request.task) for name in missing])
        if supervisor not in request.results:
            return TeamSelection(
                [
                    ChildCall(
                        supervisor,
                        supervisor,
                        {
                            "task": request.task,
                            "results": request.results,
                        },
                    )
                ]
            )
        return TeamSelection(done=True, result=request.results[supervisor])
