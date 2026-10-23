---
title: 集成与扩展
description: 连接模型、MCP、HTTP、CLI、Workspace 与 Skills，在既有执行协议内复用外部能力。
locale: zh
slug: integrations
sources: [docs/model-adapters.md, docs/managed-tools.md, docs/mcp-http.md, docs/http-tools.md, docs/cli-tools.md, docs/workspace.md, docs/workspace-writes.md, docs/skills.md, docs/sandbox.md, docs/extending.md]
---

## 先选择接入方式

| 已有能力 | 接入方式 | 应用需要明确什么 |
| --- | --- | --- |
| Python 业务函数 | `ToolRegistry.tool` / `register_function` | 参数 Schema、效果类别、版本、审批和核验 |
| MCP 工具服务 | `MCPToolSource` + stdio / HTTP Transport | 选中的工具、固定目标、凭据、策略与关闭 |
| 业务 HTTP JSON 接口 | `HTTPToolSource` | 固定 URL、POST、Schema、响应限制与效果语义 |
| 可信本地 CLI | `CLIToolSource` | 固定 argv、JSON 输入输出、环境与进程生命周期 |
| 文件资料 | Workspace 与受管理文件工具 | 固定根目录、相对路径、Scope 与读取额度 |
| 可复用操作说明 | Skill Catalog 与受管理加载 | 允许的技能、正文版本、来源与工具权限 |

所有工具仍通过注册表、授权、审批、Action 和回执协议执行。不要让模型直接选择任意 URL、可执行程序或宿主目录；这些目标由可信宿主配置。Python 函数的具体注册方式见[模型与工具](/zh/docs/models-tools/)。

## 模型按协议接入

| 协议系列 | 现有入口 | 选择提示 |
| --- | --- | --- |
| Chat Completions 兼容 | `OpenAIChatProvider` / `chat-completions` | 显式 model、base_url 与参数；兼容端点逐个验证 |
| OpenAI Responses | `openai-responses`；另有 reasoning 续接适配器 | 文本与客户端函数子集；推理状态需要专用适配和续接配置 |
| DeepSeek | `deepseek-chat` / `deepseek-thinking` | 非思考与思考续接显式选择，不自动切换 |
| Anthropic Messages | `anthropic-messages` | 文本与客户端工具；不推断 thinking 或多模态支持 |
| Gemini | `gemini-content` / `gemini-functions` | 前者为文本；函数调用使用专用适配器及续接配置 |

适配器声明其协议能力，具体账户、地区、型号、工具往返和流式取消仍需在你的环境验证。模型由应用明确选择，失败不会偷偷降级为离线结果或其他协议。密钥通过环境或可信凭据服务提供，Profile 保存凭据变量名。

SSE 文本片段可用于临时展示；完整响应通过校验并保存后，才形成可采纳的工具提案。流片段不是耐久 Run 事件，也没有逐 Token 断点恢复。详细范围见[模型适配指南](repo:docs/model-adapters.md)。

## 运行一个真实的离线 MCP 工具

MCP starter 启动本地子进程服务，并使用独立 SQLite 业务回执库；它不需要模型密钥。当前 stdio 路径需要支持 POSIX 进程管理的环境。

```bash
relf init my-mcp-agent --template mcp
cd my-mcp-agent
python -m agent_app --value 3 --command-id first-change
relf --db .ralf/runs.sqlite --factory agent_app.runtime:create_engine \
  --format text inspect RUN_ID
```

把 `RUN_ID` 换成提交返回值。检查工具、参数和摘要，执行 `inspect` 输出的批准命令，再恢复：

```bash
relf --db .ralf/runs.sqlite \
  --factory agent_app.runtime:create_engine resume RUN_ID
```

示例业务按框架注入的 `effect_key` 去重；相同提交命令找回原 Run。它验证本地服务接入、审批与回执，不代表所有 MCP 服务兼容或模型任务质量。

## 外部工具的策略由宿主决定

`register_tool_source` 只注册 `policies` 明确选择的工具。远端描述和 annotations 不能授予权限。`ToolPolicy` 默认采用保守的写入与审批策略；确认只读语义后才声明 `read_only`。

- **幂等写入：** 下游必须真正接受并按稳定效果键去重，不能只在框架中声明一个类别。
- **可查询写入：** 由 SDK 提供能查询原效果的 reconciler，核验不能隐式重做原操作。
- **HTTP：** 固定 JSON POST 入口；业务 URL、方法和请求头不由模型动态提供。它不是通用浏览器或任意 REST 代理。
- **CLI：** 固定程序与 argv、不隐式使用 shell。CLI 进程管理本身不是沙箱隔离。
- **MCP HTTP：** 使用已实现的 JSON／POST SSE 子集；OAuth、resources、prompts、tasks 等不能从“支持工具调用”推断获得。

超时或取消等待不证明远端业务已经停止。未知效果继续走[核验与恢复](/zh/docs/recovery/)，并等待实际调用和连接收尾。

## Workspace、Skills 与 Sandbox

**Workspace** 把文件访问限制在宿主选择的根目录及允许范围，提供受管理的读取能力；写入需选择对应能力并遵守版本与比较交换契约。`Scope.workspace` 是逻辑范围，不是文件系统目录或登录身份。

**Skills** 保存可复用的操作说明。目录元数据、正文和摘要固定版本，模型读取说明后仍只能使用已授权工具。加载一个 Skill 不等于执行其中的脚本，也不替代审批。

**Sandbox** 是单独选择的执行能力。已有 Docker 默认实现要求宿主准备 Linux Docker Engine 与本地不可变镜像；不会自动启动 Docker、拉镜像或注入凭据。其工具策略和资源限制按[Sandbox 指南](repo:docs/sandbox.md)配置。

这些组件在 Alpha 中按实验性范围显式启用；不存在“导入 SDK 就拥有所有系统权限”的默认路径。

## 只替换需要的一层

Provider、ToolSource、Context、记忆、检索器、Embedding 和执行器提供各自的扩展契约。结构端口通常不要求继承框架类；实现需提供稳定身份、正确的同步／异步方法、已完成返回值及资源关闭方式。

纯策略负责提出选择，不能执行网络、模型或存储调用。需要异步构造的组件使用 `abuild` 等已有入口；直接注入的资源按 owned／borrowed 规则关闭。详见[扩展契约](repo:docs/extending.md)及[运行与部署](/zh/docs/operations/)。
