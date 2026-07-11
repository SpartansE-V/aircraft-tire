"""Local demonstration UI route."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Demo"])
DEMO_FILE = Path(__file__).resolve().parents[2] / "static" / "demo.html"


@router.get("/demo", include_in_schema=False, response_class=FileResponse)
async def demo() -> FileResponse:
    """Serve the local API demonstration page."""

    return FileResponse(DEMO_FILE)
