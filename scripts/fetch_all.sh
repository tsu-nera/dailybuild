#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== Fitbitデータ取得 ==="
python scripts/fetch_fitbit.py --all "$@"

echo ""
echo "=== HealthPlanet体組成計データ取得 ==="
python scripts/fetch_healthplanet.py "$@"

echo ""
echo "=== 完了 ==="
