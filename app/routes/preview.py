# app/routes/preview.py
"""
Endpointy związane z podglądem dokumentów (PDF, Word, Image, Text).
"""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from datetime import datetime

from app.db import engine, FILES_DIR, BASE_DIR
from app.models import Document
from app.document_utils import detect_mime_type
from app.navigation import (
    BreadcrumbBuilder,
    PageActionsBuilder,
    build_preview_navigation,
    build_document_context_info
)
from app.text_extraction import extract_text_from_word, HAS_DOCX

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/document/{doc_id}/preview", name="document_preview")
def document_preview(request: Request, doc_id: int):
    """Podgląd dokumentu bezpośrednio w przeglądarce - przekierowuje do odpowiedniego typu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

    file_path = FILES_DIR / doc.stored_filename

    # Sprawdź, czy plik istnieje
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Plik nie istnieje")

    # Dla obrazów, PDF i plików tekstowych wyświetlamy bezpośrednio
    mime_type = doc.mime_type
    if not mime_type:
        mime_type = detect_mime_type(file_path)

    # Obrazy i PDF obsługujemy bezpośrednio
    if mime_type and mime_type.startswith('image/'):
        return FileResponse(
            file_path,
            filename=doc.original_filename,
            media_type=mime_type
        )
    if mime_type and (mime_type == 'application/pdf'):
        return FileResponse(file_path, media_type="application/pdf")

    # Dla dokumentów Word przekieruj do word-preview
    if mime_type and 'word' in mime_type:
        return RedirectResponse(
            request.url_for("document_word_preview", doc_id=doc.id)
        )

    # Dla plików tekstowych otwieramy specjalny podgląd
    if mime_type == 'text/plain' or doc.original_filename.lower().endswith('.txt'):
        return RedirectResponse(
            request.url_for("document_text_preview", doc_id=doc.id)
        )

    # Dla innych typów, przekierowujemy do pobierania
    return RedirectResponse(
        request.url_for("document_download", doc_id=doc.id)
    )


@router.get("/document/{doc_id}/text-preview", name="document_text_preview")
def document_text_preview(request: Request, doc_id: int):
    """Podgląd pliku tekstowego w formacie HTML."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

        # Zbuduj nawigację dla podglądu tekstowego
        navigation = build_preview_navigation(request, doc, session, 'text')

    file_path = FILES_DIR / doc.stored_filename

    # Sprawdź, czy plik istnieje
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Plik nie istnieje")

    # Odczytaj zawartość pliku
    content = None
    encodings = ['utf-8', 'latin-1', 'cp1250']
    error_message = None

    for encoding in encodings:
        try:
            content = file_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        error_message = "Nie można odczytać pliku - nieobsługiwane kodowanie znaków"

    context = {
        "request": request,
        "doc": doc,
        "content": content,
        "error_message": error_message,
        "current_year": datetime.now().year,
        "page_type": "document_preview",
        **navigation
    }

    return templates.TemplateResponse("text_preview.html", context)


@router.get("/document/{doc_id}/word-preview", name="document_word_preview")
def document_word_preview(request: Request, doc_id: int):
    """Podgląd dokumentu Word z zaawansowanymi funkcjami."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Zbuduj nawigację dla podglądu Word
        navigation = build_preview_navigation(request, doc, session, 'word')

        # Pobierz wszystkie potrzebne dane przed zamknięciem sesji
        doc_data = {
            "id": doc.id,
            "original_filename": doc.original_filename,
            "stored_filename": doc.stored_filename,
            "sygnatura": doc.sygnatura,
            "doc_type": doc.doc_type,
            "mime_type": doc.mime_type,
            "upload_time": doc.upload_time,
            "last_modified": doc.last_modified,
            "note": doc.note,
            "is_main": doc.is_main
        }

    # Sprawdź czy to pusta opinia
    is_empty_opinion = doc_data["is_main"] and doc_data["stored_filename"].endswith('.empty')

    # Ekstraktowanie tekstu z dokumentu Word
    content = None
    error_message = None

    if is_empty_opinion:
        # Pusta opinia - brak dokumentu
        error_message = "Ta opinia nie ma jeszcze dodanego dokumentu Word"
    else:
        # Normalny dokument Word - ekstraktuj tekst
        file_path = FILES_DIR / doc_data["stored_filename"]

        if not file_path.exists():
            error_message = "Plik dokumentu nie istnieje na serwerze"
        else:
            if not HAS_DOCX:
                error_message = "Serwer nie ma zainstalowanej biblioteki do odczytu dokumentów Word"
            else:
                try:
                    content = extract_text_from_word(file_path)
                    if not content or not content.strip():
                        error_message = "Dokument Word jest pusty lub nie zawiera tekstu"
                except Exception as e:
                    error_message = f"Nie udało się odczytać dokumentu Word: {str(e)}"

    context = {
        "request": request,
        "doc": doc_data,
        "content": content,
        "error_message": error_message,
        "current_year": datetime.now().year,
        "page_type": "word_preview",
        **navigation
    }

    return templates.TemplateResponse("word_preview.html", context)


@router.get("/document/{doc_id}/pdf-preview", name="document_pdf_preview")
def document_pdf_preview(request: Request, doc_id: int):
    """Prosty podgląd PDF."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź czy dokument to PDF
        if not doc.mime_type or doc.mime_type != 'application/pdf':
            raise HTTPException(status_code=400, detail="Ten widok jest dostępny tylko dla plików PDF")

        # Zbuduj nawigację dla podglądu PDF
        navigation = build_preview_navigation(request, doc, session, 'pdf')

    context = {
        "request": request,
        "doc": doc,
        "current_year": datetime.now().year,
        "page_type": "pdf_preview",
        **navigation
    }

    return templates.TemplateResponse("pdf_preview.html", context)


@router.get("/document/{doc_id}/image-preview", name="document_image_preview")
def document_image_preview(request: Request, doc_id: int):
    """Prosty podgląd obrazu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź czy dokument to obraz
        if not doc.mime_type or not doc.mime_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Ten widok jest dostępny tylko dla plików obrazowych")

        # Zbuduj nawigację dla podglądu obrazu
        navigation = build_preview_navigation(request, doc, session, 'image')

    context = {
        "request": request,
        "doc": doc,
        "current_year": datetime.now().year,
        "page_type": "image_preview",
        **navigation
    }

    return templates.TemplateResponse("image_preview.html", context)