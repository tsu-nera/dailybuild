"""リポジトリ直下 .env の読み込み

API キー・token はここ経由で読む（`config/*.json` を新設しない）。
環境変数が設定されていれば .env より優先する（systemd の EnvironmentFile や一時上書き用）。
os.environ には書き込まない。
"""

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = Path(__file__).parent.parent.parent.parent / '.env'


class MissingEnvError(RuntimeError):
    """必須のキーが環境変数にも .env にも無い"""


def get_env(name: str, default: str | None = None,
            env_file: Path = ENV_FILE, environ=os.environ) -> str | None:
    """環境変数 → .env の順に name を探す。空文字は未設定として扱う"""
    if environ.get(name):
        return environ[name]
    if env_file.exists():
        value = dotenv_values(env_file).get(name)
        if value:
            return value
    return default


def require_env(name: str, hint: str = '',
                env_file: Path = ENV_FILE, environ=os.environ) -> str:
    """get_env と同じだが、見つからなければ置き場所を案内して落ちる"""
    value = get_env(name, env_file=env_file, environ=environ)
    if not value:
        message = f"{name} がありません（環境変数か {env_file} に書く。.env.example を参照）"
        raise MissingEnvError(f"{message}\n  {hint}" if hint else message)
    return value
