/**
 * Meditation Dashboard - Chart.js based visualization
 *
 * Expects:
 * - Global variable `dashboardConfig` with:
 *   - rawData: array of meditation records
 *   - title: dashboard title
 */

// Source colors for duration chart
const sourceColors = {
    muse: {
        border: 'rgb(75, 192, 192)',
        background: 'rgba(75, 192, 192, 0.6)'
    },
    fitbit: {
        border: 'rgb(255, 159, 64)',
        background: 'rgba(255, 159, 64, 0.6)'
    }
};

// Metric group configurations
const metricGroups = {
    duration: {
        metrics: ['duration_min'],
        labels: ['Duration (min)'],
        colors: ['rgb(75, 192, 192)'],
        bgColors: ['rgba(75, 192, 192, 0.2)'],
        yLabel: 'Duration (min)',
        trendLabel: 'Total Duration (min)',
        trendLabelRight: 'Cumulative (min)',
        showCumulativeInTrend: true,
        showBySource: true  // Show separate bars by source
    },
    power: {
        metrics: ['alpha_mean', 'beta_mean'],
        labels: ['Alpha', 'Beta'],
        colors: ['rgb(54, 162, 235)', 'rgb(255, 99, 132)'],
        bgColors: ['rgba(54, 162, 235, 0.2)', 'rgba(255, 99, 132, 0.2)'],
        yLabel: 'Power (dB)',
        trendLabel: 'Avg Power (dB)',
        museOnly: true  // Only show Muse EEG data
    },
    iaf: {
        metrics: ['iaf_mean'],
        labels: ['IAF'],
        colors: ['rgb(255, 159, 64)'],
        bgColors: ['rgba(255, 159, 64, 0.2)'],
        yLabel: 'Frequency (Hz)',
        trendLabel: 'Avg IAF (Hz)',
        museOnly: true
    },
    focus: {
        metrics: ['fm_theta_mean', 'theta_alpha_mean'],
        labels: ['FM Theta', 'Theta/Alpha'],
        colors: ['rgb(153, 102, 255)', 'rgb(75, 192, 192)'],
        bgColors: ['rgba(153, 102, 255, 0.2)', 'rgba(75, 192, 192, 0.2)'],
        yLabel: 'Ratio',
        trendLabel: 'Avg Ratio',
        museOnly: true
    }
};

// Filter data by source
function filterBySource(data, source) {
    return data.filter(d => d.source === source);
}

let currentMetricGroup = 'duration';
let currentPeriod = '1w';
let currentAggregation = 'weekly';
let currentUnit = 'hours';  // 'hours' or 'chu' (1炷 = 40min)
const CHU_MINUTES = 40;
let dailyChart, trendChart;

// Filter data by period
function filterByPeriod(data, period) {
    if (period === 'all') return data;

    const now = new Date();
    let cutoff;
    switch (period) {
        case '1w': cutoff = new Date(now - 7 * 24 * 60 * 60 * 1000); break;
        case '1m': cutoff = new Date(now - 30 * 24 * 60 * 60 * 1000); break;
        case '3m': cutoff = new Date(now - 90 * 24 * 60 * 60 * 1000); break;
        default: return data;
    }

    return data.filter(d => new Date(d.timestamp) >= cutoff);
}

// Aggregate data by week or month
function aggregateData(data, mode, metrics) {
    const groups = {};

    data.forEach(d => {
        const date = new Date(d.timestamp);
        let key;

        if (mode === 'weekly') {
            // Calculate ISO week number
            const tempDate = new Date(date.getTime());
            tempDate.setHours(0, 0, 0, 0);
            tempDate.setDate(tempDate.getDate() + 3 - (tempDate.getDay() + 6) % 7);
            const week1 = new Date(tempDate.getFullYear(), 0, 4);
            const weekNum = 1 + Math.round(((tempDate - week1) / 86400000 - 3 + (week1.getDay() + 6) % 7) / 7);
            key = `${tempDate.getFullYear()}-W${String(weekNum).padStart(2, '0')}`;
        } else {
            key = d.timestamp.substring(0, 7);
        }

        if (!groups[key]) {
            groups[key] = { totals: {}, count: 0 };
            metrics.forEach(m => groups[key].totals[m] = 0);
        }
        metrics.forEach(m => groups[key].totals[m] += d[m]);
        groups[key].count += 1;
    });

    const labels = Object.keys(groups).sort();
    const result = { labels };

    metrics.forEach(m => {
        // Use sum for duration, average for others
        if (m === 'duration_min') {
            result[m] = labels.map(k => Math.round(groups[k].totals[m] * 10) / 10);
        } else {
            result[m] = labels.map(k => Math.round(groups[k].totals[m] / groups[k].count * 100) / 100);
        }
    });

    return result;
}

// Create daily chart
function createDailyChart(data, group) {
    const ctx = document.getElementById('dailyChart').getContext('2d');
    const config = metricGroups[group];

    // Filter for muse-only metrics
    let chartData = config.museOnly ? filterBySource(data, 'muse') : data;

    // For duration with showBySource, create separate datasets per source
    if (config.showBySource && group === 'duration') {
        const museData = filterBySource(data, 'muse');
        const fitbitData = filterBySource(data, 'fitbit');

        // Combine all unique dates
        const allDates = [...new Set([
            ...museData.map(d => d.timestamp.split(' ')[0]),
            ...fitbitData.map(d => d.timestamp.split(' ')[0])
        ])].sort();

        // Aggregate by date for each source
        const museByDate = {};
        museData.forEach(d => {
            const date = d.timestamp.split(' ')[0];
            if (!museByDate[date]) museByDate[date] = 0;
            museByDate[date] += d.duration_min;
        });

        const fitbitByDate = {};
        fitbitData.forEach(d => {
            const date = d.timestamp.split(' ')[0];
            if (!fitbitByDate[date]) fitbitByDate[date] = 0;
            fitbitByDate[date] += d.duration_min;
        });

        // Calculate total (combined) per date
        const totalByDate = {};
        allDates.forEach(date => {
            totalByDate[date] = (museByDate[date] || 0) + (fitbitByDate[date] || 0);
        });

        // Create datasets
        const datasets = [];

        // Total (combined) line - always show first
        datasets.push({
            label: 'Total',
            data: allDates.map(date => totalByDate[date] || null),
            borderColor: 'rgb(99, 102, 241)',  // Indigo
            backgroundColor: 'rgba(99, 102, 241, 0.2)',
            borderWidth: 3,
            tension: 0.1,
            order: 0  // Draw on top
        });

        if (museData.length > 0) {
            datasets.push({
                label: 'Muse EEG',
                data: allDates.map(date => museByDate[date] || null),
                borderColor: sourceColors.muse.border,
                backgroundColor: sourceColors.muse.background,
                borderWidth: 2,
                tension: 0.1,
                order: 1
            });
        }

        if (fitbitData.length > 0) {
            datasets.push({
                label: 'Fitbit',
                data: allDates.map(date => fitbitByDate[date] || null),
                borderColor: sourceColors.fitbit.border,
                backgroundColor: sourceColors.fitbit.background,
                borderWidth: 2,
                tension: 0.1,
                order: 2
            });
        }

        return new Chart(ctx, {
            type: 'line',
            data: { labels: allDates, datasets },
            options: {
                responsive: true,
                plugins: { title: { display: false } },
                spanGaps: true,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: { display: true, text: config.yLabel }
                    },
                    x: {
                        title: { display: true, text: 'Date' },
                        ticks: { maxTicksLimit: 10 }
                    }
                }
            }
        });
    }

    // Default behavior for other metrics
    const labels = chartData.map(d => d.timestamp.split(' ')[0]);
    const datasets = config.metrics.map((metric, i) => ({
        label: config.labels[i],
        data: chartData.map(d => d[metric]),
        borderColor: config.colors[i],
        backgroundColor: config.bgColors[i],
        tension: 0.1,
        fill: config.metrics.length === 1
    }));

    return new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: {
            responsive: true,
            plugins: { title: { display: false } },
            scales: {
                y: {
                    beginAtZero: group === 'duration',
                    title: { display: true, text: config.yLabel }
                },
                x: {
                    title: { display: true, text: 'Date' },
                    ticks: { maxTicksLimit: 10 }
                }
            }
        }
    });
}

// Create trend chart
function createTrendChart(aggregated, group) {
    const ctx = document.getElementById('trendChart').getContext('2d');
    const config = metricGroups[group];

    // Determine unit for duration
    const useChu = group === 'duration' && currentUnit === 'chu';
    const useHours = group === 'duration' && currentUnit === 'hours';
    const unitLabel = useChu ? '炷' : (useHours ? 'h' : 'min');
    const convertValue = (v) => {
        if (useChu) return Math.round(v / CHU_MINUTES * 10) / 10;
        if (useHours) return Math.round(v / 60 * 10) / 10;
        return v;
    };

    const datasets = config.metrics.map((metric, i) => ({
        label: useChu ? 'Duration (炷)' : (useHours ? 'Duration (h)' : config.labels[i]),
        data: aggregated[metric].map(convertValue),
        backgroundColor: config.colors[i].replace('rgb', 'rgba').replace(')', ', 0.6)'),
        borderColor: config.colors[i],
        borderWidth: 1,
        type: 'bar',
        yAxisID: 'y'
    }));

    // Add cumulative line for duration group
    if (config.showCumulativeInTrend) {
        let cumSum = 0;
        const cumulativeData = aggregated['duration_min'].map(v => {
            cumSum += v;
            if (useChu) {
                return Math.floor(cumSum / CHU_MINUTES);
            }
            if (useHours) {
                return Math.round(cumSum / 60 * 10) / 10;
            }
            return Math.round(cumSum * 10) / 10;
        });

        const cumLabel = useChu ? 'Cumulative (炷)' : (useHours ? 'Cumulative (h)' : 'Cumulative (min)');
        datasets.push({
            label: cumLabel,
            data: cumulativeData,
            borderColor: 'rgb(255, 159, 64)',
            backgroundColor: 'rgba(255, 159, 64, 0.2)',
            type: 'line',
            tension: 0.1,
            fill: false,
            yAxisID: 'y1'
        });
    }

    const yLabel = useChu ? 'Total (炷)' : (useHours ? 'Total (h)' : config.trendLabel);
    const y1Label = useChu ? 'Cumulative (炷)' : (useHours ? 'Cumulative (h)' : config.trendLabelRight);

    const scales = {
        y: {
            type: 'linear',
            position: 'left',
            beginAtZero: true,
            title: { display: true, text: yLabel }
        },
        x: {
            title: { display: true, text: currentAggregation === 'weekly' ? 'Week' : 'Month' }
        }
    };

    // Add right Y-axis for cumulative
    if (config.showCumulativeInTrend) {
        scales.y1 = {
            type: 'linear',
            position: 'right',
            beginAtZero: true,
            title: { display: true, text: y1Label },
            grid: { drawOnChartArea: false }
        };
    }

    return new Chart(ctx, {
        type: 'bar',
        data: { labels: aggregated.labels, datasets },
        options: {
            responsive: true,
            plugins: { title: { display: false } },
            scales: scales
        }
    });
}

// Update charts
function updateCharts() {
    if (dailyChart) dailyChart.destroy();
    if (trendChart) trendChart.destroy();

    const rawData = window.dashboardConfig.rawData;
    const filtered = filterByPeriod(rawData, currentPeriod);
    const config = metricGroups[currentMetricGroup];

    // For muse-only metrics, filter data before aggregation
    const dataForAggregation = config.museOnly ? filterBySource(rawData, 'muse') : rawData;
    const aggregated = aggregateData(dataForAggregation, currentAggregation, config.metrics);

    dailyChart = createDailyChart(filtered, currentMetricGroup);
    trendChart = createTrendChart(aggregated, currentMetricGroup);
}

function setMetricGroup(group) {
    currentMetricGroup = group;
    updateCharts();
}

function setPeriod(period) {
    currentPeriod = period;
    ['btn1W', 'btn1M', 'btn3M', 'btnAll'].forEach(id => {
        document.getElementById(id).classList.toggle('active',
            id === 'btn' + period.toUpperCase() || (period === 'all' && id === 'btnAll'));
    });
    updateCharts();
}

function setAggregation(mode) {
    currentAggregation = mode;
    document.getElementById('btnWeekly').classList.toggle('active', mode === 'weekly');
    document.getElementById('btnMonthly').classList.toggle('active', mode === 'monthly');
    updateCharts();
}

function setUnit(unit) {
    currentUnit = unit;
    document.getElementById('btnHours').classList.toggle('active', unit === 'hours');
    document.getElementById('btnChu').classList.toggle('active', unit === 'chu');
    updateCharts();
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (window.dashboardConfig && window.dashboardConfig.rawData) {
        updateCharts();
    }
});
