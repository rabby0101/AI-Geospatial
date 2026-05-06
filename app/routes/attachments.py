"""
Attachments Router

Unified multi-file upload for the chat bar. Accepts PDFs, Excel/CSV, and
Sentinel-2 satellite imagery (GeoTIFF / SAFE ZIP) — all in one batch. Each
uploaded file is classified, parsed, and registered in a per-session
manifest that the agent orchestrator reads when the user asks a question.

Endpoints:
  POST   /api/attachments/upload                — upload one or more files
  GET    /api/attachments/{session_id}          — list current manifest
  DELETE /api/attachments/{session_id}/{ref_id} — remove a single attachment
  DELETE /api/attachments/{session_id}          — clear all attachments
"""
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.utils.attachment_store import AttachmentStore

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.post("/upload")
async def upload_attachments(
    files: List[UploadFile] = File(...),
    session_id: str = Form(...),
    format_hint: str = Form("auto"),
):
    """
    Accept one or more attachments. Files of mixed types are supported in a
    single request. Each file is classified, ingested, and added to the
    session manifest. Per-file errors do not fail the request — other
    attachments still succeed.
    """
    if not files:
        raise HTTPException(status_code=422, detail="No files uploaded.")
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required.")

    store = AttachmentStore(session_id)

    results = []
    for upload in files:
        try:
            content = await upload.read()
        except Exception as e:
            results.append({
                "ref_id": None,
                "kind": None,
                "filename": upload.filename,
                "error": f"Could not read upload: {e}",
            })
            continue

        entry = store.ingest(upload.filename, content, format_hint=format_hint)
        # Strip heavy fields from the response; frontend only needs summary metadata
        results.append({
            "ref_id": entry.get("ref_id"),
            "kind": entry.get("kind"),
            "filename": entry.get("filename"),
            "size": entry.get("size"),
            "summary": entry.get("summary"),
            "error": entry.get("error"),
        })

    return {
        "success": True,
        "session_id": session_id,
        "attachments": results,
        "manifest_count": len(store.list_manifest()),
    }


@router.get("/{session_id}")
async def list_attachments(session_id: str):
    store = AttachmentStore(session_id)
    entries = store.list_manifest()
    # Return the same lightweight shape the upload endpoint uses
    return {
        "session_id": session_id,
        "attachments": [
            {
                "ref_id": e.get("ref_id"),
                "kind": e.get("kind"),
                "filename": e.get("filename"),
                "size": e.get("size"),
                "summary": e.get("summary"),
            }
            for e in entries
        ],
    }


@router.delete("/{session_id}/{ref_id}")
async def remove_attachment(session_id: str, ref_id: str):
    store = AttachmentStore(session_id)
    ok = store.remove(ref_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Attachment {ref_id} not found.")
    return {"success": True, "session_id": session_id, "ref_id": ref_id}


@router.delete("/{session_id}")
async def clear_attachments(session_id: str):
    store = AttachmentStore(session_id)
    store.clear()
    return {"success": True, "session_id": session_id, "message": "All attachments cleared."}
