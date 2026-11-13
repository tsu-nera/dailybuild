# 外部 ID（Google の place ID・Swarm の venue）を持つ Place の今の状態と、Visit の今の Place を1行の JSON で出す。
# scripts/dawarich.py capture-places が読み、data/dawarich/places.csv（UI で直した名前・merge・アーカイブの写し）を更新する
require 'json'

places = Place.where("geodata ? 'external_place_id'").map do |p|
  { place_id: p.id, external_place_id: p.geodata['external_place_id'], name: p.name,
    archived: p.archived?, note: p.note.to_s, name_locked: p.name_locked? }
end
first_visit = Visit.where(deleted_at: nil).where.not(place_id: nil).group(:place_id).minimum(:id)
places.each { |p| p[:visit_id] = first_visit[p[:place_id]] }
visit_place = Visit.where(deleted_at: nil).where.not(place_id: nil).pluck(:id, :place_id).to_h
puts "RESULT_JSON:#{JSON.generate(places: places, visit_place: visit_place)}"
