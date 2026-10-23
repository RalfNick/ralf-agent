# 每 Agent Skills：选择固定目录与收紧权限

当前 dev79 提供 `SkillBindingResource` 和 `AgentBindingDescriptor.skills`，
在 Local／Temporal 的原工具和绑定协议中选择已注册目录。安装、独立审查修复和冻结验收通过，完整能力目标仍开放。
它借用原 `ToolRegistry`，不执行技能正文、不追加业务权限、不拥有或关闭 Source／Catalog。

`inherit` 保持原工具列表；`ref` 保留 Agent 和 ToolSet 已授予的所选目录工具，移除其他 Skills 工具；
`disabled` 只移除原生 Skills 工具，保留原业务与 Workspace 工具。
Resource 可包含同一 `SkillToolSource` 的 `skill_list`／`skill_get` 注册，最多256个明确名称；
不同目录、版本、额度或非原生／写工具不能混成同一 Resource。
原生成员须保留原 `register_tool_source` 的真实 handler，且没有 reconciler；
保留该 handler 的重命名别名可用。仅复制配置标签、替换 handler 或增加包装层不能伪装为原生 Skills。
业务工具仍使用既有 canonical JSON 配置契约，不因选择 Skills 而新增普通类型限制。
Agent 声明仍是上界，所选目录没有已授予的匹配工具时接受前拒绝。

## 最小 SDK 组合

```python
import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path

from relf_agent import (
    AgentBindingDescriptor,
    AgentDefinition,
    AgentSpec,
    BindingCatalog,
    BindingSelection,
    InMemorySkillCatalog,
    LocalEngine,
    ModelResponse,
    Scope,
    SkillBindingResource,
    SkillSpec,
    SkillToolSource,
    SQLiteStore,
    ToolCall,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)


class Reader:
    identity = {"kind": "skills-guide-reader", "version": "1"}

    async def complete(self, messages, tools):
        if any(message["role"] == "tool" for message in messages):
            return ModelResponse(output="已读取获准目录")
        return ModelResponse(tool_calls=[ToolCall("help_skill_get", {"name": "help"}, "read")])


async def example():
    catalog = InMemorySkillCatalog(
        [SkillSpec("help", "业务说明", "先查证据，再使用已授权的工具。")], version="app-1"
    )
    source = SkillToolSource(catalog, version="app-1")
    try:
        registry = ToolRegistry()
        await register_tool_source(
            registry,
            source,
            prefix="help_",
            policies={
                "skill_get": ToolPolicy("app-1", effect="read_only", requires_approval=False),
            },
        )
        bindings = BindingCatalog(scope=Scope())
        bindings.register(
            "skills", "help", "app-1", SkillBindingResource(registry, names=["help_skill_get"])
        )
        definition = AgentDefinition(
            AgentSpec("reader", "使用获准参考", tools=("help_skill_get",)),
            AgentBindingDescriptor(skills=BindingSelection.ref("help", "app-1")),
        )
        with TemporaryDirectory() as directory:
            with LocalEngine(
                SQLiteStore(Path(directory) / "runs.sqlite"),
                providers={"default": Reader()},
                tools=registry,
                binding_catalog=bindings,
            ) as engine:
                handle = engine.submit(definition, "读取说明", command_id="request-1")
                result = await engine.drive(handle.run_id)
                assert result.state == "succeeded"
                assert result.result == "已读取获准目录"
    finally:
        await source.aclose()
        catalog.close()


asyncio.run(example())
```

示例模型是确定性协议演示，不是任务质量评测。实际模型可替换 Provider；工具审批仍由宿主政策配置。
关闭 Resource 不需要也不存在 close；目录和 Source 的所有者分别关闭，Source 必须先排空真实调用。

## 声明配置

先通过 `tools/skills-file` 或自定义工具工厂创建目录注册，绑定工厂只借用它们。
下面为 Profile 的片段，不是包含 Providers 的完整配置：

```json
{
  "components": {
    "tools": {
      "adapter": "skills-file",
      "config": {"root": "skills", "version": "app-1", "prefix": "help_"}
    }
  },
  "binding_components": [{
    "role": "skills", "component_id": "help", "version": "app-1",
    "component": {"adapter": "registered-tools", "config": {"names": ["help_skill_get"]}}
  }]
}
```

JSON／TOML 和同步／异步 Local 装配保持既有方式；File 目录默认使用[显式 JSON／Markdown 清单](skills.md)。
Temporal Profile 使用同一声明；宿主必须发布 Skills 目录角色，显式选择／禁用需要其协议准入。
Root 和每个成员都用原固定绑定路径，图、Team、动态 DAG 和嵌套成员可以选择不同目录。
等待审批／重启后仍使用原发布，不会重新从当前别名选目录；已保存的读结果沿原 Action／History 恢复。

## 兼容与边界

显式 Local 角色使用 `local-bindings-13`，Temporal 发布使用 `skills_binding_protocol=1`。
旧 dev78 Worker 接受新显式角色前明确拒绝，不静默忽略；默认未选择该角色的历史发布保持原身份。
普通目录文本及内容摘要不构成授权。`Skills` selector、自动目录 Context 阶段、关联资源视图、
标准 YAML／异步加载器、插件安装和 Sandbox／Runner 仍需各自实现与验收。

[本批证据](../architecture/reviews/2026-10-12-skills-bindings.md)区分源码／真实服务／安装验收；完整 R01–R26 保持开放。
