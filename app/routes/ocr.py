# app/routes/ocr.py
"""
Endpointy związane z OCR - uruchamianie, monitorowanie, zaawansowane viewery.
"""

import asyncio
import tempfile
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from datetime import datetime

from app.db import engine, FILES_DIR, BASE_DIR
from app.models import Document
from app.navigation import build_advanced_viewer_navigation
from app.background_tasks import enqueue_ocr_task

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.post("/document/{doc_id}/run_ocr", name="document_run_ocr")
async def document_run_ocr(request: Request, doc_id: int):
    """Endpoint do ręcznego uruchomienia OCR ponownie."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie ma takiego dokumentu")
        doc.ocr_status = "pending"
        doc.ocr_progress = 0.0
        doc.ocr_progress_info = "Oczekuje w kolejce"
        session.add(doc)
        session.commit()

    # Dodaj do kolejki OCR
    asyncio.create_task(enqueue_ocr_task(doc_id))

    # Dodaj parametr do URL przekierowania, aby pokazać powiadomienie
    redirect_url = request.url_for("document_detail", doc_id=doc_id)
    return RedirectResponse(f"{redirect_url}?ocr_restarted=true", status_code=303)


@router.get("/api/document/{doc_id}/ocr-progress", name="document_ocr_progress")
def document_ocr_progress(doc_id: int):
    """Zwraca informacje o postępie OCR w formacie JSON."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Przygotuj dane o postępie
        progress_data = {
            "status": doc.ocr_status,
            "progress": doc.ocr_progress or 0.0,
            "info": doc.ocr_progress_info or "",
            "current_page": doc.ocr_current_page or 0,
            "total_pages": doc.ocr_total_pages or 0,
            "confidence": doc.ocr_confidence
        }

        return progress_data


@router.get("/document/{doc_id}/ocr-status", name="document_ocr_status")
async def get_ocr_status(doc_id: int):
    """Zwraca status OCR dla pojedynczego dokumentu."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)  # ✅ Poprawna syntax SQLModel
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # ✅ Używaj istniejących pól z modelu
        return {
            "ocr_done": doc.ocr_status == "done",
            "ocr_status": doc.ocr_status,
            "ocr_progress": doc.ocr_progress or 0.0,
            "ocr_info": doc.ocr_progress_info or ""
        }


@router.get("/api/opinion/{opinion_id}/ocr-status", name="opinion_ocr_status")
async def get_opinion_ocr_status(opinion_id: int):
    """Sprawdza status OCR wszystkich dokumentów w opinii."""
    with Session(engine) as session:
        # Sprawdź czy opinia istnieje
        opinion = session.get(Document, opinion_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Pobierz wszystkie dokumenty powiązane z opinią
        related_docs = session.exec(
            select(Document).where(
                Document.parent_id == opinion_id,
                Document.doc_type != "OCR TXT"  # Ignoruj wyniki OCR
            )
        ).all()

        if not related_docs:
            # Brak dokumentów - OCR "zakończony"
            return {
                "ocr_done": True,
                "total_docs": 0,
                "completed_docs": 0,
                "pending_docs": 0,
                "progress_overall": 1.0
            }

        # Policz statusy
        total_docs = len(related_docs)
        completed_docs = sum(1 for doc in related_docs if doc.ocr_status == "done")
        pending_docs = sum(1 for doc in related_docs if doc.ocr_status in ["pending", "running"])
        failed_docs = sum(1 for doc in related_docs if doc.ocr_status == "fail")

        # Oblicz ogólny postęp
        overall_progress = 0.0
        for doc in related_docs:
            if doc.ocr_status == "done":
                overall_progress += 1.0
            elif doc.ocr_status in ["pending", "running"]:
                overall_progress += (doc.ocr_progress or 0.0)
            # fail i none = 0.0

        overall_progress = overall_progress / total_docs if total_docs > 0 else 0.0

        return {
            "ocr_done": pending_docs == 0 and completed_docs > 0,  # Wszystkie zakończone (nie pending)
            "total_docs": total_docs,
            "completed_docs": completed_docs,
            "pending_docs": pending_docs,
            "failed_docs": failed_docs,
            "progress_overall": overall_progress
        }


@router.post("/api/document/{doc_id}/ocr-selection", name="document_ocr_selection")
async def document_ocr_selection(request: Request, doc_id: int):
    """Zwraca OCR dla zaznaczonego fragmentu dokumentu (PDF lub obraz)."""
    # Import funkcji OCR
    from tasks.ocr.models import process_image_to_text
    import PyPDF2
    from pdf2image import convert_from_path
    from PIL import Image
    from tasks.ocr.config import logger

    try:
        # Pobierz dane z POST
        data = await request.json()
        page = data.get('page', 1)  # Numer strony (1-based dla PDF, zawsze 1 dla obrazów)
        x1 = data.get('x1', 0)  # Współrzędne zaznaczenia (0-1)
        y1 = data.get('y1', 0)
        x2 = data.get('x2', 1)
        y2 = data.get('y2', 1)
        skip_pdf_embed = data.get('skip_pdf_embed', False)

        # Sprawdź czy dokument istnieje
        with Session(engine) as session:
            doc = session.get(Document, doc_id)
            if not doc:
                return {"error": "Nie znaleziono dokumentu"}

            # Sprawdź, czy to jest PDF lub obraz
            if not doc.mime_type or (doc.mime_type != 'application/pdf' and not doc.mime_type.startswith('image/')):
                return {"error": "Ta funkcja obsługuje tylko pliki PDF i obrazy"}

            # Ścieżka do pliku
            file_path = FILES_DIR / doc.stored_filename
            if not file_path.exists():
                return {"error": "Nie znaleziono pliku"}

            # Obsługa PDF
            if doc.mime_type == 'application/pdf':
                # Pobierz liczbę stron z PDF
                try:
                    with open(file_path, 'rb') as pdf_file:
                        pdf_reader = PyPDF2.PdfReader(pdf_file)
                        total_pages = len(pdf_reader.pages)

                        # Sprawdź, czy żądana strona istnieje
                        if page <= 0 or page > total_pages:
                            return {"error": f"Strona {page} nie istnieje. Dokument ma {total_pages} stron."}
                except Exception as e:
                    logger.error(f"Błąd odczytu dokumentu PDF: {str(e)}", exc_info=True)
                    return {"error": f"Nie można odczytać dokumentu PDF: {str(e)}"}

                # Sprawdź czy to jest zaznaczenie całej strony
                is_full_page = (abs(x1) < 0.01 and abs(y1) < 0.01 and abs(x2 - 1.0) < 0.01 and abs(y2 - 1.0) < 0.01)

                # Jeśli to zaznaczenie całej strony, sprawdź czy mamy już OCR
                if is_full_page:

                    ocr_txt_query = select(Document).where(
                        Document.ocr_parent_id == doc_id,
                        Document.doc_type == "OCR TXT"
                    ).order_by(Document.upload_time.desc())  # ✅ NAJNOWSZY PIERWSZY
                    ocr_txt = session.exec(ocr_txt_query).first()

                    if ocr_txt:
                        # Mamy już OCR, zwróć go
                        from app.text_extraction import get_ocr_text_for_document
                        page_text = get_ocr_text_for_document(doc_id, session)
                        if page_text:
                            return {
                                "success": True,
                                "text": page_text.strip(),
                                "page": page,
                                "total_pages": total_pages,
                                "is_full_page": True
                            }

                # Konwertuj stronę PDF na obraz
                try:
                    # Konwertuj tylko wybraną stronę
                    images = convert_from_path(str(file_path), first_page=page, last_page=page, dpi=300)

                    if not images:
                        return {"error": "Nie można skonwertować strony PDF na obraz"}

                    # Weź pierwszy obraz strony
                    image = images[0]

                except Exception as e:
                    logger.error(f"Błąd konwersji PDF na obraz: {str(e)}", exc_info=True)
                    return {"error": f"Błąd podczas konwersji PDF na obraz: {str(e)}"}

            # Obsługa obrazów
            elif doc.mime_type.startswith('image/'):
                # Dla obrazów nie ma stron, zawsze używamy strony 1
                total_pages = 1

                # Sprawdź czy to jest zaznaczenie całego obrazu
                is_full_image = (abs(x1) < 0.01 and abs(y1) < 0.01 and abs(x2 - 1.0) < 0.01 and abs(y2 - 1.0) < 0.01)

                # Jeśli to zaznaczenie całego obrazu, sprawdź czy mamy już OCR
                if is_full_image:
                    ocr_txt_query = select(Document).where(
                        Document.ocr_parent_id == doc_id,
                        Document.doc_type == "OCR TXT"
                    ).order_by(Document.upload_time.desc())  # ✅ NAJNOWSZY PIERWSZY
                    ocr_txt = session.exec(ocr_txt_query).first()
                
                    if ocr_txt:
                        # Mamy już OCR, zwróć go
                        from app.text_extraction import get_ocr_text_for_document
                        image_text = get_ocr_text_for_document(doc_id, session)
                        if image_text:
                            return {
                                "success": True,
                                "text": image_text.strip(),
                                "page": 1,
                                "total_pages": 1,
                                "is_full_image": True
                            }

                # Otwórz obraz bezpośrednio
                try:
                    image = Image.open(file_path)
                except Exception as e:
                    logger.error(f"Błąd otwarcia obrazu: {str(e)}", exc_info=True)
                    return {"error": f"Nie można otworzyć obrazu: {str(e)}"}

            # Oblicz współrzędne zaznaczenia w pikselach
            width, height = image.size
            crop_x1 = int(x1 * width)
            crop_y1 = int(y1 * height)
            crop_x2 = int(x2 * width)
            crop_y2 = int(y2 * height)

            # Dodaj margines do zaznaczenia
            margin = 5
            crop_x1 = max(0, crop_x1 - margin)
            crop_y1 = max(0, crop_y1 - margin)
            crop_x2 = min(width, crop_x2 + margin)
            crop_y2 = min(height, crop_y2 + margin)

            # Wytnij zaznaczony fragment
            crop_image = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))

            # Zapisz wycięty fragment do pliku tymczasowego
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            # Opcjonalne powiększenie małych fragmentów
            crop_width, crop_height = crop_image.size
            min_dimension = 300
            if crop_width < min_dimension or crop_height < min_dimension:
                scale_factor = min_dimension / min(crop_width, crop_height)
                new_width = int(crop_width * scale_factor)
                new_height = int(crop_height * scale_factor)
                crop_image = crop_image.resize((new_width, new_height), Image.LANCZOS)

            # Zapisz obraz fragmentu
            crop_image.save(tmp_path, format="PNG", quality=95)

            try:
                # Uruchom OCR na wyciętym fragmencie
                instruction = "Extract all the text visible in this image fragment. Keep all formatting."
                fragment_text = process_image_to_text(tmp_path, instruction=instruction)

                # Usuń plik tymczasowy
                os.unlink(tmp_path)

                # Zwróć wynik
                return {
                    "success": True,
                    "text": fragment_text.strip(),
                    "page": page,
                    "total_pages": total_pages
                }

            except Exception as e:
                logger.error(f"Błąd OCR fragmentu: {str(e)}", exc_info=True)
                return {
                    "success": True,
                    "text": "Nie udało się rozpoznać tekstu z fragmentu. Spróbuj zaznaczyć większy obszar.",
                    "page": page,
                    "total_pages": total_pages,
                    "error_fragment_ocr": str(e)
                }

    except Exception as e:
        logger.error(f"Globalny błąd OCR zaznaczenia: {str(e)}", exc_info=True)
        return {"error": f"Błąd: {str(e)}"}


@router.get("/document/{doc_id}/pdf-viewer", name="document_pdf_viewer")
def document_pdf_viewer(request: Request, doc_id: int):
    """Zaawansowany podgląd PDF z funkcją zaznaczania i OCR."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź czy dokument to PDF
        if not doc.mime_type or doc.mime_type != 'application/pdf':
            raise HTTPException(status_code=400, detail="Ten widok jest dostępny tylko dla plików PDF")

        # Zbuduj nawigację dla zaawansowanego viewera PDF
        navigation = build_advanced_viewer_navigation(request, doc, session, 'pdf_viewer')

    context = {
        "request": request,
        "doc": doc,
        "current_year": datetime.now().year,
        "page_type": "pdf_viewer",
        **navigation
    }

    return templates.TemplateResponse("pdf_view_with_selection.html", context)


@router.get("/document/{doc_id}/image-viewer", name="document_image_viewer")
def document_image_viewer(request: Request, doc_id: int):
    """Zaawansowany podgląd obrazu z funkcją zaznaczania i OCR."""
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Nie znaleziono dokumentu")

        # Sprawdź czy dokument to obraz
        if not doc.mime_type or not doc.mime_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="Ten widok jest dostępny tylko dla plików obrazowych")

        # Zbuduj nawigację dla zaawansowanego viewera obrazu
        navigation = build_advanced_viewer_navigation(request, doc, session, 'image_viewer')

    context = {
        "request": request,
        "doc": doc,
        "current_year": datetime.now().year,
        "page_type": "image_viewer",
        **navigation
    }

    return templates.TemplateResponse("image_view_with_selection.html", context)