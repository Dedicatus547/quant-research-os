# 个人研究产品收尾与本地采用范围

2026-11-03；本次新增科学运行 **0**。运行终态基准为2026-11-01。

## 一次定位

- 实际协议：[用户指南](../guides/personal-research-product.md)，profile `hs300-daily-trend-tushare-lifecycle/v3`，request/v6、dataset/prepared v5、catalog/config/grant v4。
- [完整报告及七行指标](../../artifacts/personal-research-product-20261101/dividend-continuation-01/report.md)、[七行原比较](../../artifacts/personal-research-product-20261101/dividend-continuation-01/research-01/comparison.json)、[短交接](../../artifacts/personal-research-product-20261101/dividend-continuation-01/handoff.md)。
- 任务 `5f491a287a448899c5477248dfba1aef74b4f10e9bd94247798c5aafcaaf2c6c`：`SUCCEEDED / NOT_EVALUATED`。六新账户各721日，经典 `REUSED_ORIGIN`，0缺失、0事件硬停。无 ValidationReport，未授予科学资格。
- 下一动作：重启旧MCP进程加载后继工具；先用有界摘要阅读。新研究须另有明确问题和新包，终态任务不续跑；连续前瞻账户仍未资格化。默认授权null，不需要为本次收尾再运行研究。

## 来源和结果语义

供应商复权价格／数量单位场景；普通分红已由冻结因子表达，不另加现金，不证明实际支付、精确现金再投或税后实收总回报。主策略模型收益−24.14%、经典−7.79%、基准+16.54%，平均敞口约40%，不作同暴露比较或盈利资格。

经典来源任务 `40e4d6d4bcd1d42eab360293930608a773303e94663c036bc4c002179f16919c`，receipt `724ed68d35e04021ba68e67d53ed66528c670a6fe4cb4adaf1aa77dd957cde6e`，origin `a956c05499245090cea9fc1c17baecdf2ae70009ca576f5cbdc58e7fa34f73da`。采用[完整origin绑定](../../artifacts/personal-research-product-20261101/dividend-continuation-01/input-01/classic-origin.json)，不生成新经典收据。
当前 comparison SHA256 `5bc1d0271a5a723a6417799d725fc0e4b5ab16f99cd71406350d4971aa603581`。

## 可审阅差异与采用边界

集成前本地 main `761ba39`；产品分支 `work/personal-research-product-20261022`，源码头 `1820f1c`。七个提交依次为 `6d9b33e`、`02003a4`、`84e8ccd`、`d358366`、`5e54116`、`7a5748a`、`1820f1c`。可审阅差异：`git diff 761ba39..1820f1c`（51文件，12443新增行）；仅有祖先关系不自动取得主线工程接受。

采用的是有界本地源码与下列原tuple证明，不是对后继commit重授全库、部署或科学资格。本轮先登记本页与入口，再发布展示后继，最后本地快进集成；不推送、不移动历史tag。实现验证此次未授权，展示后继的工程验证仍待用户明确要求。

| 原件 | 可采用结论 | 不扩展的范围 |
|---|---|---|
| [当前manifest](../../artifacts/personal-research-product-20261101/dividend-continuation-01/run-package-01/dependency-manifest.json)及[具体运行包](../../artifacts/personal-research-product-20261101/dividend-continuation-01/run-package-01/run-package-with-config.json) | 原code `b3edd44b…`、dataset `ed6b5518…`、环境与来源精确绑定 | 不把文档或展示后继标为原tuple |
| [旧检查收据](../../artifacts/personal-research-product-20261101/dividend-continuation-01/integration-checks.json)及[最终静态检查原件](../../artifacts/personal-research-product-20261101/dividend-continuation-01/final-static-01/) | 原28服务+15核心用例、315会话组件检查及实际退出 | 不证明新投影接口、全库或新运行形状 |
| [结果语义复核](../../artifacts/personal-research-product-20261101/dividend-continuation-01/service-wiring/result-read-review.md)及其依赖原件 | 七行、经典来源、实际生产边界与收尾按原身份采用 | Agent复核意见不替代程序证据或Validation |
| [实际结果和收尾](../../artifacts/personal-research-product-20261101/dividend-continuation-01/research-01/) | 6新+1复用、原退出/清理/撤权 | 旧FAILED、付款UNKNOWN、旧报告全部保留 |

## 实际传递依赖

收尾前对当前manifest中的27个仓库源码条目逐一比对SHA256，全部匹配；另22个外部runtime/工具项此次不重新核验，其身份仍依原运行包。snapshot、view、panel、PIT、七信号、科学配置、指标实现、Qlib账户/Exchange/Simulator均复用。

展示后继新增 `application/personal_projection.py`，由 `personal_research_mcp.py` 引用；CLI和仓库Skill改用该入口。传递链为客户端/CLI → 展示投影 → 原service.results → 原outcome/comparison/receipt/origin/文件完整性路径。能力摘要直接投影服务端catalog的manifest内容身份，不运行prepare。旧capabilities/data_describe/results完整契约及原验证函数保留。

当前manifest覆盖的唯一实际变化项是 `scripts/run_hs300_study.py`；它负责显示入口，旧科学运行仍按冻结脚本身份解释。MCP、投影和Skill不在该27项集合中，但属于新展示的实际依赖，不能漏报。新整体commit不影响旧结果身份，也不要求重算信号/回测。核验加速单独等待已有成本实测，未在本次实现。

## 展示后继发布与集成记录

文档先提交为 `364c152`；展示后继按[本地差异审阅](../reviews/personal-product-local-adoption-2026-11-03.md)整理后，采用本地fast-forward集成。原完整工具保留，新增 `research_capabilities_summary`、`research_results_summary`、`research_results_boundary_page`、`research_results_boundary_read`，共20工具。客户端默认选择前两个后继摘要，原客户端仍可使用旧完整契约。实现验证未运行；只有后续用户明确要求时才运行受影响的既有接口/完整性用例，不启动全库矩阵或新科学。

实际集成已完成：本地main从 `761ba39` 快进至展示源码 `a53356d`，产品分支也保留在 `a53356d`；随后仅在main登记本段集成结果。文档提交顺序为 `364c152` → 展示 `a53356d` → 集成登记。未推送远端，工作区无遗留修改；当前未重启MCP、未运行实现验证。新源码采用范围仍受本页和差异审阅限定。
