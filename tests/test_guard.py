import os
import subprocess
from pathlib import Path

import pytest

from anvyl.guard import MAX_FILE_BYTES, is_denied, list_files, redact, resolve_inside
from anvyl.profile import Profile

BOTH = [Profile.PROFESSIONAL, Profile.PERSONAL]


@pytest.mark.parametrize("profile", BOTH)
@pytest.mark.parametrize(
    "rel",
    [
        ".env",
        ".env.local",
        ".ENV",
        "a/b/server.PEM",
        "k.key",
        "id_rsa",
        "id_rsa.pub",
        "x.p12",
        ".git/config",
        "web/node_modules/x/index.js",
        "NODE_MODULES/a.js",
    ],
)
def test_denies_env_and_keys_in_both_profiles(rel: str, profile: Profile) -> None:
    assert is_denied(rel, profile)
    assert not is_denied("src/main.py", profile)


def test_professional_denies_more_than_personal() -> None:
    for rel in ["secrets.json", "aws_credentials.txt", "a.sqlite", "dir/x.db"]:
        assert is_denied(rel, Profile.PROFESSIONAL)
        assert not is_denied(rel, Profile.PERSONAL)


def _write(root: Path, rel: str, data: bytes | str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


def test_list_files_respects_gitignore_in_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _write(tmp_path, ".gitignore", "ignored.txt\n")
    _write(tmp_path, "ignored.txt")
    _write(tmp_path, "keep.py")
    _write(tmp_path, ".env")
    assert list_files(tmp_path, Profile.PERSONAL) == [".gitignore", "keep.py"]


def test_list_files_non_git_walks_and_skips_denied_and_binary_and_huge(tmp_path: Path) -> None:
    _write(tmp_path, "b/ok.txt")
    _write(tmp_path, "a.py")
    _write(tmp_path, ".env")
    _write(tmp_path, ".git/config")
    _write(tmp_path, "node_modules/p/i.js")
    _write(tmp_path, "bin.dat", b"ab\x00cd")
    _write(tmp_path, "huge.txt", b"a" * (MAX_FILE_BYTES + 1))
    assert list_files(tmp_path, Profile.PROFESSIONAL) == ["a.py", "b/ok.txt"]


def test_anvylignore_patterns_apply(tmp_path: Path) -> None:
    _write(tmp_path, ".anvylignore", "# c\n\n*.log\nprivate/*\n")
    _write(tmp_path, "a.log")
    _write(tmp_path, "d/b.log")
    _write(tmp_path, "private/x.txt")
    _write(tmp_path, "k.txt")
    assert list_files(tmp_path, Profile.PERSONAL) == [".anvylignore", "k.txt"]


def test_empty_folder_lists_nothing(tmp_path: Path) -> None:
    assert list_files(tmp_path, Profile.PERSONAL) == []


def test_folder_with_spaces_works(tmp_path: Path) -> None:
    root = tmp_path / "my project dir"
    _write(root, "sub dir/a file.txt")
    assert list_files(root, Profile.PERSONAL) == ["sub dir/a file.txt"]
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    assert list_files(root, Profile.PERSONAL) == ["sub dir/a file.txt"]


def test_resolve_inside_rejects_dotdot_absolute_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _write(root, "ok.txt")
    outside = tmp_path / "outside.txt"
    outside.write_text("hi")
    assert resolve_inside(root, "ok.txt") == (root / "ok.txt").resolve()
    for bad in ["../outside.txt", "a/../../outside.txt", str(outside)]:
        with pytest.raises(ValueError):
            resolve_inside(root, bad)
    try:
        os.symlink(outside, root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        resolve_inside(root, "link.txt")


def test_resolve_inside_rejects_denied_file(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "A=1")
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, ".env")
    try:
        os.symlink(tmp_path / ".env", tmp_path / "innocent.txt")
    except (OSError, NotImplementedError):
        return
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, "innocent.txt")


def test_redact_aws_key_and_private_key_block() -> None:
    key = "AKIAIOSFODNN7EXAMPLE"
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\ndef\n-----END RSA PRIVATE KEY-----"
    text = f"id={key}\n{block}\ntoken = ghp_{'a' * 36}\npassword: hunter2\nsk-{'b' * 24}"
    out, n = redact(text)
    for s in [key, "MIIEabc", "hunter2", "ghp_aaaa", "sk-bbbb"]:
        assert s not in out
    assert n == 5
    assert "[redacted]" in out


def test_redact_leaves_normal_code_alone() -> None:
    code = 'password_field = form.get("x")\ndef token_count(n): return n\n'
    assert redact(code) == (code, 0)


@pytest.mark.parametrize(
    ("line", "secret"),
    [
        ("DB_PASSWORD=hunter2", "hunter2"),
        ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG", "wJalrXUtnFEMIK7MDENG"),
        ('"api_key": "abc123xyz"', "abc123xyz"),
        ("passwd=hunter2", "hunter2"),
        ("SECRET_KEY = x9y8z7", "x9y8z7"),
        ('password: "my secret pass"', "secret pass"),
        ("p = 'a b c'  # token: 'quoted tok'", "quoted tok"),
        ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
        (f"github_pat_{'A' * 30}", "AAAAAAAAAA"),
        (f"gho_{'z' * 30}", "zzzzzzzzzz"),
        (f"ghs_{'z' * 30}", "zzzzzzzzzz"),
    ],
)
def test_redact_secret_forms(line: str, secret: str) -> None:
    out, n = redact(line + "\nnext line")
    assert secret not in out
    assert n >= 1
    assert out.endswith("\nnext line")


def test_redact_pem_is_linear_time() -> None:
    import time

    text = "-----BEGIN RSA PRIVATE KEY-----\n" * 20_000
    start = time.perf_counter()
    out, n = redact(text)
    assert time.perf_counter() - start < 2
    assert "BEGIN" not in out
    assert n >= 1


@pytest.mark.parametrize(
    "rel",
    [
        "id_ed25519",
        "id_ecdsa.pub",
        "id_dsa",
        "a.pfx",
        "b.jks",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".git-credentials",
        ".ssh/config",
        "home/.SSH/known_hosts",
    ],
)
def test_denies_more_key_names(rel: str) -> None:
    assert is_denied(rel, Profile.PERSONAL)


def test_anvylignore_gitignore_forms(tmp_path: Path) -> None:
    _write(tmp_path, ".anvylignore", "/top.txt\nbuild/\nprivate\ndocs/**\n")
    for rel in [
        "top.txt",
        "sub/top.txt",
        "build/a.txt",
        "x/build/b.txt",
        "private/c.txt",
        "x/private/d.txt",
        "docs/e.md",
        "docs/f/g.md",
        "keep.txt",
    ]:
        _write(tmp_path, rel)
    assert list_files(tmp_path, Profile.PERSONAL) == [".anvylignore", "keep.txt", "sub/top.txt"]


def test_listing_excludes_symlink_to_denied(tmp_path: Path) -> None:
    _write(tmp_path, ".env", "A=1")
    _write(tmp_path, "ok.txt")
    try:
        os.symlink(tmp_path / ".env", tmp_path / "innocent.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert list_files(tmp_path, Profile.PERSONAL) == ["ok.txt"]


def test_resolve_inside_matches_listing_filters(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _write(tmp_path, ".gitignore", "gi.txt\n")
    _write(tmp_path, ".anvylignore", "ai.txt\n")
    _write(tmp_path, "gi.txt")
    _write(tmp_path, "ai.txt")
    _write(tmp_path, "big.txt", b"a" * (MAX_FILE_BYTES + 1))
    _write(tmp_path, "bin.dat", b"a\x00b")
    _write(tmp_path, "ok.txt")
    _write(tmp_path, "secrets.json")
    for bad in ["gi.txt", "ai.txt", "big.txt", "bin.dat", "missing.txt"]:
        with pytest.raises(ValueError):
            resolve_inside(tmp_path, bad)
    assert resolve_inside(tmp_path, "ok.txt") == (tmp_path / "ok.txt").resolve()
    with pytest.raises(ValueError):
        resolve_inside(tmp_path, "secrets.json")
    assert resolve_inside(tmp_path, "secrets.json", Profile.PERSONAL).name == "secrets.json"


@pytest.mark.parametrize(
    "code",
    [
        'password_field = form.get("x")',
        "pwd = os.getcwd()",
        "tokens = tokenize(text)",
        "max_tokens: 1024",
        "password_hash = bcrypt(x)",
        "token_count: int = 0",
        "def f(api_key: str = None):",
        "const secretKey = getSecret();",
        "if token == expected:",
        "x = {'token': token}",
        'SECRET_KEY = os.environ["X"]',
    ],
)
def test_redact_leaves_ordinary_code_alone(code: str) -> None:
    assert redact(code + "\n") == (code + "\n", 0)


def test_redact_quoted_literal_keeps_surrounding_code() -> None:
    out, n = redact("password = 'my pass' + suffix")
    assert "my pass" not in out
    assert out.endswith("+ suffix")
    assert n == 1


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("DB_PASSWORD=hunter2\r\nX=1\r\n", "hunter2"),
        ("password: hunter2\r\nX: 1\r\n", "hunter2"),
        ("[db]\npassword = hunter2\n", "hunter2"),
        ("Password = hunter2\n", "hunter2"),
        ("db_password = hunter2\n", "hunter2"),
        ("api-key = abc123\n", "abc123"),
        ("client_secret: abc123\n", "abc123"),
        ("db.password=hunter2\n", "hunter2"),
        ("spring.datasource.password=hunter2\n", "hunter2"),
        ("  - password: hunter2 # note\n", "hunter2"),
        ("export API_KEY=abc123\n", "abc123"),
    ],
)
def test_redact_config_file_forms(text: str, secret: str) -> None:
    out, n = redact(text)
    assert secret not in out
    assert n == 1


@pytest.mark.parametrize(
    "code",
    [
        "max_tokens: 1024",
        "token_count = 0",
        "use_token: true",
        "TOKEN = None",
        "secret: null",
        "ratio_token: 0.5",
    ],
)
def test_redact_ignores_numbers_and_literals_words(code: str) -> None:
    assert redact(code + "\n") == (code + "\n", 0)


def test_redact_adversarial_single_lines_are_fast() -> None:
    import time

    for text in [
        "a-" * 100_000,
        "a" * 200_000,
        " " * 200_000,
        "password=" * 25_000,
        "token: '" * 25_000,
        "-----BEGIN PRIVATE KEY-----" * 8_000,
    ]:
        start = time.perf_counter()
        redact(text)
        assert time.perf_counter() - start < 2


def test_redact_overlong_and_unterminated_quoted_values() -> None:
    long_secret = "s3cr3t" * 900
    out, n = redact(f'password = "{long_secret}"\nnext')
    assert "s3cr3t" not in out
    assert out.endswith("\nnext")
    assert n == 1
    out, n = redact("api_key = 'abc123unterminated\nnext")
    assert "abc123" not in out
    assert out.endswith("\nnext")


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("DB_PWD=hunter2\n", "hunter2"),
        ("db_pwd = 'hunter2'\n", "hunter2"),
        ("DB_PWD: hunter2\n", "hunter2"),
        ("db-pwd = hunter2\n", "hunter2"),
        ("PWD=hunter2\n", "hunter2"),
    ],
)
def test_redact_pwd_suffix_keys(text: str, secret: str) -> None:
    out, n = redact(text)
    assert secret not in out
    assert n == 1


@pytest.mark.parametrize("code", ["pwd = os.getcwd()", "pwd = x", "pwd = 'x'", "pwd: here"])
def test_redact_bare_lowercase_pwd_untouched(code: str) -> None:
    assert redact(code + "\n") == (code + "\n", 0)


_SOURCE_NEGATIVES = [
    "self.token = token",
    "self.api_key = api_key",
    "api_key = api_key",
    "token = token",
    "    password = password",
    "password = user.password",
    "token = auth.token",
    "secret = settings.SECRET_KEY",
    "token_type: str",
    "  secret_key: SecretStr",
    "password_hash = other_identifier",
    "    password: str",
    "  token: string;",
    "token: string",
    "    token: Token",
    "token = ''",
    "TOKEN_LIMIT = MAX",
    "token = next_token()",
    'secret = os.environ["SECRET"]',
    'password = input("pw")',
    "password: str",
    "api_key: Optional[str] = None",
    "max_tokens = 100",
    "password?: string",
]


@pytest.mark.parametrize("path", ["x.py", "x.ts"])
@pytest.mark.parametrize("line", _SOURCE_NEGATIVES)
def test_redact_source_files_keep_code(path, line):
    text = line + "\n"
    assert redact(text, path) == (text, 0)


@pytest.mark.parametrize(
    "text,secret",
    [
        ('password = "hunter2"\n', "hunter2"),
        ("API_KEY=abc123\n", "abc123"),
        ("x = 'ghp_" + "a" * 36 + "'\n", "ghp_" + "a" * 36),
        ("auth = f(Bearer abcdefghijklmnopqrstuv)\n", "abcdefghijklmnopqrstuv"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n", "MIIabc"),
        ('{"password": "x"}\n', '"x"'),
    ],
)
def test_redact_source_files_still_catch_secrets(text, secret):
    out, n = redact(text, "app.py")
    assert secret not in out and n > 0


_CONFIG_POSITIVES = [
    ("password=hunter2\r\n", "hunter2"),
    ("[db]\npassword = hunter2\n", "hunter2"),
    ("Password = hunter2\n", "hunter2"),
    ("db_password = hunter2\n", "hunter2"),
    ("api-key = abc123\n", "abc123"),
    ("client_secret: abc123\n", "abc123"),
    ("db.password=hunter2\n", "hunter2"),
    ("spring.datasource.password=hunter2\n", "hunter2"),
    ("  - password: hunter2\n", "hunter2"),
    ("password: 12345678\n", "12345678"),
    ("SECRET=123456\n", "123456"),
]


@pytest.mark.parametrize(
    "path", [".env", "app.ini", "config.yaml", "x.properties", "settings.toml", None]
)
@pytest.mark.parametrize("text,secret", _CONFIG_POSITIVES)
def test_redact_config_files_broad_rule(path, text, secret):
    out, n = redact(text, path)
    assert secret not in out and n > 0


@pytest.mark.parametrize("line", ["max_tokens: 1024\n", "token_count: 0\n", "debug: true\n"])
def test_redact_config_token_numbers_stay(line):
    assert redact(line, "config.yaml") == (line, 0)


@pytest.mark.parametrize(
    "path,text,secret",
    [
        ("Dockerfile", "ENV DB_PASSWORD=hunter2\n", "hunter2"),
        ("notes.txt", "password: hunter2\n", "hunter2"),
        ("passwords.txt", "admin password = hunter2\n", "hunter2"),
        ("x.tfvars", "db_password = hunter2\n", "hunter2"),
        ("Makefile", "API_KEY = abc123\n", "abc123"),
        ("x.foo", "secret: abc123\n", "abc123"),
        ("deploy.sh", "password=hunter2\n", "hunter2"),
        ("nb.ipynb", "password = hunter2\n", "hunter2"),
    ],
)
def test_redact_unknown_and_text_files_get_config_rule(path, text, secret):
    out, n = redact(text, path)
    assert secret not in out and n > 0


@pytest.mark.parametrize("path", ["x.go", "X.java", "x.md", "x.rs", "x.c"])
@pytest.mark.parametrize("line", _SOURCE_NEGATIVES)
def test_redact_code_extensions_keep_code(path, line):
    text = line + "\n"
    assert redact(text, path) == (text, 0)
