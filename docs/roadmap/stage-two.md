# 第二阶段：Evidence、Agent 与有界研究

目标是 Agent-assisted Research 和有限 deterministic campaign。
M0 为工程入口，Data-qualified 是独立资格轨道；
任何真实数据工程或研究声明都需继承相应输入资格。

## P8–P14 验收

| 阶段 | 交付与退出条件 | 资格限制 |
|---|---|---|
| P8 Boundary | bounded ingress、allowlist、hash-only authority、最小环境、不可变并发写 | enforcement primitives 不等于某个 runtime 已隔离 |
| P9 Semantic contracts | Evidence/proposal/admission、finite family/budget、campaign/OOS、DSL v2 | proposal 无 verdict；治理机制不授予 sealed 资格 |
| P10 Capability spike | 固定 runtime/model/config，9/9 权限、MCP、Skills、恢复、transcript/usage 证据 | 历史 CLI Go 不推广至当前 SDK |
| P11 Typed application | 三个 Skills、proposal ingress、既有 service mapping、有界队列、synthetic E2E | direct façade 证据不等于 transport/live 资格 |
| P12 Evidence acquisition | 网络 Collector 与离线 Publisher 隔离、完整性证据、双根发布 | permission/availability 决定 downstream admission |
| P13 Qualified event | 冻结 Store/benchmark、cited proposal、admission、PIT、event/native-Qlib bridge | 仅批准 benchmark；不证明通用抽取或盈利 |
| P14a | Ledger/index/ContextPack 冻结与核验 | 检索缓存不作为 authority |
| P14b | 有限候选枚举、canonical AST、重复与分母留证 | 不允许开放搜索或动态 family |
| P14c | 冻结选择方法、完整 trials、immutable report、双根核验 | 不由单实验 PASS 推导 selection |
| P14d-A / B | runtime-neutral 编排、预算、失败分类、production wiring、双根资格 | Scripted/Replay；bounded synthetic |
| P14-DQ | approved 数据/环境上的同一编排与完整核验 | 工程 PASS、自然研究无 selection |
| P14d-C | live Agent runtime 的独立资格 | 当前 `BLOCKED_UNIMPLEMENTED` |

## Factor research 入口门

| 工作 | 硬条件 |
|---|---|
| FR-01 | 已 admitted DSL/field 穿过 compiler、resolution、PIT、Signal、Validation |
| FR-02 | Qlib native IC/Rank IC 序列与摘要成为 immutable ResearchResult |
| FR-03 | 官方 Codex SDK/runtime 按冻结 P10 v3 rubric 通过 9/9，才进入 live P13 |

FR-01/FR-02 是 P14 入口，已完成；不新增公开 DSL 运算或统计语义。
FR-03 当前 `NO_GO / THIN_MAINTENANCE`。实现 adapter、shadow chain 或离线 Replay
不替代真实 runtime capability。下一候选的触发条件见[维护政策](../status/fr03.md)。

## P14 最终验收规则

- finite family、candidate manifest、inputs、periods、budget、selection policy 在 trial 前冻结。
- 所有失败、拒绝和重复进入完整 trial accounting。
- Principal、原始文件与批准投影分别绑定并核验。
- 冻结环境内复现，不声称任意 hash seed、runtime 或数据 revision 一致。
- Natural research、engineering qualification 和未 qualification 的能力分别报告。
- Failed/blocked、pre-amendment 与被替代的 accepted report 保持历史身份。

具体权威域由[冻结契约](../contracts/README.md)和当前报告规定。
阶段名称、接口或工程 PASS 都不增加 Live Agent、sealed、alpha、盈利、投资适用性、
vendor-vintage PIT 或 unrestricted autonomy 权威。

## 当前下一步

精确文档提交 `3a4a898` 已取得[独立 RC 复审 `APPROVE`](../reviews/p14-rc-3a4a898-independent-review.md)。
下一步按该结论记录 RC tag 或 release marker，并冻结 P14 主线，精确要求见[路线图](../../PLAN.md)。
本次文档优化不启动 FR-03 新试验或 P14d-C 实现。

- [P14 状态与限制](../status/p14.md)
- [当前 RC 修正记录](../releases/p14-rc-v1-equality-correction.md)
- [完整历史第二阶段计划](../history/2026-09-29/PLAN.md)
