# 标准 Skill 文档与可替换解析器

`FileSkillDocumentCatalog` 读取显式列出的 `SKILL.md`，提供现有
`SkillCatalogPort` 快照。默认 `YamlSkillDocumentParser` 按
[Agent Skills 文档格式](https://agentskills.io/specification)解析 YAML frontmatter 和 Markdown 正文。
它属于有界文档接入；目录加载和正文读取仍使用原 `SkillToolSource`、审批和执行恢复链路。

源码开发安装：`python -m pip install -e '.[dev,skills]'`；wheel／已发布包安装：
`python -m pip install 'ralf-agent[skills]'`。YAML 是可选依赖，核心导入和现有 JSON 文件目录不依赖它。
默认文件适配缺少 PyYAML 时会在打开目录前明确拒绝；不会降级成不完整解析。

## 最小文件目录

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from ralf_agent import FileSkillDocumentCatalog, Scope

with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "triage").mkdir()
    (root / "triage/SKILL.md").write_text(
        "---\nname: triage\ndescription: 工单排查\n"
        "metadata:\n  version: '1'\nallowed-tools: lookup_ticket\n"
        "---\n先查证据，再使用已获授权的工具。",
        encoding="utf-8",
    )
    catalog = FileSkillDocumentCatalog(root, version="app-1", paths=["triage/SKILL.md"])
    try:
        assert catalog.list(Scope())["skills"][0]["name"] == "triage"
        assert catalog.get(Scope(), "triage")["skill"]["version"] == "1"
    finally:
        catalog.close()
```

`paths` 默认为根下的 `SKILL.md`，此时 `name` 必须等于固定原根的目录名。
多文档目录列出每个相对路径；文件必须以 `SKILL.md` 结尾，名称与直接父目录匹配。
不递归发现目录、不读取关联脚本／资源。每份正文通过原生 `skill_get` 按需读取；
`list` 只暴露元数据。需要每 Agent 选择时使用既有 [Skills 绑定](skills-bindings.md)。

## 声明式默认组合

`RuntimeBuilder.abuild` 和 `TemporalRuntimeBuilder.abuild` 的 `tools` 组件支持：

```json
{"tools":{"adapter":"skills-markdown","config":{"root":"skills","version":"app-1","paths":["triage/SKILL.md"],"prefix":"guide_","requires_approval":true,"max_skills":100,"max_entries":100,"max_bytes":1048576,"cost":1}}}
```

`root/version` 必填；其余支持 `paths/scopes/max_skills/max_entries/max_bytes/prefix/requires_approval/cost`。
JSON／TOML 的相对根按配置宿主的 `base_dir` 解析。
可通过既有 `skills/registered-tools` 绑定选择 `guide_skill_list/guide_skill_get`；
Profile 固定原资源和策略，受管理读取是原 read-only Action，Local 或 Temporal History 各自推进执行。
配置中不接收可执行解析器；定制解析器使用 SDK，或注册应用自己的 tools 工厂。

## 替换解析器

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from ralf_agent import FileSkillDocumentCatalog, ParsedSkillDocument, Scope, SkillSpec


class AppParser:
    identity = {"kind": "app-skill-parser", "version": "1"}

    def parse(self, text, *, parent_name):
        return ParsedSkillDocument(SkillSpec(parent_name, "应用说明", text))


with TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "help").mkdir()
    (root / "help/SKILL.md").write_text("应用自己的格式", encoding="utf-8")
    catalog = FileSkillDocumentCatalog(
        root, version="app-1", paths=["help/SKILL.md"], parser=AppParser()
    )
    try:
        assert catalog.get(Scope(), "help")["skill"]["instructions"] == "应用自己的格式"
    finally:
        catalog.close()
```

纯同步 `SkillDocumentParser` 提供普通有限 JSON `identity` 和
`parse(text, *, parent_name) -> ParsedSkillDocument`；返回值包含精确的不可变 `SkillSpec`
及可选描述元数据。协程、generator、上下文管理器或其他惰性返回值不能作为已完成解析采纳。
解析器被借用，不由 Catalog 关闭；外部数据访问应先完成加载，或实现独立 CatalogPort。
实现指纹、解析器身份、原根与文件 revision 在创建完成及每次读取前后复核。
变更文件、替换同内容 inode 或改变解析策略都会拒绝旧快照；新内容须显式发布新资源版本。
已持久化的成功读 Action 按原执行协议恢复保存的结果。

## 默认格式与容量

必填 `name/description`，仅允许额外 `license/compatibility/metadata/allowed-tools`。
名称沿用 RALF 1–64 字符 ASCII slug；描述 1–1024 字符且至多4096 UTF-8 字节。
`metadata.version` 若提供须为非空字符串，最多256字节；否则为 `1`。
支持引号、YAML 块文本、Unicode 内容、UTF-8 BOM／CRLF，正文逐字保留。
重复或非字符串键、非安全 tag、多 YAML 文档、别名循环和无效类型拒绝。

默认最多100份／单文件1MiB，可设为最多1000份／16MiB；原文件总计64MiB，读取前检查剩余容量。
frontmatter 最多64KiB，容器深度16、别名32、解析事件4096；别名展开在复制前限制为4096个值／64KiB标量 UTF-8 内容。
`license/allowed-tools` 非空且至多4096字节，`compatibility` 最多500字符／2000字节。
`metadata` 最多64组普通字符串，键1–256字符／1024字节，值至多4096字节，完整描述元数据最多64KiB。
这是明确的 RALF 有界文档配置，不宣称接受标准生态中的所有扩展或 Unicode 名称。

`allowed-tools`、正文和兼容描述都不能授予实际工具、文件、网络或执行权限。
脚本资源、自动 Context 阶段、异步加载、递归发现、Sandbox／Coding Runner 和完整质量验收继续按能力清单推进。
