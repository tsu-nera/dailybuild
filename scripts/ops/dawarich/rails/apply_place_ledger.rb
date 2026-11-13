# data/dawarich/places.csv（UI で下した判断の写し）を当て直す。scripts/dawarich.py name-places が流す
# ARGV[0]: JSON [{external_place_id, name, archived, merged_into, note}, ...]
# 取り込み直しで作り直された Place だけが対象になる（今の DB と同じ行は何も変えない）
require 'json'

rows = JSON.parse(File.read(ARGV.fetch(0)))
by_ext = rows.index_by { |r| r['external_place_id'] }
place_of = ->(ext) { Place.find_by("geodata ->> 'external_place_id' = ?", ext) }

# merged_into を辿った先（ループは打ち切る）
final = lambda do |ext|
  seen = Set.new
  while (nxt = by_ext.dig(ext, 'merged_into').presence) && seen.add?(ext)
    ext = nxt
  end
  ext
end

merged = archived = renamed = 0
conflicts = []
rows.each do |r|
  place = place_of.(r['external_place_id'])
  next unless place

  if r['merged_into'].present?
    survivor = place_of.(final.(r['external_place_id']))
    next if survivor.nil? || survivor.id == place.id

    # 同じ開始時刻の Visit が survivor にあると Merge が止まる。統合される側を Place から外す
    clash = place.visits.where(started_at: survivor.visits.select(:started_at))
    clash.update_all(deleted_at: Time.current, place_id: nil, updated_at: Time.current)
    begin
      Places::Merge.new(user: place.user, survivor: survivor, duplicate: place).call
      merged += 1
    rescue Places::Merge::VisitConflict => e
      conflicts << r['external_place_id']
    end
    next
  end

  if r['archived'] == 'true' && !place.archived?
    place.update!(archived: true)
    archived += 1
  end
  next unless place.name == 'Unknown' && r['name'].present? && r['name'] != 'Unknown'

  attrs = { name: r['name'], name_locked_at: Time.current }
  attrs[:note] = r['note'] if r['note'].present?
  place.update!(attrs)
  renamed += 1
end
puts "RESULT_JSON:#{JSON.generate(merged: merged, archived: archived, renamed: renamed, conflicts: conflicts)}"
