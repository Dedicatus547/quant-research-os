# 后继基线与生成计数

2026-10-12，D07/N3。沿用[顺序生成交接](post-hm-next-sequential-generation.md)和[决策设计](post-hm-next-decision-design.md)，只实施及局部静态检查。

`generate_sequential_baseline(design, request, policy) -> tuple[str, ...]` 消费固定共同空间。模板按 return、rolling_mean、rolling_std、rank 轮转，各层保留旧空间顺序；第五项是 return 下一结构。随机固定 seed1729，无放回抽样，超空间拒绝。方法失败、中断与重复都占原槽，管理脚本按已保存 reservation 数跳过原槽，不排重补发。旧 `generate_baseline` 函数体不变，旧默认采样及 canonical output 路径不变；本次没有执行运行时回归证明。

## 独立静态入口

```shell
PYTHONPATH=src /home/zjw/quant-research-os/.venv/bin/python scripts/post_hm_discovery.py \
  --generation-root <持久顺序生成根> generation-analysis \
  --output-root <生成authority以外的持久输出根>
```

该命令读取冻结 `SequentialDiscoveryBatch`，通过 `GenerationStore.verify_frozen` 从原 reservation、response、producer、历史、source 和冻结 observations 重建核验，然后写小型 content-addressed `generation-analysis/sha256-<hash>/report.json` 与 `report.md`。未冻结或原件身份不足则失败。没有启动科学 service、研究模型或预测大文件解析；不收集冻结之后新出现的 completion，不回填 null。

报告保留三类分母：管理模型入口已确认/未知、候选机会授予/占用、科学不同候选与 attempt/resume。管理入口必须有冻结 launcher record 的实际 exit，或 exit 缺失但原 raw output 中存在可解析 CLI event；raw output 空文件的 hash 不证明启动，prelaunch 也不证明启动。来源指针由 source contract 的 manager/evidence/job 根绑定，原件 SHA256 被核验。这个入口数是管理侧外部进程观察，不是成功模型请求数；provider 内部调用未知。BASELINE 与明确 OFFLINE_IMPORT 无 source 时记零入口，缺失或 capture 拒绝仍 unknown。

每方法并列原授予机会分母上的静态准入率、方法内重复率、跨方法共享重复数、不同准入结构、原 subtask hashes、已观测 usage/费用/响应 wall 与管理入口 wall；部分观察保留 observed subtotal、覆盖项数和未知总值，不能填零。共享候选全局结构仅一次，各方法保存归属。静态准入包含重复，但不表示预测可分析，也不产生科学裁决。

## 报告集成 API

`generation_counts_from_verified_batch(wrapper) -> dict[str, object]` 的前置条件是同一管理 scope 已执行 `GenerationStore.verify_frozen(wrapper)`。函数再核读取其计数所用的小 launcher record 原件及必要的 raw events；不重复完整 generation provenance 核验，也不读取科学大数据。返回 `discovery-generation-counts/v2`，含 `management_model_entries`、`candidate_opportunities`、`scientific_execution`、`methods`、`rows`。没有科学证据时 `scientific_execution.status=NOT_OBSERVED`，不同候选执行数、attempt、resume 为 null。

`attach_verified_comparison_counts(counts, wrapper, report)` 仅消费同一 scope 已核验的旧比较 report，核对 inner batch 与完整唯一 task 集合，从 `costs.task_measurements.execution_attempt_count` 复用观察。共享 task 全局只计一次，额外 attempt 标为 resume 观察，不能解释为完整科学重跑；未知 task count 保留 null。比较报告摘要 SHA256 是来源绑定，不替代此前实际科学来源核验。缺少 task measurements 的后继 prediction report 直接使用静态计数，保持科学执行 NOT_OBSERVED。

顺序路径的既有 `run/resume/report` 明确输出 `discovery-comparison/v2`，增加 wrapper hash 与 generation counts；旧 v1 默认字段和 renderer 输出不变。没有新科学入口或权限。

## 实际检查及未观测项

[Ruff 0.16.5 与 strict Pyright 原始命令、退出和源码身份](../../artifacts/post-hm-next/counts/static-checks.json)持久保存于 counts 目录，检查仅涉及 D07 四个 application 文件及管理脚本。初次 lint/type 错误和 setup `python` 不存在退出127均保留；修改使用 `python3`。没有测试、新研究模型、科学执行、全库 CI、首轮重跑、依赖升级或 commit。

本任务没有新冻结生成原件，所以没有运行 `generation-analysis` 或声称其运行资格通过；实际新生成准入率、usage、wall 和科学执行次数仍未观测。D09 继续做跨接口集成，真实研究执行仍需明确授权、预算与来源条件。
