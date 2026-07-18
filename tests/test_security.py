def test_private_api_requires_auth(client):
    assert client.get("/api/dashboard").status_code == 401
    assert client.post("/api/library/scan").status_code == 401


def test_login_and_csrf(authenticated):
    client, csrf = authenticated
    assert client.get("/api/dashboard").status_code == 200
    assert client.post("/api/library/scan").status_code == 403
    assert client.post(
        "/api/library/scan", headers={"X-CSRF-Token": csrf}
    ).status_code == 200


def test_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_secure_headers(client):
    response = client.get("/health")
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_settings_never_return_secrets(authenticated):
    client, _ = authenticated
    payload = client.get("/api/settings").json()
    assert "plex_token" in payload
    assert payload["plex_token"] in {"", "[CONFIGURED]"}
    assert "api_key" not in str(payload).lower() or payload["emby_api_key"] in {"", "[CONFIGURED]"}
