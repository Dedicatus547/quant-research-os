# 工作区遗留修改审核

2026-10-22；审核基线为本地 main `7d27c1f05d750cea6db91a0ee3adb97753e86079`。
开始时有4份已修改文档和2份未跟踪实验脚本。结论：修正文档后提交；两份脚本保留原字节并归档，
不作为通用源码入口提交。本次不推送，历史实验、失败、冻结输入与科学判据不改。

| 原修改 | 审核结论与处理 |
|---|---|
| `PLAN.md`、`docs/status/README.md` | 持仓缓冲结果及暂停建议有原件支持；保留新增说明，补公告试点已提交和人工复核完成入口，更新脚本归档状态及日期 |
| `docs/guides/bounded-local-01621-environment.md`、`docs/guides/delivery-consolidation.md` | 后继安装成功有原件支持；明确首次阻塞属于历史时点，保留失败与未取得科学/live资格的边界 |
| `scripts/holding_retention_study.py` | 已结束的固定诊断；复用Qlib回测和既有会计对账，只扩展目标权重回调。依赖本地冻结计划和私有service辅助函数，无完整Validation/campaign管理接线；归档 |
| `scripts/announcement_understanding_trial.py` | 已结束的固定材料调用/评分脚本；导入时即加载被Git忽略的旧运行文件，并固定原材料、输出目录、额度窗口和SDK环境。当前主线相关依赖已整理，不能当作可直接复现的通用入口；归档 |

事实采用与核对范围：

- [持仓对照](../../artifacts/holding-retention-20261020/run-01/comparison.json)、
  [摘要](../../artifacts/holding-retention-20261020/run-01/summary.json)与
  [原报告](../../artifacts/holding-retention-20261020/run-01/report.txt)相符：
  年化换手35.0089→30.5188，费用98,168.62→86,392.00元，净累计收益差+0.4240个百分点。
  原换手阈值12未满足；毛复利诊断下降、实际暴露不同，新Validation仍为NOT_EVALUATED。
  [原决策](../../artifacts/research-next-decision-20261020/decision.md)是暂停建议，不是新科学裁决或授权。
- [安装摘要](../../artifacts/delivery-consolidation-20261019/run-01/environment/install-01/verified-summary.json)记录208项独立安装及隔离导入成功；
  [恢复摘要](../../artifacts/delivery-consolidation-20261019/run-01/environment/post-install-bytecode-01/verified-summary.json)记录27961文件库存hash不变。
  两份摘要均保存真实guard退出及cleanup；启动须使用`-B`或`PYTHONDONTWRITEBYTECODE=1`。
  本次采用既有小型原件，不重新扫描环境或扩展其资格。
- 公告试点的冻结分数和38项事后人工复核范围与[主线采用记录](../releases/announcement-understanding-pilot-2026-10-22.md)及其本地来源一致。
  旧报告中的“待人工复核”属于历史时点；当前已完成，冻结分数未回写。

归档位于本地持久目录`artifacts/workspace-review-20261022/run-01/`，受既有gitignore排除。
[归档收据](../../artifacts/workspace-review-20261022/run-01/source-archive.json)保存原路径、归档路径、长度及SHA256：

| 原脚本 | 原字节SHA256 | 归档路径（相对上述目录） |
|---|---|---|
| `scripts/holding_retention_study.py` | `217e1d8a652e475a4b48f6ea2f262d848f839ad054030218ebb49c35a6a160a8` | `frozen-source/scripts/holding_retention_study.py` |
| `scripts/announcement_understanding_trial.py` | `2000c9c395150d13e7451a9ec622c608dfea19e07aa68cbb6e17b33dbab270dd` | `frozen-source/scripts/announcement_understanding_trial.py` |

先核对原plan/inventory或freeze绑定，再复制并逐字及hash核对，保存收据后才移除未跟踪原路径。
原计划、freeze、inventory和交接中的路径按历史保留；本记录仅追加归档映射。
以后若获授权复现，须在独立checkout按映射恢复原脚本路径，并采用全部原冻结依赖；
归档文件本身不是可从归档目录直接启动的入口，当前主线不冒充旧运行源码。
同步修正[本地Evidence指南](../guides/local-evidence-store.md)的历史脚本位置说明。

审核使用离线源码阅读、小型原件hash/数值核对、文档链接和空白检查。
6份本次文档的123个本地链接均存在；持仓目录16份小型原件及原计划15项文件绑定核对相符，
其中脚本绑定通过上述归档映射核对。未重读市场Parquet或扫描完整环境库存。
未新增或运行测试、完整CI、安装、采集、模型调用或科学重执行；旧证明不重标为本次通过。
初始diff、状态、归档收据和检查结果留在上述本地目录；该目录不随源码提交。
