import httpx

from app.integrations.emby import EmbyClient
from app.integrations.plex import PlexClient


def test_plex_connection_and_libraries(monkeypatch):
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(200, json={"MediaContainer": {"friendlyName": "Home", "version": "1.2"}})
        return httpx.Response(200, json={"MediaContainer": {"Directory": [{"key": "7", "title": "Videos", "type": "movie"}]}})
    monkeypatch.setattr(PlexClient, "_client", lambda self: httpx.Client(transport=httpx.MockTransport(handler), base_url="http://plex"))
    client = PlexClient("http://plex", "never-print-me")
    assert client.test().name == "Home"
    assert client.libraries()[0].id == "7"


def test_emby_connection_and_libraries(monkeypatch):
    def handler(request):
        if request.url.path == "/System/Info/Public":
            return httpx.Response(200, json={"ServerName": "Emby", "Version": "4.8"})
        return httpx.Response(200, json=[{"ItemId": "9", "Name": "Music Videos", "Locations": ["/videos"]}])
    monkeypatch.setattr(EmbyClient, "_client", lambda self: httpx.Client(transport=httpx.MockTransport(handler), base_url="http://emby"))
    client = EmbyClient("http://emby", "never-print-me")
    assert client.test().name == "Emby"
    assert client.libraries()[0].id == "9"


def test_offline_errors_redact_credentials():
    result = PlexClient("http://127.0.0.1:1", "super-secret", timeout=0.01).test()
    assert not result.ok
    assert "super-secret" not in result.error
