# 名前の無い（Unknown の）Place の Google place ID を、Visit の多い順に1行の JSON で出す。scripts/dawarich.py name-places が流す
# 手で名前を固定した Place（name_locked_at あり）は対象にしない。Places API の日次上限で途中までしか引けないので、効く順に並べる
require 'json'

ids = Place.where(name: 'Unknown', name_locked_at: nil)
           .left_joins(:visits).group('places.id')
           .order(Arel.sql('COUNT(visits.id) DESC, places.id'))
           .pluck(Arel.sql("places.geodata->>'external_place_id'"))
           .compact
           .select { |e| e.start_with?('google:') }
           .map { |e| e.delete_prefix('google:') }
           .uniq
puts "RESULT_JSON:#{JSON.generate(ids)}"
