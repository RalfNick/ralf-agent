# 安全报告与支持范围

Ralf-Agent 当前为开发预览，API 和运维能力仍在演进。当前版本见 [pyproject.toml](pyproject.toml)，支持范围见[实现清单](docs/implementation-status.md)。维护者优先修复当前开发版本；尚未承诺旧预览版的补丁周期或安全响应 SLA。

## 报告漏洞

如仓库提供 GitHub 私有漏洞报告入口，请通过该入口向维护者报告。入口未提供时，可先创建不含漏洞细节的 issue 请求私密沟通方式；取得维护者回复后再提交复现。不要把可利用路径、凭据、生产数据库或用户信息直接发在公开 issue／PR。

报告包含：受影响版本或 commit、OS／Python、最小离线复现、预期与实际行为、涉及的执行／授权／数据边界。优先使用临时数据库和测试工具；敏感值应移除或替换。不要为了验证问题运行生产变更工具或真实收费模型。

## 当前信任与部署边界

- Python 工具、配置工厂、policy、Harness 和执行器等适配器属于可信宿主代码，可以访问进程资源。默认 Python 执行器不隔离宿主代码；[Docker Sandbox](docs/sandbox.md)需要显式配置，不自动约束所有工具或工厂。
- Scope 由可信宿主提供；本地 Coordinator 与执行日志不单独提供多租户隔离。服务可通过宿主 `authenticate(headers) -> Scope` 接入身份，并按原任务与资源权限校验，见[服务身份与脱敏审计](docs/service-audit.md)。这不表示内置了完整企业 OIDC、凭据代理或治理体系。
- Provider identity、backend_id、ToolSpec.config 和日志可以持久化；不得写入密钥／连接凭据。注入凭据由运行方管理。
- 框架追踪自身管理的同步调用。使用者自行创建后台工作时，负责取消、真实完成、幂等与资源生命周期。
- 未知效果和整数 credits 预算不会证明外部 exactly-once、供应商硬限额或业务效果已撤销。
- 审计默认关闭；可选内存审计和显式保留策略不等于强制耐久审计。保留或清理数据前按[备份与恢复指南](docs/framework-backup-restore.md)核对原执行、效果和授权证据。

公开支持能力见 [实现清单](docs/implementation-status.md)。审核与恢复步骤见 [恢复指南](docs/recovery-guide.md)；任何安全修复都应保留真实效果证据和执行日志。
