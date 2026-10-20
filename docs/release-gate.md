# 可复现的 Local SDK 发布门禁

本门禁是仓库维护工具，不增加SDK功能，也不执行上传、Tag、推送或公开发布。它复用[0.1.0a1冻结范围](releases/0.1.0a1.md)，验证显式指定的已安装制品；不自动运行全量测试。函数指纹专项、S2及原失败／门槛保持后置。

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
| 原生Linux AMD64 | 3.11、3.12、3.13 | 相同门禁与资源条件 | 尚未验收；模拟通过不代替原生宿主或远端CI |
| Windows、其他Python／平台 | 未选 | 门禁在安装前拒绝 | 未验收 |

manifest里的平台条目只声明允许执行，实际通过报告才形成该平台的有限证据。远端CI尚未执行；本机通过不等于GitHub Actions通过。现有`ci.yml`的广泛回归不是本门禁，当前任务不执行它。

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

此前 Docker 的 ARM64 导出／加载回环结果见收尾验收，不外推不同 Docker 存储格式或未测宿主。Docker Hub 连接超时和匿名 AMD64 镜像下载失败单独保留；后续使用同索引摘要的 AWS 官方公共镜像取得所选 AMD64 模拟通过证据，见[排障与复验](../architecture/reviews/2026-10-20-amd64-basic-validation.md)。未执行原生 AMD64 或远端 CI。

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

AMD64使用同一包装器并显式增加`--platform linux/amd64`；默认仍为`linux/arm64`。镜像准备与离线门禁分开：`linux_amd64_images`固定了[AWS公共注册表的Docker官方Python仓库](https://gallery.ecr.aws/docker/library/python)及原多平台索引摘要，先用`docker pull --platform linux/amd64`准备这些精确引用。包装器不会自行联网下载；按目标平台执行`docker image inspect --platform`，再核对实际镜像架构和容器报告，不能依赖本地缓存的默认架构。Docker需支持该按平台检查选项；本次使用Docker29.0.1。

在ARM64 Mac上运行`linux/amd64`属于模拟执行，报告中的宿主与容器架构分别保留；通过只形成所选基础SDK的模拟矩阵证据，不能替代原生AMD64、远端CI或S2验收。

输出目录必须不存在，已有成功或失败记录均不覆盖。矩阵脚本只挂载维护工具、制品、wheelhouse与输出，容器不联网、不挂载源码／Git／宿主凭据／Docker socket；先确认前一容器实际结束，再启动下一版本。创建前先保存唯一名称／归属标签，客户端超时也按名称核对，只控制归属匹配的容器。保存日志／退出状态后移除；创建结果、归属或停止状态无法确认时中止后续版本。超时后暂时查不到容器不等于创建已结束，须按保留名称再次核对。

## 放行与证据

门禁从固定sdist提取测试到临时目录，建立无system-site-packages的venv，只安装wheelhouse中的哈希锁定依赖和指定wheel。实际导入路径、版本、442产品文件及最小可选依赖状态都须匹配。

校正只在原sdist校验后应用，每段原文必须唯一且整个文件前后摘要匹配；不接受已漂移或重复应用的测试输入，不重建原a1包。采纳报告同时核对这份校正记录，不能把校正后的通过当作原测试输入通过。

收集阶段必须与311／16的**完整node身份**匹配，不能靠相同数量放行。执行阶段要求pytest返回0、JUnit存在且真实case数量匹配，失败／错误／skip均为0；不得只检查最终回答。starter另检查两例业务写入一次。Linux还须匹配资源上限并无OOM。

`report.json`默认失败，只有所有步骤通过才写`passed_selected_scope`并退出0。报告保存当前phase、输入／脚本／锁摘要、平台和结果；JUnit、原日志、依赖及pip安装来源另存。容器矩阵还在创建前保存`matrix-input.json`与包装器快照，记录四份工具摘要、实际制品摘要、宿主信息和资源声明；创建容器前先核对实际复制制品与manifest，错误时保存matrix-error.json且不创建容器；采纳报告再绑定这些实际摘要，并重新核对工具摘要、架构、测试校正、311／16／2结果及资源／OOM，不仅检查passed字符串。另存image、created／exited、网络与资源状态。临时venv会清理；报告及固定输入足以重建，不是执行恢复检查点。

失败后保留原输出，新尝试使用新目录。更新制品、测试集合或依赖须显式审查manifest／lock及新的实际证据，不能改摘要来隐藏失败。发布门禁通过只证明该制品在该平台的所选基础范围，不关闭S2、完整第三阶段、模型质量、其他服务或历史兼容资格。公开发行仍按[发布流程](releasing.md)另行授权。
