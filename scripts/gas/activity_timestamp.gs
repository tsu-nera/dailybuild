/**
 * 活動記録シート（Drive の dailybuild/活動記録）に貼るコンテナバインドの
 * Apps Script。activity 列に入力があった行の timestamp を自動で埋める。
 *
 * 設置: シートを開く → 拡張機能 → Apps Script → このファイルの中身を貼って保存。
 * 初回のトリガ承認は不要（simple trigger）。
 *
 * 手入力の摩擦を打鍵1回ぶんまで下げるためだけの仕組み。時刻を手で打たせると
 * 記録が続かない（過去の手動ログで、主観スコアの列は45%・自由記述は14%しか
 * 埋まっていない）。
 */

const SHEET_NAME = '記録';
const COL_TIMESTAMP = 1;
const COL_ACTIVITY = 2;
const TZ = 'Asia/Tokyo';

function onEdit(e) {
  if (!e || !e.range) return;
  const sheet = e.range.getSheet();
  if (sheet.getName() !== SHEET_NAME) return;

  // 貼り付けで複数行が同時に編集されることがあるので範囲で回す
  const firstRow = e.range.getRow();
  const numRows = e.range.getNumRows();
  const firstCol = e.range.getColumn();
  const lastCol = firstCol + e.range.getNumColumns() - 1;
  if (firstCol > COL_ACTIVITY || lastCol < COL_ACTIVITY) return;

  const now = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm:ss');

  for (let i = 0; i < numRows; i++) {
    const row = firstRow + i;
    if (row === 1) continue;  // ヘッダ

    // 活動を消したときに時刻だけ残らないよう、空なら何もしない
    if (!sheet.getRange(row, COL_ACTIVITY).getValue()) continue;

    // 既に時刻がある行は上書きしない。記録した瞬間を保つため、
    // 後から評定や活動名を直しても時刻は動かさない
    const cell = sheet.getRange(row, COL_TIMESTAMP);
    if (cell.getValue()) continue;

    // 文字列で入れる。リポジトリの CSV は naive な JST 文字列で揃えてある
    cell.setValue(now);
  }
}
