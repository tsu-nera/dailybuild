# Google Drive・Apps Script

**このプロジェクトが Google 上に作るものは、すべて Drive の `dailybuild` フォルダ
配下に置く**（`config/personal.yaml` の `gdrive.folder_id`）。Sheets・Forms に限らず、
今後増える種類も同じ。マイドライブ直下に散らかさない。

**Drive / Forms の作成 API は親を省略するとマイドライブ直下に作る。** 作成時は
必ず `gdrive.folder_id` を親に指定すること。Forms API の `forms.create` には親の
指定が無いので、**作成後に Drive API で移動する**（現状の4フォームは手動で移した）。

**フォルダを移動しても `form_id` / スプレッドシート ID は変わらない。** 既存の
フォームをこのフォルダへ移しても `config/*_def.yaml` の `form_id` はそのままで、
fetch は影響を受けない。

- **サービスアカウントはファイルを所有できない**（Drive の `storageQuota.limit` が 0）。
  作成は本人の OAuth で行い、サービスアカウントには**編集者として共有**する。
  Forms で `forms.create` が 500 になるのと同じ理由（[docs/forms.md](docs/forms.md)）
- Drive のアクセス制御は ACL なので、ファイル ID や フォルダ ID を public repo に
  書いても共有されない。**リンク共有を有効にしたファイルの ID は別**（それは
  実質パスワードになる）
- Google Forms の回答先スプレッドシートは作らない。回答は Forms API で直接読む

## Apps Script

シートに貼るスクリプトの正本は `scripts/gas/`。反映は clasp で行い、画面で直接
編集しない（画面で直すとリポジトリ側が古いまま気づけなくなる）。

```bash
cd scripts/gas && clasp push   # .clasp.json の scriptId へ反映
```

- **`onEdit` は simple trigger なので、API 経由の書き込みでは発火しない。**
  gspread や Sheets API で足した行には timestamp が入らない。機械が行を足す
  設計にするなら、書き込み側で timestamp を入れること
- `appsscript.json` の `timeZone` は既定が `America/New_York`。`new Date()` を
  素で使うと9時間ずれる（`Asia/Tokyo` に直してある）
- clasp は独自の OAuth クライアントを使い、トークンは `~/.clasprc.json`。
  `config/gforms_token.json` とは無関係なのでフォーム取得に影響しない。
  利用には https://script.google.com/home/usersettings の
  「Google Apps Script API」が ON である必要がある（ユーザー単位の設定で、
  API からは切り替えられない）
