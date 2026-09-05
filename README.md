# dailybuild

自分のライフログを集めて分析するための個人用リポジトリ。
睡眠・体組成・活動量・時間・お金・気分を API から取得して CSV に落とし、
Markdown のレポートを生成する。

Google Health / HealthPlanet / Toggl Track / MoneyForward ME /
Google Forms / Habitica。

**ここにはコードしか無い。** データとレポートの実体は非公開の
`dailybuild-private` にあり、`data/` `reports/` はそこへの symlink。
個人の記録が対象なので、他人が動かすことは想定していない。

運用と設計の詳細は [CLAUDE.md](CLAUDE.md) / [docs/](docs/) にある。
