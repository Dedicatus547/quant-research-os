# HM-MVP component-v2 来源采用说明

更新：2026-10-10。状态：`ACCEPTED_COMPONENT_V2_ENGINEERING / LOCAL_RELEASE_REGISTERED`。
[独立 HM09 复审](../reviews/hm09-component-v2-final-review.md)已接受固定 C15 工程组合，
HM10/HM11 已完成。完整身份见[发布标记](../releases/hm-mvp-component-v2-freeze-marker.md)，
原始事实由[接受 JSON](../../artifacts/hosted-evidence/recovery-continue01/hm09-component-v2-acceptance-01.json)绑定。

## 采用范围

| 组成 | 来源与结论 |
|---|---|
| 当前候选 | C15 commit `a47e5a95db15f51e748c1343d96e124fc5b04d8c` 及发布记录中的 B/D/I |
| Q01/Q07/Q09/Q10/Q11 | C15 五项原谓词实际 PASS；前四项复用已保存 checkpoint，Q11 由 continuation01 续做 |
| Q02/Q03/Q04/Q05/Q06/Q12 | 原 C11 tuple `8963936ecaa3efd934701b711f841f5c66f4915a` 的指定组件证明，独立复审核对后采用 |
| Q08 | 原 fullgate 保留 C11 tuple；当前范围为47项来源链与稳定库存，`SOURCE_CHAIN_AND_CURRENT_INVENTORY_ONLY` |
| runtime 绑定 | 完整两份原 receipt/report 集合、typed hash 与原文件字节分别核对，使用只读路径别名适配 |
| 业务闭环 | 原 live/export、两个独立 REEXECUTE、parent RECEIPT_REUSE、comparison 和五类 tamper 已完成 |

接受限定于 `hosted-component-full12-composition/v2` 的工程组合，
未声明 C15 v1 全12门重新通过。原 selected verifier 七项 `NOT_EVALUATED`、
原 composition 生成时的 pending 和旧失败记录保持原字节。

## 最小接续与复用

首次 source-view-01 实际失败，只保存异常类型，未保存 gate 结论；
不能复用推测的通过结果。静态读取发现原 runtime reader 扫描 `manifest.json`，
真实 ValidationReport 为 `report.json`，不将此推导冒充捕获到的异常正文。

管理适配使用完整两份 receipt 引用集合，将原 report 同 inode 的只读字节提供为
runtime-only `manifest.json`；原 report、actual Q11 root/case/inventory 和 runtime 谓词不变。
没有选择任意报告、改写报告或缩小分母。

verify02 因空间估算超限实际退出 -15，四份 canonical PASS 已保存。
continuation01 绑定其原 helper/plan/调用/失败 guard 和 checkpoint 来源，
仅续做 Q11 原谓词及原 runtime/Q08/安装/baseline 收尾，实际退出0/fullcleanup。
缺失结果的必要核对和保存后结果的直接复用分别留证，旧失败不改标为成功。

原 CI1909、106项矩阵、原七门/native、约4.79GB sealed bundle、
C15 源码冻结和实际业务工件全部复用。HM10/HM11 未新增测试、开发门禁、业务模型调用或科学执行。

## 运行与研究边界

两项科学 execution 均 `SOFT_REJECT`，ValidationReport 均 `SUCCEEDED / REJECT`。
工程审阅不成为科学证据，盈利不是工程接受标准。
正式额度8/8、诊断2次、业务 CLI10/10余额0；campaign 已完成、服务已清理。
CLI0.162.1 请求 gpt-6.1-sol/high 的路线已有实际响应，provider identity 未暴露、HTTP 请求数 UNKNOWN。
未来运行依照[快速上手](hm-mvp-quickstart.md)和[故障恢复](hm-mvp-recovery.md)办理。

## 历史追溯

完整[原文归档](hm-component-adoption-history-2026-10-10.md)保留整理前原字节：
20004B，SHA256 `1b7543283806f5392df6a5b7879fbebe3bf225a8489deccfbc1ecf5b8de3d6bb`。
归档与原入口同目录，原相对链接保持适用。
最初采用说明的冻结原字节另见[origin-01](../../artifacts/hosted-evidence/recovery-continue01/hm-component-adoption-v2-origin-01.md)，
SHA256 `70af01babb1377eb35fb50b2fec901a88d44ee6dc07667751221b9eef914e957`。
历史候选和当时的 pending 不替代当前已接受范围。
