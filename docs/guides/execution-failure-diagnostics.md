# 失败细类与只读查看

新增失败仍按既有规则记为 `FAILED / NOT_EVALUATED`。stage completion 沿用 v2，成功与采用 checkpoint 继续使用既有格式；没有改变科学判据、费用或恢复流程。诊断只解释本次代码能直接确定的触发点：

| stage | failure_detail_code | 确定触发点 |
| --- | --- | --- |
| `*-signal` | `SIGNAL_PIT_MEMBER_UNMAPPED` | PIT member 缺少 Qlib view mapping |
| `*-signal` | `SIGNAL_FINITE_WITHOUT_TRADABILITY` | 有限 signal 缺少 tradability evidence |
| `workflow` | `WORKFLOW_RECORDER_INTERFACE_MISSING` | recorder 的 `load_object` 或 `list_metrics` 不是可调用接口 |
| `workflow` | `WORKFLOW_REQUIRED_METRIC_NON_FINITE` | 已读取的 required metric 转换为 float 后非有限 |

四个触发点抛出项目专用 `QlibResearchError` 子类型，stage 只认精确类型及既有 reason/stage 边界。第三方相同文本、任意诊断属性、子类或 cause 不能选择细类；其他异常继续 `UNCLASSIFIED`。异常继续向调用者传播，失败不会发布成功 checkpoint。缺少 metric、转换失败和未知第三方错误没有被猜测归类。此实现不能反推历史 Workflow 失败的唯一根因。

从仓库根运行只读字段查看：

```sh
PYTHONPATH=src /home/zjw/quant-research-os/.venv/bin/python \
  scripts/inspect_execution_diagnostics.py \
  --stage-completion /absolute/path/to/completion.json EXPECTED_SHA256
```

可在同一命令中按需添加 `--feedback PATH SHA256`、`--selection-report PATH SHA256`、`--closeout PATH SHA256`。输入分别为既有 `adaptive-feedback/v1`、`campaign-selection-report/v1` 与 `adaptive-readonly-closeout/v1`；stage 支持原 v1/v2。该命令仅读取指定小型 JSON、核对字节 hash、输出枚举和非负整数白名单，不扫描或重执行任务、不写回原件，也不产生资格。

`execution_status` 与 `research_verdict` 取自显式提供的 feedback；`stage_status` 单独保留，不能据成功 stage 推断整个 execution 成功。父 selection 的 `reason_code` 单独展示，不覆盖 execution 原因。已知 usage 只投影既有 closeout 的 `sdk_captures[].usage` token 数，不估算余额、现金费用或未捕获用量。缺字段、旧 v1 没有的细类以及未知 usage 保持 `null`。

输出列明每份来源的 SHA256，并标记 `CALLER_SUPPLIED_NOT_VERIFIED`：这些输入的相互来源关系由调用者指定，此薄查看入口没有替代原 receipt、feedback 或 closeout 的完整绑定核验。输入不符合 hash、schema 或大小上限时，仅输出固定失败码并退出 2，不复制任意异常文本。

本轮定向验证与历史小原件查看证据保存在主仓 `artifacts/delivery-consolidation-20261019/run-01/diagnostics/`；失败记录按原 attempt 保留。没有新增真实模型、采集或科学运行。
