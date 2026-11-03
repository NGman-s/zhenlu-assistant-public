from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_ROOT, Settings
from app.device_state import read_device_state
from app.database import Database
from app.errors import setup_exception_handlers
from app.providers.demo_data import DemoCatalog
from app.providers.registry import build_asr_provider, build_draft_provider
from app.routers import audio, demo, drafts, records, sessions, transcripts
from app.schemas import HealthOut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        catalog = DemoCatalog(settings.sample_data_dir)
        catalog.list()  # 启动时校验模拟数据完整可读
        database = Database(settings.database_url)
        database.create_all()

        app.state.demo_catalog = catalog
        app.state.asr_provider = build_asr_provider(settings, catalog)
        app.state.draft_provider = build_draft_provider(settings, catalog)
        app.state.db = database
        logger.info(
            "诊录助手启动：ASR=%s，草稿=%s，数据库=%s",
            app.state.asr_provider.name,
            app.state.draft_provider.name,
            settings.database_url,
        )
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "诊录助手第一阶段原型：会话、音频上传、模拟转写、结构化草稿、"
            "医生审核确认与复制。语音识别为模拟服务，草稿生成可按配置切换。"
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def device_gate(request: Request, call_next):
        state = read_device_state(settings.device_state_file)
        # 断开后仍允许保存正在编辑的内容，其他新写操作暂停。
        saving_work = (
            request.method == "PATCH" and request.url.path.endswith("/draft")
        ) or (
            request.method == "POST" and request.url.path.endswith("/transcript/manual")
        )
        if (state["managed"] and not state["connected"]
                and request.method not in ("GET", "HEAD", "OPTIONS")
                and not saving_work):
            return JSONResponse(status_code=423, content={
                "code": "device_disconnected", "message": "设备已断开，请重新连接后继续。"
            })
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    setup_exception_handlers(app)

    app.include_router(sessions.router, prefix="/api")
    app.include_router(audio.router, prefix="/api")
    app.include_router(transcripts.router, prefix="/api")
    app.include_router(drafts.router, prefix="/api")
    app.include_router(records.router, prefix="/api")
    app.include_router(demo.router, prefix="/api")

    @app.get("/api/health", response_model=HealthOut, tags=["系统"])
    def health(request: Request) -> dict:
        asr_provider = request.app.state.asr_provider
        draft_provider = request.app.state.draft_provider
        return {
            "status": "ok",
            "asr_provider": asr_provider.name,
            "asr_is_mock": asr_provider.is_mock,
            "draft_provider": draft_provider.name,
            "draft_is_mock": draft_provider.is_mock,
            "mock_mode": bool(asr_provider.is_mock and draft_provider.is_mock),
        }

    @app.get("/api/device/status", tags=["系统"])
    def device_status() -> dict:
        return read_device_state(settings.device_state_file)

    frontend = PROJECT_ROOT / "frontend" / "dist"
    if settings.device_state_file and (frontend / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        def root() -> dict:
            return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
