from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from data_layer.periods import resolve_period
from data_layer.sync import MarketDataSynchronizer, SyncResult
from features.daily import FeatureBuildResult, build_daily_features
from reports.daily import DailyReportResult, build_daily_report
from storage.parquet import ParquetStorage
from storage.sqlite import SQLiteStore
from strategy.candidates import (
    CandidateBuildResult,
    CandidateDiagnosticsResult,
    build_candidate_diagnostics,
    build_candidates,
)


@dataclass(frozen=True)
class DailyPipelinePaths:
    daily_features: Path = Path("data/processed/daily_features.parquet")
    candidates: Path = Path("data/processed/candidates.parquet")
    diagnostics: Path = Path("data/processed/candidate_diagnostics.parquet")
    reason_summary: Path = Path("data/processed/candidate_reason_summary.csv")
    markdown_report: Path = Path("outputs/daily_report.md")
    csv_report: Path = Path("outputs/daily_report.csv")


@dataclass(frozen=True)
class DailyPipelineResult:
    sync_results: tuple[SyncResult, ...]
    feature_result: FeatureBuildResult
    candidate_result: CandidateBuildResult
    diagnostics_result: CandidateDiagnosticsResult
    report_result: DailyReportResult


def run_daily_pipeline(
    *,
    symbols: Iterable[str],
    data_config: dict[str, object],
    strategy_config: dict[str, object],
    qmt_client: object | None = None,
    end_date: str,
    fallback_start_date: str,
    paths: DailyPipelinePaths = DailyPipelinePaths(),
    skip_sync: bool = False,
) -> DailyPipelineResult:
    symbol_list = list(symbols)
    if not symbol_list:
        raise ValueError("No symbols provided for daily pipeline.")

    storage_config = data_config["storage"]
    qmt_config = data_config["data_source"]["qmt"]
    parquet_storage = ParquetStorage(storage_config["parquet_root"])
    sqlite_store = SQLiteStore(storage_config["sqlite_path"])
    sqlite_store.initialize()

    sync_results: list[SyncResult] = []
    if not skip_sync:
        if qmt_client is None:
            raise ValueError("qmt_client is required unless skip_sync=True.")
        period = resolve_period("daily")
        synchronizer = MarketDataSynchronizer(
            qmt_client=qmt_client,
            parquet_storage=parquet_storage,
            sqlite_store=sqlite_store,
        )
        sync_results = synchronizer.sync_incremental(
            symbols=symbol_list,
            period=period.qmt_period,
            storage_period=period.storage_period,
            end_date=end_date,
            fallback_start_date=fallback_start_date,
            adjust_type=qmt_config.get("adjust_type", "front"),
        )

    feature_result = build_daily_features(
        symbols=symbol_list,
        storage=parquet_storage,
        output_path=paths.daily_features,
    )
    candidate_result = build_candidates(
        features_path=paths.daily_features,
        output_path=paths.candidates,
        strategy_config=strategy_config,
        trade_date=end_date,
    )
    diagnostics_result = build_candidate_diagnostics(
        features_path=paths.daily_features,
        diagnostics_path=paths.diagnostics,
        summary_path=paths.reason_summary,
        strategy_config=strategy_config,
        trade_date=end_date,
    )
    report_result = build_daily_report(
        candidates_path=paths.candidates,
        diagnostics_path=paths.diagnostics,
        reason_summary_path=paths.reason_summary,
        sqlite_path=storage_config["sqlite_path"],
        markdown_path=paths.markdown_report,
        csv_path=paths.csv_report,
        report_date=end_date,
    )
    return DailyPipelineResult(
        sync_results=tuple(sync_results),
        feature_result=feature_result,
        candidate_result=candidate_result,
        diagnostics_result=diagnostics_result,
        report_result=report_result,
    )
