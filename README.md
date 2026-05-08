# tail_strategy_qmt

基于国金 QMT / xtquant 的 A 股尾盘趋势确认策略辅助系统。

当前仓库只落地阶段 0 和阶段 1：项目骨架、配置、SQLite、日志、QMT 数据接口抽象、Parquet 存储接口和基础测试。策略、回测、机器学习、自动交易暂不实现。

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

## 下一阶段建议

下一步建议先用 1-2 只股票验证 QMT 数据返回格式，再扩展到股票池批量同步和交易日增量更新。不要在数据管道稳定前引入回测和机器学习。
