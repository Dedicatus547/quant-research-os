# 决策记录

ADR 保留决策时的上下文、候选和限制；当前资格见[状态页](../status/README.md)。
实现决策本身不授予 runtime 或研究资格。

| 记录 | 内容 | 阅读边界 |
|---|---|---|
| [0001：GPT + Codex Harness](0001-gpt-codex-harness.md) | 冻结 CLI capability spike 与 provenance | 历史 CLI 9/9，不解除当前 SDK NO_GO |
| [0002：公告 acquisition](0002-exchange-evidence-acquisition.md) | Collector/Publisher、官方来源、许可与完整性 | 来源权限和 downstream admission 分开 |
| [0002：官方 Python SDK](0002-official-codex-python-sdk.md) | SDK runtime、Code Mode 和失败证据 | 离线实现不等于 live qualification |

两个 `0002` 是已有记录的编号，链接以完整文件名区分，保持原文件不重编号。
新 ADR 使用新的唯一编号，并记录 superseding 关系。

- [FR-03 当前维护政策](../status/fr03.md)
- [Evidence 采集操作](../guides/acquisition.md)
- [审查记录索引](../reviews/README.md)
