from urllib.parse import urlparse

from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings
from utils.rate_limiter import default_limiter, rate_limit_exceeded_handler

# ── Security response headers ─────────────────────────────────────────
# Baseline for an API backend. Critical protections: X-Frame-Options
# (clickjacking), X-Content-Type-Options (MIME sniffing), HSTS (TLS
# enforcement), CSP frame-ancestors (clickjacking, modern equivalent).
# CSP default-src='none' is strict-but-safe because the backend serves
# JSON almost exclusively; Swagger UI / ReDoc / openapi.json need a
# relaxed CSP to load external assets from cdn.jsdelivr.net, so those
# paths are exempted.

_BASE_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}

_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

# Relaxed CSP for FastAPI's built-in docs. Swagger UI + ReDoc pull
# scripts and styles from jsdelivr; they also use inline styles.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'"
)

_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def _apply_security_headers(response: Response, path: str, enable_hsts: bool) -> None:
    """Attach the baseline security headers to a response.

    Uses dict-style assignment (rather than setdefault) so that upstream
    handlers that set weaker values get overridden by our stricter ones.
    """
    for k, v in _BASE_SECURITY_HEADERS.items():
        response.headers[k] = v

    if enable_hsts:
        # 1 year, include subdomains, eligible for preload.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

    if any(path.startswith(p) for p in _DOCS_PATHS):
        response.headers["Content-Security-Policy"] = _DOCS_CSP
    else:
        response.headers["Content-Security-Policy"] = _STRICT_CSP


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a conservative set of security response headers to every
    response. HSTS only when ENV=production so local dev over HTTP still
    works in browsers that cache HSTS aggressively.
    """

    def __init__(self, app, enable_hsts: bool):
        super().__init__(app)
        self._enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        _apply_security_headers(response, request.url.path, self._enable_hsts)
        return response


class MetricsGuardMiddleware(BaseHTTPMiddleware):
    """Gate ``/metrics`` on one of: bearer token OR client-IP allow-list.

    Phase 2.3e of the production-readiness audit (audit finding T3).

    The Prometheus endpoint is installed by
    ``prometheus-fastapi-instrumentator`` and exposes internal metric
    names/values — ride counts, stripe queue depth, active WebSocket
    connections. That is enough reconnaissance to help an attacker
    figure out which subsystem to probe next, so we lock it down at
    the HTTP layer.

    Auth model (either / both work — OR semantics):
      * ``Authorization: Bearer <METRICS_BEARER_TOKEN>`` — Prometheus
        speaks this via its ``bearer_token_file`` scrape config.
      * Client IP in one of the ``METRICS_IP_ALLOWLIST`` CIDRs —
        Fly's internal metrics sidecar scrapes over 6PN private IPs
        so the operator can allow-list ``fd00::/8`` instead of
        managing bearer secrets.

    Dev (ENV != production) is open by default unless *either* env
    var is set — that keeps ``curl localhost:8000/metrics`` working
    during local dashboard work without a token.
    """

    def __init__(self, app, bearer_token: str, ip_allowlist_cidrs: tuple[str, ...], require_auth: bool):
        super().__init__(app)
        self._bearer_token = bearer_token or ""
        # Pre-parse CIDRs to avoid re-parsing on every scrape. Invalid
        # entries are dropped with a warning at init time.
        import ipaddress

        self._networks: list[ipaddress._BaseNetwork] = []
        for raw in ip_allowlist_cidrs:
            raw = raw.strip()
            if not raw:
                continue
            try:
                # strict=False lets operators write "10.0.0.0/8" instead
                # of having to zero the host bits themselves.
                self._networks.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                logger.warning(f"MetricsGuard: skipping invalid CIDR {raw!r}")
        self._require_auth = require_auth

    def _client_ip(self, request: Request) -> str | None:
        """Resolve the remote client IP honouring X-Forwarded-For.

        Fly's edge proxy sets ``Fly-Client-IP`` and also populates
        ``X-Forwarded-For``; we honour the latter as it's the industry
        standard. Take the LEFTMOST XFF entry because the leftmost
        represents the original client; the rightmost is the proxy
        closest to us (untrustworthy for allow-list decisions).
        """
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
        fly_client = request.headers.get("fly-client-ip")
        if fly_client:
            return fly_client.strip()
        if request.client:
            return request.client.host
        return None

    def _ip_allowed(self, ip_str: str | None) -> bool:
        if not self._networks or not ip_str:
            return False
        import ipaddress

        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        return any(ip in net for net in self._networks)

    def _bearer_matches(self, request: Request) -> bool:
        if not self._bearer_token:
            return False
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return False
        # Constant-time compare so we don't leak the token through
        # timing differences on mismatch.
        import hmac

        presented = auth.split(" ", 1)[1].strip()
        return hmac.compare_digest(presented, self._bearer_token)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Only guard the scrape endpoint itself — /health and /health/deep
        # are explicitly public (uptime checks, load balancer probes).
        if path != "/metrics":
            return await call_next(request)

        # Dev fall-through: if neither mechanism is configured AND we're
        # not in production, let the scrape through. This keeps
        # `curl localhost:8000/metrics` working during local dashboard
        # work without forcing every developer to plumb a token.
        if not self._require_auth and not self._bearer_token and not self._networks:
            return await call_next(request)

        if self._bearer_matches(request):
            return await call_next(request)

        client_ip = self._client_ip(request)
        if self._ip_allowed(client_ip):
            return await call_next(request)

        # 401 not 403 — 401 tells a well-behaved scraper (Prometheus)
        # that retrying with a credential would work. 403 is for "I
        # know who you are and I still said no" which isn't the case
        # here: we don't know who the caller is.
        logger.warning(f"MetricsGuard: denied /metrics scrape from {client_ip}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": 'Bearer realm="metrics"'},
        )


_INSECURE_JWT_DEFAULTS = {
    "your-strong-secret-key",  # core/config.py default
    "spinr-dev-secret-key-NOT-FOR-PRODUCTION",  # previous dependencies.py fallback
    "replace-with-strong-random-secret",  # backend/.env.example placeholder
}
_MIN_JWT_SECRET_LENGTH = 32

# Bootstrap credentials that must be overridden before the dashboard
# is exposed publicly — otherwise anyone who reads the source can log
# in as the super-admin. These are the defaults shipped in
# core/config.py; production deploys must set real values via env vars.
_INSECURE_ADMIN_EMAILS = {"admin@spinr.ca", "admin@example.com"}
_INSECURE_ADMIN_PASSWORDS = {"admin123", "replace-me", "changeme", "password", "Admin12345", "TempPass123!"}

# Supabase service-role keys are signed JWTs (ES256/HS256), ~220 chars,
# always starting with "eyJ" (base64-encoded JSON header). The .env.example
# ships a "replace-with-service-role-key" placeholder; shipping that to
# production would produce silent 401s from every DB call. Reject it and
# anything that clearly isn't a real key. We intentionally do NOT do a
# full JWT parse — that would require trusting Supabase's rotating JWKS
# — we just gate on obvious structural markers.
_SUPABASE_KEY_MIN_LENGTH = 40
_SUPABASE_KEY_PREFIX = "eyJ"

# Placeholder markers in SUPABASE_URL from backend/.env.example. A deploy
# pointing at the example project ref will 404 every query.
_SUPABASE_URL_PLACEHOLDERS = ("your-project-ref", "your-project", "example.supabase.co")


def _validate_production_config():
    """Fail fast on misconfigured production deploys.

    Called at the top of init_middleware so the server never actually
    starts serving requests with a known-insecure configuration. All
    checks only fire when ``ENV=production``; dev/local environments
    get usable defaults.
    """
    if settings.ENV.lower() != "production":
        return

    errors: list[str] = []

    # 1. JWT signing secret
    secret = settings.JWT_SECRET or ""
    if secret in _INSECURE_JWT_DEFAULTS:
        errors.append(
            "JWT_SECRET is set to a well-known default. Generate a strong "
            "secret (python -c 'import secrets; print(secrets.token_urlsafe(64))') "
            "and set JWT_SECRET in the environment."
        )
    elif len(secret) < _MIN_JWT_SECRET_LENGTH:
        errors.append(f"JWT_SECRET is shorter than {_MIN_JWT_SECRET_LENGTH} characters. Use a longer, random secret.")

    # 2. Supabase credentials — the entire backend is Supabase-backed,
    #    so an unset URL or service role key means the server comes up
    #    but every DB call hits a NoneType client. We also reject the
    #    .env.example placeholders so a half-configured deploy can't
    #    reach production (audit P0-S5).
    supabase_url = (settings.SUPABASE_URL or "").strip()
    if not supabase_url:
        errors.append("SUPABASE_URL is not set.")
    elif any(marker in supabase_url for marker in _SUPABASE_URL_PLACEHOLDERS):
        errors.append(
            "SUPABASE_URL looks like the .env.example placeholder "
            f"({supabase_url}). Set it to your real Supabase project URL "
            "(https://<project-ref>.supabase.co)."
        )

    service_key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    if not service_key:
        errors.append("SUPABASE_SERVICE_ROLE_KEY is not set.")
    elif not service_key.startswith(_SUPABASE_KEY_PREFIX):
        # Real Supabase service-role keys are JWTs; they always start
        # with "eyJ". A value that doesn't is a placeholder, a typo, or
        # someone pasted the anon key and dropped the header.
        errors.append(
            "SUPABASE_SERVICE_ROLE_KEY does not look like a real Supabase "
            "service-role JWT (expected to start with 'eyJ'). Copy the key "
            "from Supabase → Settings → API and paste it verbatim. NEVER "
            "commit this value — it bypasses RLS."
        )
    elif len(service_key) < _SUPABASE_KEY_MIN_LENGTH:
        errors.append(
            f"SUPABASE_SERVICE_ROLE_KEY is only {len(service_key)} chars; real keys are ~220. "
            "Check that the value was copied in full (a truncated key silently 401s every DB call)."
        )

    # 3. Admin bootstrap credentials — the super-admin login path in
    #    routes/admin/auth.py compares directly against these strings.
    admin_email = (settings.ADMIN_EMAIL or "").lower().strip()
    admin_password = settings.ADMIN_PASSWORD or ""
    if admin_email in _INSECURE_ADMIN_EMAILS:
        errors.append(
            "ADMIN_EMAIL is set to a well-known default. Set a real "
            "admin email in the environment before exposing the dashboard."
        )
    if admin_password in _INSECURE_ADMIN_PASSWORDS:
        errors.append(
            "ADMIN_PASSWORD is set to a well-known default. Set a strong "
            "password in the environment before exposing the dashboard."
        )
    elif len(admin_password) < 12:
        errors.append("ADMIN_PASSWORD is shorter than 12 characters. Use a stronger password.")

    # 4. Rate limiter storage — a multi-machine Fly deploy with
    #    "memory://" slowapi storage means each machine keeps its own
    #    counters, so 5/minute OTP limits become (5 × N_machines)/minute
    #    as LB stickiness shifts. Require a redis:// URL in production.
    redis_url = (settings.RATE_LIMIT_REDIS_URL or "").strip()
    if not redis_url:
        errors.append(
            "RATE_LIMIT_REDIS_URL is not set. Production rate limiting "
            "requires a shared Redis backend (e.g. Upstash / Fly Redis). "
            "Set RATE_LIMIT_REDIS_URL=redis://… or rediss://… before booting."
        )
    elif not (redis_url.startswith("redis://") or redis_url.startswith("rediss://")):
        errors.append(
            "RATE_LIMIT_REDIS_URL must start with redis:// or rediss:// "
            f"(got scheme from: {redis_url.split('://', 1)[0]}://…)."
        )

    # 5. Firebase service account — required for Firebase Auth verify
    #    and for FCM push delivery. Missing means get_current_user can't
    #    verify Firebase-issued tokens and send_push_notification no-ops.
    #    Warn rather than fail because a deploy MIGHT be intentionally
    #    running without Firebase (e.g. SMS-only auth via Twilio + a
    #    local push transport).
    if not settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        logger.warning(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not set — Firebase ID token "
            "verification and FCM push delivery will no-op. Set it if you "
            "want drivers to receive push notifications."
        )

    # 6. Sentry DSN (Phase 2.2 / audit T1). Production deploys without
    #    Sentry fly blind: errors go to loguru only, which is per-machine
    #    and has no alerting story. The SDK is already wired in
    #    server.py; this gate just ensures the DSN is actually present
    #    so deploys don't silently ship without error reporting.
    sentry_dsn = (settings.sentry_dsn or "").strip()
    if not sentry_dsn:
        errors.append(
            "SENTRY_DSN is not set. Production deploys must have Sentry "
            "configured so unhandled exceptions and tracebacks reach an "
            "alerting backend — loguru-only logging means crashes never "
            "page anyone. Set SENTRY_DSN=https://…@…ingest.sentry.io/… "
            "before booting."
        )
    elif not sentry_dsn.startswith(("https://", "http://")):
        # Common copy-paste mistake: pasting the Sentry project URL or
        # key fragment instead of the full DSN. Fail loudly.
        errors.append(f"SENTRY_DSN does not look like a DSN URL (should start with https://). Got: {sentry_dsn[:40]}…")

    # 7. /metrics protection (Phase 2.3e / audit T3). The endpoint
    #    leaks internal metric names/values; at minimum it gives an
    #    attacker a ride-count view (how many rides, how many drivers
    #    online, stripe queue depth). Require one of bearer token OR
    #    IP allow-list in production. Either is fine — Prometheus
    #    speaks bearer; Fly's metrics sidecar speaks private IP.
    metrics_bearer = (settings.metrics_bearer_token or "").strip()
    metrics_allowlist = (settings.metrics_ip_allowlist or "").strip()
    if not metrics_bearer and not metrics_allowlist:
        errors.append(
            "Neither METRICS_BEARER_TOKEN nor METRICS_IP_ALLOWLIST is set. "
            "In production, /metrics must be protected — leaving it open "
            "exposes internal service metrics (ride counts, queue depths, "
            "active connections) to anyone on the public internet. Set at "
            "least one of:\n"
            "    METRICS_BEARER_TOKEN=$(openssl rand -hex 32)\n"
            "    METRICS_IP_ALLOWLIST=10.0.0.0/8,fd00::/8   # Fly 6PN"
        )
    elif metrics_bearer and len(metrics_bearer) < 24:
        # Short tokens are a guessability risk; 32-byte random hex is
        # standard for bearer secrets.
        errors.append(
            f"METRICS_BEARER_TOKEN is only {len(metrics_bearer)} chars; "
            "use at least 24 (ideally `openssl rand -hex 32`)."
        )

    if errors:
        formatted = "\n  - ".join(errors)
        raise RuntimeError(
            f"Refusing to start: production configuration has {len(errors)} problem(s).\n  - {formatted}"
        )


def init_middleware(app):
    """Initialize all middleware components"""
    # Fail-fast on misconfigured production deploys BEFORE any routes
    # or middleware are attached. See _validate_production_config.
    _validate_production_config()

    is_production = settings.ENV.lower() == "production"

    # CORS Middleware
    origins = [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]

    # Always allow the admin and default apps explicitly regardless of env variables
    always_allowed = ["https://spinr-admin.vercel.app", "http://localhost:3000", "http://localhost:3001"]
    origins.extend(always_allowed)
    # Remove empty strings and duplicates (preserve order for determinism)
    origins = list(dict.fromkeys(o for o in origins if o))

    wildcard = "*" in origins

    if wildcard and is_production:
        # Fail fast: refuse to start with wide-open CORS in production.
        # Set ALLOWED_ORIGINS in the environment to a comma-separated list.
        raise RuntimeError(
            "CORS is configured with wildcard '*' while ENV=production. "
            "Set ALLOWED_ORIGINS to an explicit comma-separated list of origins."
        )

    # CORS spec forbids credentials with wildcard origin — browsers will drop
    # the Access-Control-Allow-Credentials header if origin is '*'. Disable
    # credentials in that case so dev requests fail loudly rather than silently.
    allow_credentials = not wildcard
    if wildcard:
        logger.warning(
            "CORS: wildcard '*' in ALLOWED_ORIGINS — allow_credentials disabled. This is acceptable for local dev only."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security headers — applied after CORS so that every response
    # (including CORS preflight 204s) carries the hardening headers.
    # HSTS is only enabled in production because emitting it over
    # plain-HTTP dev would cause browsers to pin the dev host to HTTPS.
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=is_production)

    # /metrics gate (Phase 2.3e / audit T3). Installed BEFORE the
    # prometheus-fastapi-instrumentator's /metrics handler runs, so
    # unauthorised scrapes get a 401 before the metric payload is
    # rendered. The _validate_production_config gate above guarantees
    # at least one of bearer / allow-list is set in production; in dev
    # both may be unset and the middleware falls through.
    metrics_bearer = (settings.metrics_bearer_token or "").strip()
    metrics_allowlist_raw = (settings.metrics_ip_allowlist or "").strip()
    metrics_cidrs: tuple[str, ...] = tuple(p.strip() for p in metrics_allowlist_raw.split(",") if p.strip())
    app.add_middleware(
        MetricsGuardMiddleware,
        bearer_token=metrics_bearer,
        ip_allowlist_cidrs=metrics_cidrs,
        require_auth=is_production,
    )

    # FIX: Add CORS headers to exception responses (FastAPI bug fix)
    @app.exception_handler(Exception)
    async def cors_exception_handler(request: Request, exc: Exception):
        origin = request.headers.get("origin")

        # Handle standard HTTP exceptions
        if hasattr(exc, "status_code") and hasattr(exc, "detail"):
            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        else:
            # Handle unhandled exceptions
            logger.error(f"Unhandled exception: {exc}")
            response = JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

        # Add CORS headers if origin is allowed
        if origin:
            if origin in origins:
                # Explicit match — safe to allow credentials
                response.headers["Access-Control-Allow-Origin"] = origin
                if allow_credentials:
                    response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Access-Control-Allow-Methods"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "*"
                response.headers["Vary"] = "Origin"
            elif wildcard:
                # Wildcard (dev only) — credentials already disabled above
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Methods"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "*"

        # Error responses must also carry security headers — FastAPI's
        # exception handling can short-circuit before SecurityHeadersMiddleware
        # sees the final response in some edge cases.
        _apply_security_headers(response, request.url.path, enable_hsts=is_production)

        return response

    # Relative-redirect middleware — when FastAPI issues a 307 trailing-slash
    # redirect the Location header contains an absolute backend URL
    # (e.g. http://127.0.0.1:8400/api/admin/foo/). If the Next.js rewrite proxy
    # forwards that to the browser, the browser follows it directly to the
    # backend, bypassing the proxy and triggering CORS + auth-header loss.
    # Stripping the scheme+host makes Location relative so the browser's
    # follow-up request still goes through Next.js.
    class RelativeRedirectMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if response.status_code in (301, 302, 307, 308):
                location = response.headers.get("location", "")
                if location.startswith("http"):
                    parsed = urlparse(location)
                    relative = parsed.path
                    if parsed.query:
                        relative += f"?{parsed.query}"
                    response.headers["location"] = relative
            return response

    app.add_middleware(RelativeRedirectMiddleware)
    # GZip compression — registered last so it wraps all other middleware
    # and compresses final responses. minimum_size=1000 skips tiny payloads
    # where compression overhead exceeds savings.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Rate Limiting Middleware
    app.state.limiter = default_limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    logger.info(
        f"Middleware initialized: CORS, Security Headers (HSTS={'on' if is_production else 'off'}), Rate Limiting"
    )
