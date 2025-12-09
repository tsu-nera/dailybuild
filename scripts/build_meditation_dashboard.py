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
    # Raw data for JS processing (all metrics)
    raw_data = [
        {
            "timestamp": d["timestamp"],
            "duration_min": d["duration_min"],
            "alpha_mean": d["alpha_mean"],
            "beta_mean": d["beta_mean"],
            "iaf_mean": d["iaf_mean"],
            "fm_theta_mean": d["fm_theta_mean"],
            "theta_alpha_mean": d["theta_alpha_mean"],
        }
        for d in data
    ]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>禅定波羅蜜ダッシュボード</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        h1 {{
            text-align: center;
            color: #333;
        }}
        h2 {{
            color: #555;
            font-size: 1.1rem;
            margin-bottom: 10px;
        }}
        .controls {{
            text-align: center;
            margin-bottom: 15px;
        }}
        .controls select {{
            padding: 8px 16px;
            font-size: 14px;
            border: 2px solid #4bc0c0;
            border-radius: 4px;
            background: white;
            cursor: pointer;
            margin-right: 15px;
        }}
        .controls button {{
            padding: 8px 16px;
            margin: 0 5px;
            border: 2px solid #4bc0c0;
            background: white;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        .controls button:hover {{
            background: #e0f7f7;
        }}
        .controls button.active {{
            background: #4bc0c0;
            color: white;
        }}
        .controls-trend button {{
            border-color: #9966ff;
        }}
        .controls-trend button:hover {{
            background: #f0e6ff;
        }}
        .controls-trend button.active {{
            background: #9966ff;
            color: white;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
    </style>
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
        <button id="btn1W" onclick="setPeriod('1w')">1 Week</button>
        <button id="btn1M" onclick="setPeriod('1m')">1 Month</button>
        <button id="btn3M" onclick="setPeriod('3m')">3 Months</button>
        <button id="btnAll" class="active" onclick="setPeriod('all')">All</button>
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
        <button id="btnMinutes" class="active" onclick="setUnit('minutes')">Minutes</button>
        <button id="btnChu" onclick="setUnit('chu')">炷</button>
    </div>
    <div class="chart-container">
        <h2>Trend View</h2>
        <canvas id="trendChart"></canvas>
    </div>

    <script>
        // Raw data from CSV
        const rawData = {json.dumps(raw_data)};

        // Metric group configurations
        const metricGroups = {{
            duration: {{
                metrics: ['duration_min'],
                labels: ['Duration (min)'],
                colors: ['rgb(75, 192, 192)'],
                bgColors: ['rgba(75, 192, 192, 0.2)'],
                yLabel: 'Duration (min)',
                trendLabel: 'Total Duration (min)',
                trendLabelRight: 'Cumulative (min)',
                showCumulativeInTrend: true
            }},
            power: {{
                metrics: ['alpha_mean', 'beta_mean'],
                labels: ['Alpha', 'Beta'],
                colors: ['rgb(54, 162, 235)', 'rgb(255, 99, 132)'],
                bgColors: ['rgba(54, 162, 235, 0.2)', 'rgba(255, 99, 132, 0.2)'],
                yLabel: 'Power (dB)',
                trendLabel: 'Avg Power (dB)'
            }},
            iaf: {{
                metrics: ['iaf_mean'],
                labels: ['IAF'],
                colors: ['rgb(255, 159, 64)'],
                bgColors: ['rgba(255, 159, 64, 0.2)'],
                yLabel: 'Frequency (Hz)',
                trendLabel: 'Avg IAF (Hz)'
            }},
            focus: {{
                metrics: ['fm_theta_mean', 'theta_alpha_mean'],
                labels: ['FM Theta', 'Theta/Alpha'],
                colors: ['rgb(153, 102, 255)', 'rgb(75, 192, 192)'],
                bgColors: ['rgba(153, 102, 255, 0.2)', 'rgba(75, 192, 192, 0.2)'],
                yLabel: 'Ratio',
                trendLabel: 'Avg Ratio'
            }}
        }};

        let currentMetricGroup = 'duration';
        let currentPeriod = 'all';
        let currentAggregation = 'weekly';
        let currentUnit = 'minutes';  // 'minutes' or 'chu' (1炷 = 40min)
        const CHU_MINUTES = 40;
        let dailyChart, trendChart;

        // Filter data by period
        function filterByPeriod(data, period) {{
            if (period === 'all') return data;

            const now = new Date();
            let cutoff;
            switch (period) {{
                case '1w': cutoff = new Date(now - 7 * 24 * 60 * 60 * 1000); break;
                case '1m': cutoff = new Date(now - 30 * 24 * 60 * 60 * 1000); break;
                case '3m': cutoff = new Date(now - 90 * 24 * 60 * 60 * 1000); break;
                default: return data;
            }}

            return data.filter(d => new Date(d.timestamp) >= cutoff);
        }}

        // Aggregate data by week or month
        function aggregateData(data, mode, metrics) {{
            const groups = {{}};

            data.forEach(d => {{
                const date = new Date(d.timestamp);
                let key;

                if (mode === 'weekly') {{
                    // Calculate ISO week number
                    const tempDate = new Date(date.getTime());
                    tempDate.setHours(0, 0, 0, 0);
                    tempDate.setDate(tempDate.getDate() + 3 - (tempDate.getDay() + 6) % 7);
                    const week1 = new Date(tempDate.getFullYear(), 0, 4);
                    const weekNum = 1 + Math.round(((tempDate - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
                    key = `${{tempDate.getFullYear()}}-W${{String(weekNum).padStart(2, '0')}}`;
                }} else {{
                    key = d.timestamp.substring(0, 7);
                }}

                if (!groups[key]) {{
                    groups[key] = {{ totals: {{}}, count: 0 }};
                    metrics.forEach(m => groups[key].totals[m] = 0);
                }}
                metrics.forEach(m => groups[key].totals[m] += d[m]);
                groups[key].count += 1;
            }});

            const labels = Object.keys(groups).sort();
            const result = {{ labels }};

            metrics.forEach(m => {{
                // Use sum for duration, average for others
                if (m === 'duration_min') {{
                    result[m] = labels.map(k => Math.round(groups[k].totals[m] * 10) / 10);
                }} else {{
                    result[m] = labels.map(k => Math.round(groups[k].totals[m] / groups[k].count * 100) / 100);
                }}
            }});

            return result;
        }}

        // Create daily chart
        function createDailyChart(data, group) {{
            const ctx = document.getElementById('dailyChart').getContext('2d');
            const config = metricGroups[group];
            const labels = data.map(d => d.timestamp.split(' ')[0]);  // Date only

            const datasets = config.metrics.map((metric, i) => ({{
                label: config.labels[i],
                data: data.map(d => d[metric]),
                borderColor: config.colors[i],
                backgroundColor: config.bgColors[i],
                tension: 0.1,
                fill: config.metrics.length === 1
            }}));

            return new Chart(ctx, {{
                type: 'line',
                data: {{ labels, datasets }},
                options: {{
                    responsive: true,
                    plugins: {{ title: {{ display: false }} }},
                    scales: {{
                        y: {{
                            beginAtZero: group === 'duration',
                            title: {{ display: true, text: config.yLabel }}
                        }},
                        x: {{
                            title: {{ display: true, text: 'Date' }},
                            ticks: {{ maxTicksLimit: 10 }}
                        }}
                    }}
                }}
            }});
        }}

        // Create trend chart
        function createTrendChart(aggregated, group) {{
            const ctx = document.getElementById('trendChart').getContext('2d');
            const config = metricGroups[group];

            // Determine if using chu (炷) unit for duration
            const useChu = group === 'duration' && currentUnit === 'chu';
            const unitLabel = useChu ? '炷' : 'min';
            const convertValue = (v) => useChu ? Math.round(v / CHU_MINUTES * 10) / 10 : v;

            const datasets = config.metrics.map((metric, i) => ({{
                label: useChu ? 'Duration (炷)' : config.labels[i],
                data: aggregated[metric].map(convertValue),
                backgroundColor: config.colors[i].replace('rgb', 'rgba').replace(')', ', 0.6)'),
                borderColor: config.colors[i],
                borderWidth: 1,
                type: 'bar',
                yAxisID: 'y'
            }}));

            // Add cumulative line for duration group
            if (config.showCumulativeInTrend) {{
                let cumSum = 0;
                const cumulativeData = aggregated['duration_min'].map(v => {{
                    cumSum += v;
                    // For chu: floor for cumulative, round for others
                    if (useChu) {{
                        return Math.floor(cumSum / CHU_MINUTES);
                    }}
                    return Math.round(cumSum * 10) / 10;
                }});

                datasets.push({{
                    label: useChu ? 'Cumulative (炷)' : 'Cumulative (min)',
                    data: cumulativeData,
                    borderColor: 'rgb(255, 159, 64)',
                    backgroundColor: 'rgba(255, 159, 64, 0.2)',
                    type: 'line',
                    tension: 0.1,
                    fill: false,
                    yAxisID: 'y1'
                }});
            }}

            const yLabel = useChu ? 'Total (炷)' : config.trendLabel;
            const y1Label = useChu ? 'Cumulative (炷)' : config.trendLabelRight;

            const scales = {{
                y: {{
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    title: {{ display: true, text: yLabel }}
                }},
                x: {{
                    title: {{ display: true, text: currentAggregation === 'weekly' ? 'Week' : 'Month' }}
                }}
            }};

            // Add right Y-axis for cumulative
            if (config.showCumulativeInTrend) {{
                scales.y1 = {{
                    type: 'linear',
                    position: 'right',
                    beginAtZero: true,
                    title: {{ display: true, text: y1Label }},
                    grid: {{ drawOnChartArea: false }}
                }};
            }}

            return new Chart(ctx, {{
                type: 'bar',
                data: {{ labels: aggregated.labels, datasets }},
                options: {{
                    responsive: true,
                    plugins: {{ title: {{ display: false }} }},
                    scales: scales
                }}
            }});
        }}

        // Update charts
        function updateCharts() {{
            if (dailyChart) dailyChart.destroy();
            if (trendChart) trendChart.destroy();

            const filtered = filterByPeriod(rawData, currentPeriod);
            const config = metricGroups[currentMetricGroup];
            const aggregated = aggregateData(rawData, currentAggregation, config.metrics);

            dailyChart = createDailyChart(filtered, currentMetricGroup);
            trendChart = createTrendChart(aggregated, currentMetricGroup);
        }}

        function setMetricGroup(group) {{
            currentMetricGroup = group;
            updateCharts();
        }}

        function setPeriod(period) {{
            currentPeriod = period;
            ['btn1W', 'btn1M', 'btn3M', 'btnAll'].forEach(id => {{
                document.getElementById(id).classList.toggle('active',
                    id === 'btn' + period.toUpperCase() || (period === 'all' && id === 'btnAll'));
            }});
            updateCharts();
        }}

        function setAggregation(mode) {{
            currentAggregation = mode;
            document.getElementById('btnWeekly').classList.toggle('active', mode === 'weekly');
            document.getElementById('btnMonthly').classList.toggle('active', mode === 'monthly');
            updateCharts();
        }}

        function setUnit(unit) {{
            currentUnit = unit;
            document.getElementById('btnMinutes').classList.toggle('active', unit === 'minutes');
            document.getElementById('btnChu').classList.toggle('active', unit === 'chu');
            updateCharts();
        }}

        // Initialize charts
        updateCharts();
    </script>
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
