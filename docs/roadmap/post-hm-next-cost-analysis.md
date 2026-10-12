# D03 / N4a 成本分析

状态：完成只读阶段记录与调用关系整理。机器可读的小记录见 [d03-cost-analysis.json](../../artifacts/post-hm-next/cost/d03-cost-analysis.json)。本分析未读取大型 prediction/label 文件，没有模型调用、科学重跑或测试。

原件范围是主仓库 `artifacts/hosted-evidence/post-hm-discovery-01/batch/purged-execution/` 下 10 个父任务 completion、249 个阶段 completion、批次 completion 与 `source-adoption.json`。阶段记录路径与字节摘要清单的 SHA256 为 `908c4fe530c08e0accadd51d9df04a4c12d66ab4347d22ecd032fd1bffc3e6f8`。批次记录为 `SUCCEEDED`，wall 10,428.806 秒、调用进程 CPU 10,378.854 秒；父任务自身记录包含成功的执行包装和不同的 `EXECUTION_FAILED`/`SOFT_REJECT` outcome，不能把包装状态当成科学成功。

阶段记录分为 PIT 67 次、signal 82 次（81 成功、1 失败）、Workflow 9 次（5 成功、4 失败）、Validation 5 次、reproduction 5 次，以及其他 81 次完成记录。这些是 checkpoint 记录计数；阶段耗时彼此嵌套于父任务和批次范围，不能跨阶段相加，也不能从批次耗时扣除阶段和后把差值归因于某种工作。五个 Validation completion 各只有一次；按同一 task/run/stage/input 绑定检查，未发现重复 completion attempt。该结果不等于比较、采用或 checkpoint 读取没有重复核验：这些调用没有独立持久计数或隔离计时，属于 unavailable。

调用链为：`prepare_post_hm_purged_evaluation.py` 绑定原件和 successor evaluation 来源，查找并采用已有 signal / variant checkpoint；`post_hm_discovery.py` 再建立 `DiscoveryExecutionService`，执行声明的任务阶段，最后调用 `build_discovery_comparison`；执行 service 通过阶段 checkpoint 恢复并记录各阶段计时；Qlib Workflow 位于 Workflow 阶段内部；比较阶段核验 outcome、PIT/来源和预测报告绑定，但没有独立耗时记录。因此来源采用与新评价执行是两种不同活动。

来源身份也分开保留：source capsule 03 是原始来源 `dc8d5b67babf86332fb3802fb4fe783c6aec56a8`，capsule 04 是 successor evaluation 来源 `3de5a5a33eb9a8d7d2235497dce2338cfd158670`。`source-adoption.json` 绑定原 batch/capsule 与 successor evaluation capsule，并记 `model_predictions_recomputed=true`。其中 15 条 variant 是采用/来源引用记录，不代表额外 15 次执行。capsule、源码和 adoption 文件的逐项摘要见机器记录。

**D08 建议暂缓当前优化实现。** 现有记录能确认执行链含多个参数、子期间和成本变体以及相应 PIT/signal 阶段，但不能分离这些已声明科学范围的边际成本、可避免的重复核验、比较阶段工作或潜在窄路径收益。没有可靠的后续批次数和每批节省量估计；减少变体还可能改变冻结范围。保留现有 checkpoint 与 Validation gate。在本来就要执行的下一项工作中补充轻量的独立核验调用计数和阶段成本记录，再决定是否优化；不为性能测量增加一次全量运行。

可确认的 wall/CPU 项目仅包括批次、父任务及 checkpoint stage completion。提供方账单和失败调用 usage、子进程 CPU、峰值内存、阶段读写字节、人工时间、比较/采用独立计时、checkpoint cache-hit 数和因窄路径可节省的成本均 unavailable，不按零处理。

本次命令退出：锁定环境 `/home/zjw/quant-research-os/.venv/bin/python` 的只读聚合与清单提取退出 0；源码关系 `rg` 和源码 capsule 摘要读取退出 0。初始相对路径 `find` 因原件位于主仓库而失败（退出 1），随后改用指定绝对路径。一次未使用虚拟环境的 `python` 调用退出 127（命令不存在），改用已有 `.venv` 后成功。`find … | head` 输出截断造成管道提前关闭，未用于统计；正式统计由 `.venv/bin/python` 直接遍历 249 个小 completion 文件生成。未解决项是隔离的比较/采用调用次数与可避免成本；它们不阻止本次“暂缓 D08”的范围判断。
