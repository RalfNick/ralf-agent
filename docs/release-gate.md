# 可复现的 Local SDK 发布门禁

**当前发行：`0.1.0a2`。** 默认`tools/release_gate_manifest.json`固定新候选，原a1 manifest逐字节保存在`tools/release_gate_manifest.alpha1.json`。原a1完整通过成绩仍只属于原包；原a1手动工作流固定checkout到`0b9b6c9`，不处理a2。本轮已按用户授权完成独立a2手动CI及GitHub预发行；见[公开交付](../architecture/reviews/2026-10-22-alpha2-public-release.md)。

**当前门禁修订：2。** 原a2 manifest保存在`tools/release_gate_manifest.alpha2-original.json`，原包和原交付目录不覆盖。首轮Linux3.13发现一个终态Run立即要求Session空闲的测试竞态；第2版只对原测试文件应用固定摘要及唯一文本替换，改为1秒有界观察Session空闲，不改SDK、node身份、业务断言或资源／期限。新报告须记录该校正，不称原测试未经校正通过；当前状态与原失败见[追加验证清单](alpha2-validation-status.md)。

## 当前a2门禁

复用原311基础、16恢复node身份、两条starter及17依赖锁；新sdist已包含原a1校正，第2版仅增加上段新发现的独立测试校正；资源与断网要求不变，不追加SDK能力。函数指纹与S2按各原候选的所选资格单独引用，已完成项不再笼统写成后置，也不进入本基础门禁。

| 平台 | 本候选状态 |
| --- | --- |
| macOS ARM64／Python3.12 | a2原第1版门禁311＋16及两starter通过；见原`delivery.json`，不套用旧a1成绩 |
| Linux ARM64／Python3.11–3.13 | a2第2版门禁三版本各311＋16及两starter通过，零失败／错误／跳过／OOM；2CPU／2GiB／swap0、串行断网，最高326.48MiB；见[本轮验收](../architecture/reviews/2026-10-22-alpha2-validation-audit.md) |
| 原生Linux AMD64／Python3.11–3.13 | a2三版本各311＋16及两starter通过，零失败／错误／跳过／OOM，最高288.33MiB；实际`--require-native`、2CPU／2GiB、串行断网；[run39715385289](https://github.com/RalfNick/relf-agent/actions/runs/39715385289) |
| Windows及其他平台／Python | 未验收 |

两包使用独立a2版本及精确SHA，manifest还记录产品树、测试输入树和构建工作区来源。sdist内的manifest是构建输入快照，最终放行使用交付目录`gate/`或最终维护checkout的外置manifest；这是避免sdist自身SHA循环，不是允许换包或降低校验。

本地执行使用原已锁定wheelhouse，不联网补依赖；输出目录必须不存在：

```bash
python3.12 tools/release_gate.py --plan
python3.12 tools/release_gate.py \
  --wheel /ABS/ralf_agent-0.1.0a2-py3-none-any.whl \
  --sdist /ABS/ralf_agent-0.1.0a2.tar.gz \
  --wheelhouse /ABS/locked-wheelhouse --output /ABS/new-a2-macos-evidence
```

后续经授权在本机Linux ARM64或原生AMD64使用原`run_release_gate_linux.py`，参数沿用下方原流程，仅替换a2两包与外置工具套件；不修改镜像digest、依赖锁、311／16身份或资源限制。原`alpha1-*`远端工作流仅服务历史a1，不可用于a2后冒称当前版本通过。独立[alpha2门禁](../.github/workflows/alpha2-release-gate.yml)与[暂存入口](../.github/workflows/alpha2-stage-candidate.yml)固定dfb066e，只手动执行；原a1入口保持历史身份。实际a2暂存run39715289979及原生run39715385289已完成，不以工作流存在代替通过。

公开GitHub安装已独立核验；独立采用、真实模型扩展质量和未选服务另行验收，见[当前Alpha范围](releases/0.1.0a2.md)。

## 历史a1流程与原制品记录

以下保留原a1及其后各候选的原始记录。它们不覆盖本页顶部的a2当前候选；历史“后置／待验／不推送”描述当时状态。原a1复验须使用固定维护提交`0b9b6c9682c40285d91994cd831aa93d7e814bf1`的源码与工具，不用当前a2 checkout冒充原输入。

**2026-10-20专项恢复：** 用户已恢复函数指纹与S2验证，见[恢复验证记录](../architecture/reviews/2026-10-20-s2-fingerprint-resume.md)。本文件固定的a1门禁与JSON历史deferred字段不追溯修改；新a2候选专项单独取证，不改原包、平台或放行标准。尚未公开发布。

本门禁是仓库维护工具，不增加SDK功能，也不执行上传、Tag、推送或公开发布。它复用[0.1.0a1冻结范围](releases/0.1.0a1.md)，验证显式指定的已安装制品；不自动运行全量测试。本固定a1门禁不包含函数指纹专项或S2，其恢复验证单独记录，所有原失败和门槛保留。

## 固定输入

- `tools/release_gate_manifest.json` 固定a1的wheel／sdist SHA、442个产品与939个测试／示例输入树摘要、311个基础及16个恢复node身份摘要，以及明确排除的一项Temporal测试。
- `tools/release_gate_requirements.lock` 固定17个第三方依赖的版本及官方PyPI wheel SHA256；二进制依赖按实际平台选择，禁止源码构建或联网补包。
- 原sdist先按原SHA和939文件原输入树验证。`test_corrections`仅对`test_agent_sessions.py`的两处等待加上有界Session空闲观察，固定替换前／后SHA并在报告披露；不改SDK、311／16的node身份、业务断言或S2期限。原测试3.12失败保留，校正后结果单独验收。
- 固定两条原starter检查：正常审批恢复、业务提交后进程死亡恢复；两例均须只写一次。基础／恢复pytest使用`-W error`，starter复用原子进程的默认warning行为，不扩称完整资源泄漏专项。
- 原a1制品仍来自`ba7bc46`，不重建、不覆盖。维护脚本使用当前仓库版本，报告分别记录脚本／manifest／锁文件摘要，不能把工具提交当作原包源码提交。

## 平台矩阵

| 目标 | Python | 资源／执行条件 | 资格 |
| --- | --- | --- | --- |
| Linux ARM64／Debian12缓存镜像 | 3.11、3.12、3.13 | cgroup v2、2CPU／2GiB、无额外swap、`network=none`；串行 | 本批三版本各311＋16及两条starter通过，零失败／错误／跳过／OOM；见[本批记录](../architecture/reviews/2026-10-19-release-gate.md) |
| macOS ARM64 | 3.12 | 本地隔离venv；不声称Linux容器的资源限制 | 本批311＋16及两条starter通过，独立记录 |
| Linux AMD64／Debian12（ARM64 Mac模拟） | 3.11、3.12、3.13 | 同一门禁、2CPU／2GiB、swap0、`network=none`；串行 | 三版本各311＋16＋2通过，零失败／错误／跳过／OOM；仅模拟矩阵，见[AMD64记录](../architecture/reviews/2026-10-20-amd64-basic-validation.md) |
| 原生Linux AMD64／Debian12（GitHub Ubuntu24.04 X64宿主） | 3.11、3.12、3.13 | 相同门禁，2CPU／2GiB、swap0、无网络；串行 | 各311＋16＋2通过，零失败／错误／跳过／OOM，最高286.81MiB；见[远端验收](../architecture/reviews/2026-10-20-alpha1-native-ci-validation.md) |
| Windows、其他Python／平台 | 未选 | 门禁在安装前拒绝 | 未验收 |

manifest里的平台条目只声明允许执行，实际通过报告才形成该平台的有限证据。[远端手动run 39362466673](https://github.com/RalfNick/ralf-agent/actions/runs/39362466673)已验证所选原生AMD64范围；本机报告与远端报告分别保存。现有`ci.yml`的广泛回归不是本门禁，本轮未执行它。

## 准备依赖wheelhouse

在有网络的准备阶段，使用受信任Python／pip下载锁定依赖。门禁自身只执行离线安装。以下路径均替换为自己的绝对路径：

```bash
python3.12 -m pip download --index-url https://pypi.org/simple \
  --only-binary=:all: --no-deps --require-hashes \
  -r tools/release_gate_requirements.lock -d /ABS/wheelhouse
```

Mac上准备Linux ARM64三版本时还需匹配原manylinux标签，避免漏掉二进制依赖：

```bash
for minor in 3.11 3.12 3.13; do
  python3.12 -m pip download --index-url https://pypi.org/simple \
    --only-binary=:all: --no-deps --require-hashes \
    --platform manylinux_2_17_aarch64 --python-version "$minor" \
    --implementation cp --abi "cp${minor/./}" \
    -r tools/release_gate_requirements.lock -d /ABS/wheelhouse
done
```

准备AMD64时使用同一依赖锁，将上面的`manylinux_2_17_aarch64`改为`manylinux_2_17_x86_64`。每版本的二进制wheel均须通过锁内SHA校验，不回退源码构建。

缺包、版本或哈希不符时门禁失败，不回退网络或不同版本。Linux镜像需事先按manifest里的精确digest准备；矩阵脚本使用`--pull=never`，不自动下载镜像。

## 离线准备与搬运镜像

manifest 中的 `linux_arm64_images` 是本次 Docker 存储里的固定镜像引用，不应把裸 `sha256:...` 当作可下载的仓库名称。其他机器可从已有验证环境导出三个镜像，携带归档及校验文件，再加载到目标 Docker。不要改成可移动的 `python:3.11` 等标签来绕过固定身份。

在已有三份缓存的机器上执行，先把 `/ABS` 换成自己的路径；已有归档不覆盖：

```bash
python3.12 - <<'PYEXPORT'
import hashlib
import json
from pathlib import Path
import subprocess

archive = Path("/ABS/linux-arm64-images.tar")
if archive.exists():
    raise FileExistsError(archive)
spec = json.loads(Path("tools/release_gate_manifest.json").read_text())
subprocess.run([
    "docker", "image", "save", "--platform", "linux/arm64",
    "--output", str(archive), *spec["linux_arm64_images"].values(),
], check=True)
with archive.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
archive.with_suffix(".tar.sha256").write_text(f"{digest}  {archive.name}\n")
PYEXPORT
```

将两份文件复制到目标机器同一目录，先核对 SHA，再加载。不同操作系统使用自己的 SHA256 校验工具；以下适用于本轮 Mac 环境：

```bash
cd /ABS
shasum -a256 -c linux-arm64-images.tar.sha256
docker image load --input linux-arm64-images.tar
```

随后仍须按原 manifest 验证镜像与平台；加载本身不算平台验收。Docker 的仓库／索引引用和按平台检查返回的配置 ID 可以不同，记录二者即可，不能把二者强行当成同一种摘要。目标 Docker 若无法解析原固定引用，应保留失败，不修改 manifest 来伪造同一资格。

离线复验还需要原 wheel、原 sdist、四份维护工具／输入文件及锁定 wheelhouse；不用携带整个历史 `dist/`。只复制 `release_gate.py` 不足以复验。镜像导出／加载是标准 Docker 操作，不接入 SDK、不获取模型凭据；真实门禁容器仍保持 `network=none`。

此前 Docker 的 ARM64 导出／加载回环结果见收尾验收，不外推不同 Docker 存储格式或未测宿主。Mac的Docker Hub连接超时和匿名AMD64镜像下载失败单独保留；使用同索引摘要的AWS公共镜像取得的所选AMD64模拟证据见[排障与复验](../architecture/reviews/2026-10-20-amd64-basic-validation.md)。本轮原生宿主使用Docker Hub同摘要镜像通过，不说明Mac的原网络故障已解决。

## 执行

只读查看固定范围，不运行测试或创建目录：

```bash
python3.12 tools/release_gate.py --plan
```

macOS ARM64／Python3.12直接执行单个平台：

```bash
python3.12 tools/release_gate.py \
  --wheel /ABS/ralf_agent-0.1.0a1-py3-none-any.whl \
  --sdist /ABS/ralf_agent-0.1.0a1.tar.gz \
  --wheelhouse /ABS/wheelhouse --output /ABS/new-macos-evidence
```

Linux ARM64三版本按manifest的缓存镜像严格串行运行：

```bash
python3.12 tools/run_release_gate_linux.py \
  --wheel /ABS/ralf_agent-0.1.0a1-py3-none-any.whl \
  --sdist /ABS/ralf_agent-0.1.0a1.tar.gz \
  --wheelhouse /ABS/wheelhouse --output /ABS/new-linux-matrix
```

AMD64使用同一包装器并显式增加`--platform linux/amd64`；默认仍为`linux/arm64`。镜像准备与离线门禁分开：`linux_amd64_images`固定了[Docker Hub官方Python仓库](https://hub.docker.com/_/python)及原多平台索引摘要。原生CI首次使用AWS公共镜像时被`Data limit exceeded`拒绝，因此仅切换官方仓库传输来源；原三个索引摘要不变，原AWS失败和此前Mac网络故障均保留，先用`docker pull --platform linux/amd64`准备这些精确引用。包装器不会自行联网下载；按目标平台执行`docker image inspect --platform`，再核对实际镜像架构和容器报告，不能依赖本地缓存的默认架构。Docker需支持该按平台检查选项；本次使用Docker29.0.1。

在ARM64 Mac上运行`linux/amd64`属于模拟执行，报告中的宿主与容器架构分别保留；通过只形成所选基础SDK的模拟矩阵证据，不能替代原生AMD64、远端CI或S2验收。

### 原生 AMD64 与远端手动 CI

原生验证在上述AMD64命令中增加`--require-native`。包装器在任何容器创建前核对宿主必须为Linux x86_64、Docker daemon也须为Linux AMD64；不匹配返回失败，保存`matrix-error.json`和空`matrix.json`。ARM64 Mac上的模拟运行不能通过此入口。默认不加该参数时仍允许原有明确标记的模拟验证。

远端入口为[alpha1-release-gate.yml](../.github/workflows/alpha1-release-gate.yml)，仅`workflow_dispatch`，不随push／PR运行，也不调用原宽泛`ci.yml`。单个`ubuntu-24.04` job内串行运行三Python容器；先下载、校验原包，再按原依赖锁和索引摘要准备网络输入，最后容器`network=none`执行原311／16／2。五个官方Actions引用固定到提交摘要，checkout不持久保存凭据；仓库权限仅contents／actions读取，没有发布步骤。失败时也保存已有证据；准备步骤失败不能当作门禁通过。

工作流通过[Docker官方setup action](https://github.com/docker/setup-docker-action/tree/v4)在临时runner准备Docker29.0.1及独立daemon，显式`set-host`固定连接，不依赖runner自带旧CLI。运行前保存client／server版本和`image inspect --help`的实际`--platform`能力检查；缺少能力时失败，不移除平台核验来适应旧版。匿名Docker配置不会改变已固定的daemon地址。本机不安装或替换Docker。

`DOCKER_CONFIG`在runner启动后的首个步骤通过`GITHUB_ENV`设置；job级`env`不能引用`runner.temp`。原定义被GitHub以422拒绝，尚未启动SDK测试；该拒绝与actionlint语义RED保留，修正不改变容器参数或固定输入。

手动输入`candidate_run_id`须是**本仓库**已授权暂存原包的Actions run，artifact名固定为`ralf-alpha1-original-candidate`。artifact根目录必须包含下面两份原文件，不能使用宽泛CI重新构建的包代替：

```text
ralf_agent-0.1.0a1-py3-none-any.whl
ralf_agent-0.1.0a1.tar.gz
```

工作流从指定run下载artifact的机制见[官方download-artifact说明](https://github.com/actions/download-artifact/tree/v4)。原包暂存是单独的外部交接：只上传经预检的两份原包，不上传整个`dist/`。本轮已授权[暂存run 39361602003](https://github.com/RalfNick/ralf-agent/actions/runs/39361602003)，其固定名artifact经服务端ZIP摘要及原包SHA复核后交给门禁。artifact保留14天；过期后需要重新授权暂存精确原包，不能继续使用失效ID或重新构建包代替。若使用自有原生Linux机器，可直接搬运原包／工具／锁定依赖并执行相同的`--require-native`命令。

2026-10-20用户进一步授权原包暂存及手动执行。新增[私有暂存工作流](../.github/workflows/alpha1-stage-candidate.yml)桥接本机原包到Actions artifact：仅接受`ralf-alpha1-private-stage-`前缀、`draft=true`、未发布的本仓库草稿；资产名称、数量、大小和两份原SHA均须匹配，重定向必须HTTPS且移除Authorization，失败只保留proof，不交出部分candidate。暂存任务为读取草稿可见性使用`contents: write`权限，但下载脚本只发GET，不包含发布或源码写入操作；原固定门禁仍只有只读权限。验证证据取回后删除本次草稿，保留原包、暂存proof及失败记录，不将草稿转为公开Release，也不创建正式版本Tag。实际run及通过结果另行取证，工作流存在不等于通过。

GitHub的手动触发要求该工作流先在默认分支可用，见[官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)。本轮核对默认分支为`feat/m1-local-runtime`，使用已核验的RalfNick账号推送必要CI维护提交，并经用户授权手动暂存及执行；最终通过run的checkout为`0b9b6c9`，原制品源码仍为`ba7bc46`。手动触发CI不代表允许公开发布。本次临时草稿已删除，确认未发布且没有生成对应Tag；Actions证据及原失败保留。

现有`ci.yml`仍会随push／PR执行全量检查，本批没有关闭或修改它。本轮三个CI维护提交均保留GitHub支持的`[skip ci]`，只单独手动执行这里的暂存和冻结门禁，避免恢复函数指纹／S2后置范围；已核对相应提交只有三个手动run，宽泛CI未启动。见[官方跳过说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)。这不算全量CI通过，也不绕过受保护分支的必需检查；若必需检查因此pending，应停下由维护者决定交接方式，不自动合并或修改保护规则。标记不影响今后经授权的手动触发。

远端验收必须保留Actions run／attempt／checkout SHA及输入run ID、四份工具摘要、`native-host.json`、三份实际`report.json`、JUnit、容器退出／资源／清理结果，并核对原a1制品与测试校正身份。配置、YAML语法检查和Mac拒绝测试均不能替代原生通过回执。60分钟job看门狗只约束维护任务，不改变原各阶段超时或S2的360秒门槛。

输出目录必须不存在，已有成功或失败记录均不覆盖。矩阵脚本只挂载维护工具、制品、wheelhouse与输出，容器不联网、不挂载源码／Git／宿主凭据／Docker socket；先确认前一容器实际结束，再启动下一版本。创建前先保存唯一名称／归属标签，客户端超时也按名称核对，只控制归属匹配的容器。保存日志／退出状态后移除；创建结果、归属或停止状态无法确认时中止后续版本。超时后暂时查不到容器不等于创建已结束，须按保留名称再次核对。

## 放行与证据

门禁从固定sdist提取测试到临时目录，建立无system-site-packages的venv，只安装wheelhouse中的哈希锁定依赖和指定wheel。实际导入路径、版本、442产品文件及最小可选依赖状态都须匹配。

校正只在原sdist校验后应用，每段原文必须唯一且整个文件前后摘要匹配；不接受已漂移或重复应用的测试输入，不重建原a1包。采纳报告同时核对这份校正记录，不能把校正后的通过当作原测试输入通过。

收集阶段必须与311／16的**完整node身份**匹配，不能靠相同数量放行。执行阶段要求pytest返回0、JUnit存在且真实case数量匹配，失败／错误／skip均为0；不得只检查最终回答。starter另检查两例业务写入一次。Linux还须匹配资源上限并无OOM。

`report.json`默认失败，只有所有步骤通过才写`passed_selected_scope`并退出0。报告保存当前phase、输入／脚本／锁摘要、平台和结果；JUnit、原日志、依赖及pip安装来源另存。容器矩阵还在创建前保存`matrix-input.json`与包装器快照，记录四份工具摘要、实际制品摘要、宿主信息和资源声明；创建容器前先核对实际复制制品与manifest，错误时保存matrix-error.json且不创建容器；采纳报告再绑定这些实际摘要，并重新核对工具摘要、架构、测试校正、311／16／2结果及资源／OOM，不仅检查passed字符串。另存image、created／exited、网络与资源状态。临时venv会清理；报告及固定输入足以重建，不是执行恢复检查点。

失败后保留原输出，新尝试使用新目录。更新制品、测试集合或依赖须显式审查manifest／lock及新的实际证据，不能改摘要来隐藏失败。发布门禁通过只证明该制品在该平台的所选基础范围，不关闭S2、完整第三阶段、模型质量、其他服务或历史兼容资格。公开发行仍按[发布流程](releasing.md)另行授权。
