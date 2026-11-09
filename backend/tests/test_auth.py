from datetime import UTC, datetime, timedelta

import jwt


def test_healthz_reports_db(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "up"}
    assert r.headers["x-request-id"]


def test_register_login_me(client) -> None:
    r = client.post("/api/auth/register", json={"name": "Ravi", "email": "Ravi@Example.com", "password": "s3cret-pass"})
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "ravi@example.com"
    login = client.post("/api/auth/login", json={"email": "ravi@example.com", "password": "s3cret-pass"})
    assert login.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert me.json()["name"] == "Ravi"


def test_password_is_hashed_not_stored(client, db) -> None:
    from app.models import User

    client.post("/api/auth/register", json={"name": "Ravi", "email": "ravi@example.com", "password": "s3cret-pass"})
    u = db.query(User).one()
    assert u.password_hash.startswith("$2") and "s3cret-pass" not in u.password_hash


def test_long_unicode_password_works(client) -> None:
    pw = "मेरा-बहुत-लंबा-पासवर्ड-" * 3  # > 72 bytes in UTF-8
    assert client.post("/api/auth/register", json={"name": "Ravi", "email": "r@example.com", "password": pw}).status_code == 201
    assert client.post("/api/auth/login", json={"email": "r@example.com", "password": pw}).status_code == 200


def test_duplicate_email_rejected(client) -> None:
    body = {"name": "Ravi", "email": "ravi@example.com", "password": "s3cret-pass"}
    client.post("/api/auth/register", json=body)
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_wrong_password_and_unknown_email_look_the_same(client) -> None:
    client.post("/api/auth/register", json={"name": "Ravi", "email": "ravi@example.com", "password": "s3cret-pass"})
    a = client.post("/api/auth/login", json={"email": "ravi@example.com", "password": "nope"})
    b = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"]["message"] == b.json()["error"]["message"]


def test_validation_errors_have_consistent_shape(client) -> None:
    r = client.post("/api/auth/register", json={"name": "R", "email": "not-an-email", "password": "short"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error" and err["request_id"]
    assert {d["field"] for d in err["details"]} == {"name", "email", "password"}


def test_protected_route_needs_valid_token(client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).json()["error"]["code"] == "unauthorized"


def test_expired_token_rejected(client) -> None:
    from app.config import get_settings

    r = client.post("/api/auth/register", json={"name": "Ravi", "email": "ravi@example.com", "password": "s3cret-pass"})
    uid = r.json()["user"]["id"]
    old = datetime.now(UTC) - timedelta(hours=10)
    token = jwt.encode({"sub": uid, "iat": old, "exp": old + timedelta(hours=1)}, get_settings().jwt_secret, algorithm="HS256")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


def test_demo_login_is_idempotent_and_cannot_password_login(client) -> None:
    a = client.post("/api/auth/demo").json()
    b = client.post("/api/auth/demo").json()
    assert a["user"]["id"] == b["user"]["id"] and a["user"]["is_demo"]
    r = client.post("/api/auth/login", json={"email": "demo@kaagaz.demo", "password": "anything"})
    assert r.status_code == 401


def test_cors_allows_only_frontend_origin(client) -> None:
    ok = client.options("/api/auth/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/auth/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_rate_limiter_blocks_after_limit() -> None:
    import pytest

    from app.errors import ApiError
    from app.ratelimit import RateLimiter

    t = [0.0]
    rl = RateLimiter(clock=lambda: t[0])
    for _ in range(3):
        rl.hit("ask", "u1", limit=3)
    with pytest.raises(ApiError) as e:
        rl.hit("ask", "u1", limit=3)
    assert e.value.status == 429
    rl.hit("ask", "u2", limit=3)  # other users are not affected
    t[0] = 3601
    rl.hit("ask", "u1", limit=3)  # window slid
