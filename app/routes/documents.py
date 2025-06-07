# app/routes/documents.py
"""
Endpointy związane z zarządzaniem dokumentów.
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, StreamingResponse
from sqlmodel import Session, select
from datetime import datetime

from app.db import engine, FILES_DIR, BASE_DIR
from app.models import Document
from app.search import is_fuzzy_match
from app.text_extraction import get_document_text_content, get_text_preview
from app.document_utils import STEP_ICON, detect_mime_type

from app.llm_service import llm_service, get_default_instruction, combine_note_with_summary

router = APIRouter()

@router.get("/document/{doc_id}/summarize", name="document_summarize_form")
def document_summarize_form(request: Request, doc_id: int):
    """Formularz do generowania podsumowania dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Sprawdź czy istnieje wynik OCR
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
        
        # WAŻNE: Pobierz wszystkie potrzebne dane przed zamknięciem sesji
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
    
    return templates.TemplateResponse(
        "document_summarize.html",
        {
            "request": request,
            "doc": doc_data,  # Używaj dict zamiast obiektu doc
            "default_instruction": get_default_instruction(),
            "current_note": doc_data["note"] or "",
            "title": f"Podsumowanie dokumentu: {doc_data['original_filename']}"
        }
    )

@router.post("/document/{doc_id}/quick-summarize/stream")
async def document_quick_summarize_stream(
    request: Request,
    doc_id: int,
    custom_instruction: str = Form(None),
    save_to_note: bool = Form(False),
    note_mode: str = Form("append"),
):
    """
    Strumieniowe podsumowanie dokumentu – zwraca tekst na żywo w text/plain.
    """
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
                yield token  # Wyślij token do klienta
            
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

@router.post("/document/{doc_id}/summarize")
async def document_summarize(request: Request, doc_id: int, 
                            custom_instruction: str = Form(None),
                            save_to_note: bool = Form(False),
                            note_mode: str = Form("append")):
    """Generuje podsumowanie dokumentu używając LLM i opcjonalnie zapisuje do notatki."""
    
    # Pobierz dokument i tekst OCR
    doc_name = None  # Zmienna do przechowania nazwy dokumentu
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # WAŻNE: Zapisz nazwę dokumentu przed zamknięciem sesji
        doc_name = doc.original_filename
        
        # Pobierz tekst OCR
        from app.text_extraction import get_ocr_text_for_document
        document_text = get_ocr_text_for_document(doc_id, session)
        
        if not document_text or not document_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Brak tekstu do podsumowania. Sprawdź czy OCR został wykonany poprawnie."
            )
    
    # Przygotuj instrukcję
    instruction = custom_instruction.strip() if custom_instruction else None
    
    # Generuj podsumowanie
    result = await llm_service.generate_summary(document_text, instruction)
    
    # Jeśli generowanie się udało i użytkownik chce zapisać do notatki
    if result["success"] and save_to_note:
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if doc:
                # Połącz z istniejącą notatką
                new_note = combine_note_with_summary(
                    doc.note, 
                    result["summary"], 
                    note_mode
                )
                
                # Zapisz do bazy
                doc.note = new_note
                doc.last_modified = datetime.now()
                session.add(doc)
                session.commit()
                
                result["saved_to_note"] = True
                result["note_mode"] = note_mode
    
    # Zwróć rezultat jako JSON - używaj doc_name zamiast doc.original_filename
    return {
        "success": result["success"],
        "summary": result["summary"],
        "error": result["error"],
        "saved_to_note": result.get("saved_to_note", False),
        "doc_id": doc_id,
        "doc_name": doc_name  # Używaj zmiennej lokalnej zamiast doc.original_filename!
    }

@router.post("/document/{doc_id}/quick-summarize")
async def document_quick_summarize(request: Request, doc_id: int,
                                   custom_instruction: str = Form(None),
                                   save_to_note: bool = Form(False),
                                   note_mode: str = Form("append")):
    """Szybkie podsumowanie dla modalu - NON-STREAMING wersja."""
    
    # Pobierz dokument i tekst OCR
    doc_name = None  # Zmienna do przechowania nazwy dokumentu
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # WAŻNE: Zapisz nazwę dokumentu przed zamknięciem sesji
        doc_name = doc.original_filename
        
        # Pobierz tekst OCR
        from app.text_extraction import get_ocr_text_for_document
        document_text = get_ocr_text_for_document(doc_id, session)
        
        if not document_text or not document_text.strip():
            raise HTTPException(
                status_code=400,
                detail="Brak tekstu do podsumowania. Sprawdź czy OCR został wykonany poprawnie."
            )
    
    # Przygotuj instrukcję
    instruction = custom_instruction.strip() if custom_instruction else None
    
    # Generuj podsumowanie (NON-STREAMING)
    result = await llm_service.generate_summary(document_text, instruction)
    
    # Jeśli generowanie się udało i użytkownik chce zapisać do notatki
    if result["success"] and save_to_note:
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if doc:
                # Połącz z istniejącą notatką
                new_note = combine_note_with_summary(
                    doc.note, 
                    result["summary"], 
                    note_mode
                )
                
                # Zapisz do bazy
                doc.note = new_note
                doc.last_modified = datetime.now()
                session.add(doc)
                session.commit()
                
                result["saved_to_note"] = True
                result["note_mode"] = note_mode
    
    # Zwróć rezultat jako JSON - używaj doc_name zamiast doc.original_filename
    return {
        "success": result["success"],
        "summary": result["summary"],
        "error": result["error"],
        "saved_to_note": result.get("saved_to_note", False),
        "doc_id": doc_id,
        "doc_name": doc_name  # Używaj zmiennej lokalnej zamiast doc.original_filename!
    }

@router.get("/api/llm/test-connection")
async def test_llm_connection():
    """Testuje połączenie z LLM serverem."""
    result = await llm_service.test_connection()
    return result

@router.get("/api/llm/default-instruction")
def get_llm_default_instruction():
    """Zwraca domyślną instrukcję dla LLM."""
    return {"instruction": get_default_instruction()}

@router.post("/api/llm/default-instruction")
def set_llm_default_instruction(instruction: str = Form(...)):
    """Ustawia nową domyślną instrukcję dla LLM."""
    from app.llm_service import set_default_instruction
    set_default_instruction(instruction)
    return {"success": True, "message": "Domyślna instrukcja została zaktualizowana"}

@router.get("/document/{doc_id}/preview-content")
def document_preview_content(request: Request, doc_id: int):
    """Zwraca HTML z zawartością podglądu dokumentu do wyświetlenia w modalu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        
        # Sprawdź, czy istnieje wynik OCR (dokument TXT)
        ocr_txt = None
        if doc.ocr_status == "done":
            ocr_txt_query = select(Document).where(
                Document.ocr_parent_id == doc_id,
                Document.doc_type == "OCR TXT"
            )
            ocr_txt = session.exec(ocr_txt_query).first()
    
    # Importuj i wywołaj funkcję generującą HTML podglądu
    from app.main import _generate_preview_html
    return _generate_preview_html(request, doc, ocr_txt)



@router.post("/document/{doc_id}/update-note")
def update_document_note(request: Request, doc_id: int, note: str = Form("")):
    """Aktualizacja notatki do dokumentu."""
    parent_id = None  # Zmienna do przechowania parent_id poza sesją
    
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Zapisz parent_id przed zamknięciem sesji
        parent_id = doc.parent_id
        
        # Aktualizuj notatkę
        doc.note = note.strip() or None
        doc.last_modified = datetime.now()
        # doc.last_modified_by = current_user  # Gdy będzie system użytkowników
        
        session.add(doc)
        session.commit()
    
    # Jeśli to część opinii, przekieruj do opinii
    if parent_id:
        return RedirectResponse(request.url_for("opinion_detail", doc_id=parent_id), status_code=303)
    else:
        # W przeciwnym razie wróć do szczegółów dokumentu
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
    """Lista wszystkich dokumentów z filtrowaniem i wyszukiwaniem."""
    from app.text_extraction import HAS_DOCX
    
    with Session(engine) as session:
        # Rozpocznij z podstawowym zapytaniem
        query = select(Document)
        
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
        
        # Zastosuj filtr typu dokumentu
        if doc_type_filter and doc_type_filter.strip() and doc_type_filter != "all":
            if doc_type_filter == "opinions":
                query = query.where(Document.is_main == True)
            elif doc_type_filter == "attachments":
                query = query.where(Document.is_main == False)
            elif doc_type_filter == "pdf":
                query = query.where(Document.mime_type == 'application/pdf')
            elif doc_type_filter == "images":
                query = query.where(Document.mime_type.like('image/%'))
            elif doc_type_filter == "word":
                query = query.where(Document.mime_type.like('%word%'))
            elif doc_type_filter == "ocr_results":
                query = query.where(Document.doc_type == "OCR TXT")
        
        # Wykonaj zapytanie z sortowaniem
        all_docs = session.exec(query.order_by(Document.upload_time.desc())).all()
        
        # Słownik z informacjami o dopasowaniach (doc_id -> lista typów dopasowań)
        search_matches = {}
        
        # Zastosuj wyszukiwanie
        if search and search.strip():
            search_term = search.strip().lower()
            filtered_docs = []
            
            for doc in all_docs:
                # Lista typów dopasowań dla tego dokumentu
                match_types = []
                
                # Standardowe wyszukiwanie w metadanych
                metadata_match = (
                    (doc.sygnatura and search_term in doc.sygnatura.lower()) or
                    (doc.original_filename and search_term in doc.original_filename.lower()) or
                    (doc.doc_type and search_term in doc.doc_type.lower())
                )
                
                if metadata_match:
                    match_types.append("metadata")
                
                # Wyszukiwanie rozmyte w metadanych (jeśli włączone)
                fuzzy_metadata_match = False
                if fuzzy_search and not metadata_match:
                    metadata_text = f"{doc.sygnatura or ''} {doc.original_filename or ''} {doc.doc_type or ''}".lower()
                    fuzzy_metadata_match = is_fuzzy_match(search_term, metadata_text)
                    if fuzzy_metadata_match:
                        match_types.append("fuzzy_metadata")
                
                # Wyszukiwanie w treści (jeśli włączone)
                content_match = False
                fuzzy_content_match = False
                if search_content:
                    # Wyszukaj w treści dokumentu (przekaż sesję!)
                    doc_text = get_document_text_content(doc, session)
                    if doc_text:
                        content_match = search_term in doc_text.lower()
                        if content_match:
                            match_types.append("content")
                        elif fuzzy_search:
                            fuzzy_content_match = is_fuzzy_match(search_term, doc_text.lower())
                            if fuzzy_content_match:
                                match_types.append("fuzzy_content")
                
                # Dodaj do wyników jeśli pasuje
                if match_types:
                    search_matches[doc.id] = match_types
                    filtered_docs.append(doc)
            
            docs = filtered_docs
        else:
            docs = all_docs
        
        # Przygotuj dane o aktualnych filtrach do przekazania do szablonu
        current_filters = {
            'k1': k1 if k1 is not None else (k1 is None),  # True jeśli nie określono lub jawnie True
            'k2': k2 if k2 is not None else (k2 is None),
            'k3': k3 if k3 is not None else (k3 is None),
            'k4': k4 if k4 is not None else False,  # False domyślnie dla archiwum
            'search': search or '',
            'search_content': search_content,
            'fuzzy_search': fuzzy_search,
            'doc_type_filter': doc_type_filter or 'all'
        }
        
        from fastapi.templating import Jinja2Templates
        templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
        
        return templates.TemplateResponse(
            "index.html", 
            {
                "request": request, 
                "docs": docs, 
                "icons": STEP_ICON, 
                "title": "Dokumenty",
                "current_filters": current_filters,
                "total_count": len(docs),
                "has_docx": HAS_DOCX,
                "search_matches": search_matches
            }
        )

@router.get("/document/{doc_id}", name="document_detail")
def document_detail(request: Request, doc_id: int):
    """Szczegóły dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        
        # Sprawdź, czy istnieje wynik OCR (dokument TXT)
        ocr_txt = None
        if doc.ocr_status == "done":
            ocr_txt_query = select(Document).where(
                Document.ocr_parent_id == doc_id,
                Document.doc_type == "OCR TXT"
            )
            ocr_txt = session.exec(ocr_txt_query).first()
            
    steps = [("k1", "k1 – Wywiad"),
             ("k2", "k2 – Wyciąg z akt"),
             ("k3", "k3 – Opinia"),
             ("k4", "k4 – Archiwum")]
             
    # Przygotuj kontekst odpowiedzi
    context = {
        "request": request, 
        "doc": doc, 
        "ocr_txt": ocr_txt, 
        "steps": steps, 
        "title": f"Dokument #{doc.id}"
    }
    
    # Jeśli dokument to plik tekstowy, dodaj pełny tekst
    if doc.mime_type == "text/plain":
        context["doc_text_preview"] = get_text_preview(doc.id, max_length=None)
    
    # Jeśli istnieje dokument TXT z OCR, dodaj pełny tekst OCR
    if ocr_txt:
        context["ocr_text_preview"] = get_text_preview(ocr_txt.id, max_length=None)
             
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    
    return templates.TemplateResponse("document.html", context)

@router.post("/document/{doc_id}")
def document_update(request: Request, doc_id: int,
                    step: str = Form(...),
                    sygnatura: str | None = Form(None),
                    doc_type: str | None = Form(None)):
    """Aktualizacja metadanych dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        doc.step = step
        doc.sygnatura = sygnatura or None
        doc.doc_type = doc_type or None
        session.add(doc)
        session.commit()

    return RedirectResponse(request.url_for("document_detail", doc_id=doc_id), status_code=303)

@router.get("/document/{doc_id}/download")
def document_download(doc_id: int):
    """Pobieranie dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        
        # Sprawdź czy dokument istnieje
        file_path = FILES_DIR / doc.stored_filename
        if not file_path.exists():
            # Jeśli plik nie istnieje, może być problem z integracją systemu wersjonowania
            # Spróbuj pobrać najnowszą wersję
            print(f"Plik {doc.stored_filename} nie istnieje, próbuję pobrać najnowszą wersję...")
            
            # Znajdź dokument główny i wszystkie jego wersje
            if doc.is_main:
                main_doc_id = doc.id
            else:
                main_doc_id = doc.parent_id if doc.parent_id else doc.id
                
            # Pobierz wszystkie dokumenty związane z głównym dokumentem (włącznie z głównym)
            docs_query = select(Document).where(
                (Document.id == main_doc_id) | 
                (Document.parent_id == main_doc_id)
            ).order_by(Document.last_modified.desc())
            
            all_versions = session.exec(docs_query).all()
            
            # Znajdź pierwszy dokument, którego plik istnieje
            for version in all_versions:
                version_path = FILES_DIR / version.stored_filename
                if version_path.exists():
                    # Użyj tego pliku zamiast oryginalnego
                    file_path = version_path
                    # Zachowaj oryginalne metadane
                    mime_type = version.mime_type or detect_mime_type(file_path)
                    # Informuj o tym, że użyto alternatywnej wersji
                    print(f"Znaleziono alternatywną wersję: {version.stored_filename}")
                    break
            else:
                # Jeśli żaden plik nie istnieje, zwróć błąd
                raise HTTPException(status_code=404, detail="Nie znaleziono pliku dla tego dokumentu")
            
    # Określamy MIME type na podstawie zapisanego typu lub wykrywamy na nowo
    mime_type = doc.mime_type
    if not mime_type:
        mime_type = detect_mime_type(file_path)
    
    return FileResponse(
        file_path,
        filename=doc.original_filename,
        media_type=mime_type
    )

@router.get("/document/{doc_id}/preview")
def document_preview(request: Request, doc_id: int):
    """Podgląd dokumentu bezpośrednio w przeglądarce."""
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

    # Dla plików tekstowych otwieramy specjalny podgląd
    if mime_type == 'text/plain' or doc.original_filename.lower().endswith('.txt'):
        return RedirectResponse(
            request.url_for("document_text_preview", doc_id=doc.id)
        )
    
    # Dla innych typów, przekierowujemy do pobierania
    return RedirectResponse(
        request.url_for("document_download", doc_id=doc.id)
    )

@router.get("/document/{doc_id}/image-viewer")
def document_image_viewer(request: Request, doc_id: int):
    """Zaawansowany podgląd obrazu z funkcją zaznaczania i OCR."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Sprawdź czy dokument to obraz
        if not doc.mime_type or not doc.mime_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Ten widok jest dostępny tylko dla plików obrazowych")
    
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    
    return templates.TemplateResponse(
        "image_view_with_selection.html", 
        {
            "request": request, 
            "doc": doc,
            "title": f"Podgląd obrazu z zaznaczaniem - {doc.original_filename}"
        }
    )

@router.get("/document/{doc_id}/text-preview")
def document_text_preview(request: Request, doc_id: int):
    """Podgląd pliku tekstowego w formacie HTML."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
    
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
    
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    
    # Renderuj stronę HTML z zawartością tekstu
    return templates.TemplateResponse(
        "text_preview.html",
        {
            "request": request,
            "doc": doc,
            "content": content,
            "error_message": error_message,
            "title": f"Podgląd tekstowy: {doc.original_filename}"
        }
    )

@router.post("/document/{doc_id}/delete")
async def document_delete(request: Request, doc_id: int):
    """Usuwa dokument. Jeśli to opinia, usuwa także wszystkie powiązane dokumenty."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        
        # Sprawdź czy to opinia (dokument główny)
        if doc.is_main:
            # Pobierz wszystkie powiązane dokumenty
            related_docs = session.exec(
                select(Document)
                .where(Document.parent_id == doc_id)
            ).all()
            
            # Usuń pliki powiązanych dokumentów
            for related_doc in related_docs:
                file_path = FILES_DIR / related_doc.stored_filename
                try:
                    if file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    print(f"Błąd podczas usuwania pliku {related_doc.stored_filename}: {e}")
            
            # Usuń powiązane dokumenty z bazy danych
            for related_doc in related_docs:
                session.delete(related_doc)
            
            # Komunikat o usuniętych powiązanych dokumentach
            delete_message = f"Usunięto opinię i {len(related_docs)} powiązanych dokumentów."
        else:
            delete_message = "Dokument został usunięty."
        
        # Usuń plik głównego dokumentu
        file_path = FILES_DIR / doc.stored_filename
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            print(f"Błąd podczas usuwania pliku {doc.stored_filename}: {e}")
        
        # Zapisz informacje o usuwanym dokumencie przed jego usunięciem
        was_opinion = doc.is_main
        parent_id = doc.parent_id
        
        # Usuń dokument z bazy danych
        session.delete(doc)
        session.commit()
    
    # Przekieruj w zależności od typu usuniętego dokumentu
    if was_opinion:
        base_url = str(request.url_for("list_opinions"))
        return RedirectResponse(f"{base_url}?delete_message={delete_message}", status_code=303)
    elif parent_id:
        base_url = str(request.url_for("opinion_detail", doc_id=parent_id))
        return RedirectResponse(f"{base_url}?delete_message={delete_message}", status_code=303)
    else:
        base_url = str(request.url_for("list_documents"))
        return RedirectResponse(f"{base_url}?delete_message={delete_message}", status_code=303)

# Dodaj do app/routes/documents.py

@router.post("/api/document/{doc_id}/update-ocr-text")
async def update_ocr_text(request: Request, doc_id: int, text_content: str = Form(...)):
    """
    Aktualizuje lub tworzy tekst OCR dla dokumentu.
    Używane przez zaawansowane widoki PDF/obrazów do zapisywania dodanych fragmentów.
    """
    import uuid
    from pathlib import Path
    
    with Session(engine) as session:
        # Sprawdź czy dokument źródłowy istnieje
        source_doc = session.get(Document, doc_id)
        if not source_doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Sprawdź czy już istnieje dokument OCR TXT dla tego dokumentu
        ocr_txt_query = select(Document).where(
            Document.ocr_parent_id == doc_id,
            Document.doc_type == "OCR TXT"
        )
        ocr_txt_doc = session.exec(ocr_txt_query).first()
        
        if ocr_txt_doc:
            # Aktualizuj istniejący plik OCR
            ocr_file_path = FILES_DIR / ocr_txt_doc.stored_filename
            
            try:
                # Zapisz nową zawartość do pliku
                ocr_file_path.write_text(text_content, encoding="utf-8")
                
                # Aktualizuj metadane dokumentu OCR
                ocr_txt_doc.last_modified = datetime.now()
                session.add(ocr_txt_doc)
                session.commit()
                
                return {
                    "success": True,
                    "message": "Tekst OCR został zaktualizowany",
                    "ocr_doc_id": ocr_txt_doc.id,
                    "action": "updated"
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Błąd zapisywania pliku: {str(e)}")
        
        else:
            # Utwórz nowy dokument OCR TXT
            try:
                # Utwórz nowy plik tekstowy
                txt_stored = f"{uuid.uuid4().hex}.txt"
                txt_path = FILES_DIR / txt_stored
                txt_path.write_text(text_content, encoding="utf-8")
                
                # Utwórz wpis w bazie danych
                new_ocr_doc = Document(
                    sygnatura=source_doc.sygnatura,
                    doc_type="OCR TXT",
                    original_filename=f"{Path(source_doc.original_filename).stem}_manual_ocr.txt",
                    stored_filename=txt_stored,
                    step=source_doc.step,
                    ocr_status="done",
                    ocr_parent_id=doc_id,
                    ocr_confidence=0.8,  # Średnia pewność dla ręcznie zebranego tekstu
                    mime_type="text/plain",
                    content_type="document",
                    upload_time=datetime.now(),
                    comments="Tekst OCR utworzony/zaktualizowany ręcznie przez zaawansowany podgląd"
                )
                session.add(new_ocr_doc)
                
                # Zaktualizuj status OCR dokumentu źródłowego jeśli był "none"
                if source_doc.ocr_status == "none":
                    source_doc.ocr_status = "done"
                    source_doc.ocr_confidence = 0.8
                    session.add(source_doc)
                
                session.commit()
                
                return {
                    "success": True,
                    "message": "Utworzono nowy plik z tekstem OCR",
                    "ocr_doc_id": new_ocr_doc.id,
                    "action": "created"
                }
                
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Błąd tworzenia pliku OCR: {str(e)}")

@router.get("/api/document/{doc_id}/ocr-text")
def get_ocr_text(doc_id: int):
    """
    Pobiera aktualny tekst OCR dla dokumentu.
    Używane przez zaawansowane widoki do synchronizacji z serwerem.
    """
    with Session(engine) as session:
        # Sprawdź czy dokument istnieje
        source_doc = session.get(Document, doc_id)
        if not source_doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")
        
        # Pobierz tekst OCR
        from app.text_extraction import get_ocr_text_for_document
        ocr_text = get_ocr_text_for_document(doc_id, session)
        
        return {
            "success": True,
            "text": ocr_text or "",
            "has_ocr": bool(ocr_text and ocr_text.strip()),
            "doc_id": doc_id
        }
