# TradingAgents 核心功能对应表 · v0.3

源：用户提供的 https://github.com/vondecsun/TradingAgents 。
源版本0.6.0，基准提交与93个Python源码文件SHA-256见 UPSTREAM_CORE_MANIFEST.json。
产品未改写 tradingagents/ 或 cli/ 下的任何文件；核心代码校验在原生研究页显示。

| 原始核心功能 | 直接调用/保留位置 | 产品入口 | 验证状态 |
|---|---|---|---|
| 技术、情绪、新闻、基本面四分析师 | TradingAgentsGraph / GraphSetup | 原生分析，默认全选四类 | 原始图离线执行通过 |
| 分析师工具、并行执行 | 原生 analyst graphs / vendor router | 同一原生分析 | 原始工具路由离线执行通过 |
| 多空辩论与研究经理 | 原生 Bull/Bear Researcher、Research Manager | 报告完整角色段落 | 离线执行通过 |
| 交易员计划 | 原生 Trader | 报告完整角色段落 | 离线执行通过 |
| 激进、保守、中立风险讨论 | 原生 risk debate nodes | 报告完整角色段落 | 离线执行通过 |
| 组合经理评级 | 原生 Portfolio Manager / run_rating | 原生评级、12角色覆盖表 | 离线执行通过；不是下单 |
| 持仓上下文 | 原生 PortfolioContext | 手工持仓JSON、显式模拟持仓快照 | 空仓/未提供区分与映射测试通过 |
| 多供应商与快速/深度模型分层 | 原生 provider registry / create_tier_client | 两层供应商、模型ID和预算设置 | 注册表/配置快照通过；真实供应商未联调 |
| 原生数据商与工具回退 | 原生 data_vendors / tool_vendors | 高级参数，服务端受信配置 | 继续使用源路由，不造替代数据 |
| 中文/多语言输出 | 原生 output_language | 语言设置 | 参数直接传入 |
| 决策记忆与反思 | 原生 TradingMemoryLog / Reflector | 我的记忆、原生分析自动结算 | 持久化和租户隔离离线验证通过 |
| 到期决策结算与区域基准 | 原生 settle_all_pending / benchmark_map | 手动结算任务及原图记忆节点 | 离线返回/反思验证通过；实盘收益未验证 |
| 检查点恢复 | 原生 SqliteSaver、propagate(checkpoint_enabled) | 失败/取消任务手动恢复 | 真实原图中断、恢复少于全量调用的测试通过 |
| 官方HTML/Markdown报告 | graph.save_reports / write_report_tree | 鉴权导出原生报告 | 原始报告文件生成通过 |
| 原生评级回测、单元跳过与独立日志 | run_backtest / summarize | 回测网格，原任务恢复 | 原始API离线执行通过，非资金模拟回测 |
| 原有CLI、Docker和Python API | 原仓库完整源码 | 仍可独立运行上游CLI | CLI源码保留，不强制迁移到产品UI |

## 已纠正的旧适配问题

- v0.1/v0.2的“数据核对”仍是单独轻量工具，绝不冒充TradingAgents。
- 不再把原生记忆和检查点放入结束即删除的临时目录。
- 报告不再只摘取四个字段或截断为30000字符；按原仓库报告目录展示所有角色输出。
- 沪市产品代码.SH转换为上游Yahoo使用的.SS，原生基准和公司身份解析仍由上游负责。
- 原生研究可以直接按代码/日期调用上游，不强制先下载CSV或日线文件。

## 验证含义

23项产品测试通过；另有204项选取的原仓库核心测试通过。
产品图集成测试仅替换外部模型与供应商响应，实际运行原仓库代理节点、讨论、工具路由、
记忆、检查点、回测和报告生成。该测试夹具仅在tests下，不进入生产引擎。
这不代表真实LLM供应商、真实新闻/财务数据和A股策略表现已验证。
没有真实API凭据时，页面明确显示未配置，不静默切换到轻量计算或虚构角色发言。

原仓库本身也有边界：历史评级评分不等于完整投资组合成交模拟；部分A股基本面、
历史新闻和情绪来源可能不可用。不能通过补写报告隐藏这些限制。

### v0.3.3 外部协议适配边界

product/server/provider_compat.py 在任务子进程中临时使用DeepSeek客户端子类，
将SDK输出的assistant content=null转为空字符串，其余报文不变；退出后恢复注册表。
这是产品的供应商协议适配，不替换任何分析代理、提示词或决策流程，93个原文件仍校验一致。
模型协议自检是独立辅助任务，不冒充多代理分析或行情验证。
