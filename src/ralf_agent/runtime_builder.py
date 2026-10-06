"""Explicit adapter factories and resource ownership for the local runtime."""

import inspect
import json
import os
from dataclasses import asdict
from pathlib import Path

from .context import ContextAssembler
from .engine import LocalEngine
from .errors import RalfError, ValidationError
from .executors import PythonToolExecutor
from .harness import NativeHarness
from .memory import InMemoryMemory, SQLiteMemory
from .model_native import AnthropicProvider, GeminiProvider
from .model_protocol import ModelCapabilities
from .ports import is_sync_callable as _synchronous
from .ports import validate_engine
from .providers import DeepSeekChatProvider, OpenAIChatProvider
from .recall import FixedRecallPlanner, MemoryRecallPolicy, RecallQuery
from .retrieval import KnowledgeContext, LexicalRetriever, SQLiteKnowledgeStore
from .runtime_config import COMPONENT_KINDS, RuntimeProfile
from .storage import SQLiteStore
from .tools import ToolRegistry
from .types import ModelResponse, Scope, canonical


def _completed(value, label):
    if inspect.isawaitable(value) or inspect.isgenerator(value) or inspect.isasyncgen(value):
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValidationError(f"{label} must finish synchronously")
    return value


def _close_complete(value, label):
    if _completed(value, label) is not None:
        raise ValidationError(f"{label} must return None after completion")


def _fields(config, allowed):
    if set(config) - set(allowed):
        raise ValidationError("Unknown adapter configuration fields")


class BuildContext:
    def __init__(self, store, db_path, scope, base_dir):
        self.store, self.db_path, self.scope = store, str(db_path), scope
        self.base_dir = Path(base_dir).resolve()
        self.tools = None
        self._resources = []

    def own(self, resource):
        if resource is self.store:
            return resource  # ExecutionEngine already owns this authority.
        if not _synchronous(getattr(resource, "close", None)):
            raise ValidationError("Owned resources require synchronous close")
        if not any(existing is resource for existing in self._resources):
            self._resources.append(resource)
        return resource

    def path(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Resource path must be a non-empty string")
        path = Path(value)
        return str((path if path.is_absolute() else self.base_dir / path).resolve())

    def cleanup(self):
        while self._resources:
            resource = self._resources[-1]
            _close_complete(resource.close(), "Resource close")
            self._resources.pop()


class RuntimeInstance:
    """Close execution first; cleanup failures leave a retriable, stopped instance."""

    def __init__(self, engine, context):
        self._engine, self._context = engine, context
        self._engine_closed = False

    def __getattr__(self, name):
        if self._engine_closed:
            raise ValidationError("Runtime is closed; retry resource cleanup only")
        return getattr(self._engine, name)

    def __enter__(self):
        if self._engine_closed:
            raise ValidationError("Runtime is closed")
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self._engine_closed:
            _close_complete(
                self._engine.close() if self._engine is not None else self._context.store.close(),
                "Engine close",
            )
            self._engine_closed = True
        self._context.cleanup()

    async def wait_for_threads(self):
        if self._engine is not None and not self._engine_closed:
            await self._engine.wait_for_threads()


class RuntimeBuildError(ValidationError):
    """Construction failed; cleanup can be retried through the retained handle."""

    def __init__(self, cleanup):
        super().__init__("Runtime component construction failed")
        self.cleanup = cleanup


class EchoProvider:
    def __init__(self, label):
        self.label = label

    @property
    def identity(self):
        return {"kind": "offline-echo", "version": "1", "label": self.label}

    async def complete(self, messages, tools):
        return ModelResponse(
            output={"echo": messages[1]["content"], "label": self.label},
            usage={"input_tokens": 0, "output_tokens": 0, "source": "offline-echo"},
        )


def _echo_config(config):
    _fields(config, {"label"})
    if not isinstance(config.get("label", "offline"), str):
        raise ValidationError("Echo label must be a string")


def _chat_config(config):
    _model_options(config, OpenAIChatProvider, "OPENAI_API_KEY")


def _chat(config, context):
    return _model(config, OpenAIChatProvider, "OPENAI_API_KEY")


def _model_options(config, provider_type, key_env):
    allowed = {
        "model",
        "base_url",
        "api_key_env",
        "max_output_tokens",
        "timeout",
        "temperature",
        "top_p",
        "stop",
        "stream",
        "capabilities",
    }
    if provider_type in {OpenAIChatProvider, GeminiProvider}:
        allowed.add("seed")
    if provider_type is OpenAIChatProvider:
        allowed.add("token_parameter")
    if provider_type is AnthropicProvider:
        allowed.add("api_version")
    _fields(config, allowed)
    if not isinstance(config.get("model"), str) or not config["model"].strip():
        raise ValidationError("Model adapter requires model")
    if config["model"] == "YOUR_MODEL":
        raise ValidationError("Replace YOUR_MODEL in runtime.toml with an explicit model name")
    name = config.get("api_key_env", key_env)
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("api_key_env must name an environment variable")
    options = {key: value for key, value in config.items() if key != "api_key_env"}
    if "capabilities" in options:
        values = options["capabilities"]
        if not isinstance(values, dict) or set(values) - {"text", "tools", "streaming"}:
            raise ValidationError("Invalid model capability configuration")
        options["capabilities"] = ModelCapabilities(**{**asdict(provider_type.supported), **values})
    provider_type(api_key="configuration-validation", **options)
    return name, options


def _model(config, provider_type, key_env):
    name, options = _model_options(config, provider_type, key_env)
    key = os.environ.get(name)
    if not key:
        raise ValidationError("Configured model credential environment variable is unavailable")
    return provider_type(api_key=key, **options)


def _policy(config, context):
    _fields(config, {"facts", "session", "max_pages"})
    values = dict(config)
    for name in ("facts", "session"):
        if name in values:
            if not isinstance(values[name], dict):
                raise ValidationError("Recall query config must be an object")
            values[name] = RecallQuery(**values[name])
    return MemoryRecallPolicy(**values)


def _sqlite_memory(config, context):
    _fields(config, {"path"})
    return (
        context.own(SQLiteMemory(context.path(config["path"])))
        if "path" in config
        else SQLiteMemory(context.store)
    )


def _lexical(config, context):
    _fields(config, {"path", "namespace", "limit", "max_chars", "chunk_size", "overlap"})
    path = (
        context.path(config["path"]) if "path" in config else context.db_path + ".knowledge.sqlite"
    )
    store = context.own(
        SQLiteKnowledgeStore(
            path, chunk_size=config.get("chunk_size", 1000), overlap=config.get("overlap", 100)
        )
    )
    return KnowledgeContext(
        LexicalRetriever(store),
        namespace=config.get("namespace", "default"),
        limit=config.get("limit", 5),
        max_chars=config.get("max_chars", 8000),
    )


class ComponentRegistry:
    def __init__(self):
        self._factories = {}
        self.register(
            "provider",
            "offline-echo",
            lambda c, ctx: EchoProvider(c.get("label", "offline")),
            validator=_echo_config,
        )
        self.register("provider", "chat-completions", _chat, validator=_chat_config)
        for name, provider_type, key_env in [
            ("deepseek-chat", DeepSeekChatProvider, "DEEPSEEK_API_KEY"),
            ("anthropic-messages", AnthropicProvider, "ANTHROPIC_API_KEY"),
            ("gemini-content", GeminiProvider, "GEMINI_API_KEY"),
        ]:
            # Bind values now, rather than capture the loop's final adapter.
            self.register(
                "provider",
                name,
                lambda c, ctx, cls=provider_type, env=key_env: _model(c, cls, env),
                validator=lambda c, cls=provider_type, env=key_env: (
                    _model_options(c, cls, env) and None
                ),
            )
        self.register(
            "tools", "empty", lambda c, ctx: ToolRegistry(), validator=lambda c: _fields(c, {})
        )
        self.register("context_assembler", "default", lambda c, ctx: ContextAssembler(**c))
        self.register(
            "harness", "native", lambda c, ctx: NativeHarness(), validator=lambda c: _fields(c, {})
        )
        self.register(
            "tool_executor",
            "python",
            lambda c, ctx: PythonToolExecutor(ctx.tools),
            validator=lambda c: _fields(c, {}),
        )
        self.register("recall_policy", "bounded-recall", _policy)
        self.register("recall_planner", "fixed", lambda c, ctx: FixedRecallPlanner(_policy(c, ctx)))
        for kind in ("session_store", "memory_store"):
            self.register(kind, "sqlite", _sqlite_memory)
            self.register(kind, "in-memory", lambda c, ctx: InMemoryMemory(**c))
        self.register("knowledge", "sqlite-lexical", _lexical)
        from .workflow import IdentityTransform, StaticWorkflowCompiler, StaticWorkflowInterpreter

        self.register(
            "workflow_compiler",
            "static",
            lambda c, ctx: StaticWorkflowCompiler(),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "workflow_interpreter",
            "static",
            lambda c, ctx: StaticWorkflowInterpreter(),
            validator=lambda c: _fields(c, {}),
        )
        self.register(
            "workflow_transforms",
            "identity",
            lambda c, ctx: {"identity": IdentityTransform()},
            validator=lambda c: _fields(c, {}),
        )

    def register(self, kind, name, factory, *, validator=None):
        if (
            kind not in COMPONENT_KINDS | {"provider"}
            or not isinstance(name, str)
            or not name.strip()
        ):
            raise ValidationError("Register a known component kind and non-empty adapter name")
        if not _synchronous(factory) or (validator is not None and not _synchronous(validator)):
            raise ValidationError("Adapter factories and validators must be synchronous")
        if (kind, name) in self._factories:
            raise ValidationError("An adapter name is already registered")
        self._factories[kind, name] = (factory, validator)

    def prepare(self, kind, declaration):
        entry = self._factories.get((kind, declaration["adapter"]))
        if entry is None:
            raise ValidationError("Adapter is not explicitly registered")
        factory, validator = entry
        config = json.loads(canonical(declaration["config"]))
        if validator is not None:
            try:
                outcome = _completed(validator(json.loads(canonical(config))), "Adapter validator")
                if outcome is not None:
                    raise ValidationError("Adapter validator must return None")
            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError("Adapter configuration is invalid") from exc
        return factory, config


class RuntimeBuilder:
    def __init__(
        self, registry=None, *, store_factory=SQLiteStore, engine_factory=LocalEngine, base_dir=None
    ):
        self.registry = ComponentRegistry() if registry is None else registry
        self.store_factory, self.engine_factory = store_factory, engine_factory
        self.base_dir = Path.cwd().resolve() if base_dir is None else Path(base_dir).resolve()
        if (
            not isinstance(self.registry, ComponentRegistry)
            or not _synchronous(store_factory)
            or not _synchronous(engine_factory)
        ):
            raise ValidationError(
                "RuntimeBuilder requires an explicit registry and synchronous factories"
            )

    def build(self, profile, db_path, *, scope=None):
        if not isinstance(profile, RuntimeProfile):
            raise ValidationError("Build a RuntimeProfile")
        scope = Scope() if scope is None else scope
        if not isinstance(scope, Scope):
            raise ValidationError("Runtime scope must be supplied by a trusted host")
        providers = {
            name: self.registry.prepare("provider", value)
            for name, value in profile.providers.items()
        }
        components = {
            kind: self.registry.prepare(kind, value) for kind, value in profile.components.items()
        }
        path = str(Path(db_path).resolve())
        try:
            store = _completed(self.store_factory(path), "Execution store factory")
        except RalfError:
            raise
        except Exception as exc:
            raise ValidationError("Execution authority could not be constructed") from exc
        context, candidate = BuildContext(store, path, scope, self.base_dir), None

        def construct(prepared):
            factory, config = prepared
            return _completed(factory(config, context), "Adapter factory")

        try:
            built_providers = {name: construct(prepared) for name, prepared in providers.items()}
            for provider in built_providers.values():
                LocalEngine._component_identity(provider, ("complete",), False, "Provider")
            context.tools = (
                construct(components.pop("tools")) if "tools" in components else ToolRegistry()
            )
            options = {kind: construct(prepared) for kind, prepared in components.items()}
            candidate = _completed(
                self.engine_factory(
                    store,
                    providers=built_providers,
                    tools=context.tools,
                    scope=scope,
                    runtime_profile=profile.identity,
                    **options,
                ),
                "Execution engine factory",
            )
            validate_engine(candidate)
            return RuntimeInstance(candidate, context)
        except Exception as exc:
            # A rejected value without close cannot own execution resources.
            # Close the authority we created instead; actual close-capable
            # engines retain ownership until their close completes.
            owner = candidate if callable(getattr(candidate, "close", None)) else None
            cleanup = RuntimeInstance(owner, context)
            try:
                cleanup.close()
            except Exception as cleanup_error:
                raise RuntimeBuildError(cleanup) from cleanup_error
            if isinstance(exc, RalfError):
                raise
            raise RuntimeBuildError(cleanup) from exc
