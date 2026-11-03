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
