# B0/B1：有界价格组合研究的离线准备

2026-10-12；实现已准备、未提交。本文是可审阅的研究设计草案，尚未成为绑定后继 commit 的正式运行设计；未调用模型、未运行科学批次、不改变资格。原始工作范围见[下一阶段计划](quantos-next-stage-strategy-and-implementation.md#3-b-线以现有字段开展真正不同的组合研究)。

研究问题：在同样的生成机会、可见信息、LGBModel、评价和验证政策下，短期价格收益与较长窗口收益波动／趋势的交互是否相对其组成项产生可观察的预测增量？不预期盈利或 Validation PASS。

新 profile 为 `bounded-price-composition/v1`，design schema 为 `discovery-design/v3`，grammar 为 `price-return-volatility-trend/v1`。只用 `adjusted_close`；已有 safe DAG 算子 field、return、rolling_mean、rolling_std、divide、multiply；声明窗口 `{1,5,10,20,60}`，节点上限8、深度4（field 深度1）。有限产生式为：

- `C = Return(adjusted_close,w)`；
- `N = Mean/Std(Return(adjusted_close,a),b)`；
- 输出 `C`、`N`、`C/N` 或 `C*N`，窗口均属于声明集合。

完整配置含555个结构，三个方法共用同一个 inventory 和静态 admission。节点可重命名，结构身份按现有结构 hash 核对；未被使用的节点及其他 nesting/二元规则不属于 grammar。它不是任意 Python 或通用搜索平台。

随机基线使用声明 seed1729，从结构去重后的完整 inventory 均匀无放回抽样。规则基线按交互／简单组成项／嵌套组成项 round-robin：短窗口优先5、10、20、1、60，内层窗口递增，外层优先20、60、10、5、1，std先于mean、divide先于multiply。这与随机分布不同，覆盖偏好明确记录。前三个规则机会恰是 `Return(close,5)/Std(Return(close,1),20)` 及其两个组成项；基线不退回旧30结构。LLM仅可见同方法静态生成历史，无本轮评价反馈；评价之前冻结全部响应和候选。

每个候选先按结构 hash 唯一映射到冻结 grammar 的规范 DAG，保留原 proposal bytes；窗口按规范 safe DAG 拓扑顺序映射为 `window_000`、`window_001`…，每槽只绑定该候选的实际单值，复用 family enumeration 与现有 Qlib 全链。Validation 原有 parameter-window/top-k 判据不改；后继 profile 明确采用 `first-window-node/v1`，参数变体只扰动第一个窗口节点，其余窗口固定。该敏感性检查不证明其他窗口的稳健性；singleton 报告不提供整个生成搜索的多重比较校正。PIT硬拒绝、非有限结果和失败语义继续遵守既有契约。

可复用输入身份来自保留的 regression／历史设计声明：snapshot `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`、view `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`、Ledger `2f6ad63d4f7bd9dada5911d8c1fc83c8ca08bcf768fb7bb51871784722560df9`。这些 hash 是待正式 prepare 再核对的输入引用，本次没有打开市场数据或重新验证 snapshot/view。fixture 的历史 code identity 不冒充当前未提交源码。2015–2019 train、2020–2022 validation、2023–2025 test 已暴露；第二轮报告结果也已在本会话可见。2026-01 sealed 声明保留，不访问。输入 lag、LGBModel、交易/成本/验证和数据来源政策复用明确身份，正式 prepare 将按后继 commit 冻结。

新的比较分母为每方法3个生成机会，共9个；失败、未知、parse/schema/PIT拒绝、重复和未完成机会均保留，不新增免费修复机会。先报告所有机会、不同结构和可评价产出率，再报告共同日 Rank IC 的有向值分布、有效共同日数、覆盖、缺源和 Validation 裁决。缺失值保持 unavailable。规则组成项对照和 interaction／nested／simple三类分布单独呈现；随机/LLM若未覆盖对应组成项就记缺源，不自动增补执行。相同 candidate 仅执行一次但保留各方法机会归属。预测方向为 maximize，不用绝对值择优。不同共同日集合不可直接比较；来源报告继续要求共同日政策。最佳值仅是分布的一项；不使用历史0.002门槛。小样本不做确认性显著性、不晋级Registry，不声称未暴露 OOS。

B2的草案停止规则是完成9个机会或耗尽已批准上限即停止；无共同日、无可评价候选或缺组成项时报告不可判断，不填零。相对组成项和两基线均无正向增量则停止扩大此题；即使有正增量也只形成后续独立研究建议，不自动扩大预算。

离线来源示例见[绑定记录](../../artifacts/next-stage-offline-20261012/b/example/source-binding.json)和[新 DAG](../../artifacts/next-stage-offline-20261012/b/example/example-expression.json)。示例的 LLM 名称是请求字段，producer 明确为 `OFFLINE_IMPORT`，实际模型调用数0；两基线是确定性 proposal。完整 reservation、response、static history、mapping和singleton保存在 example/generation，不产生科学结果。

离线示例可在新的持久目录运行：

```sh
.venv/bin/python scripts/prepare_discovery_composition_offline.py --output artifacts/my-composition-fixture
```

正式 prepare 的显式选项为 `scripts/prepare_post_hm_discovery.py --generation-policy composition-v3 --opportunities 3`，其他必需参数沿用其 `--help`；需要干净且已提交的 provenance。本次不尝试绕过该要求。prepare 后沿用 `post_hm_discovery.py` reserve/capture/freeze 与 `run_post_hm_generation.py` 的已有接口；新的 design/policy Reader 在 capture/load/report 边界分派后继版本。原 v1/v2 bytes 和 verifier解释保留，SDK顺序 capture 禁令仍有效。

B2最小运行请求尚未获授权：固定现有 Hosted handoff 入口及其既有 `gpt-6.1-sol / high` 配置（A1 的 medium SDK组合不是B2的来源资格），总计最多3次真实模型尝试（失败和未知均计入，不自动重发）；两基线各3个机会。旧服务已清理，因此这一入口需要单独批准新部署与资源，不能假定其在线。A0的SDK业务接入不赋予Discovery SDK资格，A2前不能切换。冻结后最多9个独特候选、全批最多1次明确失败恢复（最多10个科学尝试；未知状态不重发）；按完整555结构的既有工作量报价17–18单位／候选，本配置最坏新 compute cap 为180单位，历史余额转移为0。例子的107单位仅是其中去重候选形状报价，不是B2额度。正式 prepare 若改变科学政策须重新报价受影响形状。

实际 wall、CPU和宿主卷／VHD增量当前 unavailable，不能把180 policy units换算成秒或磁盘。拟申请的新硬上限为总 wall 4小时、总新增空间12GiB、模型单次900秒，沿用已有配置 transcript/output限制与宿主卷32GiB余量底线；共享只读snapshot/view、threads1、科学任务串行。这些是待批准上限而非已测量需求，超过立即停止，不自动扩容。运行前复用现有 StorageGuard／单租约 supervisor，核对真实宿主容量、输入及安装副本、完整候选中间输出、export/replay、失败恢复和留证空间；若不能核定这些界限，科学启动保持未授权。建议先在上述3次生成上限内完成冻结与只读报价，然后以实际独特候选清单和可核对历史stage成本收敛科学/空间/wall预算，未经该预算授权不执行。Hosted新部署、模型调用及科学预算分别审批；本次离线准备不包含这些副作用。
