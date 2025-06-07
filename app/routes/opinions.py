# app/routes/opinions.py
"""
Endpointy związane z opiniami sądowymi.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from datetime import datetime

from app.db import engine
from app.models import Document
from app.search import is_fuzzy_match
from app.text_extraction import get_document_text_content
from app.document_utils import STEP_ICON

router = APIRouter()

@router.get("/")
def root_redirect():
    """Przekierowanie ze strony głównej do listy opinii."""
    return RedirectResponse(url="/opinions", status_code=303)

@router.post("/opinion/{doc_id}/update-note")
def update_opinion_note(request: Request, doc_id: int, note: str = Form("")):
    """Aktualizacja notatki do opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")
        
        # Aktualizuj notatkę
        opinion.note = note.strip() or None
        opinion.last_modified = datetime.now()
        
        session.add(opinion)
        session.commit()
    
    # Dodaj timestamp do URL, aby zapobiec cachowaniu
    timestamp = int(datetime.now().timestamp())
    
    # Metoda 1: Konwertowanie URL na string przed dodaniem parametrów
    url = str(request.url_for("list_opinions"))
    return RedirectResponse(
        f"{url}?note_updated=true&ts={timestamp}", 
        status_code=303
    )
    
    # Alternatywnie, możesz użyć metody include_query_params() z obiektu URL:
    # url = request.url_for("list_opinions").include_query_params(note_updated="true", ts=timestamp)
    # return RedirectResponse(url, status_code=303)

@router.get("/opinions")
def list_opinions(request: Request, 
                  k1: bool | None = None,
                  k2: bool | None = None, 
                  k3: bool | None = None,
                  k4: bool | None = None,
                  search: str | None = None,
                  search_content: bool = False,
                  fuzzy_search: bool = False):
    """Lista głównych dokumentów (opinii) z filtrowaniem i wyszukiwaniem."""
    from app.text_extraction import HAS_DOCX
    
    with Session(engine) as session:
        # Rozpocznij z podstawowym zapytaniem
        query = select(Document).where(Document.is_main == True)
        
        # Przygotuj listę dozwolonych kroków - domyślnie wszystkie oprócz k4 (archiwum)
        allowed_steps = []
        
        # Jeśli żadne parametry nie są ustawione, użyj domyślnych (wszystkie oprócz k4)
        if k1 is None and k2 is None and k3 is None and k4 is None:
            allowed_steps = ['k1', 'k2', 'k3']
        else:
            # Jeśli parametry są ustawione, dodaj tylko te które są True
            if k1:
                allowed_steps.append('k1')
            if k2:
                allowed_steps.append('k2')
            if k3:
                allowed_steps.append('k3')
            if k4:
                allowed_steps.append('k4')
        
        # Zastosuj filtr kroków jeśli są jakieś dozwolone
        if allowed_steps:
            query = query.where(Document.step.in_(allowed_steps))
        
        # Wykonaj zapytanie z sortowaniem
        all_opinions = session.exec(query.order_by(Document.upload_time.desc())).all()
        
        # Słownik z informacjami o dopasowaniach (doc_id -> lista typów dopasowań)
        search_matches = {}
        
        # Zastosuj wyszukiwanie
        if search and search.strip():
            search_term = search.strip().lower()
            filtered_opinions = []
            
            for opinion in all_opinions:
                # Lista typów dopasowań dla tej opinii
                match_types = []
                
                # Standardowe wyszukiwanie w metadanych
                metadata_match = (
                    (opinion.sygnatura and search_term in opinion.sygnatura.lower()) or
                    (opinion.original_filename and search_term in opinion.original_filename.lower())
                )
                
                if metadata_match:
                    match_types.append("metadata")
                
                # Wyszukiwanie rozmyte w metadanych (jeśli włączone)
                fuzzy_metadata_match = False
                if fuzzy_search and not metadata_match:
                    metadata_text = f"{opinion.sygnatura or ''} {opinion.original_filename or ''}".lower()
                    fuzzy_metadata_match = is_fuzzy_match(search_term, metadata_text)
                    if fuzzy_metadata_match:
                        match_types.append("fuzzy_metadata")
                
                # Wyszukiwanie w treści (jeśli włączone)
                content_match = False
                fuzzy_content_match = False
                if search_content:
                    # Wyszukaj w treści głównego dokumentu (przekaż sesję!)
                    opinion_text = get_document_text_content(opinion, session)
                    if opinion_text:
                        content_match = search_term in opinion_text.lower()
                        if content_match:
                            match_types.append("content")
                        elif fuzzy_search:
                            fuzzy_content_match = is_fuzzy_match(search_term, opinion_text.lower())
                            if fuzzy_content_match:
                                match_types.append("fuzzy_content")
                    
                    # Wyszukaj w powiązanych dokumentach
                    if not content_match and not fuzzy_content_match:
                        related_docs = session.exec(
                            select(Document).where(Document.parent_id == opinion.id)
                        ).all()
                        
                        for doc in related_docs:
                            doc_text = get_document_text_content(doc, session)
                            if doc_text:
                                if search_term in doc_text.lower():
                                    match_types.append("content")
                                    break
                                elif fuzzy_search and is_fuzzy_match(search_term, doc_text.lower()):
                                    match_types.append("fuzzy_content")
                                    break
                
                # Dodaj do wyników jeśli pasuje
                if match_types:
                    search_matches[opinion.id] = match_types
                    filtered_opinions.append(opinion)
            
            opinions = filtered_opinions
        else:
            opinions = all_opinions
        
        # Przygotuj dane o aktualnych filtrach do przekazania do szablonu
        current_filters = {
            'k1': k1 if k1 is not None else (k1 is None),
            'k2': k2 if k2 is not None else (k2 is None),
            'k3': k3 if k3 is not None else (k3 is None),
            'k4': k4 if k4 is not None else False,
            'search': search or '',
            'search_content': search_content,
            'fuzzy_search': fuzzy_search
        }
        
        from fastapi.templating import Jinja2Templates
        from app.db import BASE_DIR
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
        
        return templates.TemplateResponse(
            "opinions.html", 
            {
                "request": request, 
                "opinions": opinions, 
                "icons": STEP_ICON, 
                "title": "Opinie sądowe",
                "current_filters": current_filters,
                "total_count": len(opinions),
                "has_docx": HAS_DOCX,
                "search_matches": search_matches
            }
        )

@router.get("/opinion/{doc_id}")
def opinion_detail(request: Request, doc_id: int):
    """Szczegóły opinii wraz z dokumentami powiązanymi."""
    with Session(engine) as session:
        # Pobierz główny dokument
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")
        
        # Pobierz dokumenty powiązane
        related_docs = session.exec(
            select(Document)
            .where(Document.parent_id == doc_id)
            .order_by(Document.upload_time.desc())
        ).all()
        
        # Grupuj dokumenty powiązane według doc_type
        grouped_docs = {}
        
        # Przygotuj statystyki OCR
        total_docs = 0
        pending_docs = 0
        running_docs = 0
        done_docs = 0
        failed_docs = 0
        
        for doc in related_docs:
            # Zliczanie dokumentów według statusu OCR
            total_docs += 1
            if doc.ocr_status == 'pending':
                pending_docs += 1
            elif doc.ocr_status == 'running':
                running_docs += 1
            elif doc.ocr_status == 'done':
                done_docs += 1
            elif doc.ocr_status == 'fail':
                failed_docs += 1
            
            # Grupowanie według typu dokumentu
            doc_type = doc.doc_type or "Inne"
            if doc_type not in grouped_docs:
                grouped_docs[doc_type] = []
            grouped_docs[doc_type].append(doc)
        
        steps = [("k1", "k1 – Wywiad"),
                 ("k2", "k2 – Wyciąg z akt"),
                 ("k3", "k3 – Opinia"),
                 ("k4", "k4 – Archiwum")]
        
        from fastapi.templating import Jinja2Templates
        from app.db import BASE_DIR
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
        
        return templates.TemplateResponse(
            "opinion_detail.html",
            {
                "request": request, 
                "opinion": opinion, 
                "grouped_docs": grouped_docs,
                "steps": steps, 
                "title": f"Opinia #{opinion.id}: {opinion.sygnatura or opinion.original_filename}",
                # Dodaj statystyki OCR do kontekstu
                "total_docs": total_docs,
                "pending_docs": pending_docs,
                "running_docs": running_docs,
                "done_docs": done_docs,
                "failed_docs": failed_docs,
                "has_active_ocr": pending_docs > 0 or running_docs > 0
            }
        )

@router.post("/opinion/{doc_id}/update")
def opinion_update(request: Request, doc_id: int,
                   step: str = Form(...),
                   sygnatura: str | None = Form(None),
                   note : str | None = Form(None)):
    """Aktualizacja statusu opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")
        
        # Aktualizuj dane opinii
        opinion.step = step
        opinion.sygnatura = sygnatura
        opinion.note = note 
        opinion.last_modified = datetime.now()
        # Tu można dodać last_modified_by = current_user
        
        session.add(opinion)
        session.commit()
    
    return RedirectResponse(request.url_for("opinion_detail", doc_id=doc_id), status_code=303)
