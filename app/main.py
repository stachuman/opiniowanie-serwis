# app/main.py
"""
Aplikacja FastAPI do zarządzania opiniami sądowymi.
Refaktoryzowany główny plik - zawiera tylko konfigurację i kluczowe endpointy.
POPRAWKA: Fix dla CUDA multiprocessing
"""
import sys
import os

# KRITYCZNE: Ustaw spawn method i CUDA settings PRZED wszystkimi importami
try:
    import multiprocessing as mp

    if mp.get_start_method(allow_none=True) != 'spawn':
        mp.set_start_method('spawn', force=True)
        print("🔧 [MAIN] Ustawiono spawn method dla multiprocessing")
except RuntimeError as e:
    print(f"🔧 [MAIN] Multiprocessing method już ustawiony: {e}")

# CUDA environment settings
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'

import asyncio
import time
import uuid
import shutil
from pathlib import Path

from app.navigation import build_simple_navigation

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime

# Lokalne importy
from app.db import engine, FILES_DIR, BASE_DIR, init_db
from app.models import Document
from app.document_utils import (
    detect_mime_type,
    check_file_extension,
    get_content_type_from_mime,
    STEP_ICON
)
from app.navigation import (
    BreadcrumbBuilder,
    PageActionsBuilder,
    ContextInfoBuilder,
    build_simple_navigation
)
from app.text_extraction import get_text_preview
from app.routes import opinions_router, documents_router, updates_router, upload_router, preview_router, ocr_router

# Import dla OCR
from tasks.ocr_manager import enqueue

# Konfiguracja aplikacji
app = FastAPI(title="Court Workflow", description="System zarządzania opiniami sądowymi")

# Konfiguracja statycznych plików i szablonów
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/files", StaticFiles(directory=str(FILES_DIR)), name="files")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Rejestracja routerów
app.include_router(opinions_router)
app.include_router(documents_router)
app.include_router(updates_router)
app.include_router(upload_router)
app.include_router(preview_router)
app.include_router(ocr_router)


def ensure_multiprocessing_setup():
    """Sprawdź i ustaw multiprocessing configuration."""
    try:
        current_method = mp.get_start_method()
        print(f"🔧 [MAIN] Aktualny multiprocessing method: {current_method}")

        if current_method != 'spawn':
            print(f"⚠️ [MAIN] UWAGA: Multiprocessing używa '{current_method}' zamiast 'spawn'")
            print(f"🔧 [MAIN] To może powodować problemy z CUDA")
        else:
            print(f"✅ [MAIN] Multiprocessing poprawnie skonfigurowany (spawn)")

    except Exception as e:
        print(f"❌ [MAIN] Błąd sprawdzania multiprocessing: {e}")


@app.on_event("startup")
async def startup():
    """Inicjalizacja aplikacji przy starcie."""
    print("🚀 [MAIN] Uruchamianie aplikacji...")

    # Sprawdź konfigurację multiprocessing
    ensure_multiprocessing_setup()

    # Ensure database tables are created
    init_db()

    # Uruchomienie nowego systemu workerów zadań w tle
    from app.background_tasks import start_background_workers
    asyncio.create_task(start_background_workers())

    print("✅ [MAIN] Aplikacja uruchomiona pomyślnie")


@app.on_event("shutdown")
async def shutdown():
    """Zamknięcie aplikacji - cleanup zasobów."""
    print("🛑 [MAIN] Zamykanie aplikacji...")

    from app.background_tasks import cleanup_background_workers
    await cleanup_background_workers()

    print("🛑 [MAIN] Aplikacja zamknięta, workery zatrzymane")


# Middleware do monitorowania wydajności
@app.middleware("http")
async def detect_blocking_operations(request: Request, call_next):
    """Middleware do wykrywania blokujących operacji."""
    # Rozpocznij liczenie czasu
    start_time = time.time()

    # Zidentyfikuj żądanie
    request_id = str(uuid.uuid4())[:8]
    path = request.url.path
    print(f"[{request_id}] Rozpoczęto żądanie: {path}")

    # Wykonaj żądanie
    response = await call_next(request)

    # Sprawdź czas wykonania
    elapsed = time.time() - start_time
    print(f"[{request_id}] Zakończono żądanie: {path} w {elapsed:.4f}s")

    # Loguj długie żądania
    if elapsed > 1.0:
        print(f"[{request_id}] UWAGA: Długie żądanie ({elapsed:.4f}s): {path}")

    return response


@app.get("/debug/routes", name="debug_routes")
def debug_routes(request: Request):
    """Debug endpoint - pokaż wszystkie dostępne route'y"""
    routes_info = []

    for route in request.app.router.routes:
        if hasattr(route, 'name') and route.name:
            route_info = {
                'name': route.name,
                'path': getattr(route, 'path', 'N/A'),
                'methods': getattr(route, 'methods', ['N/A'])
            }
            routes_info.append(route_info)

    # Sortuj alfabetycznie po nazwie
    routes_info.sort(key=lambda x: x['name'])

    return {
        "total_routes": len(routes_info),
        "routes": routes_info
    }


@app.get("/debug/multiprocessing", name="debug_multiprocessing")
def debug_multiprocessing():
    """Debug endpoint - sprawdź konfigurację multiprocessing"""
    try:
        import multiprocessing as mp
        import os

        info = {
            "start_method": mp.get_start_method(),
            "cpu_count": mp.cpu_count(),
            "cuda_env_vars": {
                "CUDA_LAUNCH_BLOCKING": os.environ.get("CUDA_LAUNCH_BLOCKING", "not set"),
                "TORCH_USE_CUDA_DSA": os.environ.get("TORCH_USE_CUDA_DSA", "not set"),
            }
        }

        # Check if CUDA is available
        try:
            import torch
            info["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                info["cuda_device_count"] = torch.cuda.device_count()
                info["current_device"] = torch.cuda.current_device()
        except ImportError:
            info["torch_available"] = False

        return info

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    print("🔧 [MAIN] Sprawdzanie konfiguracji multiprocessing przed uruchomieniem...")
    ensure_multiprocessing_setup()

    print("🚀 [MAIN] Uruchamianie serwera...")
    uvicorn.run(app, host="0.0.0.0", port=80)