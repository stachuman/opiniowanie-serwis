# app/routes/upload.py - REFACTORED VERSION
"""
Endpointy związane z uploadowaniem dokumentów i tworzeniem opinii.
REFAKTORYZACJA: Logika biznesowa przeniesiona do tasks/upload_manager.py
"""

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from datetime import datetime

# Lokalne importy
from app.db import engine, BASE_DIR
from app.models import Document
from app.document_utils import ALLOWED_EXTENSIONS
from app.navigation import build_form_navigation, BreadcrumbBuilder

# Import managera z tasks
from tasks.upload_manager import upload_manager

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ==================== ENDPOINTY UPLOAD OPINII ====================

@router.get("/upload", name="upload_form")
def upload_form(request: Request):
    """Formularz uploadowania nowych opinii."""
    allowed_types = ", ".join(ALLOWED_EXTENSIONS.keys())

    # Zbuduj nawigację dla formularza upload
    navigation = build_form_navigation(request, "Dodaj nową opinię", "upload")

    context = {
        "request": request,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("upload.html", context)


@router.post("/upload", name="upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """Dodawanie nowych głównych dokumentów (opinii) - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.create_opinions_from_files(files)

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)


# ==================== ENDPOINTY TWORZENIA PUSTYCH OPINII ====================

@router.get("/create_empty_opinion", name="create_empty_opinion_form")
def create_empty_opinion_form(request: Request):
    """Formularz tworzenia nowej pustej opinii."""

    # Zbuduj nawigację dla formularza create
    navigation = build_form_navigation(request, "Utwórz pustą opinię", "create")

    context = {
        "request": request,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("create_empty_opinion.html", context)


@router.post("/create_empty_opinion", name="create_empty_opinion")
def create_empty_opinion(
        request: Request,
        sygnatura: str | None = Form(None),
        doc_type: str = Form(...),
        step: str = Form("k1"),
        note: str | None = Form(None)  # DODANE: parametr note
):
    """Utworzenie nowej pustej opinii bez dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = upload_manager.create_empty_opinion(sygnatura, doc_type, step, note)  # DODANE: przekazanie note

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)

# ==================== ENDPOINTY SZYBKIEGO OCR ====================

@router.get("/quick_ocr", name="quick_ocr_form")
def quick_ocr_form(request: Request):
    """Formularz do szybkiego OCR dokumentów bez przypisywania do opinii."""
    allowed_types = ", ".join([k for k in ALLOWED_EXTENSIONS.keys()
                               if k not in ['.doc', '.docx']])

    # Zbuduj nawigację dla formularza OCR
    navigation = build_form_navigation(request, "Szybki OCR", "ocr")

    context = {
        "request": request,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("quick_ocr.html", context)


@router.post("/quick_ocr", name="quick_ocr")
async def quick_ocr(request: Request, files: list[UploadFile] = File(...)):
    """Szybki OCR - dodawanie dokumentów bez wiązania z opinią - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.create_quick_ocr_documents(files)

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)


# ==================== ENDPOINTY UPLOADU DO OPINII ====================

@router.get("/opinion/{doc_id}/upload", name="upload_to_opinion_form")
def upload_to_opinion_form(request: Request, doc_id: int):
    """Formularz dodawania dokumentów do opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Zbuduj nawigację
        breadcrumbs = (BreadcrumbBuilder(request)
                       .add_home()
                       .add_opinion(opinion)
                       .add_current("Dodaj dokumenty", "plus-circle")
                       .build())

        navigation = {
            'breadcrumbs': breadcrumbs,
            'page_title': f"Dodaj dokumenty do opinii: {opinion.sygnatura or opinion.original_filename}",
            'page_actions': [],
            'context_info': []
        }

    allowed_types = ", ".join(ALLOWED_EXTENSIONS.keys())

    context = {
        "request": request,
        "opinion": opinion,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("upload_to_opinion.html", context)


@router.post("/opinion/{doc_id}/upload", name="upload_to_opinion")
async def upload_to_opinion(request: Request, doc_id: int,
                            doc_type: str = Form(...),
                            files: list[UploadFile] = File(...),
                            run_ocr: bool = Form(False)):
    """Dodawanie dokumentów do opinii - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.add_documents_to_opinion(
        opinion_id=doc_id,
        files=files,
        doc_type=doc_type,
        run_ocr=run_ocr
    )

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)