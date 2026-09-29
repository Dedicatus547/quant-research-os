# 术语

| 术语 | 在本项目中的含义 |
|---|---|
| Snapshot | 不可变 raw/canonical Parquet 市场数据及采集、质量、时间证据 |
| Qlib view | 由 snapshot 和官方 converter/config 派生的缓存 |
| PIT | 按冻结 availability、lineage 与 schedule 阻止前视使用 |
| Vendor vintage | 供应商在历史时点提供的版本；当前来源无法保证 |
| Evidence Store | 公告等冻结来源字节、元数据与派生文本 |
| Proposal | Agent 的观察、假设、抽取或研究建议，不含验证权威 |
| Admission | 确定性或记录在案的人工检查后，允许 proposal 形成合格特征 |
| Safe DSL | 已 admission 的严格 AST，翻译为锁定 Qlib expression |
| SignalArtifact | Expression signal 的不可变产物，表含 score/score_valid/tradable 与显式时间 |
| EventSignalArtifact | P13 事件桥接的独立 signal manifest，使用相同 SignalRow/v2 表结构 |
| ResearchResult | Native Workflow prediction/label、IC/Rank IC 序列与 summary 的不可变导出 |
| BacktestArtifact | Qlib 结果、执行约束、provenance 与 reconciliation |
| ValidationReport | G0–G10、稳健性、复现和研究 verdict |
| RunStatus | 执行成功/失败，独立于研究 verdict |
| Engineering PASS | 执行和证据机制在资格范围内符合契约 |
| Data-qualified | 工程输入继承已核验的真实数据 lineage；不是研究 PASS |
| Registry | 实验与策略版本的不可变历史；索引可以重建 |
| Ledger | 来源、proposal、人工判断与确定性结果分层的研究事件历史 |
| ContextPack | 绑定 Ledger、检索、tokenizer/model 和 budget 的冻结 Agent 上下文 |
| ResearchFamily | trial 前冻结的有限候选家族 |
| Trial denominator | 预声明 family 的完整选择分母，失败/拒绝/重复不能隐藏 |
| CampaignSelectionReport | 消费完整 trials 的独立 campaign 选择证据 |
| Sealed confirmation | 对未来未暴露窗口的一次确认；当前没有执行资格 |
| Replay | Agent driver 重放已有 exchange；有效同身份 execution receipt 负责避免再次 Qlib 执行 |
| Runtime fingerprint | Python、OS/kernel、架构、libc、runtime/numeric packages 等的内容身份 |
| Principal evidence | 资格契约明确指定的主要权威对象与其内容域 |
| Raw file inventory | 实际文件的路径、size、SHA-256 清单 |
| Qualification hash | 报告的 canonical 内容 hash，排除自身 qualification_hash；区别于原始文件 SHA-256 |
| Projected inventory | 按批准字段规则投影后的比较域，不等于原始文件树 |
| Canonical run | 显式 hash、干净实现与完整冻结 provenance 的运行 |
| THIN_MAINTENANCE | FR-03 停止重复调试，只按已冻结触发条件重资格 |

状态组合和哈希规则见[Contracts](../architecture/contracts.md)；
完整资格边界见[当前状态](../status/README.md)。
