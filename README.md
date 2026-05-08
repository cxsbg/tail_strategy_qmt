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

## 阶段 1 已提供的代码

- `src/utils/config.py`：配置加载。
- `src/utils/logging.py`：日志初始化。
- `src/storage/sqlite.py`：SQLite schema 和初始化。
- `src/storage/parquet.py`：Parquet 路径、字段校验和读写接口。
- `src/qmt/client.py`：QMT 数据客户端协议。
- `src/qmt/xtquant_adapter.py`：xtquant 适配器，延迟导入，避免污染非 QMT 环境。
- `src/data_layer/sync.py`：历史数据同步编排骨架。
- `scripts/sync_history.py`：QMT 历史行情同步入口。

## 下一阶段建议

下一步建议先用 1-2 只股票验证 QMT 数据返回格式，再扩展到股票池批量同步和交易日增量更新。不要在数据管道稳定前引入回测和机器学习。
