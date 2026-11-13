# スマホの Dawarich アプリが送った点（import の無い点）を1行の JSON で出す。scripts/dawarich.py export-app-points が流す
# 座標は文字列のまま出す（CSV の重複判定キーにするので、float を経由させない）
require 'json'

rows = Point.where(import_id: nil).order(:timestamp).pluck(
  :timestamp, Arel.sql('ST_Y(lonlat::geometry)::text'), Arel.sql('ST_X(lonlat::geometry)::text'),
  :accuracy, :altitude_decimal, :velocity, :course, :battery, :battery_status, :connection, :tracker_id
).map do |ts, lat, lon, acc, alt, vel, course, bat, bat_status, conn, tracker|
  { timestamp: Time.at(ts).in_time_zone('Asia/Tokyo').iso8601, latitude: lat, longitude: lon, accuracy: acc,
    altitude: alt&.to_s, velocity: vel, course: course, battery: bat, battery_status: bat_status,
    connection: conn, tracker_id: tracker }
end
puts "RESULT_JSON:#{JSON.generate(rows)}"
