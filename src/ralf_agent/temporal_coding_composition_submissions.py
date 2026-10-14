"""Keep original SDK submissions owned through real responses, never Run authority."""

import asyncio
import re
import uuid
from dataclasses import asdict

from .errors import DefinitionMismatch, ValidationError
from .temporal_context_execution import ContextExecutionOwner
from .types import Scope, digest


class CompositionSubmissionOwner:
    def __init__(self, *, scope, release):
        if type(scope) is not Scope:
            raise ValidationError("Composition submissions require original trusted Scope")
        self.scope, self.release_digest = asdict(scope), digest(release)
        self._execution = ContextExecutionOwner(max_calls=256)
        self._loop = asyncio.get_running_loop()
        self._closing = False

    def stop_admission(self):
        self._closing = True

    async def execute(self, operation, *, scope, release_digest, request_digest):
        if asyncio.get_running_loop() is not self._loop:
            raise ValidationError("Submit on the original assembly construction loop")
        if self._closing:
            raise ValidationError("Composition submission admission is closed")
        if scope != self.scope or release_digest != self.release_digest:
            raise DefinitionMismatch("Composition submit changed trusted Scope or release")
        if type(request_digest) is not str or re.fullmatch(r"[a-f0-9]{64}", request_digest) is None:
            raise DefinitionMismatch("Composition submit requires its original request digest")
        proof = {
            "scope": self.scope,
            "action_id": uuid.uuid4().hex,
            "release_digest": self.release_digest,
            "request_digest": request_digest,
            "execution_epoch": "original-sdk-submission",
        }
        return await self._execution.execute(operation, proof=proof)

    async def wait(self, *, wait_timeout=30):
        return await self._execution.wait(wait_timeout=wait_timeout)

    async def aclose(self, *, wait_timeout=30):
        self.stop_admission()
        return await self._execution.aclose(wait_timeout=wait_timeout)
