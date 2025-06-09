# app/routes/documents.py - REFACTORED VERSION
"""
Endpointy związane z zarządzaniem dokumentów.
REFAKTORYZACJA: Logika biznesowa przeniesiona do tasks/document_manager.py
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, StreamingResponse
from sqlmodel import Session
from datetime import datetime

from app.navigation import build_document_navigation, PageActionsBuilder
from app.db import engine, BASE_DIR
from app.models import Document
from app.document_utils import STEP_ICON
from app.text_extraction import HAS_DOCX
from app.llm_service import llm_service, get_default_instruction, combine_note_with_summary

# Import managera z tasks
from tasks.document_manager import document_manager

router = APIRouter()


@router.get("/document/{doc_id}/summarize", name="document_summarize_form")
def document_summarize_form(request: Request, doc_id: int):
    """Formularz do generowania podsumowania dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź czy istnieje wynik OCR
        from sqlmodel import select
        ocr_txt_query = select(Document).where(
            Document.ocr_parent_id == doc_id,
            Document.doc_type == "OCR TXT"
        )
        ocr_txt = session.exec(ocr_txt_query).first()

        if not ocr_txt:
            raise HTTPException(
                status_code=400,
                detail="Brak tekstu do podsumowania. Najpierw wykonaj OCR dokumentu."
            )

        # Pobierz opinię nadrzędną jeśli istnieje
        parent_opinion = None
        if doc.parent_id:
            parent_opinion = session.get(Document, doc.parent_id)

        # Zbuduj nawigację
        from app.navigation import BreadcrumbBuilder

        breadcrumbs = BreadcrumbBuilder(request)

        if parent_opinion:
            breadcrumbs.add_home().add_opinion(parent_opinion).add_document(doc)
        else:
            breadcrumbs.add_documents().add_document(doc)

        breadcrumbs.add_current("Podsumowanie", "robot")

        navigation = {
            'breadcrumbs': breadcrumbs.build(),
            'page_title': f"Podsumowanie dokumentu",
            'page_actions': [],
            'context_info': []
        }

        # Pobierz dane przed zamknięciem sesji
        doc_data = {
            "id": doc.id,
            "original_filename": doc.original_filename,
            "sygnatura": doc.sygnatura,
            "doc_type": doc.doc_type,
            "step": doc.step,
            "upload_time": doc.upload_time,
            "note": doc.note,
            "parent_id": doc.parent_id
        }

    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    context = {
        "request": request,
        "doc": doc_data,
        "default_instruction": get_default_instruction(),
        "current_note": doc_data["note"] or "",
        "current_year": datetime.now().year,
        "page_type": "document_summarize",
        **navigation
    }

    return templates.TemplateResponse("document_summarize.html", context)


@router.post("/document/{doc_id}/quick-summarize/stream", name="document_quick_summarize_stream")
async def document_quick_summarize_stream(
        request: Request,
        doc_id: int,
        custom_instruction: str = Form(None),
        save_to_note: bool = Form(False),
        note_mode: str = Form("append"),
):
    """Strumieniowe podsumowanie dokumentu – zwraca tekst na żywo w text/plain."""
    # Pobierz tekst dokumentu
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        from app.text_extraction import get_ocr_text_for_document
        document_text = get_ocr_text_for_document(doc_id, session)

        if not document_text or not document_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Brak tekstu do podsumowania. Sprawdź czy OCR został wykonany."
            )

    # Generator do streamingu
    async def token_generator():
        try:
            full_summary = ""
            async for token in llm_service.stream_summary(document_text, custom_instruction):
                full_summary += token
                yield token

            # Po zakończeniu, jeśli ma zapisać do notatki
            if save_to_note and full_summary.strip():
                with Session(engine) as session:
                    doc = session.get(Document, doc_id)
                    if doc:
                        new_note = combine_note_with_summary(
                            doc.note,
                            full_summary.strip(),
                            note_mode
                        )
                        doc.note = new_note
                        doc.last_modified = datetime.now()
                        session.add(doc)
                        session.commit()

        except Exception as e:
            yield f"BŁĄD: {str(e)}"

    return StreamingResponse(token_generator(), media_type="text/plain")


@router.post("/document/{doc_id}/summarize", name="document_summarize")
async def document_summarize(request: Request, doc_id: int,
                             custom_instruction: str = Form(None),
                             save_to_note: bool = Form(False),
                             note_mode: str = Form("append")):
    """Generuje podsumowanie dokumentu używając LLM - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await document_manager.summarize_document(
        doc_id=doc_id,
        custom_instruction=custom_instruction,
        save_to_note=save_to_note,
        note_mode=note_mode
    )

    # Pobierz nazwę dokumentu dla odpowiedzi
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        doc_name = doc.original_filename if doc else f"Document {doc_id}"

    return {
        "success": result.success,
        "summary": result.summary,
        "error": result.error,
        "saved_to_note": result.saved_to_note,
        "note_mode": result.note_mode,
        "doc_id": doc_id,
        "doc_name": doc_name
    }


@router.post("/document/{doc_id}/quick-summarize", name="document_quick_summarize")
async def document_quick_summarize(request: Request, doc_id: int,
                                   custom_instruction: str = Form(None),
                                   save_to_note: bool = Form(False),
                                   note_mode: str = Form("append")):
    """Szybkie podsumowanie dla modalu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await document_manager.summarize_document(
        doc_id=doc_id,
        custom_instruction=custom_instruction,
        save_to_note=save_to_note,
        note_mode=note_mode
    )

    # Pobierz nazwę dokumentu dla odpowiedzi
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        doc_name = doc.original_filename if doc else f"Document {doc_id}"

    return {
        "success": result.success,
        "summary": result.summary,
        "error": result.error,
        "saved_to_note": result.saved_to_note,
        "note_mode": result.note_mode,
        "doc_id": doc_id,
        "doc_name": doc_name
    }


@router.get("/api/llm/test-connection", name="test_llm_connection")
async def test_llm_connection():
    """Testuje połączenie z LLM serverem."""
    result = await llm_service.test_connection()
    return result


@router.get("/api/llm/default-instruction", name="get_llm_default_instruction")
def get_llm_default_instruction():
    """Zwraca domyślną instrukcję dla LLM."""
    return {"instruction": get_default_instruction()}


@router.post("/api/llm/default-instruction", name="set_llm_default_instruction")
def set_llm_default_instruction(instruction: str = Form(...)):
    """Ustawia nową domyślną instrukcję dla LLM."""
    from app.llm_service import set_default_instruction
    set_default_instruction(instruction)
    return {"success": True, "message": "Domyślna instrukcja została zaktualizowana"}


@router.post("/document/{doc_id}/update-note", name="document_update_note")
def update_document_note(request: Request, doc_id: int, note: str = Form("")):
    """Aktualizacja notatki do dokumentu - REFACTORED."""

    # Sprawdź czy to request AJAX
    accept_header = request.headers.get("accept", "")
    is_ajax = "application/json" in accept_header or "text/javascript" in accept_header

    # Deleguj logikę do managera
    success, parent_id = document_manager.update_document_note(doc_id, note, is_ajax)

    if is_ajax:
        # Dla requestów AJAX zwróć JSON
        return {
            "success": True,
            "message": "Notatka została zaktualizowana",
            "doc_id": doc_id,
            "parent_id": parent_id
        }
    else:
        # Dla zwykłych form-ów przekieruj
        if parent_id:
            return RedirectResponse(request.url_for("opinion_detail", doc_id=parent_id), status_code=303)
        else:
            return RedirectResponse(request.url_for("document_detail", doc_id=doc_id), status_code=303)


@router.get("/documents", name="list_documents")
def list_documents(request: Request,
                   k1: bool | None = None,
                   k2: bool | None = None,
                   k3: bool | None = None,
                   k4: bool | None = None,
                   search: str | None = None,
                   search_content: bool = False,
                   fuzzy_search: bool = False,
                   doc_type_filter: str | None = None):
    """Lista wszystkich dokumentów z filtrowaniem i wyszukiwaniem - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.get_document_list(
        k1=k1, k2=k2, k3=k3, k4=k4,
        search=search,
        search_content=search_content,
        fuzzy_search=fuzzy_search,
        doc_type_filter=doc_type_filter
    )

    # Przygotuj dane filtrów
    current_filters = {
        'k1': k1 if k1 is not None else (k1 is None),
        'k2': k2 if k2 is not None else (k2 is None),
        'k3': k3 if k3 is not None else (k3 is None),
        'k4': k4 if k4 is not None else (k4 is None),
        'search': search or '',
        'search_content': search_content,
        'fuzzy_search': fuzzy_search,
        'doc_type_filter': doc_type_filter or ''
    }

    # Zbuduj akcje strony
    actions = (PageActionsBuilder(request)
               .add_primary("Szybki OCR",
                            str(request.url_for('quick_ocr_form')),
                            "lightning")
               .build())

    # Kompletny kontekst z nawigacją
    context = {
        "request": request,
        "docs": result.documents,
        "icons": STEP_ICON,
        "title": "Wszystkie dokumenty",
        "current_filters": current_filters,
        "total_count": result.total_count,
        "search_matches": result.search_matches,
        "unique_doc_types": result.unique_doc_types,
        "has_docx": HAS_DOCX,
        "current_year": datetime.now().year,
        "page_type": "documents_list",
        # Elementy nawigacji
        "page_title": "Wszystkie dokumenty",
        "page_actions": actions,
        "breadcrumbs": [],
        "context_info": []
    }

    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    return templates.TemplateResponse("documents.html", context)


@router.get("/document/{doc_id}", name="document_detail")
def document_detail(request: Request, doc_id: int):
    """Szczegóły dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.get_document_detail(doc_id)

    # Zbuduj nawigację
    navigation = build_document_navigation(request, result.document, None, result.parent_opinion)

    steps = [("k1", "k1 – Wywiad"),
             ("k2", "k2 – Wyciąg z akt"),
             ("k3", "k3 – Opinia"),
             ("k4", "k4 – Archiwum")]

    # Kontekst odpowiedzi
    context = {
        "request": request,
        "doc": result.document,
        "ocr_txt": result.ocr_txt_document,
        "steps": steps,
        "title": navigation['page_title'],
        "current_year": datetime.now().year,
        "page_type": "document_detail",
        **navigation
    }

    # Dodaj podglądy tekstów jeśli są dostępne
    if result.doc_text_preview:
        context["doc_text_preview"] = result.doc_text_preview
    if result.ocr_text_preview:
        context["ocr_text_preview"] = result.ocr_text_preview

    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    return templates.TemplateResponse("document.html", context)


@router.post("/document/{doc_id}", name="document_update")
def document_update(request: Request, doc_id: int,
                    step: str = Form(...),
                    sygnatura: str | None = Form(None),
                    doc_type: str | None = Form(None)):
    """Aktualizacja metadanych dokumentu - REFACTORED."""

    # Deleguj logikę do managera
    document_manager.update_document(doc_id, step, sygnatura, doc_type)

    return RedirectResponse(request.url_for("document_detail", doc_id=doc_id), status_code=303)


@router.get("/document/{doc_id}/download", name="document_download")
def document_download(doc_id: int):
    """Pobieranie dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.get_document_for_download(doc_id)

    return FileResponse(
        result.file_path,
        filename=result.original_filename,
        media_type=result.mime_type
    )


@router.post("/document/{doc_id}/delete", name="document_delete")
async def document_delete(request: Request, doc_id: int):
    """Usuwa dokument - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.delete_document(doc_id)

    return RedirectResponse(result.redirect_url, status_code=303)


@router.post("/api/document/{doc_id}/update-ocr-text", name="update_ocr_text")
async def update_ocr_text(request: Request, doc_id: int, text_content: str = Form(...)):
    """Aktualizuje lub tworzy tekst OCR dla dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.update_or_create_ocr_text(doc_id, text_content)

    return result


@router.get("/api/documents/export-csv", name="documents_export_csv")
def documents_export_csv(request: Request,
                         k1: bool | None = None,
                         k2: bool | None = None,
                         k3: bool | None = None,
                         k4: bool | None = None,
                         search: str | None = None,
                         search_content: bool = False,
                         fuzzy_search: bool = False,
                         doc_type_filter: str | None = None):
    """Eksport listy dokumentów do CSV."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    # Deleguj logikę listowania do managera
    result = document_manager.get_document_list(
        k1=k1, k2=k2, k3=k3, k4=k4,
        search=search,
        search_content=search_content,
        fuzzy_search=fuzzy_search,
        doc_type_filter=doc_type_filter
    )

    # Utwórz CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Nagłówki
    writer.writerow([
        'ID', 'Typ', 'Sygnatura', 'Rodzaj dokumentu', 'Nazwa pliku',
        'Status', 'OCR', 'Data dodania', 'Ostatnia modyfikacja'
    ])

    # Dane
    for doc in result.documents:
        # Określ typ ikony
        if doc.is_main:
            doc_type_icon = "Opinia główna"
        elif doc.mime_type and doc.mime_type.startswith('image/'):
            doc_type_icon = "Obraz"
        elif doc.mime_type == 'application/pdf':
            doc_type_icon = "PDF"
        elif doc.mime_type and 'word' in doc.mime_type:
            doc_type_icon = "Word"
        elif doc.doc_type == 'OCR TXT':
            doc_type_icon = "Wynik OCR"
        else:
            doc_type_icon = "Dokument"

        # Status OCR
        if doc.ocr_status == 'done':
            ocr_status = 'Zakończony'
        elif doc.ocr_status == 'running':
            ocr_status = 'W trakcie'
        elif doc.ocr_status == 'fail':
            ocr_status = 'Błąd'
        elif doc.ocr_status == 'pending':
            ocr_status = 'Oczekuje'
        else:
            ocr_status = 'Brak'

        writer.writerow([
            doc.id,
            doc_type_icon,
            doc.sygnatura or '',
            doc.doc_type or '',
            doc.original_filename,
            doc.step,
            ocr_status,
            doc.upload_time.strftime('%Y-%m-%d %H:%M') if doc.upload_time else '',
            doc.last_modified.strftime('%Y-%m-%d %H:%M') if doc.last_modified else ''
        ])

    output.seek(0)

    # Zwróć jako plik do pobrania
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        media_type='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=dokumenty_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        }
    )


@router.get("/api/document/{doc_id}/ocr-text", name="get_ocr_text")
def get_ocr_text(doc_id: int):
    """Pobiera aktualny tekst OCR dla dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = document_manager.get_ocr_text(doc_id)

    return result