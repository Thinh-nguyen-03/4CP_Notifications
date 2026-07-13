from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"view_token": ""},
    )


@router.get("/dashboard/portal", include_in_schema=False)
async def dashboard_portal() -> RedirectResponse:
    """Kept for old bookmarks: dashboard.html is now itself the portal-themed layout."""
    return RedirectResponse(url="/dashboard", status_code=308)
