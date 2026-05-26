"""FastAPI 应用入口 - 路由注册、CORS、SPA 回退"""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, engine

# 导入所有模型，确保 Base.metadata 包含所有表定义
from app.models import *  # noqa: F401,F403


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


def _cors_allowed_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """FastAPI 应用工厂"""
    app = FastAPI(
        title="CIPT Quiz App",
        version="2.0.0",
        openapi_url="/openapi.json" if settings.ENABLE_OPENAPI else None,
        docs_url="/docs" if settings.ENABLE_OPENAPI else None,
        redoc_url="/redoc" if settings.ENABLE_OPENAPI else None,
        redirect_slashes=False,
    )

    app.add_middleware(SecurityHeadersMiddleware)

    # CORS 配置：仅允许明确配置的前端 Origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Exam-Slug"],
    )

    @app.middleware("http")
    async def add_no_cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    if not settings.ENABLE_OPENAPI:
        @app.get("/openapi.json", include_in_schema=False)
        @app.get("/docs", include_in_schema=False)
        @app.get("/redoc", include_in_schema=False)
        async def disabled_openapi_routes():
            raise HTTPException(status_code=404)

    # 注册所有 API 路由（保持现有 URL 前缀）
    from app.api.routes.auth import router as auth_router
    from app.api.routes.account import router as account_router
    from app.api.routes.admin_users import router as admin_users_router
    from app.api.routes.admin_exams import router as admin_exams_router
    from app.api.routes.admin_banks import router as admin_banks_router
    from app.api.routes.exams import router as exams_router
    from app.api.routes.banks import router as banks_router
    from app.api.routes.questions import router as questions_router
    from app.api.routes.quiz import router as quiz_router
    from app.api.routes.wrong import router as wrong_router
    from app.api.routes.ai import router as ai_router
    from app.api.routes.jobs import router as jobs_router
    from app.api.routes.settings import router as settings_router
    from app.api.routes.vocab import router as vocab_router
    from app.api.routes.import_jobs import router as import_jobs_router
    from app.api.routes.import_review import router as import_review_router
    from app.api.routes.background_jobs import router as background_jobs_router

    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(account_router, prefix="/api/account", tags=["account"])
    app.include_router(exams_router, prefix="/api/exams", tags=["exams"])
    app.include_router(admin_users_router, prefix="/api/admin/users", tags=["admin-users"])
    app.include_router(admin_exams_router, prefix="/api/admin/exams", tags=["admin-exams"])
    app.include_router(admin_banks_router, prefix="/api/admin/banks", tags=["admin-banks"])
    app.include_router(banks_router, prefix="/api/banks", tags=["banks"])
    app.include_router(questions_router, prefix="/api/questions", tags=["questions"])
    app.include_router(quiz_router, prefix="/api/quiz", tags=["quiz"])
    app.include_router(wrong_router, prefix="/api/wrong", tags=["wrong"])
    app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
    app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
    app.include_router(vocab_router, prefix="/api/vocab", tags=["vocab"])
    app.include_router(import_jobs_router, prefix="/api/import-jobs", tags=["import-jobs"])
    app.include_router(import_review_router, prefix="/api/import-jobs", tags=["import-review"])
    app.include_router(background_jobs_router, prefix="/api/background-jobs", tags=["background-jobs"])

    # 前端 SPA 回退
    dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
    if os.path.isdir(dist_dir):
        # 静态资源（JS、CSS、图片等）
        assets_dir = os.path.join(dist_dir, "assets")
        if os.path.isdir(assets_dir):
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        def _spa_index_response() -> FileResponse:
            response = FileResponse(os.path.join(dist_dir, "index.html"))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        # SPA fallback：所有非 /api/* 且未匹配到静态文件的路径返回 index.html
        # 使用 APIRoute 检查排除 /api 前缀路径，避免 catch-all 路由吞掉 404 API 请求
        @app.get("/{full_path:path}")
        @app.head("/{full_path:path}")
        async def serve_frontend(request: Request, full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            file_path = os.path.join(dist_dir, full_path)
            if full_path and os.path.isfile(file_path):
                return FileResponse(file_path)
            if request.method == "HEAD":
                response = Response(status_code=200)
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
                return response
            return _spa_index_response()

    return app
