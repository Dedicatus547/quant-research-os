# 设计资料

下列链接保留原计划的设计依据，原核查日期为 **2026-09-01**。
本次文档重组未重新核验网页，也不把浮动网页内容作为 canonical 输入。

## Tushare

| 主题 | 原始资料 |
|---|---|
| 账号权限与调用频次 | [积分、频次与权限](https://tushare.pro/document/1?doc_id=290) |
| 许可 | [数据服务协议](https://tushare.pro/document/1?doc_id=405) |
| SDK | [Python SDK](https://tushare.pro/document/1?doc_id=131) |
| Instrument | [stock_basic](https://tushare.pro/document/1?doc_id=25) |
| Calendar | [trade_cal](https://tushare.pro/document/2?doc_id=26) |
| Bars | [daily](https://tushare.pro/document/1?doc_id=27) |
| Adjustment | [adj_factor](https://tushare.pro/document/2?doc_id=28) |
| Membership | [index_weight](https://tushare.pro/document/2?doc_id=96) |
| Tradability | [suspend_d](https://tushare.pro/document/2?doc_id=214) |
| Historical ST | [stock_st](https://tushare.pro/document/2?doc_id=397) |

网页不能代替账号 capability probe、返回 schema 或许可证据。
实际采集使用显式冻结 policy，详见[数据与 PIT](../architecture/data-and-pit.md)。

## Qlib

| 主题 | 资料 |
|---|---|
| 官方源码 | [项目](https://github.com/microsoft/qlib) |
| 数据转换 | [data component](https://github.com/microsoft/qlib/blob/main/docs/component/data.rst) |
| Workflow / records | [recorder component](https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst) |
| Strategy / backtest | [strategy component](https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst) |
| Exchange | [source](https://github.com/microsoft/qlib/blob/main/qlib/backtest/exchange.py) |
| 本地实际组件证据 | [0.9.7 feasibility](../feasibility/qlib-0.9.7.md) |

`main` 链接用于查找资料；canonical converter 使用冻结 source commit，
实际安装版本与 `uv.lock`、工具 hashes 进入 provenance。

## Agent 与公告来源

接口、runtime、权限与实际能力以本地冻结 ADR、benchmark 和资格记录为准：

- [Harness / SDK 决策](../adr/README.md)
- [公告 acquisition ADR](../adr/0002-exchange-evidence-acquisition.md)
- [P13 benchmark 与资格冻结](../p13-v2-freeze.md)
- [当前 FR-03 runtime 边界](../status/fr03.md)

[原计划资料章节](../history/2026-09-29/PLAN.md)保留历史上下文。
