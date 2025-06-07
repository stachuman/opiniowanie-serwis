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

    return templates.TemplateResponse(
        "document_update.html", 
        {
            "request": request, 
            "doc": doc, 
            "is_empty_opinion": is_empty_opinion,
            "title": f"{'Wgraj' if is_empty_opinion else 'Aktualizuj'} dokument: {doc.original_filename}"
        }
    )

@router.post("/document/{doc_id}/update")
async def document_update(request: Request, doc_id: int, updated_file: UploadFile = File(...), 
    keep_history: bool = Form(True), comments: str | None = Form(None)):
    """Aktualizacja istniejącego dokumentu lub wgranie dokumentu Word dla pustej opinii."""

    parent_id = None

    with Session(engine) as session:
        # Pobierz istniejący dokument
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        parent_id = doc.parent_id
        is_main_opinion = doc.is_main
    
    # Sprawdź, czy to pusta opinia
    is_empty_opinion = doc.is_main and doc.stored_filename.endswith('.empty')
    
    # Sprawdź rozszerzenie pliku - dla pustej opinii musi być .doc lub .docx
    # Dla istniejącego dokumentu musi być zgodne z oryginalnym
    new_ext = Path(updated_file.filename).suffix.lower()
    
    if is_empty_opinion:
        # Dla pustej opinii akceptujemy tylko pliki Word
        if new_ext.lower() not in ['.doc', '.docx']:
            raise HTTPException(
                status_code=400,
                detail="Dla pustej opinii można wgrać tylko pliki Word (.doc, .docx)"
            )
    else:
        # Dla istniejącego dokumentu sprawdzamy zgodność rozszerzenia
        original_ext = Path(doc.original_filename).suffix.lower()
        if original_ext != new_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Rozszerzenie pliku musi być zgodne z oryginałem ({original_ext})"
            )
    
    # Jeśli zachowujemy historię i nie jest to pusta opinia, oznacz stary dokument jako wersję historyczną
    if keep_history and not is_empty_opinion:
        # Utwórz kopię oryginalnego dokumentu jako "wersję historyczną"
        history_doc = Document(
            sygnatura=doc.sygnatura,
            doc_type="Archiwalna wersja",
            original_filename=f"Archiwalna_{doc.original_filename}",
            stored_filename=doc.stored_filename,  # Zachowujemy oryginalny plik
            step=doc.step,
            ocr_status=doc.ocr_status,
            parent_id=doc.id,  # Powiązanie z aktualnym dokumentem
            is_main=False,  # To nie jest główny dokument
            content_type=doc.content_type,
            mime_type=doc.mime_type,
            creator=doc.creator,
            upload_time=datetime.now(),
            last_modified=doc.last_modified,
            comments=f"Wersja archiwalna z {datetime.now().strftime('%Y-%m-%d %H:%M')}. {doc.comments or ''}"
        )
        session.add(history_doc)
        
    # Zapisz nowy plik
    unique_name = f"{uuid.uuid4().hex}{new_ext}"
    file_path = FILES_DIR / unique_name
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(updated_file.file, buffer)
    
    # Zaktualizuj informacje o dokumencie
    doc.stored_filename = unique_name
    doc.original_filename = updated_file.filename
    doc.mime_type = detect_mime_type(file_path)
    doc.last_modified = datetime.now()
    # doc.last_modified_by = current_user  # Gdy będzie system użytkowników
    
    if comments:
        if doc.comments:
            doc.comments = f"{comments}\n\n---\n\n{doc.comments}"
        else:
            doc.comments = comments
    
    session.add(doc)
    session.commit()
    
    # Przekieruj do widoku dokumentu
    if is_main_opinion:
        # Jeśli to główna opinia, przekieruj do opinion_detail
        return RedirectResponse(
            request.url_for("opinion_detail", doc_id=doc.id),
            status_code=303
        )
    elif parent_id:
        # Jeśli to dokument należący do opinii, przekieruj do opinion_detail
        return RedirectResponse(
            request.url_for("opinion_detail", doc_id=parent_id),
            status_code=303
        )
    else:
        return RedirectResponse(
            request.url_for("document_detail", doc_id=doc.id),
            status_code=303
        )

@router.get("/document/{doc_id}/history")
def document_history(request: Request, doc_id: int):
    """Historia wersji dokumentu."""
    with Session(engine) as session:
        # Pobierz aktualny dokument
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Pobierz historyczne wersje (dokumenty z parent_id równym ID aktualnego dokumentu)
        history_docs = session.exec(
            select(Document)
            .where(Document.parent_id == doc_id, Document.doc_type == "Archiwalna wersja")
            .order_by(Document.upload_time.desc())
        ).all()
    
    return templates.TemplateResponse(
        "document_history.html", 
        {
            "request": request, 
            "doc": doc, 
            "history_docs": history_docs,
            "title": f"Historia dokumentu: {doc.original_filename}"
        }
    )
