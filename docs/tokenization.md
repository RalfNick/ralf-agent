# 可替换 tokenizer、上下文预留与 token 分块

dev54 在现有 MessageCounter／Chunker 上增加纯文本 tokenizer 组合。
原字符计量／分块、UTF8TokenEstimator、默认 Profile 和旧摄取回执保持原行为。
本页完成 R14/R16 的计量与分块子集，不代表完整 H3 或模型费用控制。

## 无额外依赖的组合

```python
from ralf_agent import BudgetedContextAssembler, TokenChunker, TokenizerMessageCounter

counter = TokenizerMessageCounter(output_reserve=256)
context = BudgetedContextAssembler(counter=counter, max_units=8192)
chunker = TokenChunker(size=1000, overlap=100)
```

默认使用 UTF8ByteTokenizer，单位是 `utf8-bytes`，不是模型 token。
上下文计量是 canonical JSON 文本单位加 output_reserve，预留与输入使用同一单位。
完整工具组、原始任务及最终 Harness 请求继续受原有预算规则约束。
计量不包含 Provider 后加的 framing、工具 Schema、隐藏推理及实际服务端输出；
`estimated=True` 表示它不能作为供应商上下文窗口、usage 或账单的精确值。
预留不会设置 Provider 的 max_tokens，应用仍需配置生成上限及协议开销。

JSON/TOML 的 `budgeted` 和 `managed` context 工厂支持 `counter="utf8-bytes"`、
`output_reserve=256`、`max_units=8192`。其他旧 counter 不能指定 output_reserve；
缺省声明保持原身份。SDK 可传入合规 TextTokenizer，无需继承。

## 替换模型 tokenizer

| 端口 | 同步完成结果 | 契约 |
| --- | --- | --- |
| TextTokenizer.count(text) | 有界非负整数 | 无隐式 I/O；bool、惰性结果不合法 |
| prefix(text, limit) | 原文前缀字符串 | 有效 Unicode；重新计量不超过 limit |
| suffix(text, limit) | 原文后缀字符串 | 有效 Unicode；重新计量不超过 limit |
| identity / unit | 非空 JSON / 有界单位名 | 固定算法、词表、模型版本；不可运行中切换 |

```python
from ralf_agent import TextTokenizer, TokenizerMessageCounter, TokenChunker


def assemble_token_components(tokenizer: TextTokenizer):
    return (
        TokenizerMessageCounter(tokenizer, output_reserve=512),
        TokenChunker(tokenizer, size=800, overlap=80),
    )
```

组合固定 tokenizer 的 identity、单位和 count/prefix/suffix 实现，调用前后复核。
公开组合 identity 为独立副本。不同模型 tokenizer 由宿主在装配阶段显式准备，
纯计量不能下载词表、读库或调用模型。Python 适配器仍是可信宿主代码。

可选安装 `pip install 'relf-agent[tokenizer]'` 使用 TiktokenTokenizer：

```python
from ralf_agent import TiktokenTokenizer

# 离线示例只证明 BPE 接入，不对应线上模型。
ranks = {bytes([i]): i for i in range(256)}
ranks[b"ab"] = 256
tokenizer = TiktokenTokenizer(
    name="example-byte-bpe",
    pat_str=r"[\s\S]+",
    mergeable_ranks=ranks,
    special_tokens={"<|endoftext|>": 257},
)
assert tokenizer.count("ab中🙂") == 8
assert tokenizer.prefix("ab中🙂", 4) == "ab中"
assert tokenizer.count("<|endoftext|>") == 13
```

真实模型传入对应 Encoding 的 name/pat_str/mergeable_ranks/special_tokens；
应用显式加载、校验并保留来源和词表版本。构造复制词表，固定摘要及 tiktoken 版本。
核心 import 无需该依赖，缺失时构造给出 ValidationError。
不调用可能加载远程资产的 get_encoding。encode_ordinary 按普通字面文本处理特殊 token；
编码／解码必须覆盖全部源字节，不完整分词表达式不能遗漏中文。
切片不使用有损 Unicode replacement；BPE 截断后重新计量，最多回退64个 token，
不保证最大利用率，无法安全前进时拒绝。这些选择依据
[Encoding API](https://github.com/openai/tiktoken/blob/main/tiktoken/core.py)
和[词表加载实现](https://github.com/openai/tiktoken/blob/main/tiktoken/load.py)。

## 入库、来源和恢复

TokenChunker 输出原文字符偏移，复用 IngestionCoordinator 原子知识提交。
window_chars 默认8192、最多32768，限定每次 tokenizer 的工作窗口；
最多4096块，扩展总字符最多4MiB。size/overlap 使用 tokenizer 单位；
为保证前进，重叠不能包含整个上一块。当重叠占满预算而不能覆盖新字符时，
去掉此次重叠并重试新内容，原文仍完整覆盖。若单个 Unicode 字符无法装入预算，
失败且不消费知识版本，不插入替换字符。

相同请求重提先返回历史回执，即使新 parser/chunker 不同；回执保留首次 pipeline。
位置单位仍为 parsed_character。默认 ingest starter 不改分块策略，应用通过 SDK 替换。
模型词表、语义分块、索引就绪、质量和恢复依赖清理分别验收。
Local 审批重启及 Temporal 状态采纳测试覆盖同一预算组合；真实 Temporal Service 的
tokenizer 新组合尚未单独验收，不把状态机测试写成跨 Worker/History 故障证明。
