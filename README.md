# tail_strategy_qmt

基于国金 QMT / xtquant 的 A 股尾盘趋势确认策略辅助系统。

当前仓库已落地项目骨架、QMT 数据接入、本地 Parquet 缓存、SQLite、股票池、日线特征、规则候选、尾盘分钟线确认、信号落库、基础风控决策、每日报告流水线、基础持仓状态机和轻量离线回测。机器学习、自动交易暂不实现。

## 当前边界

- 初期只输出辅助决策，不自动下单。
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

当前回测假设为：决策日之后第一个交易日开盘买入，然后逐日检查 `backtest.exit.stop_loss_pct` 和 `backtest.exit.take_profit_pct`，触发后按阈值价退出；如果未触发，则持有 `backtest.holding_days` 指定的交易日数后收盘卖出。由于日线无法判断同一天高低点先后顺序，如果止损和止盈同日触发，会按更保守的止损处理。回测会按 `backtest.cost` 扣减滑点、佣金和卖出印花税，同时保留 `gross_return` 与 `net_return`。`backtest.limit` 会近似处理涨跌停：开盘接近涨停时跳过买入，卖出日接近跌停时延后到后续可卖日期。权益曲线按交易退出日确认收益，把同日退出交易的 `weighted_net_return` 聚合为当日组合收益，并计算复合收益和最大回撤。它用于快速评估信号方向，不包含真实撮合、盘口排队和每日持仓盯市。

## 阶段 1 已提供的代码

- `src/utils/config.py`：配置加载。
- `src/utils/logging.py`：日志初始化。
- `src/storage/sqlite.py`：SQLite schema 和初始化。
- `src/storage/parquet.py`：Parquet 路径、字段校验和读写接口。
- `src/qmt/client.py`：QMT 数据客户端协议。
- `src/qmt/xtquant_adapter.py`：xtquant 适配器，延迟导入，避免污染非 QMT 环境。
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
- `scripts/run_backtest.py`：基于风控决策和本地日线缓存运行轻量回测。
- `src/strategy/signals.py`：信号构建、建议动作和信号 SQLite 仓储。
- `src/strategy/decisions.py`：基础风控决策构建和决策 SQLite 仓储。
- `src/backtest/simple.py`：轻量决策回测引擎。
- `src/reports/decisions.py`：生成面向人工查看的操作建议报告。
- `src/position/models.py`：持仓状态、动作和交易记录模型。
- `src/position/repository.py`：持仓和交易记录 SQLite 仓储。
- `src/position/service.py`：基础持仓状态转换服务。

## 下一阶段建议

下一步建议补充更细的组合再平衡和每日持仓盯市，让回测更接近真实资金占用。自动交易仍建议最后再接。
