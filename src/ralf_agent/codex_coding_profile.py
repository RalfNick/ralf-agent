"""Frozen Linux Coding candidate and control gates; no execution authorization.

The profile is pure data/validation. It does not launch Codex, resolve auth,
select a business factory, or certify sandbox/tool/cancellation enforcement.
"""

import hashlib
import json
import re
import tomllib

from .codex_protocol import _snapshot
from .errors import DefinitionMismatch, ValidationError

_VERSION = "0.144.4"
_IMAGE = "sha256:0a38a968acc4f11ab75cfd4b65a1c2f1982a18bfc27d9fb0dc1045bef5e79d43"
_NATIVE_ORIGIN = "sha256:d3195ce1484a937eaf84cec38dfd6c86992d41dc4ffbe7640ccfc7f448f9abfa"
_EMPTY_ORIGIN = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
_BASE_CONFIG_TEXT = 'default_permissions = "ralf-coding-v1"\napproval_policy = "never"\napprovals_reviewer = "user"\nallow_login_shell = false\nweb_search = "disabled"\ncli_auth_credentials_store = "ephemeral"\ncheck_for_update_on_startup = false\n\n[permissions.ralf-coding-v1.filesystem]\n":minimal" = "read"\n"/home/ralf" = "deny"\n"/traps" = "deny"\n"/forbidden" = "deny"\n"/tmp" = "deny"\n"/opt/codex/bin/codex" = "read"\n\n[permissions.ralf-coding-v1.filesystem.":workspace_roots"]\n"." = "write"\n".codex" = "deny"\n".agents" = "deny"\n".git" = "deny"\n\n[permissions.ralf-coding-v1.network]\nenabled = false\n\n[shell_environment_policy]\ninherit = "none"\nexperimental_use_profile = false\nignore_default_excludes = false\nset = { PATH = "/usr/bin:/bin", TMPDIR = "/workspace/.tmp" }\n\n[analytics]\nenabled = false\n\n[apps._default]\nenabled = false\ndestructive_enabled = false\nopen_world_enabled = false\n\n'
# (native lifecycle stage, native default, frozen effective value).
_FEATURES = {
    "apply_patch_freeform": ("removed", False, False),
    "apply_patch_streaming_events": ("underDevelopment", False, False),
    "apps": ("stable", True, False),
    "apps_mcp_path_override": ("removed", False, False),
    "artifact": ("underDevelopment", False, False),
    "auth_elicitation": ("stable", True, False),
    "browser_use": ("stable", True, False),
    "browser_use_external": ("stable", True, False),
    "browser_use_full_cdp_access": ("stable", True, False),
    "chronicle": ("underDevelopment", False, False),
    "code_mode": ("underDevelopment", False, False),
    "code_mode_host": ("stable", True, False),
    "code_mode_only": ("underDevelopment", False, False),
    "codex_git_commit": ("removed", False, False),
    "collaboration_modes": ("removed", True, False),
    "computer_use": ("stable", True, False),
    "concurrent_reasoning_summaries": ("underDevelopment", False, False),
    "current_time_reminder": ("underDevelopment", False, False),
    "default_mode_request_user_input": ("underDevelopment", False, False),
    "deferred_executor": ("underDevelopment", False, False),
    "elevated_windows_sandbox": ("removed", False, False),
    "enable_fanout": ("underDevelopment", False, False),
    "enable_mcp_apps": ("underDevelopment", False, False),
    "enable_request_compression": ("stable", True, False),
    "exec_permission_approvals": ("underDevelopment", False, False),
    "experimental_windows_sandbox": ("removed", False, False),
    "external_migration": ("removed", False, False),
    "fast_mode": ("stable", True, False),
    "goals": ("stable", True, False),
    "guardian_approval": ("stable", True, False),
    "hooks": ("stable", True, False),
    "image_detail_original": ("removed", False, False),
    "image_generation": ("stable", True, False),
    "in_app_browser": ("stable", True, False),
    "item_ids": ("underDevelopment", False, False),
    "js_repl": ("removed", False, False),
    "js_repl_tools_only": ("removed", False, False),
    "local_thread_store_compression": ("underDevelopment", False, False),
    "memories": ("beta", False, False),
    "mentions_v2": ("stable", True, False),
    "multi_agent": ("stable", True, False),
    "multi_agent_mode": ("removed", False, False),
    "multi_agent_v2": ("underDevelopment", False, False),
    "network_proxy": ("beta", False, False),
    "non_prefixed_mcp_tool_names": ("underDevelopment", False, False),
    "personality": ("stable", True, False),
    "plugin_hooks": ("removed", False, False),
    "plugin_sharing": ("stable", True, False),
    "plugins": ("stable", True, False),
    "prevent_idle_sleep": ("beta", False, False),
    "realtime_conversation": ("underDevelopment", False, False),
    "remote_compaction_v2": ("stable", True, False),
    "remote_control": ("removed", False, False),
    "remote_models": ("removed", False, False),
    "remote_plugin": ("stable", True, False),
    "request_permissions_tool": ("underDevelopment", False, False),
    "request_rule": ("removed", False, False),
    "resize_all_images": ("removed", True, True),
    "respect_system_proxy": ("underDevelopment", False, False),
    "responses_websockets": ("removed", False, False),
    "responses_websockets_v2": ("removed", False, False),
    "rollout_budget": ("underDevelopment", False, False),
    "runtime_metrics": ("underDevelopment", False, False),
    "search_tool": ("removed", False, False),
    "secret_auth_storage": ("stable", False, False),
    "shell_snapshot": ("stable", True, False),
    "shell_tool": ("stable", True, True),
    "shell_zsh_fork": ("underDevelopment", False, False),
    "skill_env_var_dependency_prompt": ("removed", False, False),
    "skill_mcp_dependency_install": ("stable", True, False),
    "sqlite": ("removed", True, False),
    "standalone_web_search": ("underDevelopment", False, False),
    "steer": ("removed", True, False),
    "terminal_resize_reflow": ("removed", True, True),
    "terminal_visualization_instructions": ("underDevelopment", False, False),
    "token_budget": ("underDevelopment", False, False),
    "tool_call_mcp_elicitation": ("stable", True, False),
    "tool_search": ("removed", False, False),
    "tool_search_always_defer_mcp_tools": ("removed", True, True),
    "tool_suggest": ("stable", True, False),
    "tui_app_server": ("removed", True, True),
    "unavailable_dummy_tools": ("removed", False, False),
    "undo": ("removed", False, False),
    "unified_exec": ("stable", True, True),
    "unified_exec_zsh_fork": ("underDevelopment", False, False),
    "use_agent_identity": ("underDevelopment", False, False),
    "use_legacy_landlock": ("deprecated", False, False),
    "use_linux_sandbox_bwrap": ("removed", False, False),
    "web_search_cached": ("deprecated", False, False),
    "web_search_request": ("deprecated", False, False),
    "workspace_dependencies": ("stable", True, False),
    "workspace_owner_usage_nudge": ("removed", False, False),
}
_SKILLS = ("imagegen", "openai-docs", "plugin-creator", "skill-creator", "skill-installer")
_NULL_DEFAULTS = (
    "agents",
    "apps_mcp_product_sku",
    "audio",
    "auto_review",
    "background_terminal_max_timeout",
    "chatgpt_base_url",
    "compact_prompt",
    "debug",
    "desktop",
    "developer_instructions",
    "disable_paste_burst",
    "experimental_compact_prompt_file",
    "experimental_realtime_start_instructions",
    "experimental_realtime_webrtc_call_base_url",
    "experimental_realtime_ws_backend_prompt",
    "experimental_realtime_ws_base_url",
    "experimental_realtime_ws_model",
    "experimental_realtime_ws_startup_context",
    "experimental_thread_config_endpoint",
    "experimental_thread_store",
    "experimental_thread_store_endpoint",
    "experimental_use_unified_exec_tool",
    "feedback",
    "file_opener",
    "forced_chatgpt_workspace_id",
    "forced_login_method",
    "ghost_snapshot",
    "hooks",
    "include_apps_instructions",
    "include_collaboration_mode_instructions",
    "include_environment_context",
    "include_permissions_instructions",
    "instructions",
    "js_repl_node_module_dirs",
    "js_repl_node_path",
    "log_dir",
    "mcp_oauth_callback_port",
    "mcp_oauth_callback_url",
    "mcp_oauth_credentials_store",
    "memories",
    "model",
    "model_auto_compact_token_limit",
    "model_auto_compact_token_limit_scope",
    "model_catalog_json",
    "model_context_window",
    "model_instructions_file",
    "model_provider",
    "model_reasoning_effort",
    "model_reasoning_summary",
    "model_supports_reasoning_summaries",
    "model_verbosity",
    "notice",
    "notify",
    "openai_base_url",
    "orchestrator",
    "oss_provider",
    "otel",
    "personality",
    "plan_mode_reasoning_effort",
    "profile",
    "project_root_markers",
    "projects",
    "realtime",
    "review_model",
    "sandbox_mode",
    "sandbox_workspace_write",
    "service_tier",
    "show_raw_agent_reasoning",
    "sqlite_home",
    "suppress_unstable_features_warning",
    "tool_output_token_limit",
    "tool_suggest",
    "tools",
    "tui",
    "windows",
)
_NATIVE_DEFAULTS = {
    "allow_login_shell": False,
    "analytics": {"enabled": False},
    "approval_policy": "never",
    "approvals_reviewer": "user",
    "apps": {
        "_default": {
            "approvals_reviewer": None,
            "default_tools_approval_mode": None,
            "destructive_enabled": False,
            "enabled": False,
            "open_world_enabled": False,
        }
    },
    "check_for_update_on_startup": False,
    "cli_auth_credentials_store": "ephemeral",
    "default_permissions": "ralf-coding-v1",
    "hide_agent_reasoning": False,
    "history": {"max_bytes": None, "persistence": "save-all"},
    "marketplaces": {},
    "mcp_servers": {},
    "model_providers": {},
    "plugins": {},
    "profiles": {},
    "project_doc_fallback_filenames": [],
    "project_doc_max_bytes": 32768,
    "shell_environment_policy": {
        "exclude": None,
        "experimental_use_profile": False,
        "ignore_default_excludes": False,
        "include_only": None,
        "inherit": "none",
        "set": {"PATH": "/usr/bin:/bin", "TMPDIR": "/workspace/.tmp"},
    },
    "web_search": "disabled",
}
_NATIVE_PERMISSIONS = {
    "ralf-coding-v1": {
        "description": None,
        "extends": None,
        "filesystem": {
            "/forbidden": "deny",
            "/home/ralf": "deny",
            "/opt/codex/bin/codex": "read",
            "/tmp": "deny",
            "/traps": "deny",
            ":minimal": "read",
            ":workspace_roots": {".": "write", ".agents": "deny", ".codex": "deny", ".git": "deny"},
            "glob_scan_max_depth": None,
        },
        "network": {
            "allow_local_binding": None,
            "allow_upstream_proxy": None,
            "dangerously_allow_all_unix_sockets": None,
            "dangerously_allow_non_loopback_proxy": None,
            "domains": None,
            "enable_socks5": None,
            "enable_socks5_udp": None,
            "enabled": False,
            "mitm": None,
            "mode": None,
            "proxy_url": None,
            "socks_url": None,
            "unix_sockets": None,
        },
        "workspace_roots": None,
    }
}
_SKILL_DEPENDENCIES = {
    "imagegen": None,
    "openai-docs": {
        "tools": [
            {
                "description": "OpenAI Developer Docs MCP server",
                "transport": "streamable_http",
                "type": "mcp",
                "url": "https://developers.openai.com/mcp",
                "value": "openaiDeveloperDocs",
            }
        ]
    },
    "plugin-creator": None,
    "skill-creator": None,
    "skill-installer": None,
}
_METHODS = frozenset(
    {
        "initialize",
        "config/read",
        "configRequirements/read",
        "experimentalFeature/list",
        "permissionProfile/list",
        "mcpServerStatus/list",
        "skills/list",
        "plugin/list",
        "plugin/installed",
    }
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _same(actual, expected):
    # Canonical JSON deliberately distinguishes 0/False and 1/True.
    return _canonical(actual) == _canonical(expected)


def _require(condition):
    if not condition:
        raise ValidationError("Codex Coding control response differs from the frozen candidate")


def _skill_path(name):
    return f"/home/ralf/.codex/skills/.system/{name}/SKILL.md"


def _leaf_keys(value, prefix=""):
    keys = set()
    pairs = value.items() if type(value) is dict else enumerate(value)
    for key, item in pairs:
        path = f"{prefix}.{key}" if prefix else key
        if type(item) in (dict, list) and item:
            keys.update(_leaf_keys(item, path))
        else:
            keys.add(path)
    return keys


class CodexCodingProfile:
    """One pinned candidate; verified control data never admits execution."""

    def __init__(self):
        config = _BASE_CONFIG_TEXT + "[features]\n"
        config += "".join(
            f"{name} = {str(name in ('shell_tool', 'unified_exec')).lower()}\n"
            for name in sorted(_FEATURES)
        )
        for name in _SKILLS:
            config += f'\n[[skills.config]]\npath = "{_skill_path(name)}"\nenabled = false\n'
        self._config_text = config
        self._parsed = tomllib.loads(config)
        self._origin = "sha256:" + hashlib.sha256(_canonical(self._parsed).encode()).hexdigest()
        if self._origin != _NATIVE_ORIGIN:
            raise DefinitionMismatch(
                "Codex Coding candidate differs from the native config baseline"
            )
        self._digest = hashlib.sha256(config.encode()).hexdigest()
        self._expected_config = {name: None for name in _NULL_DEFAULTS}
        self._expected_config.update(_snapshot(_NATIVE_DEFAULTS, "candidate defaults"))
        self._expected_config["permissions"] = _snapshot(
            _NATIVE_PERMISSIONS, "candidate permissions"
        )
        self._expected_config["skills"] = _snapshot(self._parsed["skills"], "candidate skills")
        self._expected_config["features"] = {
            name: name in ("shell_tool", "unified_exec")
            for name in _FEATURES
            if name != "apps_mcp_path_override"
        }

    @property
    def config_text(self) -> str:
        return self._config_text

    @property
    def identity(self) -> dict:
        return {
            "kind": "codex-coding-candidate",
            "version": "1",
            "native_version": _VERSION,
            "image_id": _IMAGE,
            "config_digest": self._digest,
            "config_origin_digest": self._origin,
            "permission_profile": "ralf-coding-v1",
            "normal_account": {"uid": 10001, "gid": 10001, "home": "/home/ralf"},
            "control_verified": False,
            "execution_admitted": False,
        }

    def validate_control(self, results: dict[str, dict]) -> dict:
        """Validate result objects, not RPC envelopes; return only sanitized metadata."""
        _require(type(results) is dict)
        values = _snapshot(results, "Coding control")
        _require(set(values) == _METHODS and all(type(v) is dict for v in values.values()))
        handshake = values["initialize"]
        _require(set(handshake) == {"userAgent", "codexHome", "platformFamily", "platformOs"})
        _require(handshake["codexHome"] == "/home/ralf/.codex")
        _require(handshake["platformFamily"] == "unix" and handshake["platformOs"] == "linux")
        agent = handshake["userAgent"]
        _require(
            type(agent) is str
            and bool(re.match(r"^[^/ ]+/0\.144\.4 \(Alpine Linux 3\.22\.6; aarch64\) ", agent))
        )
        self._validate_config(values["config/read"])
        _require(_same(values["configRequirements/read"], {"requirements": None}))
        self._validate_features(values["experimentalFeature/list"])
        self._validate_profiles(values["permissionProfile/list"])
        _require(_same(values["mcpServerStatus/list"], {"data": [], "nextCursor": None}))
        self._validate_skills(values["skills/list"])
        _require(
            _same(
                values["plugin/list"],
                {
                    "marketplaces": [],
                    "marketplaceLoadErrors": [],
                    "featuredPluginIds": [],
                },
            )
        )
        _require(
            _same(values["plugin/installed"], {"marketplaces": [], "marketplaceLoadErrors": []})
        )
        return {
            **self.identity,
            "control_verified": True,
            "execution_admitted": False,
            "enabled_coding_features": ["shell_tool", "unified_exec"],
            "removed_enabled_exceptions": sorted(
                name
                for name, (stage, _, enabled) in _FEATURES.items()
                if stage == "removed" and enabled
            ),
            "disabled_system_skill_count": len(_SKILLS),
            "mcp_count": 0,
            "plugin_count": 0,
        }

    def _validate_config(self, read):
        _require(set(read) == {"config", "origins", "layers"})
        _require(_same(read["config"], self._expected_config))
        name = {"type": "user", "file": "/home/ralf/.codex/config.toml", "profile": None}
        metadata = {"name": name, "version": self._origin}
        _require(_same(read["origins"], {key: metadata for key in _leaf_keys(self._parsed)}))
        expected_layers = [
            {
                "name": {"type": "project", "dotCodexFolder": "/workspace/.codex"},
                "version": _EMPTY_ORIGIN,
                "config": {},
                "disabledReason": (
                    "To load project-local config, hooks, and exec policies, add /workspace "
                    "as a trusted project in /home/ralf/.codex/config.toml."
                ),
            },
            {**metadata, "config": self._parsed},
            {
                "name": {"type": "system", "file": "/etc/codex/config.toml"},
                "version": _EMPTY_ORIGIN,
                "config": {},
            },
        ]
        _require(_same(read["layers"], expected_layers))

    def _validate_features(self, result):
        _require(set(result) == {"data", "nextCursor"} and result["nextCursor"] is None)
        data = result["data"]
        _require(type(data) is list and len(data) == len(_FEATURES))
        seen = set()
        for feature in data:
            _require(type(feature) is dict)
            _require(
                set(feature)
                == {
                    "name",
                    "stage",
                    "enabled",
                    "defaultEnabled",
                    "displayName",
                    "description",
                    "announcement",
                }
            )
            name = feature["name"]
            _require(type(name) is str and name in _FEATURES and name not in seen)
            seen.add(name)
            stage, default, enabled = _FEATURES[name]
            _require(
                _same(
                    [feature["stage"], feature["defaultEnabled"], feature["enabled"]],
                    [stage, default, enabled],
                )
            )
            _require(
                all(
                    feature[k] is None or type(feature[k]) is str
                    for k in ("displayName", "description", "announcement")
                )
            )

    def _validate_profiles(self, result):
        _require(set(result) == {"data", "nextCursor"} and result["nextCursor"] is None)
        data = result["data"]
        _require(type(data) is list and len(data) == 4)
        profiles = [":read-only", ":workspace", ":danger-full-access", "ralf-coding-v1"]
        expected = [{"id": name, "description": None, "allowed": True} for name in profiles]
        _require(_same(data, expected))

    def _validate_skills(self, result):
        _require(
            set(result) == {"data"} and type(result["data"]) is list and len(result["data"]) == 1
        )
        entry = result["data"][0]
        _require(type(entry) is dict and set(entry) == {"cwd", "skills", "errors"})
        _require(entry["cwd"] == "/workspace" and _same(entry["errors"], []))
        skills = entry["skills"]
        _require(type(skills) is list and len(skills) == len(_SKILLS))
        seen = set()
        for skill in skills:
            _require(type(skill) is dict)
            required = {"name", "description", "path", "scope", "enabled"}
            _require(
                required
                <= set(skill)
                <= required | {"dependencies", "interface", "shortDescription"}
            )
            name = skill["name"]
            _require(type(name) is str and name in _SKILLS and name not in seen)
            seen.add(name)
            _require(
                skill["path"] == _skill_path(name)
                and skill["scope"] == "system"
                and skill["enabled"] is False
            )
            _require(type(skill["description"]) is str)
            _require(_same(skill.get("dependencies"), _SKILL_DEPENDENCIES[name]))
            _require(
                "shortDescription" not in skill
                or skill["shortDescription"] is None
                or type(skill["shortDescription"]) is str
            )
            if "interface" in skill and skill["interface"] is not None:
                interface = skill["interface"]
                _require(
                    type(interface) is dict
                    and set(interface)
                    <= {
                        "displayName",
                        "shortDescription",
                        "iconSmall",
                        "iconLarge",
                        "brandColor",
                        "defaultPrompt",
                    }
                )
                _require(all(v is None or type(v) is str for v in interface.values()))
