from keenetic_dns.core import updater as U


def test_versions():
    assert U.parse_version("v0.4.12") == (0, 4, 12)
    assert U.parse_version("0.4.12") > U.parse_version("0.4.9")
    r = U.Release("v99.0.1", "", "", "", 0)
    assert r.newer
    assert not U.Release("v0.0.1", "", "", "", 0).newer


def test_check_parses_release(monkeypatch):
    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"tag_name": "v0.4.20", "body": "fix", "assets": [
                {"name": "KeenRoute.exe", "url": "api/1", "browser_download_url": "dl/1", "size": 5}]}
    monkeypatch.setattr(U.requests, "get", lambda *a, **k: R())
    rel = U.check("tok")
    assert rel.version == "v0.4.20" and rel.asset_url == "api/1" and rel.size == 5


def test_install_and_restart_rename(monkeypatch, tmp_path):
    cur = tmp_path / "KeenRoute.exe"
    cur.write_bytes(b"old")
    new = tmp_path / "KeenRoute.new.exe"
    new.write_bytes(b"new")
    monkeypatch.setattr(U.sys, "frozen", True, raising=False)
    monkeypatch.setattr(U.sys, "executable", str(cur))
    started = []
    monkeypatch.setenv("_MEIPASS2", "C:/tmp/_MEI123")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/tmp/_MEI123")
    envs = []
    monkeypatch.setattr(U.subprocess, "Popen", lambda args, **k: (started.append(args), envs.append(k["env"])))
    assert U._download_dir() == tmp_path  # качаем рядом с exe
    U.install_and_restart(new)
    assert cur.read_bytes() == b"new" and (tmp_path / "KeenRoute.old.exe").read_bytes() == b"old"
    assert started == [[str(cur.resolve())]]
    assert envs[0]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_MEIPASS2" not in envs[0] and "_PYI_APPLICATION_HOME_DIR" not in envs[0]
    U.cleanup_old()
    assert not (tmp_path / "KeenRoute.old.exe").exists()
