from pathlib import Path

from keenetic_dns.core import install as I


def test_paths_and_not_frozen(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert I.installed_exe() == tmp_path / "Programs" / "KeenRoute" / "KeenRoute.exe"
    assert I.current_exe() is None and not I.is_installed()  # из исходников — не exe


def test_install_copies(monkeypatch, tmp_path):
    exe = tmp_path / "Downloads" / "KeenRoute.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(I.sys, "frozen", True, raising=False)
    monkeypatch.setattr(I.sys, "executable", str(exe))
    made = []
    monkeypatch.setattr(I, "create_shortcuts", lambda t: made.append(t) or [])
    dst = I.install()
    assert dst.read_bytes() == b"MZ" and made == [dst]
    assert I._q("C:\\it's") == "'C:\\it''s'"
    assert not I.is_installed()
    monkeypatch.setattr(I.sys, "executable", str(dst))
    assert I.is_installed()
