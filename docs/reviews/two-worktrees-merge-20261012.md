# 两个 worktree 合并审核

2026-10-12：在用户授权的审核与安全合并范围内，未发现阻止本次源码集成的问题。
两分支在独立审查 worktree 无冲突合并，完成以下检查后合入本地 main；未推送或部署。

| 对象 | 提交 |
| --- | --- |
| 合并前 main | `3eb4730fc5d73db9dd5bfd954777acb1fd728fd9` |
| `work/fr03-unblock-20261011` | `a92b2415f875179e9e9857fc3aeab94732b5042f` |
| `work/post-hm-discovery-next-steps` | `e0094eda0279b38b4d1ea4c9593cc09650a5a21f` |
| FR-03 合并节点 | `16a8196` |
| 两分支组合源码节点 | `e24fa11` |

采用两个 merge commit 保留原开发历史；原 worktree、分支及其持久证据继续保留。
最终文档提交修正 README、状态页和 ADR 中已过期的集成状态及 FR-03 NO_GO 描述。
[原 FR-03 接受说明](fr03-go-acceptance-20261012.md)中的未集成状态按接受时点解释。

## 审核与实际检查

- 复核 SDK/runtime 显式 profile、Apps/MCP 限制、P10/P13 失败留证及原生 split 文件归属。
- 复核 Discovery 顺序历史冻结、原件采用、独立科学预算、预测证据核验、完整机会分母及共同日期比较。
  合并交叉点是 `autonomous.py` 的类型注解和 `discovery_baselines.py` 的后继基线；main 既有阶段失败诊断被保留。
- 检查变更的 contracts 导入，没有引入 Tushare、Qlib、application harness 或 LLM SDK 依赖。
- 组合源码的 Discovery、P10 v4、P13 runner、SDK host 及异常脱敏定向离线回归：**245 passed**，pytest 报告耗时 **79.15 秒**，实际退出 **0**。
- 全部变更 Python 文件 Ruff 与格式检查通过；组合 `src` 的 strict Pyright 为 **0 errors**。
  初次 Pyright 因 worktree 内没有 `.venv` 而失败；显式指定主仓既有环境后通过，初次失败日志保留。
- FR-03 接受记录引用的 **69 份原件**及 Discovery 科学报告引用的 **8 份关键原件**，大小与 SHA256 全部一致。
  对照接受源码清单及统计源码胶囊，保留实际依赖差异清单，没有重新解析大型预测或重新执行科学。

本次检查的命令、真实退出、源码身份和原件核对结果见
[持久审核记录](../../artifacts/merge-review-20261012/review.json)、
[原件及源码差异](../../artifacts/merge-review-20261012/retained-evidence-review.json)和
[JUnit](../../artifacts/merge-review-20261012/pytest.xml)。

## 采用范围

本次结论是源码合并审核及定向离线验证。没有重跑全量 CI、覆盖率、真实模型、HM 场景矩阵或科学批次。
新增 Discovery 模块与跨分支依赖改变了组合源码；FR-03 原接受的 85.0220588235294% 覆盖率和
1970 节点增量证明仅保留原源码适用范围，不能据此声称合并后全量 CI 或 85% 覆盖率门已通过。
后续若需完整 CI 或发布资格，应按实际变化和已有授权确定补验范围。

FR-03 的 GO 仍限定于冻结 benchmark、环境与 `0.162.1 + gpt-6.1-sol / medium`；
默认依赖仍为 `0.154.0`，实际使用后继需显式命名 profile。接受原件及绑定配置中的
`main_integrated=false` 保留原接受时点的字节身份，当前集成状态由本记录和 Git 历史说明。
P14d-C、SDK discovery/campaign 入口仍未资格化。合并本身不启动调用、追加额度或改变科学裁决。

[Discovery 后继科学报告](../roadmap/post-hm-next-scientific-report.md)继续绑定原生成与科学来源：
12 个候选、9 项可比预测、3 项缺源；LLM 相对最佳基线增量为 0，冻结规则建议暂停扩大当前空间的同类生成。
该探索性结论和所有失败、拒绝原件保持原身份，不转成策略 PASS 或工程资格。
