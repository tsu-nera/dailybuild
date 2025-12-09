#!/usr/bin/env python3
"""Build meditation log dashboard.

Reads CSV data and generates a static HTML dashboard with Chart.js.
Supports both Muse EEG and Fitbit meditation data.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


def load_muse_meditation_log(csv_path: Path) -> list[dict]:
    """Load Muse EEG meditation log from CSV file.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dictionaries containing meditation data with source='muse'.
    """
    if not csv_path.exists():
        return []

    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(
                {
                    "timestamp": row["timestamp"],
                    "duration_min": float(row["duration_min"]),
                    "alpha_mean": float(row["alpha_mean"]),
                    "beta_mean": float(row["beta_mean"]),
                    "iaf_mean": float(row["iaf_mean"]),
                    "fm_theta_mean": float(row["fm_theta_mean"]),
                    "theta_alpha_mean": float(row["theta_alpha_mean"]),
                    "source": "muse",
                }
            )
    return data


def load_fitbit_meditation_log(csv_path: Path) -> list[dict]:
    """Load Fitbit meditation log from CSV file.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dictionaries containing meditation data with source='fitbit'.
    """
    if not csv_path.exists():
        return []

    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            avg_hr = row.get("average_hr")
            data.append(
                {
                    "timestamp": row["timestamp"],
                    "duration_min": float(row["duration_min"]),
                    "average_hr": float(avg_hr) if avg_hr else None,
                    "source": "fitbit",
                }
            )
    return data


def normalize_timestamp(ts: str) -> str:
    """Normalize timestamp to ISO format (YYYY-MM-DD HH:MM:SS).

    Args:
        ts: Timestamp string in various formats.

    Returns:
        Normalized timestamp string.
    """
    # Try parsing various formats
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z"]:
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # Return as-is if no format matches
    return ts


def merge_meditation_data(muse_data: list[dict], fitbit_data: list[dict]) -> list[dict]:
    """Merge Muse EEG and Fitbit meditation data.

    Args:
        muse_data: List of Muse EEG meditation records.
        fitbit_data: List of Fitbit meditation records.

    Returns:
        Combined list sorted by timestamp.
    """
    combined = muse_data + fitbit_data
    # Normalize timestamps for consistent sorting and display
    for record in combined:
        record["timestamp"] = normalize_timestamp(record["timestamp"])
    combined.sort(key=lambda x: x["timestamp"])
    return combined


def generate_html(data: list[dict]) -> str:
    """Generate HTML dashboard with embedded data.

    Args:
        data: List of meditation data dictionaries.

    Returns:
        HTML string.
    """
    data_json = json.dumps(data)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>禅定波羅蜜ダッシュボード</title>
    <link rel="stylesheet" href="../static/dashboard.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h1>禅定波羅蜜ダッシュボード</h1>

    <!-- Metric Group & Period Selection -->
    <div class="controls">
        <select id="metricGroup" onchange="setMetricGroup(this.value)">
            <option value="duration">Duration</option>
            <option value="power">Power (Alpha/Beta)</option>
            <option value="iaf">IAF</option>
            <option value="focus">Focus (FM Theta/Theta-Alpha)</option>
        </select>
        <button id="btn1W" class="active" onclick="setPeriod('1w')">1 Week</button>
        <button id="btn1M" onclick="setPeriod('1m')">1 Month</button>
        <button id="btn3M" onclick="setPeriod('3m')">3 Months</button>
        <button id="btnAll" onclick="setPeriod('all')">All</button>
    </div>
    <div class="chart-container">
        <h2>Daily View</h2>
        <canvas id="dailyChart"></canvas>
    </div>

    <!-- Trend View -->
    <div class="controls controls-trend">
        <button id="btnWeekly" class="active" onclick="setAggregation('weekly')">Weekly</button>
        <button id="btnMonthly" onclick="setAggregation('monthly')">Monthly</button>
        <span style="margin: 0 10px; color: #999;">|</span>
        <button id="btnHours" class="active" onclick="setUnit('hours')">Hours</button>
        <button id="btnChu" onclick="setUnit('chu')">炷</button>
    </div>
    <div class="chart-container">
        <h2>Trend View</h2>
        <canvas id="trendChart"></canvas>
    </div>

    <script>
        // Dashboard configuration with data
        window.dashboardConfig = {{
            rawData: {data_json},
            title: "禅定波羅蜜ダッシュボード"
        }};
    </script>
    <script src="../static/dashboard.js"></script>
</body>
</html>
"""
    return html


def main():
    """Main function to build the dashboard."""
    project_root = Path(__file__).parent.parent
    muse_csv_path = project_root / "data" / "meditation_log.csv"
    fitbit_csv_path = project_root / "data" / "meditation_fitbit.csv"
    output_dir = project_root / "web" / "meditation"
    output_path = output_dir / "index.html"

    # Create output directory
    output_dir.mkdir(exist_ok=True)

    # Load Muse EEG data
    print(f"Loading Muse EEG data from {muse_csv_path}")
    muse_data = load_muse_meditation_log(muse_csv_path)
    print(f"Loaded {len(muse_data)} Muse EEG records")

    # Load Fitbit data
    print(f"Loading Fitbit data from {fitbit_csv_path}")
    fitbit_data = load_fitbit_meditation_log(fitbit_csv_path)
    print(f"Loaded {len(fitbit_data)} Fitbit records")

    # Merge data
    data = merge_meditation_data(muse_data, fitbit_data)
    print(f"Total: {len(data)} records")

    # Generate HTML
    html = generate_html(data)

    # Write output
    output_path.write_text(html, encoding="utf-8")
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
