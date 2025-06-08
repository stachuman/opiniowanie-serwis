# app/routes/opinions.py - ZAKTUALIZOWANA WERSJA
"""
Endpointy związane z zarządzaniem opiniami.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from datetime import datetime

from app.db import engine, BASE_DIR
from app.models import Document
from app.search import is_fuzzy_match, normalize_text_for_search
from app.document_utils import STEP_ICON
from app.text_extraction import get_document_text_content, HAS_DOCX

# NOWY IMPORT: Moduł nawigacji
from app.navigation import build_opinion_navigation, PageActionsBuilder

router = APIRouter()

@router.get("/", name="list_opinions")
def list_opinions(request: Request,
                  k1: bool | None = None,
                  k2: bool | None = None,
                  k3: bool | None = None,
                  k4: bool | None = None,
                  search: str | None = None,
                  search_content: bool = False,
                  fuzzy_search: bool = False):
    """Lista opinii z filtrowaniem i wyszukiwaniem."""

    with Session(engine) as session:
        # Pobierz wszystkie główne dokumenty (opinie)
        query = select(Document).where(Document.is_main == True)

        # NOWA LOGIKA: Sprawdź czy to pierwsza wizyta czy użytkownik faktycznie filtruje
        query_params = request.query_params
        has_any_filter_params = any(param in query_params for param in ['k1', 'k2', 'k3', 'k4', 'search'])
        
        if not has_any_filter_params:
            # PIERWSZA WIZYTA - ustaw domyślne filtry (k1, k2, k3 = True, k4 = False)
            k1, k2, k3, k4 = True, True, True, False
        else:
            # UŻYTKOWNIK FILTRUJE - użyj dokładnie tego co przesłał
            # Checkboxy które nie są zaznaczone w ogóle nie są przesyłane, więc None oznacza False
            k1 = k1 if k1 is not None else False
            k2 = k2 if k2 is not None else False  
            k3 = k3 if k3 is not None else False
            k4 = k4 if k4 is not None else False

        # Zastosuj filtry statusów - tylko te które są True
        status_filters = []
        if k1:
            status_filters.append("k1")
        if k2:
            status_filters.append("k2")
        if k3:
            status_filters.append("k3")
        if k4:
            status_filters.append("k4")

        # Jeśli wybrano jakieś filtry, zastosuj je
        if status_filters:
            query = query.where(Document.step.in_(status_filters))
        else:
            # Jeśli żaden filtr nie jest aktywny, pokaż pustą listę
            # (użytkownik świadomie odznaczył wszystko)
            query = query.where(Document.id == -1)  # Brak wyników

        opinions = session.exec(query.order_by(Document.upload_time.desc())).all()

        # Wyszukiwanie (kod bez zmian - zachowujemy istniejącą logikę)
        search_matches = {}
        if search and search.strip():
            search_term = search.strip()
            filtered_opinions = []

            for opinion in opinions:
                matches = []

                # Wyszukiwanie w metadanych
                searchable_text = ' '.join(filter(None, [
                    opinion.original_filename or '',
                    opinion.sygnatura or '',
                    opinion.doc_type or ''
                ]))

                if search_term.lower() in searchable_text.lower():
                    matches.append('metadata')
                elif fuzzy_search and is_fuzzy_match(search_term, searchable_text):
                    matches.append('fuzzy_metadata')

                # Wyszukiwanie w treści
                if search_content:
                    content_text = get_document_text_content(opinion)
                    if content_text:
                        if search_term.lower() in content_text.lower():
                            matches.append('content')
                        elif fuzzy_search and is_fuzzy_match(search_term, content_text):
                            matches.append('fuzzy_content')

                if matches:
                    search_matches[opinion.id] = matches
                    filtered_opinions.append(opinion)

            opinions = filtered_opinions

        # Przygotuj dane filtrów do wyświetlenia
        current_filters = {
            'k1': k1,
            'k2': k2,
            'k3': k3,
            'k4': k4,
            'search': search or '',
            'search_content': search_content,
            'fuzzy_search': fuzzy_search
        }

        # NOWE: Zbuduj akcje strony
        actions = (PageActionsBuilder(request)
                   .add_primary("Nowa opinia z Word",
                                str(request.url_for('upload_form')),
                                "file-earmark-word")
                   .add_secondary("Pusta opinia",
                                  str(request.url_for('create_empty_opinion_form')),
                                  "file-earmark")
                   .add_secondary("Szybki OCR",
                                  str(request.url_for('quick_ocr_form')),
                                  "lightning")
                   .build())

        # NOWE: Kompletny kontekst z nawigacją
        context = {
          "request": request, 
          "opinions": opinions, 
          "icons": STEP_ICON, 
          "title": "Lista opinii",
          "current_filters": current_filters,
          "total_count": len(opinions),
          "has_docx": HAS_DOCX,
          "search_matches": search_matches,
          # NOWE: Elementy nawigacji
          "page_title": "Lista opinii",
          "page_actions": actions,
          "breadcrumbs": [],
          "context_info": []
        }
    
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    
        return templates.TemplateResponse("opinions.html", context)

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

        # NOWE: Zbuduj nawigację za pomocą helpera
        navigation = build_opinion_navigation(request, opinion, session)

        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

        # NOWE: Dodaj elementy nawigacji do kontekstu
        context = {
            "request": request,
            "opinion": opinion,
            "grouped_docs": grouped_docs,
            "steps": steps,
            "title": navigation['page_title'],
            "total_docs": total_docs,
            "pending_docs": pending_docs,
            "running_docs": running_docs,
            "done_docs": done_docs,
            "failed_docs": failed_docs,
            "has_active_ocr": pending_docs > 0 or running_docs > 0,
            # NOWE: Elementy nawigacji
            **navigation
        }

        return templates.TemplateResponse("opinion_detail.html", context)


@router.post("/opinion/{doc_id}/update")
def opinion_update(request: Request, doc_id: int,
                   step: str = Form(...),
                   sygnatura: str | None = Form(None),
                   note: str | None = Form(None)):
    """Aktualizacja statusu opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Aktualizuj pola
        opinion.step = step
        opinion.sygnatura = sygnatura or None
        opinion.note = note or None
        opinion.last_modified = datetime.now()
        # opinion.last_modified_by = current_user  # Gdy będzie system użytkowników

        session.add(opinion)
        session.commit()

    return RedirectResponse(request.url_for("opinion_detail", doc_id=doc_id), status_code=303)


@router.post("/opinion/{doc_id}/update-note")
def opinion_update_note(request: Request, doc_id: int, note: str = Form("")):
    """Aktualizacja notatki do opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Aktualizuj notatkę
        opinion.note = note.strip() or None
        opinion.last_modified = datetime.now()
        # opinion.last_modified_by = current_user  # Gdy będzie system użytkowników

        session.add(opinion)
        session.commit()

    # POPRAWKA: Skonwertuj URL do stringa przed dodaniem parametrów
    base_url = str(request.url_for("list_opinions"))
    return RedirectResponse(
        f"{base_url}?note_updated=true",
        status_code=303
    )
