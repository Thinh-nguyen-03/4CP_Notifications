from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine
from app.db_init import create_tables
from app.routes import admin, chart, dashboard, history, latest, peaks, predictions, viewer

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

TEMPLATE_DIR = Path(__file__).parent / "templates"
_root_templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(
    title="4CP Cloud API",
    description="Standalone API serving ERCOT 4CP predictions and peak data.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_dashboard(request: Request) -> HTMLResponse:
    """Ensure the site root serves the dashboard (some deploys only matched deeper routes)."""
    return _root_templates.TemplateResponse(
        request,
        "dashboard.html",
        {"view_token": ""},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "4cp-cloud-api"}


@app.get("/health/db")
async def health_db():
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            if result.scalar() != 1:
                raise HTTPException(status_code=503, detail="Unexpected DB response")
        return {"status": "ok", "database": "connected"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


app.include_router(admin.router)
app.include_router(predictions.router)
app.include_router(peaks.router)
app.include_router(latest.router)
app.include_router(chart.router)
app.include_router(history.router)
app.include_router(dashboard.router)
app.include_router(viewer.router)   # public token-gated dashboard + JSON API
