"""
目標管理モジュール

config/targets.yaml で宣言された数値目標を読み込み、
既存の data/ から現在値を算出する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGETS_YAML = REPO_ROOT / "config" / "targets.yaml"


@dataclass
class TargetSpec:
    key: str
    target: float
    unit: str
    direction: str  # up / down / zero
    review: str     # weekly / monthly / quarterly
    note: str = ""


@dataclass
class TargetProgress:
    spec: TargetSpec
    current: Optional[float]
    period_label: str         # 例: "2026-W20 (Mon-Sun)" / "latest"
    detail: str = ""          # 補足情報（任意）

    @property
    def remaining(self) -> Optional[float]:
        """目標までの残差（正=未達, 負=超過達成）。"""
        if self.current is None:
            return None
        d = self.spec.direction
        if d == "up":
            return self.spec.target - self.current
        if d == "down":
            return self.current - self.spec.target
        if d == "zero":
            return self.current
        return None

    @property
    def achieved(self) -> Optional[bool]:
        r = self.remaining
        if r is None:
            return None
        return r <= 0


def load_specs(path: Path = TARGETS_YAML) -> list[TargetSpec]:
    with path.open() as f:
        data = yaml.safe_load(f)
    return [
        TargetSpec(
            key=t["key"],
            target=float(t["target"]),
            unit=t.get("unit", ""),
            direction=t["direction"],
            review=t["review"],
            note=t.get("note", ""),
        )
        for t in data.get("targets", [])
    ]


# ----- evaluators -----

def _week_bounds(today: date) -> tuple[date, date]:
    """ISO週(月曜起点)の月曜と当日を返す。"""
    monday = today - timedelta(days=today.weekday())
    return monday, today


def eval_ffmi(spec: TargetSpec, today: date) -> TargetProgress:
    from .analytics.body import calc_ffmi, DEFAULT_HEIGHT_CM

    csv = REPO_ROOT / "data" / "healthplanet_innerscan.csv"
    df = pd.read_csv(csv, parse_dates=["date"])
    df = df.dropna(subset=["weight", "body_fat_rate"]).sort_values("date")
    if df.empty:
        return TargetProgress(spec, None, "no-data")
    df["lbm"] = df["weight"] * (1 - df["body_fat_rate"] / 100)
    df = calc_ffmi(df, DEFAULT_HEIGHT_CM)
    latest = df.iloc[-1]
    return TargetProgress(
        spec,
        current=round(float(latest["ffmi"]), 2),
        period_label=f"latest ({latest['date'].date()})",
        detail=f"weight={latest['weight']:.1f}kg, bf={latest['body_fat_rate']:.1f}%",
    )


def eval_sleep_debt_h(spec: TargetSpec, today: date) -> TargetProgress:
    from .analytics.sleep.sleep_debt_clean import SleepDebtCalculator

    SLEEP_NEED_FOR_DEBT = 7.75  # scripts/generate_sleep_report_daily.py と同値
    csv = REPO_ROOT / "data" / "fitbit" / "sleep.csv"
    df = pd.read_csv(csv, parse_dates=["dateOfSleep"])
    df = df.sort_values("dateOfSleep")
    if df.empty or len(df) < 7:
        return TargetProgress(spec, None, "no-data")
    # 主睡眠+昼寝を合算した日別総睡眠（既存スクリプトと同じ前処理）
    daily = df.groupby("dateOfSleep", as_index=False).agg({"minutesAsleep": "sum"})
    full_range = pd.date_range(daily["dateOfSleep"].min(), daily["dateOfSleep"].max())
    daily = (
        daily.set_index("dateOfSleep").reindex(full_range, fill_value=0)
        .rename_axis("dateOfSleep").reset_index()
    )
    calc = SleepDebtCalculator(
        sleep_data=daily,
        sleep_need_hours=SLEEP_NEED_FOR_DEBT,
        window_days=14,
        min_data_points=5,
        rise_last_night_ratio=0.20,
    )
    result = calc.calculate()
    return TargetProgress(
        spec,
        current=round(float(result.sleep_debt_hours), 2),
        period_label=f"as of {result.date.date()}",
        detail=f"avg={result.avg_sleep_hours}h, category={result.category}",
    )


def eval_zone2_min_weekly(spec: TargetSpec, today: date) -> TargetProgress:
    csv = REPO_ROOT / "data" / "fitbit" / "active_zone_minutes.csv"
    df = pd.read_csv(csv, parse_dates=["date"])
    monday, end = _week_bounds(today)
    mask = (df["date"].dt.date >= monday) & (df["date"].dt.date <= end)
    week = df.loc[mask]
    current = float(week["fatBurnActiveZoneMinutes"].fillna(0).sum())
    iso_year, iso_week, _ = today.isocalendar()
    return TargetProgress(
        spec,
        current=round(current, 1),
        period_label=f"{iso_year}-W{iso_week:02d} ({monday}〜{end})",
        detail=f"{(end - monday).days + 1}日経過 / 週7日",
    )


EVALUATORS: dict[str, Callable[[TargetSpec, date], TargetProgress]] = {
    "ffmi": eval_ffmi,
    "sleep_debt_h": eval_sleep_debt_h,
    "zone2_min_weekly": eval_zone2_min_weekly,
}


def evaluate(
    interval: Optional[str] = None,
    today: Optional[date] = None,
    specs: Optional[list[TargetSpec]] = None,
) -> list[TargetProgress]:
    """指定intervalの目標を評価。interval=None で全件。"""
    if today is None:
        today = datetime.now().date()
    if specs is None:
        specs = load_specs()
    results: list[TargetProgress] = []
    for spec in specs:
        if interval and spec.review != interval:
            continue
        evaluator = EVALUATORS.get(spec.key)
        if evaluator is None:
            results.append(TargetProgress(spec, None, "no-evaluator"))
            continue
        try:
            results.append(evaluator(spec, today))
        except Exception as e:
            results.append(TargetProgress(spec, None, f"error: {e}"))
    return results
