# P13 真实公告 benchmark v2 待审批对照

状态：APPROVED。用户于 2026-09-10 明确回复“批准，请继续”。正式 runner 已选择 v2。
批准的 policy hash 为 `a1eecec872b784c1dea5f90cbf6197a47e494a0be79eb65fa411879fa2c0b8f3`，
binding hash 为 `580b372f53ae96cce298e22c47ef0261eae703c7d76637ac9165eb37b9d6c12c`。
以下对照保留审批时内容；正式配置位于 `configs/research/`，`proposals/` 保留原草案。

## 恢复核查与保存位置

在项目 artifacts、已知 /tmp 产物的 manifest 和 Git 历史中，未找到旧 Store
`be484479b61c7096ffd58e99fa31168dc06a7fc7ae4597a2d455cda2c41250b1` 的完整文件。
这仅表示本次核查范围内不可恢复，不代表其他介质不存在备份。

2026-09-10 采集的候选 Store 已复制到项目的 git-ignored 本地产物目录：
`artifacts/evidence-stores/sha256-4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306`。
复制后重新通过 exact-file、文件 hash、manifest 与 Evidence/text 引用校验。
原始文件和完整提取文本不加入 Git；该本地副本尚不等同于异地备份。

## 审阅内容

| 项目 | v2 提议 | 与 v1 比较 |
|---|---|---|
| 公告 | 包钢股份关于股份回购进展情况的公告，2025-08-05 | 同一公告身份 |
| 来源 | 留存 SSE 查询记录及 SSE HTTPS 镜像 PDF | 本次重新采集 |
| 实体 / 标签 | `600010.SH` / `share_repurchase` | 不变 |
| 事件时间 | `2025-08-05T15:59:59.999999Z` | 不变；日期精度的保守日末时间 |
| 标题引用 | 第 1 页字符 `[99,112)` | 文本 hash 与 v1 完全一致 |
| 进展引用 | 第 2 页字符 `[1066,1193)` | 文本 hash 与 v1 完全一致 |
| 属性 | `[]` | 不变 |

标题为“关于股份回购进展情况的公告”。进展段记录截至 2025-07-31，累计回购
9,856,800 股，占总股本 0.022%，成交最高价 2.72 元/股、最低价 1.79 元/股，
支付总金额 2049.98 万元，不含佣金、手续费等交易费用。这些数字仅用于人工核对原文；
v2 仍采用空属性集，不将其新增为 Agent 抽取或执行字段。

两段原文的字符区间和文本 hash 已用留存文本重新计算。旧 PDF 和旧 Store 未恢复，
因此不能推断整份旧文档与本次 PDF 逐字节相同，也不能确定所有 hash 变化仅由采集时间造成。
本次 PDF 为 91,583 字节，提取结果为 3 页、1,378 字符；留存权限值为 `RESEARCH_ALLOWED`。
继续保留非 vintage、日期精度、来源内容未独立核实及修订历史无保证等限制。

## 可复核的版本绑定

- Store：`4fb04acc23c62b72d37df826560e2515a68cf7c7973ce1a0527a42a2b14fc306`
- Evidence：`e1e8591a6b3daa9678923c0fd4318fac991679587e1f434efc7da8ae29a1e800`
- ExtractedText：`3d78e4f9f4d05fd67eeca16f589be0179feef1dc131ab6e452b26080348ec3db`
- PDF：`9dafede8cab4fa3d2a205942ebba9657a702cc125e044d719c5c3931a36939cf`
- v2 policy：`a1eecec872b784c1dea5f90cbf6197a47e494a0be79eb65fa411879fa2c0b8f3`

待审批文件位于 `configs/research/proposals/p13_real_sse_share_repurchase_benchmark_v2.yaml`
和 `configs/research/proposals/p13_real_sse_benchmark_binding_v2.yaml`。
本次未切换正式入口、未运行 v2 正式 qualification，也未产生真实 EventFeature 或市场结论。

## 需要批准的具体决定

批准使用上述候选 Store 创建 v2 benchmark，沿用 v1 的抽取预期，再运行真实 Agent、
deterministic admission 和后续正式资格验证。v1 及全部历史失败证据继续保留。
该批准只固定验收输入，不预先认可 Agent 输出或研究结果。
