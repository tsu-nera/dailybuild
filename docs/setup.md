# セットアップ（新マシン・worktree）

```bash
git clone git@github.com:tsu-nera/dailybuild-private.git ~/repo/dailybuild-private
./scripts/setup_private_links.sh   # 冪等。別の場所に置くなら DAILYBUILD_PRIVATE を設定
```

**git worktree では symlink が引き継がれない。** worktree を作ったら
`setup_private_links.sh` を実行すること。

## vaio（取得専用サーバ）

```bash
git clone git@github.com:tsu-nera/dailybuild.git ~/repo/dailybuild
git clone git@github.com:tsu-nera/dailybuild-private.git ~/repo/dailybuild-private
cd ~/repo/dailybuild && uv sync && ./scripts/setup_private_links.sh
# .env と config/*.json（OAuth token・セッション）を iiyama からコピー（gitignore 済みなので clone では来ない）
uv run playwright install chromium
uv run scripts/mf.py fetch --login      # GUI セッション（VNC 可）で一度だけ（TEPCO は取得停止中なので不要）
# config/lastfm_session.json も iiyama で `lastfm.py fetch --login` して作り、vaio へコピーする
# config/googlehealth_location_token.json も iiyama で `exercise_route.py login` して作り、vaio へコピーする（無いと日次の運動の軌跡ステップが失敗する）
# config/gcalendar_token.json は iiyama で `gcalendar.py fetch --login` して作り、vaio へコピーする（無いと日次の Google Calendar ステップが失敗する）
loginctl enable-linger tsu-nera
systemctl --user link ~/repo/dailybuild/scripts/ops/systemd/dailybuild-routine.{service,timer}
systemctl --user enable --now dailybuild-routine.timer
```

## 認証情報（`config/`）

認証情報は`config/`ディレクトリにJSONファイルとして配置:
- `mf_state.json` - MoneyForward ME のブラウザセッション（`mf.py fetch --login` が生成）
- `tepco_state.json` - くらしTEPCO web のブラウザセッション（`tepco.py fetch --login` が生成）
- `gcloud_creds.json` - Google サービスアカウント（手動記録のGoogle Sheets取得用）
- `tuya_creds.json` - Tuya Cloud API（api_region, api_key, api_secret, device_id）
- `gcalendar_token.json` - Google Calendar（readonly）のトークン（`gcalendar.py fetch --login` が生成。`gforms_token.json` とスコープを分けてある）
- `lastfm_session.json` - Last.fm の認証セッション（`lastfm.py fetch --login` が生成。再生履歴を非公開にしているので API key だけでは読めない）
- `swarm_token.json` - Foursquare（Swarm）の access token（`swarm.py fetch --login` が生成。期限なし。Client ID / Secret は `.env`）
- `gmail_token.json` - Gmail（readonly）のトークン（`purchases.py fetch --login` が生成。gtd の modify トークンとは別）
- `googlehealth_location_token.json` - 運動の GPS 軌跡（TCX）用の Google Health トークン（`exercise_route.py login` が生成。location スコープを日次取得の `googlehealth_token.json` に混ぜないため別ファイル）
- `gforms_token.json` - Google Forms のトークン（`emotion.py` が生成し `bowel.py` / `phq9.py` とも共用。OAuth クライアントは `googlehealth_creds.json` と共用）
- `toggl_push.yaml` - Toggl push のソース別マッピング（プロジェクト名・説明・タグ）。yamlなのでコミット対象
- `phq9_def.yaml` - PHQ-9 の設問文・選択肢の実体。**著作権の都合で `.gitignore` 済み**（`phq9_def.yaml.sample` から作る。詳細は「PHQ-9（週次）」節）
- `private/habits.yaml` - 習慣レビューの対象と週の目標値。**実体は dailybuild-private**（`config/private` は symlink。習慣名が非公開なため）
- `private/contracts.yaml` - 定期契約の台帳（`mf.py contracts` が読む）。**実体は dailybuild-private**。`config/contracts.yaml.sample` を `config/private/contracts.yaml` へ `cp` して作る

Google Sheets クライアント（`src/lib/clients/gsheets_client.py`）は `config/gcloud_creds.json` を直接参照しない。環境変数 `GOOGLE_APPLICATION_CREDENTIALS` か既定パス `~/.config/gcp/gdrive-creds.json` を探すため、新マシンではどちらかを用意する（リポジトリの認証情報を使う場合は `ln -sf "$PWD/config/gcloud_creds.json" ~/.config/gcp/gdrive-creds.json`）。
