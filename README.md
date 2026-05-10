# tail_strategy_qmt

基于国金 QMT / xtquant 的 A 股尾盘趋势确认策略辅助系统。

当前仓库已落地项目骨架、QMT 数据接入、本地 Parquet 缓存、SQLite、股票池、日线特征、规则候选、尾盘分钟线确认、信号落库、基础风控决策、每日报告流水线、基础持仓状态机、轻量离线回测、自动下单前风控闸门、QMT 自动委托边界、交易循环监控和机器学习研究数据集。

## 当前边界

- 当前支持自动生成订单草稿，并按 `paper` / `live` 模式走模拟提交或 QMT 提交边界。
- 所有 `xtquant` 相关代码隔离在 `src/qmt/`。
- 策略参数放在 `config/*.yaml`，业务代码不硬编码策略阈值。
- 持仓、交易记录、策略信号、同步状态使用 SQLite。
- 本地行情缓存使用 Parquet。
- 策略层不能直接调用 QMT / xtquant。

## 目录

```text
config/
data/
  raw/
  processed/
  parquet/
  database/
src/
  qmt/
  storage/
  data_layer/
  features/
  strategy/
  position/
  trading/
  backtest/
  ml/
  reports/
  utils/
tests/
outputs/
scripts/
```

## 安装

如果使用现有 Conda 环境：

```powershell
conda activate stock
python -m pip install -e ".[dev]"
```

如果需要新建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

如果当前机器需要连接 QMT，请另外确保国金 QMT 客户端和 `xtquant` Python 包可用。没有 QMT 环境时，基础测试仍应可以运行。

## 初始化数据库

```powershell
python -m scripts.init_db
```

默认数据库路径来自 `config/data_source.yaml`：

```text
data/database/tail_strategy.db
```

## 运行测试

```powershell
conda activate stock
pytest
```

## 同步历史行情

在 QMT 客户端和 `xtquant` 可用时，可以先同步少量股票验证数据管道：

```powershell
conda activate stock
python -m scripts.sync_history --symbols 000001.SZ,600000.SH --period daily --start-date 20240101 --end-date 20240501
```

分钟线示例：

```powershell
python -m scripts.sync_history --symbols 000001.SZ --period minute --start-date 20240501 --end-date 20240501
```

默认会把新数据与已有 Parquet 缓存合并并按 `symbol + date/datetime` 去重；如需覆盖缓存，追加 `--replace`。

## 每日增量更新

已有缓存后，使用增量同步脚本。脚本会读取每只股票本地 Parquet 的最大日期，自动从下一天开始补齐；已经更新到目标日期的股票会跳过。

```powershell
conda activate stock
python -m scripts.sync_incremental --symbols 000001.SZ,600000.SH --period daily --end-date 20260508 --fallback-start-date 20240101
```

`--fallback-start-date` 只用于没有本地缓存的股票。

## 股票池文件

从 QMT 本地板块数据生成股票池文件：

```powershell
conda activate stock
python -m scripts.build_universe
```

默认读取 `config/universe.yaml`，使用 QMT 的 `沪深A股` 板块，输出到：

```text
data/processed/universe_symbols.txt
```

如需先刷新 QMT 板块分类信息，可以追加 `--refresh-sector-data`。这个动作可能较慢，日常不必每次执行。

之后可以用股票池文件做批量增量同步：

```powershell
python -m scripts.sync_incremental --symbols-file data/processed/universe_symbols.txt --period daily --end-date 20260508 --fallback-start-date 20240101
```

初次验证建议先限制数量：

```powershell
python -m scripts.sync_incremental --symbols-file data/processed/universe_symbols.txt --period daily --end-date 20260508 --fallback-start-date 20240101 --limit 10
```

## 日线特征

从本地日线 Parquet 缓存生成基础特征：

```powershell
conda activate stock
python -m scripts.build_daily_features --symbols-file data/processed/universe_symbols.txt --limit 10
```

默认输出：

```text
data/processed/daily_features.parquet
```

当前特征包括 `ma5/ma10/ma20`、`return_5d/return_20d`、`avg_amount_20d`、`volume_ratio_5d`、`close_position_20d`、`distance_to_ma20`、`upper_shadow_ratio` 等。

## 规则候选股

从日线特征生成规则版候选股：

```powershell
conda activate stock
python -m scripts.build_candidates
```

默认读取：

```text
data/processed/daily_features.parquet
```

默认输出：

```text
data/processed/candidates.parquet
```

这一步只做日线基础筛选和评分，不生成买卖建议，不处理持仓，也不使用机器学习。

如果候选为空，生成诊断文件查看每只股票的落选原因：

```powershell
python -m scripts.build_candidate_diagnostics
```

默认输出：

```text
data/processed/candidate_diagnostics.parquet
data/processed/candidate_reason_summary.csv
```

## 每日报告

生成 Markdown 和 CSV 日报：

```powershell
conda activate stock
python -m scripts.build_daily_report
```

默认输出：

```text
outputs/daily_report.md
outputs/daily_report.csv
```

日报会汇总候选股、落选原因和最近的数据同步状态；即使当天候选为空，也会输出诊断信息。

## 一键日常流水线

每天可以用一个命令串起增量同步、特征、候选、诊断、信号、风控决策和报告：

```powershell
conda activate stock
python -m scripts.run_daily_pipeline --symbols-file data/processed/universe_symbols.txt --end-date 20260508 --fallback-start-date 20240101 --limit 10
```

如果只想用本地缓存离线验证，不连接 QMT：

```powershell
python -m scripts.run_daily_pipeline --symbols-file data/processed/universe_symbols.txt --end-date 20260508 --fallback-start-date 20240101 --limit 10 --skip-sync
```

流水线默认会额外生成：

```text
data/processed/signals.parquet
data/processed/decisions.parquet
outputs/decision_report.md
outputs/decision_report.csv
```

如果当天还没有生成 `data/processed/tail_confirmation.parquet`，信号会自动降级为观察，不会直接给 `OPEN_POSITION`。

## 尾盘分钟线确认

先同步目标日期分钟线：

```powershell
python -m scripts.sync_history --symbols 000001.SZ --period minute --start-date 20260508 --end-date 20260508
```

再生成尾盘确认：

```powershell
python -m scripts.build_tail_confirmation --symbols 000001.SZ --date 20260508
```

默认输出：

```text
data/processed/tail_confirmation.parquet
```

尾盘确认会计算 `14:30-15:00`、`14:45-15:00` 涨幅，以及尾盘成交量占全天比例，并按 `config/strategy.yaml` 中的 `intraday` 阈值给出 `tail_confirmed` 和失败原因。

## 持仓状态机

基础持仓状态机封装在 `src/position/`，当前支持开仓、状态标记、一次加仓、减仓和平仓，并把动作写入 SQLite `positions` / `trades` 表。它只记录和管理策略辅助决策，不会自动下单。

## 信号落库

候选股和尾盘确认都准备好以后，可以生成策略信号并写入 SQLite `signals` 表：

```powershell
conda activate stock
python -m scripts.build_signals --date 20260508
```

默认输入：

```text
data/processed/candidates.parquet
data/processed/tail_confirmation.parquet
```

默认输出：

```text
data/processed/signals.parquet
data/database/tail_strategy.db
```

信号动作当前只有辅助含义：`OPEN` 表示候选股和尾盘确认均通过，`WATCH` 表示继续观察，`SKIP` 表示尾盘确认失败。脚本会覆盖同一日期、同一策略版本的旧信号，重复运行不会产生重复记录。

## 风控决策

信号生成后，可以结合当前持仓生成每日操作建议：

```powershell
conda activate stock
python -m scripts.build_decisions --date 20260508
```

默认读取 SQLite 中的 `signals` 和 `positions`，输出：

```text
data/processed/decisions.parquet
data/database/tail_strategy.db
```

当前决策动作仍是辅助建议：`OPEN_POSITION`、`HOLD_POSITION`、`WATCH_POSITION`、`REDUCE_POSITION`、`WATCH_SIGNAL`、`SKIP_SIGNAL`。规则会限制总持仓数量和单日新开数量，并避免对已有持仓重复开仓。

## 下单前自动风控

生成 `decisions` 后，可以自动生成订单草稿、执行下单前风控，并提交通过的订单。默认 `trading.mode: paper`，只模拟提交：

```powershell
conda activate stock
python -m scripts.run_pre_trade --date 20260508
```

默认读取 SQLite `decisions`、当前 `positions` 和本地日线缓存，写入：

```text
data/database/tail_strategy.db
outputs/pre_trade_report.md
```

风控闸门会自动检查重复持仓、单笔仓位、组合总仓位、持仓数量、涨跌停和行情缺失等条件。通过的订单在 `paper` 模式下会标记为 `PAPER_SUBMITTED`；在 `live` 模式下会调用 QMT 交易适配器并标记为 `SUBMITTED` 或 `REJECTED`，同时写入 `broker_orders`。被拦截的订单会标记为 `BLOCKED` 并记录原因。重复运行不会重复提交已经提交过的订单。

如只想生成订单草稿和检查结果，不模拟提交：

```powershell
python -m scripts.run_pre_trade --date 20260508 --no-submit
```

切换真实委托前，需要在 `config/strategy.yaml` 设置：

```yaml
trading:
  mode: live
  order_value_base: 100000
  qmt:
    trader_path: "QMT userdata path"
    account_id: "your account id"
```

`BUY` 委托数量会按 `order_value_base * position_ratio / reference_price` 计算并按 100 股取整；`SELL` 委托会读取 QMT 持仓可用数量。建议先保留 `mode: paper` 跑通报告和状态，再切 `live`。

## QMT 委托成交同步

真实委托发出后，可以同步 QMT 的委托和成交回报：

```powershell
conda activate stock
python -m scripts.sync_broker_executions --date 20260508
```

默认会更新：

```text
broker_orders
broker_fills
```

如果希望在委托完全成交后同步更新本地 `positions` / `trades`，可以追加：

```powershell
python -m scripts.sync_broker_executions --date 20260508 --apply-positions
```

成交回写带有幂等记录：同一笔成交重复查询不会重复写入 `broker_fills`，同一个已成交委托重复同步也不会重复开仓或重复平仓。

## 日内交易循环

也可以用一个脚本串起下单前风控、提交订单和同步回报：

```powershell
conda activate stock
python -m scripts.run_trading_cycle --date 20260508 --apply-positions
```

执行顺序为：

```text
run_pre_trade
sync_broker_executions
optional apply positions
```

默认会同时生成：

```text
outputs/pre_trade_report.md
outputs/trading_cycle_report.md
```

在 `paper` 模式下，脚本只会模拟提交，不会连接 QMT，也不会执行 broker sync。在 `live` 模式下，脚本会使用 QMT trader 提交订单，并按 `--sync-attempts` / `--sync-interval-seconds` 同步回报。若只想做风控检查但不提交：

```powershell
python -m scripts.run_trading_cycle --date 20260508 --no-submit
```

## QMT 交易接口边界

真实自动委托的接口边界已经隔离在 `src/qmt/`，包括下单、撤单、查询委托、查询成交和查询持仓的协议模型，以及 `XtQuantTraderAdapter`。它会延迟导入 `xtquant`，没有 QMT 环境时不会影响普通测试。

委托和成交回写会落到 SQLite：

```text
broker_orders
broker_fills
broker_order_applications
broker_fill_applications
```

当前版本已经支持把 `READY` 订单接到 QMT live 提交器，并同步委托/成交回报。开启 `--apply-positions` 后，成交会按 `broker_fills` 逐笔增量应用到本地持仓，支持 `PARTIAL_FILLED` 和 `FILLED` 两种状态；`broker_fill_applications` 用于保证同一笔成交不会重复开仓、加仓或减仓。

成交后可以复核本地持仓和 QMT 当前持仓是否一致：

```powershell
conda activate stock
python -m scripts.reconcile_positions
```

默认输出：

```text
outputs/position_reconciliation.md
```

复核逻辑当前以“本地是否有未关闭持仓、QMT 是否有对应持仓”为主：两边都有则 `MATCH`，本地有但券商无则 `MISSING_BROKER`，券商有但本地无则 `MISSING_LOCAL`。仓位比例和券商股数单位不同，后续如接入账户总资产和实时市值，可再做更严格的比例偏差校验。

## 应用决策到本地持仓

确认 `decisions` 没问题后，可以把指定日期的决策应用到本地持仓状态机：

```powershell
conda activate stock
python -m scripts.apply_decisions --date 20260508
```

脚本会读取 SQLite `decisions`、本地日线缓存 `data/parquet/daily/*.parquet`，并把结果写入：

```text
data/database/tail_strategy.db
```

应用规则只更新本地 `positions`、`trades` 和 `decision_applications` 表，不会连接真实交易接口。`OPEN_POSITION` 会按决策日收盘价本地记账开仓，并把仓位限制在 `position.max_single_stock_ratio` 内；`HOLD_POSITION` / `WATCH_POSITION` 会标记持仓状态；`REDUCE_POSITION` 会按决策日收盘价本地减到 0。`WATCH_SIGNAL` 和 `SKIP_SIGNAL` 不改变持仓。

可以先预览不落库：

```powershell
python -m scripts.apply_decisions --date 20260508 --dry-run
```

脚本会记录每条决策的应用结果，重复运行已经成功应用或跳过的决策不会重复写交易。失败的决策会保留失败原因，修复日线缓存等问题后可以再次运行。

## 轻量回测

可以基于 `OPEN_POSITION` 决策和本地日线缓存运行一个基础离线回测：

```powershell
conda activate stock
python -m scripts.run_backtest --start-date 20240101 --end-date 20260508
```

默认读取：

```text
data/processed/decisions.parquet
data/parquet/daily/*.parquet
```

默认输出：

```text
outputs/backtest_trades.parquet
outputs/backtest_summary.csv
outputs/backtest_equity_curve.csv
outputs/backtest_report.md
```

当前回测假设为：决策日之后第一个交易日开盘买入，然后逐日检查 `backtest.exit.stop_loss_pct` 和 `backtest.exit.take_profit_pct`，触发后按阈值价退出；如果未触发，则持有 `backtest.holding_days` 指定的交易日数后收盘卖出。由于日线无法判断同一天高低点先后顺序，如果止损和止盈同日触发，会按更保守的止损处理。回测会按 `backtest.cost` 扣减滑点、佣金和卖出印花税，同时保留 `gross_return` 与 `net_return`。`backtest.limit` 会近似处理涨跌停：开盘接近涨停时跳过买入，卖出日接近跌停时延后到后续可卖日期。`backtest.portfolio` 会限制组合总仓位和并发持仓数量，超出限制的新交易会跳过并计入 `portfolio_skipped_count`。权益曲线会在持仓期间用日线收盘价估算浮盈浮亏，退出日使用最终 `weighted_net_return`，并计算复合收益和最大回撤。它用于快速评估信号方向，不包含真实撮合、盘口排队和复杂资金再分配。

## 回测参数扫描

可以批量比较不同持有天数、止损、止盈和总仓位上限：

```powershell
conda activate stock
python -m scripts.run_backtest_sweep --start-date 20240101 --end-date 20260508
```

默认输出：

```text
outputs/backtest_sweep.csv
outputs/backtest_sweep_report.md
```

也可以手动指定参数网格：

```powershell
python -m scripts.run_backtest_sweep --holding-days 3,5,8 --stop-loss 0.03,0.05 --take-profit 0.08,0.12 --max-gross-exposure 0.6,0.8,1.0
```

扫描结果会按 `score`、`compounded_return`、`max_drawdown` 和 `win_rate` 排序。`score` 是一个简单综合评分，只用于快速筛选参数组合，最终仍建议看交易数、回撤和收益稳定性。Markdown 摘要会列出最佳参数和 Top 组合，方便直接查看。

## 机器学习研究数据集

规则版可以先跑，机器学习层用于后续研究和筛选增强。先从日线特征生成带标签的数据集：

```powershell
conda activate stock
python -m scripts.build_ml_dataset --horizon-days 5 --min-forward-return 0.03
```

默认读取：

```text
data/processed/daily_features.parquet
```

默认输出：

```text
data/processed/ml_dataset.parquet
```

如果只想基于规则候选股训练，可以加候选文件：

```powershell
python -m scripts.build_ml_dataset --candidates data/processed/candidates.parquet --horizon-days 5 --min-forward-return 0.03
```

标签含义：`forward_return >= min_forward_return` 记为 `label=1`，否则为 `0`。当前只负责产出稳定训练数据，不在实盘链路里直接使用模型下单。

## 交易循环调度与监控

每次运行 `run_trading_cycle` 都会写入 SQLite 表：

```text
trading_cycle_runs
```

其中会记录运行日期、模式、状态、耗时、订单草稿数、提交数、回报同步次数、成交写入数和持仓回写数。可以随时生成最近运行监控报告：

```powershell
conda activate stock
python -m scripts.build_trading_run_report
```

默认输出：

```text
outputs/trading_run_monitor.md
```

如果要交给 Windows 任务计划程序调用，建议使用 scheduled 入口，日期默认取当天：

```powershell
conda activate stock
python -m scripts.run_trading_cycle_scheduled --skip-weekend --no-submit
```

实盘自动提交时去掉 `--no-submit`，并按需要开启：

```powershell
python -m scripts.run_trading_cycle_scheduled --skip-weekend --apply-positions --sync-attempts 3 --sync-interval-seconds 20
```

这个入口会在正常交易循环后自动刷新 `outputs/trading_run_monitor.md`；如果周末加了 `--skip-weekend`，会记录一条 `SKIPPED`，但不会下单。

可以先复制 live 配置模板，再填 QMT 路径、资金基准和账号：

```powershell
Copy-Item config/strategy.live.example.yaml config/strategy.live.yaml
```

生成 Windows 任务计划程序命令：

```powershell
python -m scripts.print_windows_task_commands --strategy-config config/strategy.live.yaml
```

默认生成的是 `--no-submit` 演练任务。确认无误后，才生成真实提交任务：

```powershell
python -m scripts.print_windows_task_commands --strategy-config config/strategy.live.yaml --submit --apply-positions
```

任务计划程序里还可以在交易循环后追加一个健康检查步骤，让失败状态直接反映成非零退出码：

```powershell
python -m scripts.check_trading_run_health --today --max-age-hours 12 --fail-on-warn
```

默认输出：

```text
outputs/trading_run_health.md
```

如果周末允许 `SKIPPED`，可以加：

```powershell
python -m scripts.check_trading_run_health --today --allow-skipped
```

## QMT 实盘前 Smoke Test

真正打开自动提交前，先跑安全检查。默认只检查配置、SQLite 和本地目录，不连接 QMT：

```powershell
conda activate stock
python -m scripts.qmt_smoke_test
```

在装有 QMT/xtquant 的交易电脑上，可以加 `--connect`，它只会连接并查询持仓、委托、成交，不会提交订单：

```powershell
python -m scripts.qmt_smoke_test --connect
```

默认输出：

```text
outputs/qmt_smoke_test.md
```

如果报告里有 `FAIL`，先处理失败项；如果只有 `WARN`，通常表示某些可选项还没跑过或当前没有连接检查。

## 上线就绪总报告

可以生成一张总检查表，把配置、数据库、smoke test、运行健康检查和关键报告产物收拢到一起：

```powershell
conda activate stock
python -m scripts.build_readiness_report
```

默认输出：

```text
outputs/readiness_report.md
```

上线前更严格地检查 live 配置和最近运行记录：

```powershell
python -m scripts.build_readiness_report --require-live-config --require-recent-run --fail-on-warn
```

默认模式会把“还没演练、还没生成某些报告”标成 `WARN`；严格模式适合正式切到自动运行前使用。

## Web 控制台

如果不想记命令，可以启动本地 Web 控制台：

```powershell
conda activate stock
python -m scripts.run_web_console
```

然后在浏览器打开：

```text
http://127.0.0.1:8765
```

控制台目前提供：

- QMT 配置检查
- 上线就绪报告
- 运行监控报告
- 运行健康检查
- 交易循环 `--no-submit` 演练
- Windows 任务计划命令生成
- Live 交易循环入口

红色 Live 入口会要求二次确认。正式实盘前，建议先用按钮跑完 QMT 检查、上线就绪报告和 `--no-submit` 演练。

## 全流程体检

完整跑完数据、信号、决策、报告和回测后，可以生成一份本地体检报告：

```powershell
conda activate stock
python -m scripts.validate_pipeline --date 20260508 --symbols-file data/processed/universe_symbols.txt --limit 10
```

默认输出：

```text
outputs/pipeline_validation.md
```

体检会检查核心 Parquet 输出、SQLite 表和日期行数、日报/操作建议报告、回测摘要、日线缓存是否存在。结果分为 `PASS`、`WARN`、`FAIL`：缺核心文件或表是失败；候选为空、尾盘确认缺失、回测文件缺失等会先标为警告，方便定位还没跑的步骤。

## 阶段 1 已提供的代码

- `src/utils/config.py`：配置加载。
- `src/utils/logging.py`：日志初始化。
- `src/storage/sqlite.py`：SQLite schema 和初始化。
- `src/storage/parquet.py`：Parquet 路径、字段校验和读写接口。
- `src/qmt/client.py`：QMT 数据客户端协议。
- `src/qmt/xtquant_adapter.py`：xtquant 适配器，延迟导入，避免污染非 QMT 环境。
- `src/qmt/trader.py`：QMT 交易协议、订单、成交和持仓快照模型。
- `src/qmt/xtquant_trader_adapter.py`：真实 xtquant 交易适配器边界。
- `src/data_layer/sync.py`：历史数据同步编排骨架。
- `src/data_layer/universe.py`：股票池构建与基础代码过滤。
- `scripts/build_universe.py`：从 QMT 板块生成本地股票池文件。
- `scripts/sync_history.py`：QMT 历史行情同步入口。
- `scripts/sync_incremental.py`：基于本地缓存最大日期的增量同步入口。
- `scripts/build_daily_features.py`：从日线缓存生成基础特征。
- `scripts/build_candidates.py`：从日线特征生成规则版候选列表。
- `scripts/build_candidate_diagnostics.py`：生成候选筛选诊断和落选原因汇总。
- `scripts/build_daily_report.py`：生成 Markdown 和 CSV 每日报告。
- `scripts/run_daily_pipeline.py`：一键执行日常数据、特征、候选、诊断、信号、决策和报告流水线。
- `scripts/build_tail_confirmation.py`：从分钟线缓存生成尾盘确认结果。
- `scripts/build_signals.py`：从候选股和尾盘确认生成信号并写入 SQLite。
- `scripts/build_decisions.py`：从信号和当前持仓生成每日风控决策。
- `scripts/run_pre_trade.py`：生成订单草稿、执行下单前风控，并按 paper/live 模式提交。
- `scripts/sync_broker_executions.py`：同步 QMT 委托/成交回报，并可按成交更新本地持仓。
- `scripts/run_trading_cycle.py`：串起下单前风控、提交订单和 broker 回报同步。
- `scripts/apply_decisions.py`：把风控决策应用到本地持仓状态机。
- `scripts/run_backtest.py`：基于风控决策和本地日线缓存运行轻量回测。
- `scripts/run_backtest_sweep.py`：批量扫描回测参数组合并生成 Markdown 摘要。
- `scripts/validate_pipeline.py`：检查本地全流程产物和 SQLite 状态。
- `src/strategy/signals.py`：信号构建、建议动作和信号 SQLite 仓储。
- `src/strategy/decisions.py`：基础风控决策构建和决策 SQLite 仓储。
- `src/strategy/apply_decisions.py`：决策应用、幂等记录和持仓状态机衔接。
- `src/trading/pre_trade.py`：订单草稿、自动风控闸门和提交编排。
- `src/trading/submitter.py`：paper/live 订单提交器。
- `src/trading/execution.py`：券商委托和成交 SQLite 仓储。
- `src/trading/sync.py`：QMT 委托/成交同步和成交后持仓回写。
- `src/trading/cycle.py`：日内交易循环编排。
- `src/backtest/simple.py`：轻量决策回测引擎。
- `src/backtest/sweep.py`：回测参数扫描和摘要报告渲染。
- `src/validation/pipeline.py`：本地流水线产物体检。
- `src/reports/decisions.py`：生成面向人工查看的操作建议报告。
- `src/position/models.py`：持仓状态、动作和交易记录模型。
- `src/position/repository.py`：持仓和交易记录 SQLite 仓储。
- `src/position/service.py`：基础持仓状态转换服务。

## 下一阶段建议

下一步建议在真实 QMT 环境复制 `config/strategy.live.example.yaml` 为 `config/strategy.live.yaml` 并填好账号，再跑 `scripts.qmt_smoke_test --connect` 和一次 `scripts.run_trading_cycle_scheduled --no-submit` 演练。
