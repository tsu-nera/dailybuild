#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Fitbit睡眠データ取得 ==="
python scripts/fetch_sleep.py "$@"

echo ""
echo "=== HealthPlanet体組成計データ取得 ==="
python scripts/fetch_healthplanet.py "$@"

echo ""
echo "=== 完了 ==="
