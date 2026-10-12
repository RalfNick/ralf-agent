# Skills：可替换目录和受管理加载

当前 dev78 提供同步 `SkillCatalogPort`、不可变 Memory／固定版本的 File 默认，
以及原工具层的 `skill_list`／`skill_get`。安装、独立审查修复及冻结验收通过，见[证据](../architecture/reviews/2026-10-12-skills-catalog.md)。
技能正文是参考数据；实际工具授权、审批和执行仍由原 Engine／History 管理。

## 最小内存目录

```python
from ralf_agent import InMemorySkillCatalog, Scope, SkillSpec

catalog = InMemorySkillCatalog(
    [SkillSpec("triage", "工单排查", "先查证据，再使用已经授权的工具。")], version="app-1"
)
try:
    page = catalog.list(Scope())
    assert page["skills"][0]["name"] == "triage"
    reference = catalog.get(Scope(), "triage")
    assert reference["skill"]["instructions"] == "先查证据，再使用已经授权的工具。"
finally:
    catalog.close()
```

目录身份固定元数据和正文摘要。原生 Source 的首个受管理调用按原 Scope 分页核验完整有界元数据及摘要，之后校验每页和正文的成员身份；自定义适配器必须遵守相同不可变目录。`list` 只提供元数据，支持 `offset/max_entries` 分页；
`get` 返回指定正文和 SHA256／字节数。修改返回值不会改变目录。
名称为1–64字符的小写 ASCII slug；描述最多4096字节，版本最多256字节。
目录默认100项／每项1MiB，总正文64MiB；可配置项数最多1000、单项最多16MiB。
显式 Scope 由宿主配置，字符串不构成企业身份认证。

## 文件默认

File 默认读取明确的 `skills.json` 元数据和 Markdown 文件，不递归执行脚本。
它保留原根、清单和正文文件版本；文件变化时拒绝继续使用该目录。
重新创建目录和发布新版本是显式更新，不能把新文件静默采纳到已接受的 Run。

```python
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from ralf_agent import FileSystemSkillCatalog, Scope

with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "triage").mkdir()
    (root / "triage/SKILL.md").write_text("先查证据，再使用已授权工具。", encoding="utf-8")
    (root / "skills.json").write_text(
        json.dumps(
            {
                "version": "1",
                "skills": [
                    {
                        "name": "triage",
                        "description": "工单排查",
                        "version": "1",
                        "path": "triage/SKILL.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = FileSystemSkillCatalog(root, version="app-1")
    try:
        assert (
            catalog.get(Scope(), "triage")["skill"]["instructions"]
            == "先查证据，再使用已授权工具。"
        )
    finally:
        catalog.close()
```

清单最多1MiB，正文遵循原 Workspace 的相对路径、禁止保护目录、nofollow 和单链接要求。
这份默认不解析完整 YAML frontmatter；接入标准 SKILL.md 加载器可先生成 `SkillSpec`，
再注入 Memory 目录，或实现自己的 CatalogPort。异步加载器有待单独定义契约。

## 注入原工具层

```python
import asyncio
from ralf_agent import (
    InMemorySkillCatalog,
    Scope,
    SkillSpec,
    SkillToolSource,
    ToolPolicy,
    ToolRegistry,
    register_tool_source,
)
from ralf_agent.types import InvocationContext


async def load_reference():
    catalog = InMemorySkillCatalog(
        [SkillSpec("triage", "排查", "先使用已授权的查询工具。")], version="1"
    )
    source = SkillToolSource(catalog, version="1")
    try:
        tools = ToolRegistry()
        await register_tool_source(
            tools,
            source,
            policies={
                "skill_get": ToolPolicy("1", effect="read_only", requires_approval=False),
            },
        )
        context = InvocationContext(Scope(), "run", "action", "attempt", "effect", "epoch")
        value = await tools.get("skill_get").handler({"name": "triage"}, context)
        assert value["skill"]["name"] == "triage"
        await source.aclose()
        assert catalog.get(Scope(), "triage")["skill"]["name"] == "triage"  # Source借用目录
    finally:
        await source.aclose()
        catalog.close()


asyncio.run(load_reference())
```

业务 Agent 在 `AgentSpec.tools` 选择已注册名称；不同成员可用既有 `tool_set` 绑定选择独立目录。
加载是原 read-only Action，工具结果、审批和恢复沿原协议持久化；不会隐藏在纯 Harness／Context。
技能文本提到的命令、网络、文件或其他工具仍需宿主分别授权。当前专用 `Agent.skills` 角色仍拒绝显式选择。

## 声明与替换

`RuntimeBuilder.abuild` 和 `TemporalRuntimeBuilder.abuild` 的 tools 组件可以声明：

```json
{"tools": {"adapter": "skills-file", "config": {"root": "skills", "version": "app-1", "max_skills": 100, "max_entries": 100, "max_bytes": 1048576}}}
```

完整 Profile 的 providers、Agent 和 Scope 使用原[异步装配](async-assembly.md)及[Temporal Profile](temporal-profiles.md)。
工厂预检普通参数，拥有一个 File 目录和 Source，先排空真实处理器再关闭目录。
自定义 CatalogPort 提供固定有限 JSON identity（含 catalog_digest）及同步 list/get/close；
使用相同快照协议，Scope／分页／正文摘要／字节数和返回类型会在公共采纳边界校验。
它可以包装自己的数据库、文件加载器或服务客户端，实际操作与关闭责任由适配器承担。

专用 skills 绑定／selector、自动索引上下文阶段、标准 frontmatter、远端／异步加载器、
插件安装和激活、Sandbox／Runner与真实任务质量仍待交付。
[本批验收](../architecture/reviews/2026-10-12-skills-catalog.md)区分运行实现和未完成门槛。
