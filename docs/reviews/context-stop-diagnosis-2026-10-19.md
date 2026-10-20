# 两次真实首次 STOP 的上下文诊断

2026-10-19。结论：两次均为正常、可接受的模型停止，不能解释为预算耗尽或全部结构失败。
发现后继输入遗漏父 selection 的原因码，已完成一个 recipe 字段的离线补差；没有修改运行时、
重跑终态任务或启动模型/科学实验。历史意见影响决策仍是未确认假设，本轮不推进 A/B 或长期分支搜索。

## 基线、范围和证据身份

审阅 HEAD：`09edac2070aff4eaa2e13d5b803aee0a8cd08e6a`，分支 `main`，与
[建议稿](../roadmap/quantos-context-search-implementation-2026-10-19-v1.md)一致。
开始时唯一工作区差异是该未跟踪建议稿，保留其原字节。本轮没有重新查询远端，不对远端即时状态作新断言。
已读当前 AGENTS.md、实施纪律、状态和相关 runtime/history/SDK/prepare/grammar/admission 源码。
`b0725b7` 到 HEAD 的 `src/scripts/tests/pyproject.toml/uv.lock` 无差异；旧证明按原身份采用。
源码确认 SDK adapter 每次建立临时配置目录和新进程组，host 调用 `thread_start(ephemeral=True)`
后将 `request.prompt` 交给 `thread.turn`；不需要另加会话 flush。已有 N1/N2 继续复用。

以下结论来自本地原件。先从 manifest/spec 定位 output_root，再由 `DECISION_RESERVED` 事件取得
request hash；没有猜测 SDK 路径，也没有把重建 prompt 当作历史发送记录。
两份完成库存的哈希分别为 `8b53c572850a99bba5cb16e2a8f07854026564a7ea7c333373795e8e56ac7d77`、
`e17073c6caba97ac0e23e971ae6308bc515215702962186e5c85f65776e99484`。
完整路径及原件 SHA256 见[本次核验](../../artifacts/context-stop-diagnosis-20261019/verification.json)。

| 身份 | 首包：bounded-adaptive | 后继包：adaptive-closure |
|---|---|---|
| 原运行源码 | `5235445296207d29ec9513905d938f2ccae652f0` | `b0725b7c88a3d255eda61d0010cf291fba6f330a` |
| task/spec hash | `ce713513681cf19edbc63c881375b3e8e9229e3f2f148faa608fe438b5708d7f` | `2b573b7595b83e03c152781a0453a2424d74235c903f637a61b2e8a813c5f950` |
| request hash | `9b8773efba95f220ea928e92d7871a5c3e553828b767e7d0a4ca51cd26a07bae` | `ce311f128c645336f5ec2a71004e2ba9adbc1370ad918ebe3ed3adbc6b61be7d` |
| 原件 | [spec][s1] · [request.prompt][q1] · [原始响应][a1] · [收尾][c1] | [spec][s2] · [request.prompt][q2] · [原始响应][a2] · [投影][p2] · [收尾][c2] |
| 问题 | 当前价格组合空间是否值得提出一个新假说 | 是否值得检查一个独立平滑收益结构；若检查，其原生 G5 换手率是否 ≤12 |
| 实际历史输入 | v1 自由摘要，1011 字符；5 个来源 hash | v2 精确投影，23 字段、6163 字符；9 个来源 hash |
| 实际结果 | `MODEL_STOP`；SDK 1/2、候选 0/2、科学 0/2、units 0/36 | 同左 |
| 实际 SDK 输入/输出 token | 16508 / 351 | 18476 / 566 |

两包都是 ordinal=1、`parent_proposal_hash=null`、`feedback=[]`；请求中余额均为 SDK 2、候选 2、
compute units 36。事件链都是 ACTIVATED → DECISION_RESERVED → DECISION_CAPTURED → STOPPED，
没有 `DUPLICATE_AST`、`STATIC_ADMISSION_REJECTED` 或 `PARENT_BUDGET_EXHAUSTED`。
独立 SDK 退出为 0；采用已核对库存中的 controller/operator/observer/guard 退出及 cleanup 证明，
协议正常结束。首包曾有只读审计脚本失败并保留后继成功审计，不是 SDK/科学执行失败。

## 停止理由及支持范围

**首包。** 原始理由包括 “Remaining budget and structural novelty alone do not justify another hypothesis.”，
并明确不声称所有允许假说失败。其依据是输入中的两份 Validation 科学 REJECT、B2 无观察到的正增量、
先前 Discovery 暂停意见，以及尚无本任务反馈。

- 两份 Validation 原件 `ffe9652f…`、`2804f31b…` 均为 `SUCCEEDED / REJECT`，G5 同时未满足 Sharpe
  和换手阈值。B2 原件 `bf465a37…` 为 9 个冻结 request 中 6 个可分析来源、720 个共同日，
  `llm_minus_best_baseline=-0.0008272191343387846`。这些是有限来源下的观测。
- “Earlier two Discovery rounds also support pausing…” 是首包自由摘要中的研究判断。该包引用的两份
  Discovery `frozen.json` 绑定生成批次，不能单独证明其最终科学结果或暂停结论。v1 的 pin 正确只证明
  来源身份，未逐字段核验这句摘要；本轮不把它升级为新增科学事实。
- 没有本任务反馈是真实的初始状态，并非继续探索必须满足而未满足的科学门。
  该 STOP 是资源配置判断，符合当时宽泛问题和停止权限；无法据此否定未试结构。

**后继包。** 原始响应以 “Retain the earlier STOP.” 开始，明确所问换手率仍未评估。
上一包的 `/rationale` 确实作为 `adaptive-decision/v1` 字段进入真实首轮 prompt，且被响应引用；
不是仅从白名单推测。其余依据包括历史换手率 58.40685726397001、59.86533808324048（阈值 12）、
B2 无正增量和缺失组成部分比较，以及没有本任务执行反馈。

- 两个 B2 null 与 `UNAVAILABLE_NO_EXTRA_EXECUTION_NO_ZERO_FILL` 均进入实际投影，响应也明确“unavailable…not zero”。
  没有发现 null 填零或把两份 REJECT 改成执行失败的问题。
- N0 的独立平滑收益假说、非退化限制、保持原门限和允许首次 STOP 都已进入输入；
  `task_framing_inference_not_evidence` 清楚标注其为推断。模型正确指出任务 framing 不是新的科学证据。
- 旧 rationale 的 schema 身份仍可辨认，prompt 明示模型输出是 proposal，响应也重申这点。
  观察到了旧意见被采用，但没有证明模型将其误当成科学证据；合理保守与历史意见影响均可解释当前选择。
  与首包相比，问题和事实内容同时改变，两次首轮结果不能组成单变量对照或反馈后的两步轨迹。
- 一处语义不足可复核：实际投影只有父 selection 的 `FAILED / NOT_EVALUATED`，遗漏同源
  `/reason_code=SOURCE_INCOMPLETE`。响应将该历史父结果称为 “an execution failure”。这可以描述父流程
  未完成，但不能作为科学进程崩溃的证据。原 N4 收尾已注明该边界；本轮补齐输入中的原因码，
  不把这一措辞认定为 STOP 的已证实成因。

## 可行动作与实际信息缺口

两份 prompt 都只有 22 个已见结构 hash，没有可读表达式或完整未试目录；不允许工具调用。
本轮复用 `structural_expression_hash`、共享 grammar、`capability_rejection` 和已有 Qlib 表达式翻译器，
生成[只读映射](../../artifacts/context-stop-diagnosis-20261019/historical-structure-mapping.json)，逐条绑定三批原件的 JSON pointer、准入状态与原因。

实际三个冻结批次共 39 条 mapping，完整 AST 去重为 22 个；其中 **11 个**属于当前 555 结构空间。
20 个 `Mean(Return(close,h),s)`、s>1 的独立完整结构均可静态准入，且与这些批次的完整 AST 交集为 0。
该统计只表示已核对批次中的出现范围，包括失败/拒绝 proposal，不等于全项目搜索历史、科学执行次数
或成功覆盖；不能简单说“555 中已试 22 个”。均值子树已在交互结构中暴露，独立输出未出现不代表未暴露数据。

当时仍有合法动作：runtime 自选一个上述结构并完成一次冻结阈值检查，能回答该结构的换手率处于阈值哪侧。
历史 delta 的 G7 top50 窗口 15/20/25 已得到约 33.73/29.24/26.35，不能重做来充当新问题，
也不是该平滑收益结构的匹配因果对照。一次新检查有信息价值的可能，但尚无原件证明其预期价值足以覆盖成本；
科学 REJECT 可能有信息价值，STOP 也仍可接受。映射供审阅使用，本轮没有向模型注入或选择候选。

## 最小离线补差及验证

新增[recipe 字段片段](context-stop-reason-field-2026-10-19.json)，四个键均沿用现有 `historical_facts`
格式。只从已经 pin 的同一 selection 原件增加 `/reason_code`，值为 `SOURCE_INCOMPLETE`。
未来合规的新 recipe 可附加此字段；它不是完整 recipe、spec、请求或运行授权，不能用于续跑旧包。
本轮在内存副本上应用并通过现有 `project_history` 生成
[修正投影](../../artifacts/context-stop-diagnosis-20261019/corrected-historical-projection.json)，保留旧投影原件。

| 检查 | 实际结果 |
|---|---|
| 真实输入/响应绑定 | 两包 `verify_capture`、provider 同 thread/turn user echo、事件链、spec/manifest/批准身份对应 |
| 历史库存 | 76 + 93 份小型原件哈希及字节数核对通过；复用其已完成退出/收尾证明 |
| 旧投影复核 | 从相关来源重建后与真实 context 相等；后继 proof 与原 historical-projection.json 相等 |
| 修正前后 | 23→24 字段，6163→6332 字符；原有字段值/类型/顺序、两个 null、REJECT/FAILED/NOT_EVALUATED、旧意见、framing 和来源集合不变 |
| 实际反例 | 将新增值伪造为 `EXECUTION_FAILED` 时，被原投影器以值不符拒绝 |
| 边界 | 不写旧 spec、request、events、response、receipt 或授权；未调用 runtime.run/launcher；预算、曝光和终态不变 |

核验脚本与实际退出分别见[verify.py](../../artifacts/context-stop-diagnosis-20261019/verify.py)和
[退出记录](../../artifacts/context-stop-diagnosis-20261019/verification-01-exit.json)：exit 0，约 8.52 秒。
只验证上下文依赖，剔除环境等无关 pin 后调用既有投影器；这不是修改冻结 verifier 的分母，
也不是新的完整包、环境或科学资格验证。未重读市场 Parquet/预测文件、重算科学或重新校验 294 MB SDK 二进制。
依赖导入产生现有可选模型缺包和 Gym 提示，留在原日志，不影响本次只读核验；未安装或升级依赖。
没有生产代码改动，不新增测试门或重跑全仓测试；原工程证明保持原 originating tuple。

## 后续决定与未解决事项

本轮结束于**最小离线输入补差完成**。没有运行时默认投影变更，没有已准备可运行的 A/B 包。

第 6 节条件中，“实际含旧意见”已满足；但目前只观察到合法 STOP，没有可据以裁定另一种
意见呈现会提高决策质量的任务标准。换手率是否达标是科学执行问题，不能靠更高 PROPOSE 比例回答。
原因码完整性已经可以确定性验证，不需要为它增加模型调用。因此本轮不为锚定假设准备付费对照，
不删除旧暂停依据，不反复改措辞抽样。将来若有明确的决策质量对照目标，可在同一固定状态预分 A/B
预算；若目标是反馈后决策，必须先有真实本任务反馈。旧两包均不能提供该反馈状态。

第 7 节要求的有价值多轮轨迹、可利用方向差异和每支足够反馈预算均未观察到，不开发长期分支调度。
当前没有开发停滞问题，也未采用第 8 节独立探索。

本会话授权覆盖上述本地审核、离线修复和定向验证。已存两次用户批准都精确绑定各自历史 manifest/proposal，
且包已终态、原期限已过；它们不覆盖新对照或新科学，剩余机会不转移。本轮没有新研究 SDK 调用、
科学执行、采集、部署、提交或推送；开发会话消耗与研究 SDK 次数分开。

仍未解决：所选新结构的换手率问题、真实新 AST→科学→本任务反馈→后继决策、历史意见的因果影响、
投影改动的模型效果。两包 `NOT_QUALIFIED`、P14d-C 和所有历史科学状态不变。
建议稿需要补充本次原件已可取得、旧 rationale 确已进入后继首轮、父原因码遗漏及 11/555 的限定覆盖；
无需增加 flush 或重做 N1/N2。论文实验证据未在本轮重新审计，本判断不依赖论文均值或跨任务效果迁移。

[s1]: ../../artifacts/bounded-adaptive-research-20261017/package-01/spec.json
[s2]: ../../artifacts/adaptive-closure-20261018/package-01/spec.json
[q1]: ../../artifacts/hosted-evidence/bounded-adaptive-20261017-01/task-01/sdk/9b8773efba95f220ea928e92d7871a5c3e553828b767e7d0a4ca51cd26a07bae/request.json
[q2]: ../../artifacts/hosted-evidence/adaptive-closure-20261018-01/task-01/sdk/ce311f128c645336f5ec2a71004e2ba9adbc1370ad918ebe3ed3adbc6b61be7d/request.json
[a1]: ../../artifacts/hosted-evidence/bounded-adaptive-20261017-01/task-01/sdk/9b8773efba95f220ea928e92d7871a5c3e553828b767e7d0a4ca51cd26a07bae/raw-response.txt
[a2]: ../../artifacts/hosted-evidence/adaptive-closure-20261018-01/task-01/sdk/ce311f128c645336f5ec2a71004e2ba9adbc1370ad918ebe3ed3adbc6b61be7d/raw-response.txt
[p2]: ../../artifacts/adaptive-closure-20261018/package-01/historical-projection.json
[c1]: ../../artifacts/bounded-adaptive-research-20261017/authorized-run-01/closeout.json
[c2]: ../../artifacts/adaptive-closure-20261018/authorized-run-01/closeout.json
