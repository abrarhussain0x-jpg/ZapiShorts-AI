"""FastAPI main application — rate limiting, request IDs, Gzip, Prometheus, WebSocket, Admin UI."""

import os
import time
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.config.settings import settings
from src.database.database import check_db_connection, init_db
from src.utils.exceptions import ZAPIException
from src.utils.logger import get_request_id, set_request_id, setup_logging

logger = setup_logging("zapi.api")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("Starting ZAPI  v2.0")
    logger.info("=" * 60)

    init_db()
    logger.info("✓ Database initialised")

    # Startup checks
    if not check_db_connection():
        logger.warning("⚠ Database connection check failed")
    else:
        logger.info("✓ Database reachable")

    import subprocess

    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        if r.returncode == 0:
            logger.info("✓ FFmpeg available")
        else:
            logger.warning("⚠ FFmpeg not found in PATH")
    except Exception:
        logger.warning("⚠ FFmpeg not found in PATH")

    if not settings.facebook_access_token:
        logger.warning("⚠ Facebook access token not configured")
    if not settings.facebook_page_id:
        logger.warning("⚠ Facebook page ID not configured")

    logger.info("✓ Environment: %s | Debug: %s", settings.environment, settings.debug)
    logger.info("=" * 60)

    yield

    logger.info("ZAPI shutting down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ZAPI — YouTube to Social Automation",
    description=(
        "Enterprise-grade YouTube → Facebook Reels / Instagram / TikTok / YouTube Shorts "
        "automation pipeline with AI clip scoring, A/B testing, and smart scheduling."
    ),
    version="2.0.0",
    docs_url=None,
    redoc_url="/api/redoc" if settings.enable_api_docs else None,
    lifespan=lifespan,
    contact={"name": "ZAPI", "url": "https://github.com/zapi"},
    license_info={"name": "MIT"},
)

# ── Static files ──────────────────────────────────────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Page-Count", "X-Request-ID", "X-Process-Time"],
)

# SlowAPI rate limiting (optional, graceful if not installed)
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address

    limiter = Limiter(
        key_func=get_remote_address, default_limits=[settings.slowapi_rate_limit]
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    logger.info("✓ SlowAPI rate limiting: %s", settings.slowapi_rate_limit)
except ImportError:
    logger.warning("slowapi not installed — rate limiting disabled")

# Prometheus metrics (optional)
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
    logger.info("✓ Prometheus metrics at /metrics")
except ImportError:
    logger.warning(
        "prometheus-fastapi-instrumentator not installed — /metrics disabled"
    )


# ── Request ID + timing middleware ─────────────────────────────────────────────
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get(settings.request_id_header) or str(_uuid.uuid4())
    set_request_id(rid)
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t0
    response.headers["X-Request-ID"] = rid
    response.headers["X-Process-Time"] = f"{elapsed:.4f}s"
    logger.info(
        "%s %s → %d (%.3fs)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(ZAPIException)
async def zapi_exc_handler(request, exc: ZAPIException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "request_id": get_request_id(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "request_id": get_request_id(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors(),
                "request_id": get_request_id(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


@app.exception_handler(Exception)
async def general_exc_handler(request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "request_id": get_request_id(),
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


# ── Custom Swagger UI with logo ───────────────────────────────────────────────
@app.get("/api/docs", include_in_schema=False)
async def custom_swagger_ui():
    if not settings.enable_api_docs:
        raise HTTPException(status_code=404, detail="Not Found")

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui.css">
    <link rel="stylesheet" type="text/css" href="/static/custom.css">
    <link rel="icon" type="image/png" href="/static/logo.png">
    <title>{app.title} — API Docs</title>
    </head>
    <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.9.0/swagger-ui-standalone-preset.js"></script>
    <script>
    window.onload = function() {{
        const ui = SwaggerUIBundle({{
            url: '{app.openapi_url}',
            dom_id: '#swagger-ui',
            presets: [
                SwaggerUIBundle.presets.apis,
                SwaggerUIStandalonePreset
            ],
            layout: "StandaloneLayout",
            deepLinking: true,
            showExtensions: true,
            showCommonExtensions: true
        }});
        window.ui = ui;
    }};
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ── Health endpoints ──────────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "healthy",
        "service": "ZAPI",
        "version": "2.0.0",
        "environment": settings.environment,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health", tags=["Health"])
async def health():
    db_ok = check_db_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "environment": settings.environment,
        "components": {
            "database": {
                "status": "ok" if db_ok else "error",
                "url": (
                    settings.database_url.split("@")[-1]
                    if "@" in settings.database_url
                    else "configured"
                ),
            },
            "redis": {
                "url": (
                    settings.redis_url.split("@")[-1]
                    if "@" in settings.redis_url
                    else "configured"
                )
            },
            "facebook": {
                "configured": bool(
                    settings.facebook_access_token and settings.facebook_page_id
                )
            },
        },
        "features": {
            "api_docs": settings.enable_api_docs,
            "scheduler": getattr(settings, "scheduler_enabled", False),
            "analytics": settings.enable_analytics,
            "websocket": settings.enable_websocket,
            "admin_ui": settings.admin_ui_enabled,
            "hw_accel": settings.ffmpeg_use_hwaccel,
            "real_whisper": settings.enable_real_whisper,
            "ai_metadata": settings.enable_ai_metadata,
        },
    }


@app.get("/demo", include_in_schema=False, tags=["Demo"])
async def demo():
    db_ok = check_db_connection()
    demo_features = [
        "Ad-free showcase",
        "Real API endpoints",
        "Live health snapshot",
        "FastAPI + Celery architecture",
        "YouTube-to-Shorts workflow",
    ]
    status_label = "healthy" if db_ok else "degraded"
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>ZAPI Demo</title>
        <style>
            :root {{
                --bg: #08111f;
                --panel: rgba(13, 22, 40, 0.92);
                --panel-2: rgba(19, 30, 54, 0.88);
                --text: #f4f7fb;
                --muted: #aab7cf;
                --accent: #7cf7c6;
                --accent-2: #74b9ff;
                --border: rgba(148, 163, 184, 0.18);
            }}
            * {{ box-sizing: border-box; }}
            body {{
                margin: 0;
                min-height: 100vh;
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                color: var(--text);
                background:
                    radial-gradient(circle at top left, rgba(116, 185, 255, 0.22), transparent 36%),
                    radial-gradient(circle at top right, rgba(124, 247, 198, 0.18), transparent 30%),
                    linear-gradient(180deg, #09111d 0%, #04070d 100%);
            }}
            .wrap {{ max-width: 1120px; margin: 0 auto; padding: 44px 20px 56px; }}
            .hero {{
                display: grid;
                grid-template-columns: 1.3fr 0.9fr;
                gap: 24px;
                align-items: stretch;
            }}
            .card {{
                background: var(--panel);
                border: 1px solid var(--border);
                border-radius: 24px;
                padding: 28px;
                box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
                backdrop-filter: blur(18px);
            }}
            .kicker {{
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 8px 14px;
                border-radius: 999px;
                background: rgba(124, 247, 198, 0.1);
                color: var(--accent);
                font-size: 0.82rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }}
            h1 {{
                margin: 18px 0 10px;
                font-size: clamp(2.5rem, 5vw, 4.8rem);
                line-height: 0.96;
                letter-spacing: -0.05em;
            }}
            p {{ color: var(--muted); font-size: 1.03rem; line-height: 1.7; }}
            .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 22px; }}
            .metric {{
                background: var(--panel-2);
                border: 1px solid var(--border);
                border-radius: 20px;
                padding: 18px;
            }}
            .metric .label {{ color: var(--muted); font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em; }}
            .metric .value {{ margin-top: 8px; font-size: 1.2rem; font-weight: 700; }}
            .stack {{ display: grid; gap: 14px; }}
            .pill-list {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
            .pill {{
                border: 1px solid var(--border);
                background: rgba(255, 255, 255, 0.04);
                border-radius: 999px;
                padding: 10px 14px;
                color: var(--text);
                font-size: 0.9rem;
            }}
            .links {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 20px; }}
            .btn {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 10px;
                padding: 12px 18px;
                border-radius: 14px;
                text-decoration: none;
                font-weight: 700;
                border: 1px solid transparent;
                transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
            }}
            .btn:hover {{ transform: translateY(-1px); }}
            .btn-primary {{ background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #07111d; }}
            .btn-ghost {{ color: var(--text); border-color: var(--border); background: rgba(255, 255, 255, 0.03); }}
            .section {{ margin-top: 22px; }}
            .title {{ font-size: 0.86rem; text-transform: uppercase; letter-spacing: 0.12em; color: var(--muted); margin-bottom: 12px; }}
            ul {{ margin: 0; padding-left: 18px; color: var(--text); line-height: 1.8; }}
            code {{ color: var(--accent); }}
            .status {{ color: {"#7cf7c6" if db_ok else "#ffb86b"}; font-weight: 700; }}
            @media (max-width: 920px) {{
                .hero {{ grid-template-columns: 1fr; }}
                .grid {{ grid-template-columns: 1fr 1fr; }}
            }}
            @media (max-width: 640px) {{
                .wrap {{ padding: 22px 14px 34px; }}
                .card {{ padding: 20px; border-radius: 20px; }}
                .grid {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <main class="wrap">
            <section class="hero">
                <article class="card">
                    <div class="kicker">Ad-free real demo</div>
                    <h1>ZAPI turns long-form video into publishable shorts.</h1>
                    <p>
                        This page is a real, ad-free demo for the project. It uses the live app stack,
                        shows the current service status, and points straight to the API and docs.
                    </p>
                    <div class="pill-list">
                        <span class="pill">No ads</span>
                        <span class="pill">No tracking banners</span>
                        <span class="pill">No fake placeholder data</span>
                        <span class="pill">Live backend endpoints</span>
                    </div>
                    <div class="links">
                        <a class="btn btn-primary" href="/api/docs">Open API Docs</a>
                        <a class="btn btn-ghost" href="/health">View Health</a>
                    </div>
                </article>
                <aside class="card stack">
                    <div>
                        <div class="title">System status</div>
                        <div class="value status">{status_label}</div>
                        <p>Live app state from the current deployment.</p>
                    </div>
                    <div class="grid">
                        <div class="metric">
                            <div class="label">Mode</div>
                            <div class="value">Demo</div>
                        </div>
                        <div class="metric">
                            <div class="label">Version</div>
                            <div class="value">2.0.0</div>
                        </div>
                        <div class="metric">
                            <div class="label">Delivery</div>
                            <div class="value">Shorts</div>
                        </div>
                        <div class="metric">
                            <div class="label">Ads</div>
                            <div class="value">None</div>
                        </div>
                    </div>
                </aside>
            </section>
            <section class="card section">
                <div class="title">What you can see here</div>
                <ul>
                    {''.join(f'<li>{feature}</li>' for feature in demo_features)}
                </ul>
            </section>
        </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


# ── Routers ───────────────────────────────────────────────────────────────────
from src.api import advanced, analytics, jobs, scheduling, videos
from src.api.admin import router as admin_router
from src.api.websocket import router as ws_router

app.include_router(videos.router, prefix="/api/videos", tags=["Videos"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(scheduling.router, prefix="/api/scheduling", tags=["Scheduling"])
app.include_router(advanced.router, prefix="/api/advanced", tags=["Advanced"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])
app.include_router(admin_router, prefix="", tags=["Admin"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
        workers=1 if settings.debug else 2,
    )
