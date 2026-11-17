# MAX mini-app: server-side authorization contract

This repository contains **only the FastAPI backend**, not the web page opened from the MAX button.

## Two distinct tokens

1. `CORE_SERVICE_TOKEN` is a long-lived credential issued to the team and stored **only on the backend**. Never put it in a URL, React code, `.env.example`, a Git commit, issue, log, or chat message. Rotate it if it has been exposed.
2. The **user JWT** is a short-lived token in the **mini-app launch URL** (`https://web.example/?token=<USER_JWT>`), valid for approximately five minutes. The browser sends it **once** to the backend to obtain an application session. This is **not** the service token.

## Backend environment (on the API server)

```dotenv
CORE_URL=https://tm-test-yakut.hostco.ru
CORE_SERVICE_TOKEN=
SESSION_SIGNING_KEY=
DEMO_MODE=false
CORS_ORIGINS=https://web.example
FRAME_ANCESTORS='self'
```

Supply `CORE_SERVICE_TOKEN` and a separately generated, random `SESSION_SIGNING_KEY` (at least 32 characters) through the hosting provider's secret settings. Never commit a populated `.env`. The `CORS_ORIGINS` value must exactly match the deployed frontend origin, without a trailing slash. An iframe-based API-only backend does not itself need to be embedded; `FRAME_ANCESTORS` is mainly relevant if you choose to serve pages from this backend later.

## Browser-to-backend contract

The frontend team should read `token` from its opening URL, POST it to the backend **in the request body**, then remove it from the address bar (e.g. `history.replaceState`). The browser must never call Core directly.

```http
POST https://api.example/api/v1/auth/launch
Content-Type: application/json

{"mode":"host","host_token":"<USER_JWT_FROM_URL>"}
```

Upon a successful Core verification, the API returns:

```json
{"access_token":"<OUR_APP_TOKEN>","token_type":"bearer","expires_in":3600}
```

The frontend uses that **app token**, not the MAX JWT, in `Authorization: Bearer <OUR_APP_TOKEN>` when accessing `/api/v1/sessions` and other routes. The expiry of the original MAX JWT does not end the already issued app session. The frontend must not retain the MAX JWT in localStorage, server access logs, browser history, or telemetry.

## Backend-to-Core request (performed server-side)

```http
GET https://tm-test-yakut.hostco.ru/api/v3/users/user-for-external-service?token=<USER_JWT_FROM_URL>
Authorization: Bearer <CORE_SERVICE_TOKEN>
```

Core verifies JWT validity/expiry and responds with a user profile. The API uses **only `_id`** as a stable owner identity and deliberately discards `SNILS`, `OMS`, `phone`, `birthDate`, and `full_name`. No identifying profile is returned in the frontend launch response. This is a synthetic/demo-only prototype, and should not process real medical complaints.

- Core 401 or 404: `401 invalid_host_token` (ask user to open MAX mini-app again).
- Core 403: `503 host_service_unauthorized` (server credential or permission problem; check **server-side** secret).
- Network failure, timeout or Core 5xx: `503 host_auth_unavailable`.
- Invalid/missing Core `_id`: `503 host_auth_invalid_response`.
- Missing backend `CORE_SERVICE_TOKEN`: `503 host_auth_not_configured`.

## URL to send the organizers

Send the **public HTTPS URL of the frontend web application** (React app) as the MAX button target, for example `https://web.example/` with no token hardcoded. The host mini-app adds `?token=<USER_JWT>` automatically. **Do not** send the Core URL, `http://127.0.0.1:8000`, or `https://api.example/docs` to the organizers as the mini-app target: those are not the interactive web app.

The separately deployed backend has its own HTTPS API origin `https://api.example`, which the frontend calls over CORS. Both URLs must be deployed before a full end-to-end test inside MAX.

## Testing

```bash
python -m pytest -q tests
```

Tests use `httpx.MockTransport` and **synthetic** data, so no live Core requests or API tokens are needed. Integration with a real MAX launch requires a newly issued user JWT and a valid service credential. The public URLs are deployment outputs; this code package cannot know them in advance.
