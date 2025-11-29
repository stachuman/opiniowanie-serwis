# app/routes/opinions.py - ZAKTUALIZOWANA WERSJA
"""
Endpointy związane z zarządzaniem opiniami.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from datetime import datetime
from pydantic import BaseModel
from typing import List

from app.db import engine, BASE_DIR
from app.models import Document
from app.search import is_fuzzy_match, normalize_text_for_search, extract_context_snippets, ContextSnippet
from app.document_utils import STEP_ICON
from app.text_extraction import get_document_text_content, HAS_DOCX
from app.config import case_status_config
from app.config.search_settings import SEARCH_SETTINGS

# Moduł nawigacji
from app.navigation import build_opinion_navigation, PageActionsBuilder

router = APIRouter()


# Model dla żądania dodatkowych kontekstów
class AdditionalContextsRequest(BaseModel):
    doc_id: int
    search_term: str
    search_content: bool = False
    fuzzy_search: bool = False


# Model dla odpowiedzi z kontekstami
class ContextSnippetResponse(BaseModel):
    highlighted_text: str
    match_type: str
    source_info: str
    confidence: float


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
        search_contexts = {}  # NOWE: przechowuje konteksty wyszukiwania (ograniczone do wyświetlenia)
        search_total_contexts = {}  # NOWE: przechowuje rzeczywistą liczbę WSZYSTKICH kontekstów
        
        if search and search.strip():
            search_term = search.strip()
            filtered_opinions = []

            # Pobierz WSZYSTKIE główne dokumenty dla wyszukiwania (bez filtrów statusów)
            all_docs_query = select(Document).where(Document.is_main == True)
            all_opinions = session.exec(all_docs_query).all()

            for opinion in all_opinions:
                matches = []
                context_snippets = []
                all_context_snippets = []  # NOWE: wszystkie konteksty (bez limitów)

                # Wyszukiwanie w metadanych
                searchable_text = ' '.join(filter(None, [
                    opinion.original_filename or '',
                    opinion.sygnatura or '',
                    opinion.doc_type or ''
                ]))

                metadata_found = False
                if search_term.lower() in searchable_text.lower():
                    matches.append('metadata')
                    metadata_found = True
                elif fuzzy_search and is_fuzzy_match(search_term, searchable_text):
                    matches.append('fuzzy_metadata')
                    metadata_found = True

                if metadata_found:
                    # Dodaj kontekst dla metadanych
                    metadata_contexts = extract_context_snippets(
                        searchable_text, 
                        search_term, 
                        context_length=SEARCH_SETTINGS.get_context_length(),
                        max_snippets=1,
                        is_fuzzy=fuzzy_search
                    )
                    for snippet in metadata_contexts:
                        snippet.match_type = 'metadata'
                        snippet.source_info = 'Metadane dokumentu'
                    context_snippets.extend(metadata_contexts)

                # Wyszukiwanie w treści
                if search_content:
                    content_text = get_document_text_content(opinion)
                    if content_text:
                        content_found = False
                        if search_term.lower() in content_text.lower():
                            matches.append('content')
                            content_found = True
                        elif fuzzy_search and is_fuzzy_match(search_term, content_text):
                            matches.append('fuzzy_content')
                            content_found = True
                        
                        if content_found:
                            # Dodaj kontekst dla treści głównej
                            content_contexts = extract_context_snippets(
                                content_text, 
                                search_term, 
                                context_length=SEARCH_SETTINGS.get_context_length(),
                                max_snippets=SEARCH_SETTINGS.max_context_snippets_per_document,
                                is_fuzzy=fuzzy_search
                            )
                            for snippet in content_contexts:
                                snippet.match_type = 'content'
                                snippet.source_info = 'Treść główna'
                            context_snippets.extend(content_contexts)
                    
                    # NOWE: Wyszukiwanie także w dokumentach podrzędnych (załącznikach)
                    child_docs = session.exec(
                        select(Document).where(Document.parent_id == opinion.id)
                    ).all()
                    
                    for child_doc in child_docs:
                        child_content = get_document_text_content(child_doc)
                        if child_content:
                            child_found = False
                            if search_term.lower() in child_content.lower():
                                matches.append('child_content')
                                child_found = True
                            elif fuzzy_search and is_fuzzy_match(search_term, child_content):
                                matches.append('fuzzy_child_content')
                                child_found = True
                            
                            if child_found:
                                # Dodaj kontekst dla dokumentów podrzędnych
                                child_contexts = extract_context_snippets(
                                    child_content, 
                                    search_term, 
                                    context_length=SEARCH_SETTINGS.get_context_length(),
                                    max_snippets=SEARCH_SETTINGS.max_context_snippets_per_child,
                                    is_fuzzy=fuzzy_search
                                )
                                for snippet in child_contexts:
                                    snippet.match_type = 'attachment'
                                    snippet.source_info = f'Załącznik: {child_doc.original_filename or "bez nazwy"}'
                                context_snippets.extend(child_contexts)

                if matches:
                    search_matches[opinion.id] = matches
                    
                    # NOWE: Oblicz rzeczywistą liczbę WSZYSTKICH kontekstów (tak jak w API)
                    # Użyj tej samej logiki co w API endpoint
                    all_contexts_for_api = []
                    
                    # Metadane (takie same jak powyżej)
                    if metadata_found:
                        metadata_contexts_all = extract_context_snippets(
                            searchable_text, 
                            search_term, 
                            context_length=SEARCH_SETTINGS.get_context_length(),
                            max_snippets=1,
                            is_fuzzy=fuzzy_search
                        )
                        all_contexts_for_api.extend(metadata_contexts_all)
                    
                    # Treść główna z wysokimi limitami
                    if search_content:
                        content_text = get_document_text_content(opinion)
                        if content_text and (search_term.lower() in content_text.lower() or 
                                           (fuzzy_search and is_fuzzy_match(search_term, content_text))):
                            content_contexts_all = extract_context_snippets(
                                content_text, 
                                search_term, 
                                context_length=SEARCH_SETTINGS.get_context_length(),
                                max_snippets=50,  # WYSOKI LIMIT jak w API
                                is_fuzzy=fuzzy_search
                            )
                            all_contexts_for_api.extend(content_contexts_all)
                        
                        # Załączniki z wysokimi limitami
                        child_docs = session.exec(
                            select(Document).where(Document.parent_id == opinion.id)
                        ).all()
                        
                        for child_doc in child_docs:
                            child_content = get_document_text_content(child_doc)
                            if child_content and (search_term.lower() in child_content.lower() or 
                                                (fuzzy_search and is_fuzzy_match(search_term, child_content))):
                                child_contexts_all = extract_context_snippets(
                                    child_content, 
                                    search_term, 
                                    context_length=SEARCH_SETTINGS.get_context_length(),
                                    max_snippets=50,  # WYSOKI LIMIT jak w API
                                    is_fuzzy=fuzzy_search
                                )
                                all_contexts_for_api.extend(child_contexts_all)
                    
                    search_contexts[opinion.id] = context_snippets  # Ograniczone konteksty dla wyświetlenia
                    search_total_contexts[opinion.id] = len(all_contexts_for_api)  # Rzeczywista liczba wszystkich
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
            "search_contexts": search_contexts,  # NOWE: Konteksty wyszukiwania (ograniczone)
            "search_total_contexts": search_total_contexts,  # NOWE: Rzeczywista liczba wszystkich kontekstów
            "search_settings": SEARCH_SETTINGS,  # NOWE: Ustawienia wyszukiwania
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


@router.post("/opinion/{doc_id}/delete", name="opinion_delete")
async def delete_empty_opinion(request: Request, doc_id: int):
    """
    Deletes an empty opinia.

    Validates that:
    - Opinia exists and is a main document
    - Opinia has no user documents (only system files like OCR results)
    - System files will be cascade-deleted
    """
    from tasks.opinion_manager import opinion_manager, ValidationError, DeletionError

    try:
        # Validate first - fail fast
        validation = opinion_manager.validate_opinia_can_be_deleted(doc_id)

        if not validation.can_delete:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete opinia: {validation.reason}"
            )

        # Show warning if system files will be deleted
        if validation.system_documents:
            # Could add a confirmation parameter here if needed
            pass

        # Perform deletion
        result = opinion_manager.delete_empty_opinia(doc_id)

        return RedirectResponse("/", status_code=303)

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DeletionError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting opinia: {str(e)}")


@router.get("/api/opinion/{doc_id}/can-delete", name="api_opinion_can_delete")
def check_opinion_can_delete(doc_id: int):
    """
    Checks if an opinia can be deleted and returns validation details.

    This is useful for UI to show/hide delete button and display warnings.
    """
    from tasks.opinion_manager import opinion_manager, ValidationError

    try:
        validation = opinion_manager.validate_opinia_can_be_deleted(doc_id)

        return {
            "success": True,
            "can_delete": validation.can_delete,
            "reason": validation.reason,
            "user_documents_count": len(validation.user_documents),
            "system_documents_count": len(validation.system_documents),
            "user_documents": [
                {
                    "id": doc.id,
                    "filename": doc.original_filename,
                    "type": doc.doc_type
                }
                for doc in validation.user_documents
            ],
            "system_documents": [
                {
                    "id": doc.id,
                    "filename": doc.original_filename,
                    "type": doc.doc_type
                }
                for doc in validation.system_documents
            ]
        }
    except ValidationError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Validation error: {str(e)}"}


@router.get("/api/opinions/list", name="api_opinions_list")
def get_opinions_list():
    """
    Returns a simple list of all opinions for dropdowns.

    Returns JSON array with opinion id, sygnatura, original_filename, and step.
    """
    with Session(engine) as session:
        opinions = session.exec(
            select(Document)
            .where(Document.is_main == True)
            .order_by(Document.upload_time.desc())
        ).all()

        return [
            {
                "id": opinion.id,
                "sygnatura": opinion.sygnatura,
                "original_filename": opinion.original_filename,
                "step": opinion.step,
                "doc_type": opinion.doc_type
            }
            for opinion in opinions
        ]


@router.post("/api/search/additional-contexts", name="api_additional_contexts")
def get_additional_contexts(request: AdditionalContextsRequest):
    """API endpoint do pobierania dodatkowych kontekstów wyszukiwania."""

    with Session(engine) as session:
        # Pobierz dokument
        document = session.get(Document, request.doc_id)
        if not document:
            return {"success": False, "error": "Dokument nie znaleziony"}
        
        # Odtwórz DOKŁADNIE tę samą logikę co na stronie głównej
        all_contexts = []
        
        # 1. Wyszukiwanie w metadanych (jak na stronie głównej)
        searchable_text = ' '.join(filter(None, [
            document.original_filename or '',
            document.sygnatura or '',
            document.doc_type or ''
        ]))
        
        if request.search_term.lower() in searchable_text.lower():
            metadata_contexts = extract_context_snippets(
                searchable_text, 
                request.search_term, 
                context_length=SEARCH_SETTINGS.get_context_length(),
                max_snippets=1,
                is_fuzzy=request.fuzzy_search
            )
            for snippet in metadata_contexts:
                snippet.match_type = 'metadata'
                snippet.source_info = 'Metadane dokumentu'
            all_contexts.extend(metadata_contexts)
        elif request.fuzzy_search and is_fuzzy_match(request.search_term, searchable_text):
            metadata_contexts = extract_context_snippets(
                searchable_text, 
                request.search_term, 
                context_length=SEARCH_SETTINGS.get_context_length(),
                max_snippets=1,
                is_fuzzy=request.fuzzy_search
            )
            for snippet in metadata_contexts:
                snippet.match_type = 'metadata'
                snippet.source_info = 'Metadane dokumentu'
            all_contexts.extend(metadata_contexts)
        
        # 2. Wyszukiwanie w treści głównej (jak na stronie głównej)
        if request.search_content:
            content_text = get_document_text_content(document)
            if content_text:
                content_found = False
                if request.search_term.lower() in content_text.lower():
                    content_found = True
                elif request.fuzzy_search and is_fuzzy_match(request.search_term, content_text):
                    content_found = True
                
                if content_found:
                    content_contexts = extract_context_snippets(
                        content_text, 
                        request.search_term, 
                        context_length=SEARCH_SETTINGS.get_context_length(),
                        max_snippets=50,  # API: WYSOKIE LIMITY żeby pokazać WSZYSTKIE konteksty
                        is_fuzzy=request.fuzzy_search
                    )
                    for snippet in content_contexts:
                        snippet.match_type = 'content'
                        snippet.source_info = 'Treść główna'
                    all_contexts.extend(content_contexts)
        
        # 3. Wyszukiwanie w dokumentach podrzędnych (jak na stronie głównej)
        if request.search_content:
            child_docs = session.exec(
                select(Document).where(Document.parent_id == document.id)
            ).all()
            
            for child_doc in child_docs:
                child_content = get_document_text_content(child_doc)
                if child_content:
                    child_found = False
                    if request.search_term.lower() in child_content.lower():
                        child_found = True
                    elif request.fuzzy_search and is_fuzzy_match(request.search_term, child_content):
                        child_found = True
                    
                    if child_found:
                        child_contexts = extract_context_snippets(
                            child_content, 
                            request.search_term, 
                            context_length=SEARCH_SETTINGS.get_context_length(),
                            max_snippets=50,  # API: WYSOKIE LIMITY żeby pokazać WSZYSTKIE konteksty
                            is_fuzzy=request.fuzzy_search
                        )
                        for snippet in child_contexts:
                            snippet.match_type = 'attachment'
                            snippet.source_info = f'Załącznik: {child_doc.original_filename or "bez nazwy"}'
                        all_contexts.extend(child_contexts)
        
        # DEBUG: Sprawdź ile kontekstów znaleziono
        print(f"🔍 [API] Znaleziono łącznie {len(all_contexts)} kontekstów dla dokumentu {request.doc_id}")
        for i, ctx in enumerate(all_contexts):
            print(f"  {i}: {ctx.match_type} - {ctx.source_info[:50]}...")
        
        # 4. KLUCZOWE: Zwróć WSZYSTKIE konteksty POWYŻEJ pierwszych 3 (wszystkie pozostałe)
        additional_contexts = all_contexts[3:]  # Pomiń pierwsze 3 pokazane na stronie, zwróć wszystkie pozostałe
        print(f"🔍 [API] Po pominięciu pierwszych 3: {len(additional_contexts)} dodatkowych kontekstów (wszystkie pozostałe)")
        
        # Konwertuj konteksty na format odpowiedzi
        context_responses = []
        for context in additional_contexts:
            context_responses.append(ContextSnippetResponse(
                highlighted_text=context.highlighted_text,
                match_type=context.match_type,
                source_info=context.source_info,
                confidence=context.confidence
            ))
        
        return {
            "success": True,
            "contexts": [ctx.dict() for ctx in context_responses],
            "total_count": len(context_responses)
        }