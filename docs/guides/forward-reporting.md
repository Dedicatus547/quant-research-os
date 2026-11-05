# 前瞻等待期间的维护与报告

2026-11-06：首日采集缺陷已修复，后继计划 `recovery-05/campaign-plan-05.json` 已通过
实际运行目录的预检并接管两个定时器。下一次采集为11月6日22:30，信号观察为11月7日
00:01（UTC+8）。注册行情截至11月5日，两组scope均为OPEN，仍是0条信号、0次原生推进。
11月5日缺失保留，剩余59个信号日，首次计划执行改为11月9日，结束日仍为2027年1月29日。

修复包含同一交易所的非重叠日历分区、准确失败原因、恢复时预算继承、首日1/2交易日
衔接，以及Qlib原子发布期间目录容量扫描的改名竞争。新增公告规则只识别国联民生
2026-060号公告中的明确交易主体；核验合并方、被合并方、换股取得方及子公司股权条款，
不能仅凭“子公司”标题放行上市主体换股。

421份行情检查点全部离线复用。真实补采完成301家分红和35次官方HTTP请求，加上原来
17次行情请求，恢复相关实际请求为353次；后续离线完成没有再请求供应商。初始与恢复
累计实际1892次，保守初始计费2539次，保留两个失败作业共1000次预留，仍在初始5000次
额度内。后续每日作业继续最多500次，总4万次、48小时和32GiB上限不变。
总墙钟保守计费15496秒，旧失败退出与UNKNOWN评估不改写；第二次恢复复用已发布且
完整核验的Qlib视图，仅补做未来日历扩展、目录构建和新版公司行动评估。

- [恢复后的状态报告](../../artifacts/forward-recovery-20261106/run-01/report-05/report.md)
- [部署、真实退出与最终核验](../../artifacts/forward-recovery-20261106/run-01)
- [后继计划与原缺失日期说明](../../artifacts/hosted-evidence/hs300-lowvol-forward-20261104-01/recovery-05/migration/migration.json)
- [定时器安装回执](../../artifacts/hosted-evidence/hs300-lowvol-forward-20261104-01/recovery-05/migration/scheduler-installed.json)

修复源码已推送至`cf6df45c9918619ab636df8c632f8aeff6dbfdab`。
[该提交CI](https://github.com/Dedicatus547/quant-research-os/actions/runs/42076674574)
的static和offline-unit已通过；此页更新时isolated-tests仍在运行，尚无本次最终覆盖率。
局部检查及两次真实离线恢复已经通过，不能据此把旧85.12%覆盖率标为新提交结果。

以下保留11月5日等待期间的维护背景：冻结采集和账户运行使用原工作目录；维护在独立 worktree
`artifacts/development/waiting-maintenance-20261105` 完成，没有修改运行中的130项源码绑定。
新报告仅读取已有原件。没有新增行情请求、研究账户、信号观察或账户推进。

## 11月5日报告原件

- [前瞻状态报告](../../artifacts/maintenance-20261105/run-01/forward-report-02/report.md)：
  读取时两组均为0条观察、0次原生推进，状态WAITING；行情注册截至11月3日。
- [已有研究阅读报告](../../artifacts/maintenance-20261105/run-01/research-reading.md)：
  原七组与confirm2共八行，完整保留收益、回撤、敞口、费用与原结论。三份记忆诊断及
  四份来源原件已核验；资格退出占卖出金额69.06%，仍是描述性路径分类。
- [CI耗时诊断](../../artifacts/maintenance-20261105/run-01/ci-timing-diagnostic.json)：
  复用已完成的87分钟CI日志，没有为计时重跑科研或全套测试。

这些文件是本地读取时点的快照，不是自动刷新的看板。报告原件在本地保留，不随Git上传。

## 生成新的前瞻状态报告

在运行仓库根目录，用冻结计划对应的解释器调用新脚本；每次指定一个不存在的输出目录：

```sh
.venv/bin/python -B \
  artifacts/development/waiting-maintenance-20261105/scripts/forward_report.py \
  --plan artifacts/hosted-evidence/hs300-lowvol-forward-20261104-01/recovery-05/campaign-plan-05.json \
  --sha256 4eb75fdf0c93959d37184e18633dcceea4e7ca27eeddcb954d0a38db06e7c416 \
  --output-dir artifacts/forward-recovery-20261106/report-manual-01
```

新克隆或后续开发工作区可直接调用 `scripts/forward_report.py`。市场原件不随Git分发，
必须提供实际可核验的计划和原件；不能只复制示例哈希就获得真实报告。

报告输出Markdown和JSON，分别显示：

- 计划日期、已注册数据边界、逐日任务状态和下一计划时间。
- 两组信号记录数量、状态、迟到记录、UNKNOWN尝试及原生完成日期。
- Qlib原生现金、持仓数量、最近报告和检查点身份；未开始时指标保持null。
- 调度实际墙钟与原初始计费、各scope剩余限额及未结预留。两套墙钟不相加；未知作业
  或计划外目录存在时全局剩余墙钟为null。完整增长量依赖宿主守卫，不用目录大小冒充。

`DUE_WITHOUT_RECORD`表示到期尚无记录；`IN_PROGRESS_OR_UNKNOWN`不推断成功或退款。
报告不接收任意历史时钟参数，不把今天读取的结果伪装成过去已知。来源哈希、注册表链
或原生状态不一致时拒绝读取；不会回退到旧成功结果。

现有原生状态接口包含恢复发布行为，所以报告使用只读适配：复用原生状态验证、codec
和Qlib报告读取，禁用会话初始化及未完成步骤发布。读取前后，两组产品的22份原件
文件哈希一致；没有把空现金账户或待恢复步骤写成成功。

## 报告口径

真实观察开始后，原生最近报告的资金、费用、换手及敞口可直接显示。完整净值曲线、
累计净收益、回撤和逐日成交诊断仍需读取完整原生报告历史；本次没有实现新的业绩计算器，
也没有用缺失数据画零收益曲线。正式科学结论保持NOT_EVALUATED，沿用冻结方案的判据。
两组比较始终并列现金和敞口；信号、委托及成交不互相替代，迟到、弃权和失败不删行。

定时器是否在线需要另行只读查询，不能从计划文件推断：

```sh
systemctl --user show \
  quantos-hs300-20261104-acquire.timer quantos-hs300-20261104-observe.timer \
  -p Id -p ActiveState -p SubState -p NextElapseUSecRealtime
```

当前会话的旧MCP进程拒绝了一次运行版本查询；使用新CLI进程读取策略能力和三份研究诊断
均成功。默认研究产品与独立前瞻产品的scope分开，不能以默认产品没有授权推断前瞻被取消。
本前瞻计划绑定`.venv/bin/python`环境；不同MCP解释器下的原生运行身份可能不匹配。

## CI维护的接受范围

两个离线供应商夹具已使用惰性限流替身，避免后台事件循环触发禁网环境的socket异常。
生产采集限流器保持原样。定向测试把线程异常及RuntimeWarning当成错误验证，未关闭
禁网检查或全局过滤警告；另用已有Qlib Account合成夹具验证完整账户读取和原件不变。

原CI日志在业务端到端、隔离进程协议、故障探针等阶段出现较长输出间隔。日志缓冲使这些
间隔不能精确归因到单个测试，也没有CPU/内存峰值证据，因此本次不声称已加速87分钟套件。
工作流增加`--durations=30`和JUnit XML制品，供下一次正常完整CI直接提供每项耗时。
原覆盖统计范围及85%门槛保持不变，没有新增验收门禁或拆分共享authority的恢复链。

源码执行路径未变，本轮采用定向检查及一次真实只读报告；先前完整CI
[41957943631](https://github.com/Dedicatus547/quant-research-os/actions/runs/41957943631)
的3662通过、5跳过、85.12%覆盖率仍绑定其原提交，不改标为此次新脚本的完整CI结果。
本次检查、失败尝试及修正结果均保留在
[维护目录](../../artifacts/maintenance-20261105/run-01)。
