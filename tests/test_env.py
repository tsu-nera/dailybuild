"""lib.utils.env: .env と環境変数の優先順位"""

import pytest

from lib.utils.env import MissingEnvError, get_env, require_env


def test_reads_env_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text('A=file\n')
    assert get_env('A', env_file=p, environ={}) == 'file'


def test_environ_overrides_env_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text('A=file\n')
    assert get_env('A', env_file=p, environ={'A': 'env'}) == 'env'


def test_empty_value_is_unset(tmp_path):
    p = tmp_path / '.env'
    p.write_text('A=\n')
    assert get_env('A', 'dflt', env_file=p, environ={'A': ''}) == 'dflt'
    with pytest.raises(MissingEnvError):
        require_env('A', env_file=p, environ={})


def test_missing_file_is_not_an_error_until_required(tmp_path):
    missing = tmp_path / 'none'
    assert get_env('A', env_file=missing, environ={}) is None
    with pytest.raises(MissingEnvError, match='A がありません'):
        require_env('A', env_file=missing, environ={})
