#!/usr/bin/env python3
"""Build meditation log dashboard.

Reads CSV data and generates a static HTML dashboard with Chart.js.
"""

import csv
import json
from pathlib import Path


def load_meditation_log(csv_path: Path) -> list[dict]:
    """Load meditation log from CSV file.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dictionaries containing meditation data.
    """
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
                }
            )
    return data


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
    csv_path = project_root / "data" / "meditation_log.csv"
    output_dir = project_root / "web" / "meditation"
    output_path = output_dir / "index.html"

    # Create output directory
    output_dir.mkdir(exist_ok=True)

    # Load data
    print(f"Loading data from {csv_path}")
    data = load_meditation_log(csv_path)
    print(f"Loaded {len(data)} records")

    # Generate HTML
    html = generate_html(data)

    # Write output
    output_path.write_text(html, encoding="utf-8")
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    main()
