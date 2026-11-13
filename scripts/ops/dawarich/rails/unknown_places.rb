# 名前の無い（Unknown の）Place の Google place ID を1行の JSON で出す。scripts/dawarich.py name-places が流す
# 手で名前を固定した Place（name_locked_at あり）は対象にしない
require 'json'

ids = Place.where(name: 'Unknown', name_locked_at: nil)
           .pluck(Arel.sql("geodata->>'external_place_id'"))
           .compact
           .select { |e| e.start_with?('google:') }
           .map { |e| e.delete_prefix('google:') }
           .uniq
puts "RESULT_JSON:#{JSON.generate(ids)}"
