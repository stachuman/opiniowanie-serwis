# tasks/document_manager.py
"""
Manager dla operacji na dokumentach.
Zawiera całą logikę biznesową przeniesioną z routes/documents.py.
"""

import shutil
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db import engine, FILES_DIR
from app.models import Document
from app.search import is_fuzzy_match
from app.text_extraction import get_document_text_content, get_ocr_text_for_document
from app.document_utils import detect_mime_type
from app.llm_service import llm_service, combine_note_with_summary


@dataclass
class DocumentListResult:
    """Wynik operacji listowania dokumentów."""
    documents: List[Document]
    search_matches: Dict[int, List[str]]
    total_count: int
    unique_doc_types: List[str]


@dataclass
class DocumentDetailResult:
    """Wynik operacji szczegółów dokumentu."""
    document: Document
    parent_opinion: Optional[Document]
    ocr_txt_document: Optional[Document]
    doc_text_preview: Optional[str] = None
    ocr_text_preview: Optional[str] = None


@dataclass
class DocumentDownloadResult:
    """Wynik operacji pobierania dokumentu."""
    file_path: Path
    original_filename: str
    mime_type: str


@dataclass
class DocumentDeleteResult:
    """Wynik operacji usuwania dokumentu."""
    success: bool
    deleted_count: int
    redirect_url: str
    message: str
    was_opinion: bool


@dataclass
class DocumentSummaryResult:
    """Wynik operacji podsumowania dokumentu."""
    success: bool
    summary: str
    error: Optional[str] = None
    saved_to_note: bool = False
    note_mode: Optional[str] = None


class DocumentManager:
    """Manager dla wszystkich operacji na dokumentach."""

    @staticmethod
    def get_document_list(
            k1: Optional[bool] = None,
            k2: Optional[bool] = None,
            k3: Optional[bool] = None,
            k4: Optional[bool] = None,
            search: Optional[str] = None,
            search_content: bool = False,
            fuzzy_search: bool = False,
            doc_type_filter: Optional[str] = None
    ) -> DocumentListResult:
        """
        Pobiera listę dokumentów z filtrowaniem i wyszukiwaniem.
        Logika z routes/documents.py -> list_documents()
        """
        with Session(engine) as session:
            # Pobierz wszystkie dokumenty
            query = select(Document)

            # Zastosuj filtry statusów
            status_filters = []
            if k1 is not None and k1:
                status_filters.append("k1")
            if k2 is not None and k2:
                status_filters.append("k2")
            if k3 is not None and k3:
                status_filters.append("k3")
            if k4 is not None and k4:
                status_filters.append("k4")

            if status_filters:
                query = query.where(Document.step.in_(status_filters))

            # Filtr typu dokumentu
            if doc_type_filter:
                query = query.where(Document.doc_type == doc_type_filter)

            docs = session.exec(query.order_by(Document.upload_time.desc())).all()

            # Wyszukiwanie
            search_matches = {}
            if search and search.strip():
                search_term = search.strip()
                filtered_docs = []

                for doc in docs:
                    matches = []

                    # Wyszukiwanie w metadanych
                    searchable_text = ' '.join(filter(None, [
                        doc.original_filename or '',
                        doc.sygnatura or '',
                        doc.doc_type or ''
                    ]))

                    if search_term.lower() in searchable_text.lower():
                        matches.append('metadata')
                    elif fuzzy_search and is_fuzzy_match(search_term, searchable_text):
                        matches.append('fuzzy_metadata')

                    # Wyszukiwanie w treści
                    if search_content:
                        content_text = get_document_text_content(doc, session)
                        if content_text:
                            if search_term.lower() in content_text.lower():
                                matches.append('content')
                            elif fuzzy_search and is_fuzzy_match(search_term, content_text):
                                matches.append('fuzzy_content')

                    if matches:
                        search_matches[doc.id] = matches
                        filtered_docs.append(doc)

                docs = filtered_docs

            # Pobierz unikalne typy dokumentów
            unique_doc_types = list(set(filter(None, [doc.doc_type for doc in session.exec(select(Document)).all()])))
            unique_doc_types.sort()

            return DocumentListResult(
                documents=docs,
                search_matches=search_matches,
                total_count=len(docs),
                unique_doc_types=unique_doc_types
            )

    @staticmethod
    def get_document_detail(doc_id: int) -> DocumentDetailResult:
        """
        Pobiera szczegóły dokumentu wraz z powiązanymi danymi.
        Logika z routes/documents.py -> document_detail()
        """
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

            # Pobierz opinię nadrzędną jeśli istnieje
            parent_opinion = None
            if doc.parent_id:
                parent_opinion = session.get(Document, doc.parent_id)

            # Sprawdź, czy istnieje wynik OCR (dokument TXT)
            ocr_txt = None
            if doc.ocr_status == "done":
                ocr_txt_query = select(Document).where(
                    Document.ocr_parent_id == doc_id,
                    Document.doc_type == "OCR TXT"
                )
                ocr_txt = session.exec(ocr_txt_query).first()

            # Przygotuj podglądy tekstów
            doc_text_preview = None
            ocr_text_preview = None

            # Jeśli dokument to plik tekstowy, dodaj pełny tekst
            if doc.mime_type == "text/plain":
                from app.text_extraction import get_text_preview
                doc_text_preview = get_text_preview(doc.id, max_length=None)

            # Jeśli istnieje dokument TXT z OCR, dodaj pełny tekst OCR
            if ocr_txt:
                from app.text_extraction import get_text_preview
                ocr_text_preview = get_text_preview(ocr_txt.id, max_length=None)

            return DocumentDetailResult(
                document=doc,
                parent_opinion=parent_opinion,
                ocr_txt_document=ocr_txt,
                doc_text_preview=doc_text_preview,
                ocr_text_preview=ocr_text_preview
            )

    @staticmethod
    def get_document_for_download(doc_id: int) -> DocumentDownloadResult:
        """
        Przygotowuje dokument do pobrania z obsługą plików historycznych.
        Logika z routes/documents.py -> document_download()
        """
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

            # Obsługa plików historycznych
            if doc.stored_filename.startswith('history/'):
                # Plik historyczny - używaj bezpośrednio ścieżki z stored_filename
                file_path = FILES_DIR / doc.stored_filename
            else:
                # Zwykły plik - sprawdź czy istnieje, jeśli nie to szukaj alternatyw
                file_path = FILES_DIR / doc.stored_filename

                if not file_path.exists():
                    # Znajdź dokument główny i wszystkie jego wersje
                    if doc.is_main:
                        main_doc_id = doc.id
                    else:
                        main_doc_id = doc.parent_id if doc.parent_id else doc.id

                    # Pobierz wszystkie dokumenty związane z głównym dokumentem
                    docs_query = select(Document).where(
                        (Document.id == main_doc_id) |
                        (Document.parent_id == main_doc_id)
                    ).order_by(Document.last_modified.desc())

                    all_versions = session.exec(docs_query).all()

                    # Znajdź pierwszy dokument, którego plik istnieje
                    for version in all_versions:
                        if version.stored_filename.startswith('history/'):
                            version_path = FILES_DIR / version.stored_filename
                        else:
                            version_path = FILES_DIR / version.stored_filename

                        if version_path.exists():
                            file_path = version_path
                            break
                    else:
                        raise HTTPException(status_code=404, detail="Nie znaleziono pliku dla tego dokumentu")

            # Sprawdź końcowo czy plik istnieje
            if not file_path.exists():
                raise HTTPException(status_code=404, detail=f"Plik nie istnieje: {file_path}")

            # Określ MIME type
            mime_type = doc.mime_type
            if not mime_type:
                mime_type = detect_mime_type(file_path)

            return DocumentDownloadResult(
                file_path=file_path,
                original_filename=doc.original_filename,
                mime_type=mime_type
            )

    @staticmethod
    def delete_document(doc_id: int) -> DocumentDeleteResult:
        """
        Usuwa dokument wraz z powiązanymi plikami i dokumentami.
        Logika z routes/documents.py -> document_delete()
        """
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

            deleted_count = 1
            was_opinion = doc.is_main
            parent_id = doc.parent_id

            # Sprawdź czy to opinia (dokument główny)
            if doc.is_main:
                # Pobierz wszystkie powiązane dokumenty
                related_docs = session.exec(
                    select(Document).where(Document.parent_id == doc_id)
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

                deleted_count += len(related_docs)
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

            # Usuń dokument z bazy danych
            session.delete(doc)
            session.commit()

            # Określ URL przekierowania
            if was_opinion:
                redirect_url = f"/?delete_message={delete_message}"
            elif parent_id:
                redirect_url = f"/opinion/{parent_id}?delete_message={delete_message}"
            else:
                redirect_url = f"/documents?delete_message={delete_message}"

            return DocumentDeleteResult(
                success=True,
                deleted_count=deleted_count,
                redirect_url=redirect_url,
                message=delete_message,
                was_opinion=was_opinion
            )

    @staticmethod
    async def summarize_document(
            doc_id: int,
            custom_instruction: Optional[str] = None,
            save_to_note: bool = False,
            note_mode: str = "append"
    ) -> DocumentSummaryResult:
        """
        Generuje podsumowanie dokumentu używając LLM.
        Logika z routes/documents.py -> document_summarize()
        """
        # Pobierz dokument i tekst OCR
        doc_name = None
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

            doc_name = doc.original_filename

            # Pobierz tekst OCR
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

        return DocumentSummaryResult(
            success=result["success"],
            summary=result["summary"],
            error=result["error"],
            saved_to_note=save_to_note and result["success"],
            note_mode=note_mode if save_to_note and result["success"] else None
        )

    @staticmethod
    def update_document(
            doc_id: int,
            step: str,
            sygnatura: Optional[str] = None,
            doc_type: Optional[str] = None
    ) -> bool:
        """
        Aktualizuje metadane dokumentu.
        Logika z routes/documents.py -> document_update()
        """
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")

            doc.step = step
            doc.sygnatura = sygnatura or None
            doc.doc_type = doc_type or None
            doc.last_modified = datetime.now()
            session.add(doc)
            session.commit()
            return True

    @staticmethod
    def update_document_note(
            doc_id: int,
            note: str,
            is_ajax: bool = False
    ) -> Tuple[bool, Optional[int]]:
        """
        Aktualizuje notatkę dokumentu.
        Logika z routes/documents.py -> update_document_note()

        Returns:
            Tuple[success, parent_id] - parent_id needed for redirect logic
        """
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

            parent_id = doc.parent_id

            # Aktualizuj notatkę
            doc.note = note.strip() or None
            doc.last_modified = datetime.now()
            session.add(doc)
            session.commit()

            return True, parent_id

    @staticmethod
    def update_or_create_ocr_text(
            doc_id: int,
            text_content: str
    ) -> Dict[str, Any]:
        """
        Aktualizuje lub tworzy tekst OCR dla dokumentu.
        Logika z routes/documents.py -> update_ocr_text()
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

    @staticmethod
    def get_ocr_text(doc_id: int) -> Dict[str, Any]:
        """
        Pobiera aktualny tekst OCR dla dokumentu.
        Logika z routes/documents.py -> get_ocr_text()
        """
        with Session(engine) as session:
            # Sprawdź czy dokument istnieje
            source_doc = session.get(Document, doc_id)
            if not source_doc:
                raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

            # Pobierz tekst OCR
            ocr_text = get_ocr_text_for_document(doc_id, session)

            return {
                "success": True,
                "text": ocr_text or "",
                "has_ocr": bool(ocr_text and ocr_text.strip()),
                "doc_id": doc_id
            }


# Stwórz singleton instance
document_manager = DocumentManager()