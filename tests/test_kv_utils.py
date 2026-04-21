"""Unit tests for kv_utils helper functions (write_env_multiline, mask_value, normalize_pem, cmd_fetch_app_token_creds)."""
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github"))
from scripts.kv_utils import write_env, write_env_multiline, mask_value, normalize_pem, cmd_fetch_app_token_creds


# ─── write_env_multiline ──────────────────────────────────────────────────────

def test_write_env_multiline_heredoc_format(tmp_path):
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    os.environ["GITHUB_ENV"] = str(env_file)
    try:
        write_env_multiline("MY_KEY", "line1\nline2\nline3")
        content = env_file.read_text()
        assert "MY_KEY<<EOF_KV_ML\n" in content
        assert "line1\nline2\nline3\n" in content
        assert "EOF_KV_ML\n" in content
    finally:
        del os.environ["GITHUB_ENV"]


def test_write_env_multiline_custom_delimiter(tmp_path):
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    os.environ["GITHUB_ENV"] = str(env_file)
    try:
        write_env_multiline("PEM", "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", delimiter="PEM_DELIM")
        content = env_file.read_text()
        assert "PEM<<PEM_DELIM\n" in content
        assert "PEM_DELIM\n" in content
    finally:
        del os.environ["GITHUB_ENV"]


def test_write_env_multiline_no_github_env(capsys):
    if "GITHUB_ENV" in os.environ:
        del os.environ["GITHUB_ENV"]
    write_env_multiline("KEY", "value")
    captured = capsys.readouterr()
    assert "KEY=<multiline>" in captured.out


# ─── mask_value ───────────────────────────────────────────────────────────────

def test_mask_value_emits_add_mask_command(capsys):
    mask_value("super-secret-pem")
    captured = capsys.readouterr()
    assert "::add-mask::super-secret-pem" in captured.out


# ─── normalize_pem ───────────────────────────────────────────────────────────

_PROPER_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "ABCDEF1234567890\n"
    "-----END RSA PRIVATE KEY-----"
)
_LITERAL_NL_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\\n"
    "ABCDEF1234567890\\n"
    "-----END RSA PRIVATE KEY-----"
)


def test_normalize_pem_converts_literal_backslash_n():
    """PEM stored in KV as one line with \\n must become multi-line."""
    result = normalize_pem(_LITERAL_NL_PEM)
    assert result == _PROPER_PEM
    assert "\\n" not in result


def test_normalize_pem_leaves_proper_pem_unchanged():
    """PEM that already has real newlines must pass through untouched."""
    result = normalize_pem(_PROPER_PEM)
    assert result == _PROPER_PEM


def test_normalize_pem_empty_string():
    assert normalize_pem("") == ""


def test_normalize_pem_no_header():
    """Bare base64 blob with literal \\n still gets normalized."""
    result = normalize_pem("abc\\ndef\\nghi")
    assert result == "abc\ndef\nghi"


# ─── cmd_fetch_app_token_creds ────────────────────────────────────────────────

def test_fetch_app_token_creds_normalizes_literal_backslash_n_in_pem(tmp_path, capsys):
    """Regression: PEM stored in KV with literal \\n must be normalized before writing to GITHUB_ENV.

    Without normalization, actions/create-github-app-token passes the single-line
    blob to Node's createPrivateKey, which raises ERR_OSSL_UNSUPPORTED.
    """
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    os.environ["GITHUB_ENV"] = str(env_file)
    os.environ["GH_APP_ID_KV_NAME"] = "my-app-id-secret"
    os.environ["GH_APP_PEM_KV_NAME"] = "my-app-pem-secret"

    def fake_get_secret(name):
        return "123456" if name == "my-app-id-secret" else _LITERAL_NL_PEM

    try:
        with patch("scripts.kv_utils.get_secret", side_effect=fake_get_secret):
            cmd_fetch_app_token_creds()

        content = env_file.read_text()
        assert _PROPER_PEM in content, "PEM must have actual newlines in GITHUB_ENV"
        assert "\\n" not in content, "Literal backslash-n must not survive into GITHUB_ENV"
    finally:
        del os.environ["GITHUB_ENV"]
        del os.environ["GH_APP_ID_KV_NAME"]
        del os.environ["GH_APP_PEM_KV_NAME"]


def test_fetch_app_token_creds_writes_id_and_pem(tmp_path, capsys):
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    os.environ["GITHUB_ENV"] = str(env_file)
    os.environ["GH_APP_ID_KV_NAME"] = "my-app-id-secret"
    os.environ["GH_APP_PEM_KV_NAME"] = "my-app-pem-secret"

    fake_pem = "-----BEGIN RSA PRIVATE KEY-----\nABCDEF\n-----END RSA PRIVATE KEY-----"

    def fake_get_secret(name):
        return "123456" if name == "my-app-id-secret" else fake_pem

    try:
        with patch("scripts.kv_utils.get_secret", side_effect=fake_get_secret):
            cmd_fetch_app_token_creds()

        content = env_file.read_text()
        # App ID written as plain key=value
        assert "GH_APP_ID_VALUE=123456\n" in content
        # PEM written as heredoc
        assert "GH_APP_PEM_VALUE<<EOF_KV_ML\n" in content
        assert fake_pem in content
        # Mask command emitted
        captured = capsys.readouterr()
        assert f"::add-mask::{fake_pem}" in captured.out
    finally:
        del os.environ["GITHUB_ENV"]
        del os.environ["GH_APP_ID_KV_NAME"]
        del os.environ["GH_APP_PEM_KV_NAME"]
