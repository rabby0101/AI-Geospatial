"""
AttachmentStore — manages chat-bar file attachments per session.

Stages files under /tmp/attachments_{session_id}/ with a manifest of per-file
metadata. Four kinds of files are supported:
  - satellite : .tif / .tiff / .zip (Sentinel-2 SAFE)  → delegated to the
    existing satellite upload logic in app/routes/satellite.py, which writes
    into /tmp/satellite_{session_id}/. This keeps the existing analysis
    pipeline working unchanged.
  - pdf       : .pdf → text extracted via pypdf
  - tabular   : .xlsx / .xls / .csv → sheet/column summary via pandas
  - unsupported (images, etc.) → rejected with a clear error

The manifest is the source of truth. It is also used to build a compact
context block that the agent orchestrator injects into the LLM user message.
"""
from __future__ import annotations

import contextvars
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Set by the agent orchestrator at the start of a query. Lets agent tools
# (read_pdf_attachment, read_tabular_attachment, ndvi_by_district) resolve
# ref_ids without the LLM having to pass session_id as an argument.
current_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_session_id", default=None
)


PDF_EXTS = {".pdf"}
TABULAR_EXTS = {".xlsx", ".xls", ".csv"}
SATELLITE_EXTS = {".tif", ".tiff", ".zip"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SUPPORTED_EXTS = PDF_EXTS | TABULAR_EXTS | SATELLITE_EXTS


def _sanitize_session_id(session_id: str) -> str:
    return session_id.replace("-", "_").replace(" ", "_")[:60]


def _classify(filename: str) -> Optional[str]:
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in TABULAR_EXTS:
        return "tabular"
    if ext in SATELLITE_EXTS:
        return "satellite"
    if ext in IMAGE_EXTS:
        return "image"
    return None


class AttachmentStore:
    """File-based attachment store. One instance per session."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.safe_id = _sanitize_session_id(session_id)
        self.root = Path(f"/tmp/attachments_{self.safe_id}")
        self.docs_dir = self.root / "documents"
        self.tab_dir = self.root / "tabular"
        self.manifest_path = self.root / "manifest.json"
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Manifest I/O
    # ------------------------------------------------------------------

    def _load(self) -> List[Dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        try:
            with open(self.manifest_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read manifest {self.manifest_path}: {e}")
            return []

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        with open(self.manifest_path, "w") as f:
            json.dump(entries, f, indent=2, default=str)

    def list_manifest(self) -> List[Dict[str, Any]]:
        return self._load()

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest(
        self,
        filename: str,
        content: bytes,
        format_hint: str = "auto",
    ) -> Dict[str, Any]:
        """
        Classify and ingest a single uploaded file. Returns a manifest entry
        (on success) with shape:
          {ref_id, kind, filename, size, path, summary, ...}
        On failure returns {ref_id: None, kind, filename, error}.
        """
        kind = _classify(filename)
        if kind is None:
            return {
                "ref_id": None,
                "kind": None,
                "filename": filename,
                "error": f"Unsupported file type '{Path(filename).suffix}'. "
                         f"Supported: PDF, Excel/CSV, satellite GeoTIFF/SAFE.",
            }
        if kind == "image":
            return {
                "ref_id": None,
                "kind": "image",
                "filename": filename,
                "error": "Regular images (PNG/JPG) are not supported yet.",
            }

        ref_id = f"att_{uuid.uuid4().hex[:8]}"

        try:
            if kind == "pdf":
                entry = self._ingest_pdf(ref_id, filename, content)
            elif kind == "tabular":
                entry = self._ingest_tabular(ref_id, filename, content)
            elif kind == "satellite":
                entry = self._ingest_satellite(ref_id, filename, content, format_hint)
            else:  # pragma: no cover — classify already filtered
                return {
                    "ref_id": None, "kind": kind, "filename": filename,
                    "error": f"Internal: kind '{kind}' has no ingest handler.",
                }
        except Exception as e:
            logger.exception(f"Attachment ingest failed for {filename}")
            return {"ref_id": None, "kind": kind, "filename": filename, "error": str(e)}

        existing = self._load()
        existing.append(entry)
        self._save(existing)
        return entry

    # ------------------------------------------------------------------
    # Per-kind ingest helpers
    # ------------------------------------------------------------------

    def _ingest_pdf(self, ref_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        from pypdf import PdfReader
        from io import BytesIO

        self.docs_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        dest = self.docs_dir / f"{ref_id}_{safe_name}"
        dest.write_bytes(content)

        reader = PdfReader(BytesIO(content))
        n_pages = len(reader.pages)
        title = None
        try:
            if reader.metadata and reader.metadata.title:
                title = str(reader.metadata.title)[:200]
        except Exception:
            pass

        # Small preview: first ~1500 chars of text across the first few pages
        preview_chars: List[str] = []
        remaining = 1500
        for i, page in enumerate(reader.pages[:5]):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if not t:
                continue
            snippet = t[:remaining]
            preview_chars.append(snippet)
            remaining -= len(snippet)
            if remaining <= 0:
                break
        text_preview = "\n".join(preview_chars).strip()

        summary = f"PDF · {n_pages} page(s)"
        if title:
            summary += f" · title: {title}"

        return {
            "ref_id": ref_id,
            "kind": "pdf",
            "filename": safe_name,
            "size": len(content),
            "path": str(dest),
            "pages": n_pages,
            "title": title,
            "text_preview": text_preview,
            "summary": summary,
        }

    def _ingest_tabular(self, ref_id: str, filename: str, content: bytes) -> Dict[str, Any]:
        import pandas as pd
        from io import BytesIO

        self.tab_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        dest = self.tab_dir / f"{ref_id}_{safe_name}"
        dest.write_bytes(content)

        ext = Path(filename).suffix.lower()
        sheets_info: List[Dict[str, Any]] = []

        if ext == ".csv":
            df = pd.read_csv(BytesIO(content))
            sheets_info.append(self._summarize_sheet("data", df))
        else:
            # .xlsx / .xls — require openpyxl (xlsx) / xlrd (xls)
            try:
                xls = pd.ExcelFile(BytesIO(content))
            except ImportError as ie:
                missing = "openpyxl" if ext == ".xlsx" else "xlrd"
                raise RuntimeError(
                    f"Missing Python dependency '{missing}' needed to read {ext} files. "
                    f"Install it on the server with: pip install {missing}"
                ) from ie
            for sheet_name in xls.sheet_names:
                df = xls.parse(sheet_name)
                sheets_info.append(self._summarize_sheet(sheet_name, df))

        total_rows = sum(s["n_rows"] for s in sheets_info)
        sheet_names = [s["name"] for s in sheets_info]
        summary = (
            f"{'CSV' if ext == '.csv' else 'Excel'} · "
            f"{len(sheets_info)} sheet(s) [{', '.join(sheet_names)}] · "
            f"{total_rows} row(s) total"
        )

        return {
            "ref_id": ref_id,
            "kind": "tabular",
            "filename": safe_name,
            "size": len(content),
            "path": str(dest),
            "sheets": sheets_info,
            "summary": summary,
        }

    @staticmethod
    def _summarize_sheet(name: str, df) -> Dict[str, Any]:
        head = df.head(5)
        return {
            "name": name,
            "n_rows": int(len(df)),
            "n_cols": int(df.shape[1]),
            "columns": [str(c) for c in df.columns],
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "head": json.loads(head.to_json(orient="records", default_handler=str)),
        }

    def _ingest_satellite(
        self, ref_id: str, filename: str, content: bytes, format_hint: str
    ) -> Dict[str, Any]:
        """
        Delegate to the satellite.py upload logic. The satellite session id
        is the same as the attachment session id, so /tmp/satellite_{sid}/
        stays in sync and the existing analysis pipeline works unchanged.
        """
        from pathlib import Path as _P
        import rasterio
        from app.routes.satellite import (
            _session_dir as _sat_session_dir,
            _load_session as _sat_load,
            _save_session as _sat_save,
        )
        from app.utils.satellite_processor import (
            extract_bands_from_safe,
            extract_metadata_from_filename,
            extract_metadata_from_safe,
        )

        sat_dir = _sat_session_dir(self.session_id)
        sat_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _P(filename).name
        dest = sat_dir / safe_name
        dest.write_bytes(content)

        suffix = _P(filename).suffix.lower()
        existing = _sat_load(self.session_id)
        new_entries: List[Dict[str, Any]] = []

        is_zip = suffix == ".zip"
        is_safe_hint = format_hint in ("safe_zip", "auto")

        if is_zip and is_safe_hint:
            band_entries = extract_metadata_from_safe(str(dest))
            extracted = extract_bands_from_safe(str(dest), str(sat_dir), band_entries)
            for e in extracted:
                if e.get("path") and _P(e["path"]).exists():
                    try:
                        with rasterio.open(e["path"]) as src:
                            b = src.bounds
                            e["bounds"] = [b.left, b.bottom, b.right, b.top]
                            e["crs"] = str(src.crs)
                    except Exception:
                        pass
                e["ref_id"] = ref_id
            new_entries.extend(extracted)
        elif not is_zip:
            meta = extract_metadata_from_filename(filename)
            meta["path"] = str(dest)
            with rasterio.open(str(dest)) as src:
                b = src.bounds
                meta["bounds"] = [b.left, b.bottom, b.right, b.top]
                meta["crs"] = str(src.crs)
            meta["ref_id"] = ref_id
            new_entries.append(meta)
        else:
            raise ValueError(
                f"'{filename}' is a ZIP but format_hint='{format_hint}'. "
                "If this is a SAFE archive, leave the hint on 'auto' or set 'safe_zip'."
            )

        # Merge into satellite session (dedupe by path)
        existing_paths = {e.get("path") for e in existing}
        merged = existing + [e for e in new_entries if e.get("path") not in existing_paths]
        _sat_save(self.session_id, merged)

        dates = sorted({e["date"] for e in new_entries if e.get("date")})
        bands = sorted({e["band"] for e in new_entries if e.get("band")})
        tiles = sorted({e["tile_id"] for e in new_entries if e.get("tile_id")})

        summary_bits = [f"{len(new_entries)} band file(s)"]
        if dates:
            summary_bits.append(f"date(s): {', '.join(dates)}")
        if bands:
            summary_bits.append(f"bands: {', '.join(bands)}")
        summary = "Satellite · " + " · ".join(summary_bits)

        return {
            "ref_id": ref_id,
            "kind": "satellite",
            "filename": safe_name,
            "size": len(content),
            "path": str(dest),
            "bands": bands,
            "dates": dates,
            "tile_ids": tiles,
            "band_file_count": len(new_entries),
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Retrieval / mutation
    # ------------------------------------------------------------------

    def get(self, ref_id: str) -> Optional[Dict[str, Any]]:
        for e in self._load():
            if e.get("ref_id") == ref_id:
                return e
        return None

    def remove(self, ref_id: str) -> bool:
        entries = self._load()
        target = next((e for e in entries if e.get("ref_id") == ref_id), None)
        if target is None:
            return False
        # Delete the file itself
        path = target.get("path")
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Could not delete {path}: {e}")
        # If satellite: also remove the matching rows from the satellite session
        if target.get("kind") == "satellite":
            try:
                from app.routes.satellite import _load_session as _sat_load, _save_session as _sat_save
                sat = _sat_load(self.session_id)
                sat = [e for e in sat if e.get("ref_id") != ref_id]
                _sat_save(self.session_id, sat)
            except Exception as e:
                logger.warning(f"Could not prune satellite session for {ref_id}: {e}")

        remaining = [e for e in entries if e.get("ref_id") != ref_id]
        self._save(remaining)
        return True

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        # Also clear the satellite-session directory for this session id
        try:
            from app.routes.satellite import _session_dir as _sat_session_dir
            sat_dir = _sat_session_dir(self.session_id)
            if sat_dir.exists():
                shutil.rmtree(sat_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Could not clear satellite session dir: {e}")

    # ------------------------------------------------------------------
    # Prompt context
    # ------------------------------------------------------------------

    def get_context_block(self) -> Optional[str]:
        """
        Return a compact summary block suitable for injection into the LLM
        user message. Returns None if there are no attachments.
        """
        entries = self._load()
        if not entries:
            return None

        lines: List[str] = []
        for e in entries:
            kind = e.get("kind")
            ref = e.get("ref_id")
            fn = e.get("filename", "?")
            summ = e.get("summary", "")
            lines.append(f"  - [{kind}] {fn}  →  ref_id={ref}  ({summ})")

        tool_hint = (
            "To read content, use one of:\n"
            "    read_pdf_attachment(ref_id, pages?, max_chars?)\n"
            "    read_tabular_attachment(ref_id, sheet?, head_rows?)\n"
            "  For satellite attachments, call ndvi_by_district(district_name) "
            "or analyze_satellite with the session_id — the uploaded tiles are "
            "already staged in the session and will be used automatically."
        )
        return (
            f"\n\nUser has attached {len(entries)} file(s) to this query:\n"
            + "\n".join(lines)
            + "\n  "
            + tool_hint
        )
