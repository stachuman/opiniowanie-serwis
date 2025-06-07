# app/routes/updates.py
"""
Endpointy związane z aktualizacją dokumentów i opiniami.
"""

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime
from pathlib import Path
import shutil
import uuid

from app.navigation import BreadcrumbBuilder
from app.db import engine, FILES_DIR, BASE_DIR
from app.models import Document
from app.document_utils import detect_mime_type

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

@router.get("/document/{doc_id}/update")
def document_update_form(request: Request, doc_id: int):
    """Formularz aktualizacji istniejącego dokumentu lub wgrania dokumentu Word dla pustej opinii."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź, czy to pusta opinia (bez pliku) lub dokument w formacie Word
        is_empty_opinion = doc.is_main and doc.stored_filename.endswith('.empty')
        is_word_doc = doc.mime_type and 'word' in doc.mime_type

        if not (is_empty_opinion or is_word_doc):
            raise HTTPException(
                status_code=400,
                detail="Tylko dokumenty Word lub puste opinie mogą być aktualizowane tą metodą"
            )

        # NOWE: Zbuduj nawigację
        breadcrumbs = BreadcrumbBuilder(request)

        if doc.is_main:
            # To jest opinia - breadcrumb przez listę opinii
            breadcrumbs.add_home().add_opinion(doc)
        else:
            # To jest dokument - sprawdź czy ma opinię nadrzędną
            parent_opinion = None
            if doc.parent_id:
                parent_opinion = session.get(Document, doc.parent_id)
                if parent_opinion:
                    breadcrumbs.add_home().add_opinion(parent_opinion).add_document(doc)
                else:
                    breadcrumbs.add_documents().add_document(doc)
            else:
                breadcrumbs.add_documents().add_document(doc)

        page_title = f"{'Wgraj' if is_empty_opinion else 'Aktualizuj'} dokument"
        breadcrumbs.add_current(page_title, "pencil")

        navigation = {
            'breadcrumbs': breadcrumbs.build(),
            'page_title': page_title,
            'page_actions': [],
            'context_info': []
        }

    context = {
        "request": request,
        "doc": doc,
        "is_empty_opinion": is_empty_opinion,
        "current_year": datetime.now().year,  # Dodaj rok
        **navigation
    }

    return templates.TemplateResponse("document_update.html", context)

@router.post("/document/{doc_id}/update")
async def document_update(request: Request, doc_id: int, updated_file: UploadFile = File(...),
                          keep_history: bool = Form(True), comments: str | None = Form(None)):
    """Aktualizacja istniejącego dokumentu lub wgranie dokumentu Word dla pustej opinii."""

    # Sprawdź czy plik został przesłany
    if not updated_file or not updated_file.filename:
        raise HTTPException(status_code=400, detail="Nie wybrano pliku do wgrania")

    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź uprawnienia
        is_empty_opinion = doc.is_main and doc.stored_filename.endswith('.empty')
        is_word_doc = doc.mime_type and 'word' in doc.mime_type

        if not (is_empty_opinion or is_word_doc):
            raise HTTPException(
                status_code=400,
                detail="Tylko dokumenty Word lub puste opinie mogą być aktualizowane"
            )

        # Sprawdź rozszerzenie nowego pliku
        suffix = Path(updated_file.filename).suffix.lower()
        if suffix not in ['.doc', '.docx']:
            raise HTTPException(
                status_code=400,
                detail=f"Obsługiwane są tylko pliki Word (.doc, .docx). Przesłano: {suffix}"
            )

        # Zachowaj stary plik jeśli trzeba
        old_file_path = None
        if keep_history and not is_empty_opinion:
            old_file_path = FILES_DIR / doc.stored_filename
            if old_file_path.exists():
                # Utwórz kopię historyczną
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                history_name = f"{doc.id}_backup_{timestamp}{Path(doc.stored_filename).suffix}"
                history_path = FILES_DIR / "history" / history_name
                history_path.parent.mkdir(exist_ok=True)
                shutil.copy2(old_file_path, history_path)

        # Generuj nową nazwę pliku
        unique_name = f"{uuid.uuid4().hex}{suffix}"
        dest = FILES_DIR / unique_name

        # Zapisz nowy plik
        with dest.open("wb") as buffer:
            shutil.copyfileobj(updated_file.file, buffer)

        # Wykryj MIME type
        actual_mime_type = detect_mime_type(dest)

        # Usuń stary plik (jeśli nie jest kopią historyczną)
        if not is_empty_opinion and old_file_path and old_file_path.exists():
            try:
                old_file_path.unlink()
            except Exception as e:
                print(f"Błąd podczas usuwania starego pliku: {e}")

        # Aktualizuj rekord w bazie
        doc.original_filename = updated_file.filename
        doc.stored_filename = unique_name
        doc.mime_type = actual_mime_type
        doc.last_modified = datetime.now()
        # doc.last_modified_by = current_user  # Gdy będzie system użytkowników

        # Jeśli to była pusta opinia, zaktualizuj też inne pola
        if is_empty_opinion:
            doc.content_type = "opinion"

        # Dodaj komentarz do historii jeśli podano
        if comments:
            doc.note = (doc.note or "") + f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Aktualizacja: {comments}"

        session.add(doc)
        session.commit()

        # Przekieruj do odpowiedniego widoku
        if doc.is_main:
            return RedirectResponse(request.url_for("opinion_detail", doc_id=doc_id), status_code=303)
        else:
            return RedirectResponse(request.url_for("document_detail", doc_id=doc_id), status_code=303)


@router.get("/document/{doc_id}/history")
def document_history(request: Request, doc_id: int):
    """Historia wersji dokumentu."""
    with Session(engine) as session:
        # Pobierz aktualny dokument
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Pobierz opinię nadrzędną jeśli istnieje
        parent_opinion = None
        if doc.parent_id:
            parent_opinion = session.get(Document, doc.parent_id)
        
        # Pobierz historyczne wersje (dokumenty z parent_id równym ID aktualnego dokumentu)
        history_docs = session.exec(
            select(Document)
            .where(Document.parent_id == doc_id, Document.doc_type == "Archiwalna wersja")
            .order_by(Document.upload_time.desc())
        ).all()

        # NOWE: Zbuduj nawigację
        breadcrumbs = BreadcrumbBuilder(request)
        
        if doc.is_main:
            # To jest opinia
            breadcrumbs.add_home().add_opinion(doc)
        else:
            # To jest dokument
            if parent_opinion:
                breadcrumbs.add_home().add_opinion(parent_opinion).add_document(doc)
            else:
                breadcrumbs.add_documents().add_document(doc)
                
        breadcrumbs.add_current("Historia wersji", "clock-history")
        
        navigation = {
            'breadcrumbs': breadcrumbs.build(),
            'page_title': f"Historia dokumentu: {doc.original_filename}",
            'page_actions': [],
            'context_info': []
        }
    
    context = {
        "request": request, 
        "doc": doc, 
        "history_docs": history_docs,
        "current_year": datetime.now().year,  # Dodaj rok
        **navigation
    }
    
    return templates.TemplateResponse("document_history.html", context)
