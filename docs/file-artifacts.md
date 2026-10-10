# 文件 Artifact 与卸载恢复

dev55 提供可替换 FileArtifactStore，复用已有 ArtifactStore、ArtifactReference 和受管理卸载链路。
无额外依赖，适用于支持 POSIX flock、原子 rename、fsync 和 SQLite WAL 的本地文件系统。
默认仍是 SQLiteArtifactStore；不把网络文件系统或跨主机共享盘的存在当成分布式一致性保证。

```python
from ralf_agent import FileArtifactStore, Scope

with FileArtifactStore(".ralf/artifacts", capacity=1024) as artifacts:
    reference = artifacts.put(Scope(), "results", {"evidence": "中文🙂"})
    assert artifacts.get(Scope(), reference) == {"evidence": "中文🙂"}
    assert artifacts.put(Scope(), "results", {"evidence": "中文🙂"}) == reference
```

正文为 canonical JSON，写入 `<artifact_id>.json`；`.index.sqlite` 保存原引用元数据，
`.artifact.lock` 串行化多个协作客户端的发布、读取、删除和 namespace 容量检查。
创建新目录时使用0700并同步父目录，正文与锁文件使用0600；已有目录权限由宿主管理。
根目录、实际持有的锁与目录描述符、文件 inode、根内索引入口及内部索引实例／连接／配置／方法固定；
索引或正文软链接、硬链接和配置漂移拒绝。关闭只释放原本拥有的描述符，不关闭替换的借用描述符。
这是逻辑 Scope 隔离与宿主可信文件访问，不是操作系统沙箱或企业认证。

## 配置与资源所有权

SDK 直接创建并注入 `ManagedDataContext(artifacts, ...)`，宿主负责在 Engine／Worker 停止后关闭。
由 RuntimeBuilder 的 JSON／TOML 工厂创建则归 Runtime 所有，sync/async 关闭均复用原资源账本。

```json
{
  "adapter": "managed-data",
  "config": {
    "artifacts": {
      "adapter": "file",
      "config": {"path": "payloads", "max_bytes": 1048576, "capacity": 1024}
    },
    "tool_result_chars": 1024,
    "preview_chars": 64,
    "counter": "utf8-bytes",
    "output_reserve": 256,
    "max_units": 8192
  }
}
```

上述为 Profile 的 `context_assembler` 声明；也可用于 managed-data-async。
path 相对 RuntimeBuilder 的 base_dir；缺省为 `<run-db-path>.artifacts` 目录。
backend_id 未声明时由固定绝对根路径生成；显式稳定 backend_id 不会迁移数据。
更换地址、max_bytes、capacity 或后端需新发布，恢复保留原声明与根目录。
FileArtifactStore 包含 JSON metadata 索引格式，不能直接打开旧 SQLiteArtifactStore 数据库代替迁移。

## 发布、删除与恢复

发布先核验 namespace 容量，再将有界正文写入随机临时文件，flush/fsync，原子 rename，
fsync 根目录，最后提交 SQLite 元数据并复核正文。只有两者可验证才返回引用。
未提交索引的正文不对 get 可见；进程中断后，同一内容和 Scope／namespace／TTL 重提
核验已有正文，重新 fsync 正文与根目录后补齐原引用，不重新使用不同内容。
这也覆盖 rename 成功但目录尚未同步的进程中断窗口。损坏／超限／别名拒绝，不覆盖损坏来伪装成功。
确实缺失正文时，有原始相同值的 put 可重建；get 不会把缺失当成空值。

delete 先删除元数据再移除正文并同步目录；重复删除返回 false。
不支持任意跨系统事务：元数据发布失败、删除中断或 rename 前进程死亡可能保留孤儿／临时文件。
namespace 容量统计保留的索引项，包括过期项；显式删除释放容量。
完整 orphan GC、保留依赖管理、全局磁盘配额和 S3 后端仍待验收，不手工删除仍被恢复依赖的文件。
进程 exit 测试证明提交窗口，不代替硬件掉电、NFS 或文件系统故障认证。

Local 原生及图／Team／动态 DAG／嵌套通过原 Engine 的 intent／receipt／verify 使用文件后端；
正文提交但 ACK 丢失时读回核验，不重复业务工具调用。
Temporal 使用自身 History 和受管理 Activity，Worker 必须部署相同发布及可验证的原资源。
状态机重开测试与实际 Worker／History 测试分别记录，不用接口存在替代真实服务证据。
自动卸载保留 Run 中原始工具结果，模型收到引用和有界样本；FileArtifactStore 不改变上下文计量或执行额度。

详见[上下文与产物协议](context-artifacts.md)、[自动上下文](managed-context-stages.md)
和[持续能力清单](remaining-work.md)。

实际 installed dev55 的文件6项及原SQLite6项 Temporal Worker/History 对照已通过，详见[验收](../architecture/reviews/2026-10-11-file-artifacts.md)。Worker 在同机原资源重开；跨主机要求真实共享原资源，不由路径相同或接口存在推导一致性。
