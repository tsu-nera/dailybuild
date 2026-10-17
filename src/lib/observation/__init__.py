"""
観察日記（reports/observation/）の材料集めと区切りの判定

HA の state 履歴（ha）、それを区切りに読む判定（landmarks）、markdown（render）に分ける。
判定の閾値は config/observation.yaml が持ち、答え合わせ（labels.csv）とのズレを見て直す。
scripts/observation.py と scripts/early_rising.py から使う。
"""
