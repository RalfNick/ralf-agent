# 贡献指南

欢迎通过问题复现、文档、示例、测试和代码改进 Relf-Agent。项目当前为 Python 开发预览；应用接入从[首用教程](docs/getting-started.md)开始，查找专题从[文档目录](docs/README.md)开始。

## 报告问题与提出需求

提交前先搜索已有 [Issues](https://github.com/RalfNick/relf-agent/issues)，确认[实现清单](docs/implementation-status.md)中的支持范围。问题报告请包含：

- 包版本或 commit、OS、Python 版本及所选后端／可选依赖。
- 可独立运行的最小复现、操作步骤、预期与实际行为。
- 脱敏后的状态、事件和错误；涉及恢复时说明是否重启进程及使用原配置。

功能建议说明具体使用场景、当前障碍、现有替代方式和期望行为。漏洞通过[安全报告流程](SECURITY.md)提交，避免在公开 issue 中暴露利用细节或凭据。

## 准备开发环境

使用 Python 3.11+，在 Linux 或 macOS 的仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,pdf,tokenizer,skills,temporal]'
```

产品代码在 `src/relf_agent/`，回归测试在 `tests/`，源码示例在 `examples/`，功能文档在 `docs/`。涉及执行保证前，阅读[总体设计](architecture/design.md)、[Run 命令契约](architecture/specs/run-command-contract.md)、[Action 恢复契约](architecture/specs/action-recovery-contract.md)、[Runner 契约](architecture/specs/runner-capability-contract.md)与[当前支持状态](docs/implementation-status.md)。

## 修改与验证

先运行与改动相关的现有测试。新运行时行为应先有能复现问题或期望行为的失败回归，再修改实现。合并前按改动范围运行检查，代码改动的基础命令为：

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build
```

当前基础 CI 使用 Linux、Python 3.11／3.12／3.13，安装 `.[dev,pdf,tokenizer,skills,temporal]`，与上述开发环境一致。全量测试在收集时需要 Temporal SDK；安装 `temporal` extra 不会启动或连接 Temporal 服务，也不会改变 SDK 的基础依赖。其他安装、服务和契约检查见[CI 配置](.github/workflows/ci.yml)。外部服务测试可能因缺少配置而跳过，跳过不视为服务能力验收。打包与安装后验证见[发布指南](docs/releasing.md)。

只修改文字、导航或链接时，检查链接、锚点与 `git diff --check`；修改示例命令时实际运行对应的最小示例。分类、写法和参考项目见[文档维护指南](docs/documentation-guide.md)，无需为文字调整运行全量产品测试。

执行与恢复相关改动还需遵循以下约束：

- 保持唯一执行权威、稳定 Action 身份和明确的 `outcome_unknown` 处理；不静默增加 SDK／业务重试或批准变更后的操作。
- 恢复测试检查真实外部写入次数、持久身份和原回执，不能只断言最终回答。
- 使用临时 SQLite 和测试业务工具，不调用生产变更工具；fixture 子进程不继承凭据环境。
- 新后端／Runner 在声明支持前提供能力报告及适用契约测试；离线回归、真实模型质量与实际服务验收分别记录，见[M1 验收协议](docs/m1-acceptance.md)。

## 提交 Pull Request

使用聚焦的分支与 PR。说明具体触发条件、修改后行为、验证命令和已知限制；关联 issue，并同步更新受影响指南、示例索引及必要的支持状态。涉及行为变更时按项目版本记录方式更新 [CHANGELOG](CHANGELOG.md)。

不要提交 `.env`、凭据、运行数据库或生成的打包制品。保留已有验收证据，不把不同快照或未执行实验标记为本次通过。PR 模板见[提交模板](.github/PULL_REQUEST_TEMPLATE.md)。

## License

Relf-Agent 采用 [Apache License 2.0](LICENSE)。除非明确另行说明，主动提交用于纳入本项目的贡献按该许可证第 5 条提供。引入第三方材料时，保留适用的版权与归属声明，包括 [NOTICE](NOTICE)。
