# ARGV[0] の JSON（Google place ID → {name, note}）で Unknown の Place を改名し、名前を固定する
# 名前の固定された Place と、Unknown 以外の名前の Place には触れない。scripts/dawarich.py name-places が流す
require 'json'

names = JSON.parse(File.read(ARGV.fetch(0)))
renamed = 0
Place.where(name: 'Unknown', name_locked_at: nil).find_each do |place|
  entry = names[place.geodata&.dig('external_place_id').to_s.delete_prefix('google:')]
  next unless entry

  attrs = { name: entry['name'], name_locked_at: Time.current }
  attrs[:note] = entry['note'] if entry['note'].present?
  place.update!(attrs)
  renamed += 1
end

# Visit の name が Unknown だと Place の名前より先に表示される（visits.name → places.name の順）
cleared = Visit.where(name: 'Unknown').joins(:place).where.not(places: { name: 'Unknown' }).update_all(name: nil)

rows = Visit.where(deleted_at: nil).left_joins(:place, :area).pluck(Arel.sql(Visit.display_name_sql))
unknown = rows.count { |n| ['Unknown', Visit::DEFAULT_NAME].include?(n) }
puts "RESULT_JSON:#{JSON.generate(renamed: renamed, visit_names_cleared: cleared,
                                  places_unknown: Place.where(name: 'Unknown').count,
                                  visits_unknown: unknown, visits_total: rows.size)}"
