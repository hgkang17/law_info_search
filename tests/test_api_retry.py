"""법제처 HTTP 재시도. 실제 네트워크는 쓰지 않는다."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

import molit_cgm_expc_api as api


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "{}", json_data=None) -> None:
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code}")
            error.response = SimpleNamespace(status_code=self.status_code)
            raise error

    def json(self):
        return self._json


def test_request_retries_404_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return _FakeResponse(404, "")
        return _FakeResponse(200, '{"ok": true}', {"ok": True})

    monkeypatch.setattr(api.requests, "get", fake_get)
    monkeypatch.setattr(api.time, "sleep", lambda *_: None)
    response = api._request("https://www.law.go.kr/DRF/lawSearch.do", {}, timeout=5)
    assert response.status_code == 200
    assert calls["n"] == 3


def test_request_rejects_persistent_html_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api.requests,
        "get",
        lambda *a, **k: _FakeResponse(200, "<!DOCTYPE html><html>점검</html>"),
    )
    monkeypatch.setattr(api.time, "sleep", lambda *_: None)
    with pytest.raises(ValueError, match="HTML"):
        api._request(
            "https://www.law.go.kr/DRF/lawService.do",
            {},
            timeout=5,
            expect_json=True,
        )
