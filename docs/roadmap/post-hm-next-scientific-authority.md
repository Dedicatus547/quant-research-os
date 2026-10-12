# 冻结顺序提案的独立科学评价 authority

2026-10-12。用户明确要求继续科学阶段，新增范围是冻结第二轮提案的离线科学评价；不包含新 LLM 生成、测试或确认期访问。原生成阶段 A 的 design cap=1、wrapper、政策与所有原件只读不变。此页记录 authority 实施，实际科学执行由运行管理入口另行留证。

新增 `discovery-scientific-evaluation-declaration/v2`，严格绑定原 sequential wrapper、generation policy、内层 singleton batch/design、原 generation source commit/capsule、当前 science source capsule/实际 bindings、snapshot/view、用户科学授权及新 scheduling cutoff。只有明确新 schema 使用独立预算；旧 `DiscoveryEvaluationDeclaration/v1` 和其 `max_compute_units <= original_design.max_compute_units`、源码变更及科学 bindings 判据保持原义，未放宽或绕过。

科学声明的 `budget` 是独立 `ScientificEvaluationBudget`，分别绑定完整 cohort 的 shape 报价、本次真正新增执行的报价、不同结构数、新执行数、新总 cap 与全局最多一次失败任务恢复。单位沿用既有 deterministic accounting，不代表实测秒数。历史耗用、249 单位和旧360设计 cap 均不成为新余额。实际新增 cap 由报价、用户授权及真实容量/lease 准备结果冻结，本声明不自授容量。

`ScientificExecutionAuthorization` 保存实际用户指令和原 wrapper hash；`ScientificSchedulingCutoff` 绑定 wrapper/inner batch/design/authorization，并明确不允许旧 generation 调度、新生成或 sealed confirmation。不伪造旧 unpurged 作业、supervisor 退出或退款证据。

## 原件和入口

service 的 `evaluation_declaration` 接受旧 v1 与新 scientific v2 两个明确类型；管理 CLI 和 science runner 保留 `--evaluation-declaration` flag，通过 `parse_discovery_evaluation_declaration` 严格 schema 分派及 canonical bytes 核验，不回落解释未知版本。

在新独立 execution root 保留以下原件：

| 文件 | 绑定 |
|---|---|
| `scientific-authorization.json` | 声明的 `authorization_hash`，实际授权及原 wrapper |
| `scientific-scheduling-cutoff.json` | `scientific_scheduling_cutoff_hash`，只允许本科学范围 |
| `original-generation-source.json` | 原 A capsule 声明 hash、commit、原 lock |
| `evaluation-source.json` | 当前 science capsule 声明 hash、实际 commit/lock |
| `source-adoption.json` | 新独立科学 dependency adoption；原 source04 与当前 science 依赖 |
| `scientific-adoption-plan.json` | 全 cohort 的原 origin/新执行分区，声明 hash |
| `evaluation-declaration.json`、`evaluation-authority.json`、`scientific-budget.json` | 启动时保存本次 authority，不改生成 authority |
| `sequential-batch.json`、`batch.json` | 原冻结 wrapper 和内层 singleton 的只读采用副本 |

`post_hm_discovery.py workload-quote` 从已经核验的冻结提案生成 shape 报价，不读数据或建立科学任务。模块级 `quote_discovery_tasks(batch)` / `quote_discovery_workload(batch)` 返回分任务/完整参考单位，不能授予重跑旧科学的权限。实际 service `quote()` 返回采用计划中新增任务的单位。

## 保留科学来源，执行新增分区

科学模型、label horizon、交易日 purge、PIT、cost/backtest、Validation/P14c、snapshot/view 与 lock 等实际科学 tuple 继续冻结；v2 只允许明确 actual code/execution identity 改变，不能换科学输入。原件缺失和 PIT 问题继续硬拒绝；执行失败保持 FAILED/NOT_EVALUATED。

新 `ScientificSourceDependencyAdoption` 区分历史模型没有重训与新任务重新计算预测。v2 service 保留它为 `scientific_dependency_adoption`，并将旧 `source_adoption` 留空，新任务执行原 full-chain。旧 stage adoption 强制 `model_predictions_recomputed=True`，只能用于旧 v1 的实际适用情形，不用它冒充整个 cohort 预测重新执行或完整 native 复用。

主 agent 的 `verify_scientific_adoption_plan(service)` 核对来源 metadata、原 request/outcome/receipt、capsule、实际科学依赖、DSL 翻译及 alias 兼容；返回缓存的 `ScientificVerifiedAdoption`。service 的公开 `scientific_new_subtasks()` / `scientific_execution_subtask_hashes()` 供 runtime 挂载和调度使用，`scientific_verified_adoption()` 供来源 cohort 报告消费。quote、挂载与同一 instance 内的查询复用一次已核原件；实际 run 在执行 namespace 再核一次。

`_run` 的 compute reservation、任务循环、adapter 与新 MLflow runtime 仅覆盖新增分区。已采用旧 origin 不创建新 adapter、request/outcome 文件或 receipt；`task_request` 的全 cohort shape 映射继续可读，不能把它当执行证据。旧 origin 的 `inspect_completed_execution` 在新 service 返回 None，工程报告因此不会误评分旧 origin。最终科学结论由独立 origin-cohort 比较涵盖全部候选，每行区分 REUSED_OLD_ORIGIN/NEW_EXECUTION，沿既有预测 importer/verifier 复核数据/PIT/native；无效来源拒绝评分、缺分数不填零。

本轮管理计划拟保留八个 source04 原 origin（含原失败）并仅执行四个新任务；完整 shape 为213，新执行72，另保留全局一个失败任务恢复18，新 cap90。这些数字须以实际冻结 adoption plan/budget 原件为准；此实施文档不是作业已启动或已完成的证明。旧 signal source failure 不因新目录盲目重跑。

## 检查与交接范围

仅修改 `contracts/discovery_evaluation.py`、`application/discovery_execution.py` 和 `scripts/post_hm_discovery.py`，配合主 agent 的独立 scientific adoption 模块及管理代理的 science runner。授权范围内局部 Ruff0.16.5 和主仓库 `.venv` strict Pyright 的实际输出保存在 `artifacts/post-hm-next/science-02/authority/`，失败输出保留；最终检查状态见该目录交接记录。静态 AST 比对确认旧 v1 declaration 与旧 cap/source 判据未变；它不是运行时兼容测试。

没有运行测试、完整 CI、研究模型或科学 heavy job，没有升级依赖或 commit。后继科学调用已经由用户授权；执行管理仍要核对实际宿主卷全量增长、并发保留和既有 formal lease。完成后的科学结果、失败、恢复与实测成本另在独立输出根留存，不能用实现或静态检查替代。
