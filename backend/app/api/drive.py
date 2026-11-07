"""Google Drive knowledge-source setup endpoints."""
import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/drive", tags=["knowledge sources"])


class FolderSelection(BaseModel):
    folderId: str = Field(min_length=1, max_length=300)


def _connector(request: Request):
    registry = getattr(request.app.state.agent_orchestrator, "connectors", None)
    drive = getattr(registry, "drive", None)
    if drive is None:
        raise HTTPException(503, "Drive service is unavailable")
    return drive


@router.get("/folders")
def folders(request: Request):
    drive = _connector(request)
    if not request.app.state.oauth_store.get("drive"):
        raise HTTPException(401, "Connect Google Drive first")
    try:
        return {"folders": drive.folders(), "selectedFolderId": drive.selected_folder()}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "Could not list Google Drive folders. Check that the Drive read-only scope was granted.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach Google Drive.") from exc


@router.put("/folder")
def choose_folder(payload: FolderSelection, request: Request):
    drive = _connector(request)
    if not request.app.state.oauth_store.get("drive"):
        raise HTTPException(401, "Connect Google Drive first")
    try:
        folders = drive.folders()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Could not verify that folder in Google Drive.") from exc
    if not any(folder["id"] == payload.folderId for folder in folders):
        raise HTTPException(404, "Choose a folder visible to the connected Google account.")
    drive.set_folder(payload.folderId)
    return {"selectedFolderId": payload.folderId}


@router.delete("/folder")
def clear_folder(request: Request):
    _connector(request).set_folder(None)
    return {"selectedFolderId": None}
