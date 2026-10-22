# 沪深300 / Tushare 日频研究后继

本地实施增加 `hs300-daily-trend-tushare/v1`、request/v3、dataset/v2、prepared/v2。
冻结的周度真实合同及旧主板/THS个人合同不修改；旧任务、失败、额度和来源身份保留。
策略、目标仓位、成本、限价与交易单位均在新typed profile内固定。

真实来源接线复用指定snapshot `6297a968a2649f0777614d539cd1391e0e479e13b5f91b1124a7dccc277e3dd9`
与view `fc809bedc8180b27134362beca02fc3b67a5565e8b447bab756a78557385716b`。
成交额绑定canonical bars.amount_cny；成员与各输入绑定其实际可用时间。
next-open限价薄适配使用原始每日up/down limit，仍由Qlib Workflow/PortAnaRecord/原生
策略、Exchange与Simulator生成全部订单、成交、账户和持仓。
导出包含完整七候选、实际暴露、费用、年度/子期、原生订单/成交记录及比较报告。

MCP/Skill接好16工具、受信本地catalog与精确授权原件，默认无授权。
继承单worker、幂等、取消、UNKNOWN不重发；重任务复用既有storage lease/namespace，
加有限wall timeout。修正worker不能在子PID namespace里对宿主PID做存活对账的问题，
并保留PIT硬拒绝跨worker的安全原因与真实失败退出。

完整目标区间仍BLOCKED：离线来源适配实际发现38个退市日后成员/交易日缺bars且无suspension，
涉及600837.SH与601989.SH。缺口是生命周期历史可用时间及吸并/退市持仓处置，不能补零、
静默裁剪成员或重写账户会计。另需宿主恢复既有64 MiB scratch硬配额挂载。
本轮没有真实市场策略执行、训练、回测、Validation、新采集、付费模型、外部公告PDF或前瞻调度。

工程验证与科学结果分开：定向service/PIT/amount/原生接口及小型Qlib演练证据保留；
失败父运行、原native artifacts与独立恢复证明均按原身份留存，不重跑已保存的七账户。
小型合成账户与恢复不构成策略资格。连续前瞻Account依然是独立后继，未以Position字典代替。

具体策略与MCP使用见 [用户指南](../guides/personal-research-product.md)。
正式证据根为 `artifacts/personal-research-product-20261022/hs300-implementation-01/`，
运行准备及输入/源码/配置/环境实际hash见其 `run-package-02/`；
唯一主handoff沿用 `artifacts/personal-research-product-20261022/run-01/handoff.md`。
来源/生命周期和宿主依赖解决后须形成新的完整绑定包，再集中请求一次真实运行批准，
不把本地实施授权、已失败的旧父包或模型提案当作运行授权。
