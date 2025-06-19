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
                Document.doc_type != "ocr_txt"  # Ignoruj wyniki OCR
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
        rotation = data.get('rotation', 0)  # Kąt obrotu z interfejsu (0, 90, 180, 270)
        # DODANE: Informacje o rozmiarach obrazu które frontend widzi
        frontend_width = data.get('frontend_image_width')
        frontend_height = data.get('frontend_image_height')
        display_width = data.get('display_width')
        display_height = data.get('display_height')
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
                        Document.doc_type == "ocr_txt"
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
                    
                    # NOWE: Obsłuż rotację PDF przed crop
                    if rotation != 0:
                        print(f"🔧 [OCR_SELECTION] Obracam stronę PDF o {rotation}° przed crop")
                        
                        # Obróć obraz strony PDF
                        rotation_angle = rotation
                        if rotation_angle == 90:
                            image = image.rotate(-90, expand=True)
                        elif rotation_angle == 180:
                            image = image.rotate(-180, expand=True)
                        elif rotation_angle == 270:
                            image = image.rotate(-270, expand=True)
                        
                        print(f"✅ [OCR_SELECTION] Strona PDF obrócona, nowy rozmiar: {image.size}")
                    
                    cleanup_preprocessed = False  # PDF nie ma preprocessing
                    preprocessed_path = None

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
                        Document.doc_type == "ocr_txt"
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

                # KRYTYCZNE: Zastosuj preprocessing PRZED obliczeniem współrzędnych crop
                # To zapewnia spójność z OCR całego obrazu i obsługuje EXIF orientation
                try:
                    from tasks.ocr.preprocessors import preprocess_image
                    print(f"🔧 [OCR_SELECTION] Preprocessing obrazu przed crop: {file_path}")
                    
                    # Preprocessing zwraca ścieżkę do przetworzonego obrazu
                    # Pomijamy EXIF rotation, bo użytkownik ma kontrolę w interfejsie
                    preprocessed_path = preprocess_image(str(file_path), skip_exif_rotation=True)
                    image = Image.open(preprocessed_path)
                    print(f"✅ [OCR_SELECTION] Obraz po preprocessing: {image.size}")
                    
                    # NOWE: Obsłuż rotację obrazu w backend przed crop
                    if rotation != 0:
                        print(f"🔧 [OCR_SELECTION] Obracam obraz o {rotation}° przed crop")
                        
                        # Obróć obraz zgodnie z rotacją z interfejsu
                        rotation_angle = rotation
                        if rotation_angle == 90:
                            image = image.rotate(-90, expand=True)  # CSS rotate(90°) = PIL rotate(-90°)
                        elif rotation_angle == 180:
                            image = image.rotate(-180, expand=True)
                        elif rotation_angle == 270:
                            image = image.rotate(-270, expand=True)  # CSS rotate(270°) = PIL rotate(90°)
                        
                        print(f"✅ [OCR_SELECTION] Obraz obrócony, nowy rozmiar: {image.size}")
                    
                    # Zapamiętaj ścieżkę do usunięcia później
                    cleanup_preprocessed = preprocessed_path != str(file_path)
                    
                except Exception as e:
                    logger.warning(f"Preprocessing się nie udał, używam oryginału: {str(e)}")
                    # Fallback - użyj oryginalnego obrazu
                    image = Image.open(file_path)
                    
                    # USUŃ: Frontend już skonwertował współrzędne dla obrotu
                    if rotation != 0:
                        print(f"🔧 [OCR_SELECTION] Frontend przesłał rotation={rotation}° - współrzędne już skonwertowane (fallback)")
                    
                    cleanup_preprocessed = False
                    preprocessed_path = str(file_path)

            # KRYTYCZNE: Mapowanie współrzędnych z frontend na backend
            # Frontend: współrzędne (0-1) względem oryginalnego obrazu (naturalWidth/Height)
            # Backend: potrzebuje pikseli względem preprocessowanego obrazu
            
            processed_width, processed_height = image.size
            
            # Jeśli mamy informacje z frontend o rozmiarach
            if frontend_width and frontend_height:
                print(f"🔧 [OCR_SELECTION] Frontend widzi obraz: {frontend_width}x{frontend_height}")
                print(f"🔧 [OCR_SELECTION] Backend ma obraz: {processed_width}x{processed_height}")
                print(f"🔧 [OCR_SELECTION] Wyświetlany rozmiar: {display_width}x{display_height}")
                
                # Oblicz scale factor między tym co frontend widzi a tym co backend ma
                scale_x = processed_width / frontend_width
                scale_y = processed_height / frontend_height
                
                print(f"🔧 [OCR_SELECTION] Scale factors: x={scale_x:.3f}, y={scale_y:.3f}")
                
                # Przelicz współrzędne: (0-1) → piksele frontend → piksele backend 
                crop_x1 = int(x1 * frontend_width * scale_x)
                crop_y1 = int(y1 * frontend_height * scale_y)
                crop_x2 = int(x2 * frontend_width * scale_x)
                crop_y2 = int(y2 * frontend_height * scale_y)
            else:
                # Fallback - bezpośrednie mapowanie (może nie być dokładne dla dużych obrazów)
                print(f"🔧 [OCR_SELECTION] Brak informacji frontend - używam bezpośredniego mapowania")
                crop_x1 = int(x1 * processed_width)
                crop_y1 = int(y1 * processed_height)
                crop_x2 = int(x2 * processed_width)
                crop_y2 = int(y2 * processed_height)
            
            print(f"🔧 [OCR_SELECTION] Crop coordinates: ({crop_x1},{crop_y1}) -> ({crop_x2},{crop_y2}) na obrazie {processed_width}x{processed_height}")

            # Dodaj margines do zaznaczenia
            margin = 5
            crop_x1 = max(0, crop_x1 - margin)
            crop_y1 = max(0, crop_y1 - margin)
            crop_x2 = min(processed_width, crop_x2 + margin)
            crop_y2 = min(processed_height, crop_y2 + margin)

            # Wytnij zaznaczony fragment
            crop_image = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))
            print(f"🔧 [OCR_SELECTION] Fragment po crop: {crop_image.size}")

            # Dodatkowa optymalizacja fragmentu - upewnij się że nie jest za duży
            # (obraz już przeszedł główny preprocessing, więc fragment powinien być bezpieczny)
            from tasks.ocr.config import MAX_IMAGE_DIMENSION
            frag_width, frag_height = crop_image.size
            max_frag_dim = min(MAX_IMAGE_DIMENSION, 1024)  # Maksymalnie 1024px dla fragmentu
            
            if frag_width > max_frag_dim or frag_height > max_frag_dim:
                scale_factor = max_frag_dim / max(frag_width, frag_height)
                new_frag_width = int(frag_width * scale_factor)
                new_frag_height = int(frag_height * scale_factor)
                crop_image = crop_image.resize((new_frag_width, new_frag_height), Image.LANCZOS)
                print(f"🔧 [OCR_SELECTION] Fragment przeskalowany do {new_frag_width}x{new_frag_height}")
            
            # Minimal fragment size
            if crop_image.size[0] < 100 or crop_image.size[1] < 50:
                print(f"⚠️ [OCR_SELECTION] Fragment bardzo mały: {crop_image.size}")
                # Nie skaluj w górę za bardzo - może powodować artefakty

            # Zapisz wycięty fragment do pliku tymczasowego
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name

            # Zapisz obraz fragmentu
            crop_image.save(tmp_path, format="PNG", quality=95)

            try:
                # Uruchom OCR na wyciętym fragmencie - BEZ DODATKOWEGO PREPROCESSING
                # Fragment już przeszedł preprocessing jako część większego obrazu
                instruction = "Extract all the text visible in this image fragment. Keep all formatting."
                
                # KRYTYCZNE: Wyłączamy preprocessing dla fragmentów - już są gotowe
                print(f"🔧 [OCR_SELECTION] OCR fragmentu bez dodatkowego preprocessing")
                fragment_text = process_image_to_text(tmp_path, instruction=instruction, skip_preprocessing=True)

                # Usuń pliki tymczasowe
                try:
                    os.unlink(tmp_path)
                    if cleanup_preprocessed and preprocessed_path != str(file_path):
                        os.unlink(preprocessed_path)
                        print(f"🧹 [OCR_SELECTION] Usunięto preprocessing temp file: {preprocessed_path}")
                except Exception as cleanup_error:
                    print(f"⚠️ [OCR_SELECTION] Błąd czyszczenia: {cleanup_error}")

                # Zwróć wynik
                return {
                    "success": True,
                    "text": fragment_text.strip(),
                    "page": page,
                    "total_pages": total_pages
                }

            except Exception as e:
                logger.error(f"Błąd OCR fragmentu: {str(e)}", exc_info=True)
                
                # Usuń pliki tymczasowe także przy błędzie
                try:
                    os.unlink(tmp_path)
                    if cleanup_preprocessed and preprocessed_path != str(file_path):
                        os.unlink(preprocessed_path)
                except:
                    pass
                
                # Sprawdź czy to błąd CUDA OOM
                if "CUDA out of memory" in str(e) or "OutOfMemoryError" in str(e):
                    return {
                        "success": True,
                        "text": f"Błąd pamięci GPU podczas OCR fragmentu. Fragment może być za duży ({crop_image.size[0]}x{crop_image.size[1]} px). Spróbuj zaznaczyć mniejszy obszar.",
                        "page": page,
                        "total_pages": total_pages,
                        "error_fragment_ocr": "CUDA OOM"
                    }
                else:
                    return {
                        "success": True,
                        "text": "Nie udało się rozpoznać tekstu z fragmentu. Spróbuj zaznaczyć większy obszar lub sprawdź jakość obrazu.",
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