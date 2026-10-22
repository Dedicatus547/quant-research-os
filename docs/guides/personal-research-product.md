# 个人量化研究入口

## 安装与状态

产品 Skill 位于仓库 `skills/quantos-research`，用户目录 `~/.agents/skills/quantos-research` 指向该目录。MCP 服务名为 `quantos_research`，配置在 `~/.codex/config.toml`。安装器只管理这个 Skill 和 MCP 项；配置备份保存在 `~/.codex/backups/quantos-personal-research/`。安装或卸载后重启 Codex。

服务使用 `.tools/personal-research-mcp-1.26.0/bin/python -B` 和官方 MCP Python SDK 1.26.0。环境里的只读 `.pth` 将源码目录及原 `.venv` 科学环境加入解释器路径；原科学环境没有升级。

以下命令可在仓库目录直接粘贴。产品数据根目录固定为本次安装所用的 `artifacts/personal-research-product-20261022/run-01/product`。

```sh
cd /home/zjw/quant-research-os
PYTHON=/home/zjw/quant-research-os/.tools/personal-research-mcp-1.26.0/bin/python
ROOT=/home/zjw/quant-research-os/artifacts/personal-research-product-20261022/run-01/product

"$PYTHON" -B scripts/install_personal_research.py status \
  --repo-root /home/zjw/quant-research-os --root "$ROOT" --python "$PYTHON"
```

重新安装时将 `status` 换成 `install`。卸载产品条目与 Skill 链接用：

```sh
"$PYTHON" -B scripts/install_personal_research.py uninstall \
  --repo-root /home/zjw/quant-research-os --root "$ROOT" --python "$PYTHON"
```

目前安装状态检查显示 Skill 与 MCP 配置均匹配，原配置中的其他项目得到保留并已备份。SDK 1.26.0 的两次独立服务连接分别从 `/tmp` 和 `/` 启动，能跨工作目录查到同一个 `BLOCKED` 任务，说明服务状态使用固定产品根目录。当前 Codex 会话不能刷新 MCP；实际新 Codex 会话的工具调用仍待确认，不能据 SDK 检查声称客户端验收通过。重启后可让新会话先列出 `quantos_research` 工具并调用 `research_capabilities`。

## 工具与研究边界

服务入口在 `src/quantos/personal_research_mcp.py`，通过 `src/quantos/application/personal_research.py`、证据/历史服务及 `src/quantos/contracts/personal_research.py` 提供能力。共提供 15 个工具：

- 研究：`research_capabilities`、`research_history`、`research_retained_read`、`research_prepare`、`research_status`、`research_execute`、`research_cancel`、`research_results`、`research_simulation_prepare`。
- 公告材料：`announcement_list`、`announcement_read`、`announcement_cite`、`announcement_propose`、`announcement_review`、`announcement_import_local`。

默认没有真实市场研究执行授权。`research_prepare` 保存研究提案和准备状态，不会运行回测；`research_execute` 只有在服务端已有匹配授权时才可能执行，工具参数本身不能授权。`research_simulation_prepare` 只准备条件性请求，不启动前瞻模拟或定时任务。`research_history` 和 `research_status` 在对账未知状态时可能补记状态事件，因此它们可能留下持久记录。

当前有限策略方向是 `daily-mainboard-trend/v1`：收盘后形成日频信号、下一交易日开盘执行，以趋势、量价和同花顺板块资格构成提案；不把日线解释成盘中策略。具体规则由模型按可用数据提出并说明。用户无需手填哈希或普通策略参数；后续操作使用工具返回的明确任务 ID 和证据 ID。

本机已有真实快照仅覆盖沪深300，不能代表全体主板。同花顺 `ths_member` 的公开接口说明目前只提供最新成分，未提供可用的纳入/剔除日期；因此真实全主板与同花顺历史成员组合仍受阻。[同花顺板块成分接口说明](https://tushare.pro/document/2?doc_id=261)。真实数据 PIT 与时点费用适配器尚未接纳。现阶段只导出了原生 Qlib 历史账户/持仓产物，尚未实现跨不同数据视图的连续账户推进，真实前瞻模拟尚未启动。

已完成的小型合成演练中，主策略、经典对照和 5 个固定随机种子共 7 项均生成了 Qlib 账户输出；其科学判定仍为 `NOT_EVALUATED`。这验证的是工程路径，不代表真实市场结论或策略通过。旧诊断、REJECT 和失败记录只保留原件供读取，没有重跑或改写结论。

公告入口目前列有 27 份本地材料，但权限和历史可用时间均为 `UNKNOWN`，研究准入未授予。引用检查只能核对原文位置，不能证明语义正确；辅助阅读也不能推出“没有利空”。需要明确材料 ID 后再读和引用，不要把这些材料当成历史交易特征。

## 可直接使用的提问

```text
请研究A股主板短线趋势，结合同花顺板块与量价，公告作为辅助风险分析。先查当前能力和已有结果，自行提出完整规则及对照，用research_prepare保存提案并解释数据缺口；普通指标参数由你决定，不执行真实研究。

请只检查当前研究能力、历史目录和公告目录，列出明确的数据范围、权限和历史可用时间未知项。不要准备或执行研究；如核对历史状态会写入对账事件，请指出这一点。

请根据公告目录中我指定的材料 ID 读取原文并核对精确引用，说明哪些判断只是辅助分析提案、哪些权限或可用时间仍未知。不要推断历史上没有利空，也不要把结论纳入策略。

请基于当前能力说明全主板、同花顺历史成员、PIT 和费用适配分别缺什么，并给出下一步需要我审阅的具体数据或研究准备范围。不要用沪深300替代全主板，也不要启动执行。
```

目录查询可使用 `research_history`，读取已登记的旧报告可使用 `research_retained_read`；针对某项明确任务，使用 `research_status` 与 `research_results`。公告阅读链路是 `announcement_list` → `announcement_read` → `announcement_cite`，必要时再用 `announcement_propose` 和 `announcement_review`。提案和引用审查都不自动完成研究准入。

首个真实方向已保存为受阻提案 `a49f263b832df681ccd687193df336bd924afd4a04881ac7b34929e71c09f12c`。
具体设计、来源差异与唯一后续审批点见 `artifacts/personal-research-product-20261022/run-01/first-study-proposal.md`；
实际绑定包在同根 `first-study-final/`，主交接为 `handoff.md`。缺数据/真实适配时不提供伪可执行的市场运行命令。
