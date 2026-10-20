# Alpha 首版原生 AMD64／远端 CI 准备 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. User has already authorized implementation; no push, remote execution or publication.

**Goal:** 准备可审查的原生 AMD64 固定门禁与原 a1 制品交接预检，不扩大 SDK 或验收范围。

**Architecture:** 复用 release_gate.py 的原制品与输入校验，在现有 Linux 包装器加显式原生宿主要求。独立手动 Actions 工作流下载同仓库已暂存制品、预检、准备锁定镜像／依赖，再串行运行原门禁；输出只证明实际已执行步骤。

**Tech Stack:** Python 3.11+ 标准库、pytest、Docker、GitHub Actions。

**Spec:** docs/releases/0.1.0a1.md、docs/release-gate.md、用户本轮授权。

## Global Constraints

- 不改 src、运行依赖、版本和原 a1 wheel／sdist；不重建或覆盖原制品。
- Python 3.11–3.13 串行；2CPU／2GiB／swap0／network=none；原311／16／2及校正身份不变。
- 函数指纹专项、S2原失败与原门槛后置；不跑全量 CI。
- 本批不推送、上传原包、触发远端工作流或公开发布；配置不等于验收通过。

## Review Focus

- Mac模拟或另一架构daemon不能获得原生资格：宿主、daemon均须匹配。
- 错误／重建包、源码或许可证漂移不得形成可交接成功记录。
- 预检非零退出／失败报告不能放行；复制不完整不交出candidate目录，旧输出不得覆盖。
- CI不能取任意仓库包、把宽泛CI重建包当原包，或自动随push执行。
- 实际运行失败的证据仍上传；依赖准备及镜像拉取失败不得被忽略。

## Tasks

### 1. 原生要求与制品预检

Files: tools/run_release_gate_linux.py、tools/release_preflight.py、tests/test_release_gate.py、tests/test_release_preflight.py、MANIFEST.in。

- [x] 为原生宿主／daemon错误、合法与漂移制品、输出拒绝覆盖写失败测试并确认RED。
- [x] 实现`verify_native_host(target_platform)`及`--require-native`，在创建容器前失败并保存原因。
- [x] 实现离线预检：复用原SHA／产品／测试树校验，核对当前源码版本与产品字节、wheel／sdist许可证；成功后仅复制两份原包到新candidate目录，输出摘要及未验收边界。
- [x] 运行两个维护测试模块、Ruff、格式和空白检查，不运行后置专项。

### 2. 手动远端入口与核对文档

Files: .github/workflows/alpha1-release-gate.yml、docs/release-gate.md、docs/releasing.md、docs/implementation-status.md、architecture/reviews/2026-10-20-alpha1-native-ci-preparation.md。

- [x] 仅workflow_dispatch，固定同仓库artifact名与来源run ID、只读权限、原生AMD64检查、单job串行原门禁；不build／publish。
- [x] 检查YAML与脚本语法；本地原包真实执行离线预检，并在Mac上实际确认require-native拒绝且不创建容器。
- [x] 核对工作流可用输入／失败证据上传、文档链接和产品／原包不变；记录本地结果与远端未执行。
- [x] 形成交接目录及明确下一步：需授权推送、建立原包暂存run、触发CI时停止，不自行执行。

## 执行记录与裁决

- 本地95项维护检查、原a1预检、Mac原生拒绝、YAML/Bash语法已完成；实际原生／远端运行未执行。
- 独立复核1个P2：runner默认Docker缺少inspect平台参数；工作流固定官方Docker29.0.1及专用daemon，保留原平台检查并增加版本／能力检查。
- 两个能力拒绝探针均非零退出，本机真实Docker29.0.1能力检查通过；不代替远端安装或原生资格。
- Ruling: 报告落盘失败时的目录完成标记收紧属于非阻断建议，本批记后续；交接必须同时检查CLI、通过报告和SHA，不能只看目录。
- Ruling: 不自动本地提交或推送；本轮仅准备交接，原有CI仍保留。未来推送需明确隔离宽泛自动CI并获授权，使用skip指令不视作全量通过或合并许可。
- 后续用户已明确授权将本批工具、测试、CI与文档本地提交，单次跳过钩子；提交带`[skip ci]`交接标记，不修改持久钩子配置，不推送或公开发布，函数指纹和S2继续后置。此授权只改变本地提交安排，不恢复远端执行或后置专项。
