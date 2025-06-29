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
from app.config import case_status_config

# Moduł nawigacji
from app.navigation import build_opinion_navigation, PageActionsBuilder

router = APIRouter()


@router.get("/", name="list_opinions")
def list_opinions(request: Request,
                  search: str | None = None,
                  search_content: bool = False,
                  fuzzy_search: bool = False,
                  sort_by: str | None = None,
                  sort_order: str = "asc"):
    """Lista opinii z filtrowaniem i wyszukiwaniem."""

    with Session(engine) as session:
        # Pobierz wszystkie główne dokumenty (opinie)
        query = select(Document).where(Document.is_main == True)

        # Pobierz wszystkie dostępne statusy z konfiguracji
        all_status_codes = [status.code for status in case_status_config.get_all_statuses()]
        
        # Sprawdź czy to pierwsza wizyta czy użytkownik faktycznie filtruje
        query_params = request.query_params
        status_filter_params = [code for code in all_status_codes if code in query_params]
        has_any_filter_params = status_filter_params or 'search' in query_params

        # Ustal aktywne filtry statusów
        if not has_any_filter_params:
            # PIERWSZA WIZYTA - użyj domyślnie widocznych statusów z konfiguracji
            active_status_filters = case_status_config.get_default_visible_codes()
        else:
            # UŻYTKOWNIK FILTRUJE - użyj tylko te statusy które są w query params
            # Checkboxy które nie są zaznaczone w ogóle nie są przesyłane
            active_status_filters = status_filter_params

        # Zastosuj filtry statusów
        if active_status_filters:
            query = query.where(Document.step.in_(active_status_filters))
        else:
            # Jeśli żaden filtr nie jest aktywny, pokaż pustą listę
            # (użytkownik świadomie odznaczył wszystko)
            query = query.where(Document.id == -1)  # Brak wyników

        # Sortowanie
        if sort_by == "sygnatura":
            if sort_order == "desc":
                query = query.order_by(Document.sygnatura.desc())
            else:
                query = query.order_by(Document.sygnatura.asc())
        elif sort_by == "filename":
            if sort_order == "desc":
                query = query.order_by(Document.original_filename.desc())
            else:
                query = query.order_by(Document.original_filename.asc())
        elif sort_by == "last_modified":
            if sort_order == "desc":
                query = query.order_by(Document.last_modified.desc())
            else:
                query = query.order_by(Document.last_modified.asc())
        elif sort_by == "status":
            if sort_order == "desc":
                query = query.order_by(Document.step.desc())
            else:
                query = query.order_by(Document.step.asc())
        else:
            # Domyślne sortowanie po czasie dodania (najnowsze pierwsze)
            query = query.order_by(Document.upload_time.desc())

        opinions = session.exec(query).all()

        # Wyszukiwanie - ZMIENIONA LOGIKA: wyszukiwanie w WSZYSTKICH dokumentach niezależnie od filtrów
        search_matches = {}
        if search and search.strip():
            search_term = search.strip()
            filtered_opinions = []

            # Pobierz WSZYSTKIE główne dokumenty dla wyszukiwania (bez filtrów statusów)
            all_docs_query = select(Document).where(Document.is_main == True)
            all_opinions = session.exec(all_docs_query).all()

            for opinion in all_opinions:
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
                    
                    # NOWE: Wyszukiwanie także w dokumentach podrzędnych (załącznikach)
                    child_docs = session.exec(
                        select(Document).where(Document.parent_id == opinion.id)
                    ).all()
                    
                    for child_doc in child_docs:
                        child_content = get_document_text_content(child_doc)
                        if child_content:
                            if search_term.lower() in child_content.lower():
                                matches.append('child_content')
                            elif fuzzy_search and is_fuzzy_match(search_term, child_content):
                                matches.append('fuzzy_child_content')

                if matches:
                    search_matches[opinion.id] = matches
                    filtered_opinions.append(opinion)

            # NOWA LOGIKA: gdy wyszukiwanie jest aktywne, pokazuj WSZYSTKIE znalezione dokumenty
            # niezależnie od filtrów statusów
            opinions = filtered_opinions

        # Przygotuj dane filtrów do wyświetlenia
        current_filters = {
            'search': search or '',
            'search_content': search_content,
            'fuzzy_search': fuzzy_search,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'active_statuses': active_status_filters
        }
        
        # Dodaj każdy status osobno dla kompatybilności z template
        for status_code in all_status_codes:
            current_filters[status_code] = status_code in active_status_filters

        # Zbuduj akcje strony
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

        # Kompletny kontekst z nawigacją
        context = {
            "request": request,
            "opinions": opinions,
            "icons": STEP_ICON,
            "title": "Lista opinii",
            "current_filters": current_filters,
            "total_count": len(opinions),
            "has_docx": HAS_DOCX,
            "search_matches": search_matches,
            "current_year": datetime.now().year,
            "page_type": "opinions_list",  # NOWE: Dodany page_type
            # Dane statusów z konfiguracji
            "all_statuses": case_status_config.get_all_statuses(),
            "status_colors": case_status_config.get_status_colors(),
            "status_icons": case_status_config.get_status_icons(),
            # Elementy nawigacji
            "page_title": "Lista opinii",
            "page_actions": actions,
            "breadcrumbs": [],
            "context_info": []
        }

        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

        return templates.TemplateResponse("opinions.html", context)


@router.get("/opinion/{doc_id}", name="opinion_detail")
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

        # Pobierz steps z konfiguracji
        steps = [(status.code, status.name) for status in case_status_config.get_all_statuses()]

        # Zbuduj nawigację za pomocą helpera
        navigation = build_opinion_navigation(request, opinion, session)

        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

        # Dodaj elementy nawigacji do kontekstu
        context = {
            "request": request,
            "opinion": opinion,
            "related_docs": related_docs,  # DODANE: Potrzebne dla opinion_detail.html
            "grouped_docs": grouped_docs,
            "steps": steps,
            "steps_dict": case_status_config.get_status_dict(),  # Mapowanie z konfiguracji
            "title": navigation['page_title'],
            "total_docs": total_docs,
            "pending_docs": pending_docs,
            "running_docs": running_docs,
            "done_docs": done_docs,
            "failed_docs": failed_docs,
            "has_active_ocr": pending_docs > 0 or running_docs > 0,
            "current_year": datetime.now().year,
            "page_type": "opinion_detail",  # NOWE: Dodany page_type
            # Elementy nawigacji
            **navigation
        }

        return templates.TemplateResponse("opinion_detail.html", context)


@router.post("/opinion/{doc_id}/update", name="opinion_update")
def opinion_update(request: Request, doc_id: int,
                   step: str = Form(...),
                   sygnatura: str | None = Form(None)):
                   # note: str | None = Form(None)):
    """Aktualizacja statusu opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Aktualizuj pola
        opinion.step = step
        opinion.sygnatura = sygnatura or None
        # opinion.note = note or None
        opinion.last_modified = datetime.now()
        # opinion.last_modified_by = current_user  # Gdy będzie system użytkowników

        session.add(opinion)
        session.commit()

    return RedirectResponse(request.url_for("opinion_detail", doc_id=doc_id), status_code=303)


@router.post("/opinion/{doc_id}/update-note", name="opinion_update_note")
def opinion_update_note(request: Request, doc_id: int, note: str = Form("")):
    """Aktualizacja notatki do opinii."""

    # Sprawdź czy to request AJAX
    accept_header = request.headers.get("accept", "")
    is_ajax = "application/json" in accept_header or "text/javascript" in accept_header

    # Przechowaj notatkę do zwrócenia
    updated_note = None

    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            if is_ajax:
                return {"success": False, "error": "Nie znaleziono opinii"}
            else:
                raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Aktualizuj notatkę
        opinion.note = note.strip() or None
        opinion.last_modified = datetime.now()
        updated_note = opinion.note

        session.add(opinion)
        session.commit()

    if is_ajax:
        # Dla requestów AJAX zwróć JSON
        return {
            "success": True,
            "message": "Notatka została zaktualizowana",
            "doc_id": doc_id,
            "note": updated_note
        }
    else:
        # Dla zwykłych form-ów - inteligentne przekierowanie
        referer = request.headers.get("referer", "")

        if f"/opinion/{doc_id}" in referer:
            # Jeśli przyszedł ze strony szczegółów opinii
            return RedirectResponse(
                request.url_for("opinion_detail", doc_id=doc_id),
                status_code=303
            )
        else:
            # Jeśli przyszedł z listy opinii lub innej strony
            return RedirectResponse(
                str(request.url_for("list_opinions")) + "?note_updated=true",
                status_code=303
            )