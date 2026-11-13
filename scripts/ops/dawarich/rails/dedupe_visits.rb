# 開始時刻が同じ Visit を1件に減らす。scripts/dawarich.py name-places が流す
# ARGV[0]: JSON {"level0": ["<google place ID>@<開始の epoch 秒>", ...], "dry_run": bool}
#
# Timeline の取り込みは hierarchyLevel 違いの同じ訪問を落とさず、Dawarich 自身の検出も同じ時刻に重なる。
# 同じ開始時刻の Visit が2つの Place にあると Places::Merge が VisitConflict で止まる（UI の merge も同じ）。
# 削除済み（deleted_at）の Visit も衝突の判定に入るので、落とす側は Place からも外す。
# 残す順: Timeline の level 0（data/timeline/visits.csv にある組）> 取り込み由来 > 長い > id の小さい
require 'json'

args = JSON.parse(File.read(ARGV.fetch(0)))
level0 = args.fetch('level0').to_set
dry_run = args.fetch('dry_run')

linked = Visit.where.not(place_id: nil)  # Place から外した行は衝突しないので数えない
starts = linked.group(:started_at).having('COUNT(*) > 1').pluck(:started_at)
drop_ids = []
starts.each_slice(500) do |slice|
  linked.where(started_at: slice).includes(:place).group_by(&:started_at).each_value do |group|
    keep = group.min_by do |v|
      ext = v.place&.geodata&.dig('external_place_id').to_s
      is_level0 = ext.start_with?('google:') && level0.include?("#{ext.delete_prefix('google:')}@#{v.started_at.to_i}")
      [v.deleted_at ? 1 : 0, is_level0 ? 0 : 1, v.import_id ? 0 : 1, -(v.ended_at - v.started_at), v.id]
    end
    drop_ids.concat(group.map(&:id) - [keep.id])
  end
end

unless dry_run
  drop_ids.each_slice(1000) do |ids|
    Visit.where(id: ids).update_all(deleted_at: Time.current, place_id: nil, updated_at: Time.current)
  end
end
puts "RESULT_JSON:#{JSON.generate(groups: starts.size, dropped: drop_ids.size, dry_run: dry_run)}"
