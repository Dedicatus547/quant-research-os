# 个人研究记忆与诊断

`PersonalMemoryService(product_root, repo_root)` 把有引用的派生JSON加入原
`history-catalog/v1`。原结果、失败、收据和Validation仍为权威；记忆不会授予执行权或科学资格。
文件位于产品根的 `history-derived/request-<draft-hash>.json`，索引可重建。

准备研究时先调用 `PersonalHistoryService.search(query, limit, tags=(), as_of=None)`，
再读取命中的 `record_id`。旧JSON记录继续按原身份读取；不支持给Markdown套用旧JSON reader。
对记忆调用 `diagnostic_report(record_id, as_of=None)`，会重新核对引用原件hash及JSON Pointer所指的值。
缺失指标保留null，失败不能变为零收益。自由文字解释明确列为 `MODEL_INTERPRETATION`，
代码经验列为 `ENGINEERING_EXPERIENCE`；事实只从已核对原件的确定性字段拷贝。

记录声明假设和预期、股票池/时期/数据及成本情景、来源、观察、支持与反例、解释、不确定性、
失效条件、未回答问题以及继续/停止理由。换手路径是描述性分类，不是因果识别。
S/T/B只在原假设给出定义时使用；原净收益、回撤、年度描述、暴露、费用、订单和限制可以并列阅读。

追加接口为 `append(MemoryDraft | dict)`。相同请求幂等返回；同一record_id不允许改写。
修订须用新record_id及原记录 `revises_hash`，原件不变。来源必须是仓库内显式相对路径，
绑定SHA256，拒绝sealed、越界、符号链接、超限和缺失字段。单源2MiB、总来源8MiB、
每条派生记录256KiB、最多16来源/64观察、共享历史索引最多100条。
任何事实或原件篡改均硬拒绝，不作为“检索不到”静默忽略。

系统首次持久化时记录 `recorded_at`，请求不能自报此字段回溯时间。
显式as_of须含时区，并同时满足记录与所有来源的可得时间；未知来源时间不进入该查询。
旧索引没有可信可得时间，因此只在无as_of的当前阅读中返回。
本次初始记录的来源时间采用实际核对时间，未声称2023年策略在当时能读到2026年的结果。

首批离线示例位于
`artifacts/personal-research-complete-20261104/engineering-01/w4/seed-results.json`，包括
沪深300原七组、confirm2和换手归因。核对范围是既有冻结JSON与外部保存hash，不是重跑PIT、
账户或正式科学验证。confirm2只能概括为“在该范围未获支持”，其STOP不授予后继搜索。
初次有字段缺失的seed失败保留为attempt-01；修正只跳过真实不存在的adoption字段，
新账户身份仍来自原结果，既已完成的七组记忆被幂等复用。

Python示例（使用实际绝对产品根和仓库根）：

```python
from pathlib import Path
from quantos.application.personal_memory import PersonalMemoryService

memory = PersonalMemoryService(product_root, Path("/home/zjw/quant-research-os"))
hits = memory.search("confirm2", tags=("counterevidence",))
record = memory.read("hs300-confirm2-not-supported-20261103")
report = memory.diagnostic_report("hs300-confirm2-not-supported-20261103")
```

MCP可继续让 `research_history` 和 `research_retained_read` 使用这些兼容方法，
并为检索暴露可选tags/as_of。追加和诊断工具应只接受有界 `MemoryDraft` 或逻辑record_id，
不接受任意服务器路径。公告仍走既有本地证据工具作为辅助材料；缺交易时间依据时不进入历史信号。
