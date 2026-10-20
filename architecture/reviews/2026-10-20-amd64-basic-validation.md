# AMD64 基础 SDK 模拟验证与镜像下载排障

日期：2026-10-20。基线 `2ade2b0`。用户授权排查 Docker Hub 超时，解决后继续原 AMD64 基础矩阵。原 a1 wheel／sdist、依赖版本、311／16／2 的验收范围和两处显式 Session 测试校正保持不变；函数指纹专项及 S2 继续后置。不推送、打公开 Tag 或发布。

## 下载故障与处理

原 Docker Hub 清单 HEAD 请求约 62.322 秒后超时，镜像未取得且未启动测试；原记录 `dist/amd64-validation-retry-20261020/` 保留。此前首轮镜像下载、Linux 原测试失败及校正后结果也不覆盖。

本轮宿主 IPv4／IPv6 连接 Docker Hub 均在 TLS 前超时。系统／路由器 DNS 与公开 HTTPS DNS 返回明显不同的地址；仅对诊断命令指定公开返回的地址、保留原域名及 TLS 验证后，连接仍被重置。Docker daemon 使用 Desktop 的内部 HTTP／HTTPS 代理 `http.docker.internal:3128`；宿主 shell 和系统网页代理未启用。证据将问题定位到当前 Docker Hub 的 DNS／HTTPS 访问路径，尚不能据此确定具体解析器、路由／网关策略或远端地址的最终责任，也没有证明 Docker Hub 本身已恢复。

[AWS 公共注册表](https://docs.aws.amazon.com/AmazonECR/latest/public/docker-pull-ecr-image.html)可正常建立 HTTPS 连接。使用空临时 Docker CLI 配置，匿名从其[Docker 官方 Python 仓库](https://gallery.ecr.aws/docker/library/python)串行取得原三个补丁版本的 AMD64 镜像；未更改系统／Docker DNS、代理、认证或安全组件，未关闭证书校验。三个多平台索引摘要均与原冻结镜像一致；按平台镜像 ID／manifest descriptor 单独登记，不将不同种类的摘要混为一谈。

| Python | 多平台索引摘要 | AMD64 镜像 ID／manifest descriptor |
| --- | --- | --- |
| 3.11.17 | `0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89` | `8a00ecb83ed9d0864dfd102a1bdb2067fda907ceb30bb86d09da9ee558b19590` |
| 3.12.15 | `34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258` | `2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d` |
| 3.13.16 | `a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641` | `f040863673aea2570c3ff6a5c3fb4c673a016cbc5375005ad145915922b6b78a` |

## 验证维护

包装器新增显式 `--platform linux/amd64`，默认 ARM64 不变。准备后的镜像引用固定至 manifest；按目标平台 inspect，实际镜像与报告架构均须匹配，继续绑定实际制品、工具／manifest／依赖锁和测试校正身份。即使多架构共用同一索引，也不能用默认缓存架构或另一架构报告代替。

新增的八个双架构矩阵场景先因不支持平台参数而失败，修复后整个维护模块 **80 passed**。覆盖同架构接纳、错误报告／镜像／制品拒绝，以及原资源、无网络、前一容器移除后再启动下一版本的顺序；不把单测当作真实平台通过。AMD64 wheelhouse 使用原哈希锁中的三个 `rpds-py` manylinux wheel，其他依赖版本不变。

## 实际结果

原 a1 安装包在以下三个模拟平台均通过，每版本 **311 项基础＋16 项恢复＋2 条 starter**，零失败／错误／实际跳过／OOM，starter 两例业务各只写一次。基础测试仍保留原显式 deselect 的一项 Temporal 检查，没有新增跳过。

| Linux AMD64／Debian12（Mac ARM64 模拟） | 门禁耗时（秒） | cgroup 内存峰值（MiB） |
| --- | --- | --- |
| Python 3.11.17 | 143.097 | 334.38 |
| Python 3.12.15 | 131.785 | 310.37 |
| Python 3.13.16 | 134.540 | 313.43 |

实际 Docker 配置与 cgroup 报告均核对 2 CPU、2 GiB、swap0、network=none。三轮真实启动／结束时间严格串行；三个容器均已停止并移除，另行只读 inspect 确认不存在。峰值包含安装和测试，不是进程 RSS；耗时不是 S2 或框架性能成绩。仍沿原维护门禁的超时，不执行 S2 或改变其原 360 秒门槛。

独立复核首次误要求 `container.Image == image_inspect.Id`，断言失败已单独保留。当前 Docker 的前者是多平台索引，后者与所选平台 manifest descriptor 相同；修正复核脚本后，分别核对固定 Config.Image／索引、inspect Descriptor／容器 ImageManifestDescriptor、AMD64 架构及安装报告，全部匹配。这是诊断脚本的身份类型假设错误，没有改 SDK、测试、原门禁结果或容器运行参数。

本轮仅形成 Mac ARM64 上 Linux AMD64 的所选基础 SDK **模拟矩阵**证据，原生 AMD64、远端 CI、其他服务／模型质量及完整阶段不由此验收。实际报告与汇总分别在 `dist/docker-hub-diagnosis-20261020/linux-amd64/`、`acceptance.json`；原制品、工具、manifest、锁和测试校正身份均记录并复核。

历史七组 **1,318** 份文件摘要已复核匹配，包含上一轮下载失败。产品／版本／运行依赖与原制品不变。本批原始网络探测、镜像身份、依赖准备、单测 RED／GREEN、矩阵来源和容器状态单独保存，不覆盖旧证据。本批按用户授权仅作本地提交，单次跳过钩子，不推送或公开发布；函数指纹专项和 S2 继续后置。
