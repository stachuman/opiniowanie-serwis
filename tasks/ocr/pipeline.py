"""
Główny pipeline przetwarzania OCR.
CZYSTA WERSJA - tylko SQLite, bez SQLModel Session.
"""
import sqlite3
import uuid
import tempfile
import os
from datetime import datetime
from pathlib import Path

from app.db import FILES_DIR

# Importujemy funkcje z innych modułów OCR
from .models import process_image_to_text
from .postprocessors import clean_ocr_text, estimate_ocr_confidence


def process_document_sync(doc_id: int) -> dict:
    """
    Główna funkcja OCR dla ProcessPoolExecutor.
    Używa tylko SQLite - bez SQLModel Session.
    """
    try:
        print(f"🔄 [PROCES] Rozpoczynam OCR dla dokumentu {doc_id}")

        # Uruchom główne przetwarzanie
        result_id = process_document_sqlite(doc_id)

        print(f"✅ [PROCES] OCR zakończony dla {doc_id}, txt_doc_id: {result_id}")
        return {"success": True, "doc_id": doc_id, "result_id": result_id}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ [PROCES] Błąd OCR dla {doc_id}: {error_msg}")

        # Zaktualizuj status na błąd
        update_document_status(doc_id, "fail", f"Błąd: {error_msg}")

        return {"success": False, "error": error_msg, "doc_id": doc_id}


def process_document_sqlite(doc_id: int) -> int:
    """
    Główna funkcja przetwarzania OCR używająca tylko SQLite.

    Returns:
        int: ID utworzonego dokumentu TXT lub None w przypadku błędu
    """
    # Połączenie z bazą
    db_path = get_db_path()

    # Pobierz dane dokumentu
    doc_data = get_document_data(doc_id)
    if not doc_data:
        raise Exception(f"Nie znaleziono dokumentu o ID={doc_id}")

    stored_filename, original_filename, mime_type, content_type, sygnatura, step = doc_data

    # Oznacz jako running
    update_document_status(doc_id, "running", "Inicjalizacja procesu OCR", 0.0)

    print(f"🔄 [PROCES] Przetwarzam: {original_filename}")

    # Sprawdź czy plik istnieje
    file_path = FILES_DIR / stored_filename
    if not file_path.exists():
        raise Exception(f"Plik źródłowy nie istnieje: {file_path}")

    # Określ typ przetwarzania
    is_image = content_type == 'image' or (mime_type and mime_type.startswith('image/'))

    try:
        if is_image:
            # Przetwarzanie pojedynczego obrazu
            text_all, confidence_score = process_single_image(doc_id, file_path, original_filename)
        else:
            # Przetwarzanie PDF (wielostronicowe)
            text_all, confidence_score = process_pdf_document(doc_id, file_path, original_filename)

            # Osadź tekst w PDF jeśli to PDF
            if mime_type == 'application/pdf':
                print(f"📎 [PROCES] Osadzanie tekstu w PDF")
                update_document_status(doc_id, "running", "Osadzanie tekstu w pliku PDF", 0.95)
                embed_text_in_pdf(file_path)

        # Zapisz wyniki do plików i bazy
        txt_doc_id = save_ocr_results(doc_id, text_all, confidence_score, original_filename, sygnatura, step)

        # Zaktualizuj status na done
        update_document_status(doc_id, "done", "OCR zakończony", 1.0, confidence_score)

        print(f"✅ [PROCES] OCR zakończony pomyślnie dla {doc_id}")
        return txt_doc_id

    except Exception as e:
        error_msg = str(e)
        print(f"❌ [PROCES] Błąd przetwarzania OCR: {error_msg}")
        update_document_status(doc_id, "fail", f"Błąd: {error_msg}", 1.0)
        raise


def process_single_image(doc_id: int, file_path: Path, filename: str):
    """Przetwarzanie pojedynczego obrazu."""
    print(f"🖼️ [PROCES] Obraz: {filename}")

    update_document_status(doc_id, "running", "Przygotowanie obrazu do OCR", 0.3)

    # OCR obrazu
    page_text = process_image_to_text(str(file_path))

    update_document_status(doc_id, "running", "Czyszczenie tekstu", 0.8)

    # Oczyść tekst i oblicz pewność
    clean_text = clean_ocr_text(page_text)
    confidence = estimate_ocr_confidence(clean_text)

    print(f"✅ [PROCES] Obraz: {len(clean_text)} znaków, pewność: {confidence:.2f}")

    return clean_text, confidence


def process_pdf_document(doc_id: int, file_path: Path, filename: str):
    """Przetwarzanie dokumentu PDF (wielostronicowe)."""
    print(f"📄 [PROCES] PDF: {filename}")

    update_document_status(doc_id, "running", "Konwersja PDF na obrazy", 0.1)

    # Konwertuj PDF na obrazy
    from pdf2image import convert_from_path
    pages = convert_from_path(str(file_path), dpi=200)
    total_pages = len(pages)

    update_document_status(doc_id, "running", f"Wykryto {total_pages} stron", 0.2, total_pages=total_pages)

    print(f"📄 [PROCES] Wykryto {total_pages} stron")

    # Przetwarzaj każdą stronę
    page_texts = []
    confidence_scores = []

    for page_number, img in enumerate(pages, 1):
        print(f"🔍 [PROCES] Strona {page_number}/{total_pages}")

        # Aktualizuj postęp
        progress = 0.2 + (0.7 * page_number / total_pages)
        update_document_status(
            doc_id, "running",
            f"Przetwarzanie strony {page_number}/{total_pages}",
            progress, current_page=page_number, total_pages=total_pages
        )

        # Zapisz obraz do pliku tymczasowego
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            img_path = tmp_img.name

        try:
            # Zapisz i przetwórz stronę
            img.save(img_path, "PNG")

            # OCR strony
            page_text = process_image_to_text(img_path)
            clean_text = clean_ocr_text(page_text)
            confidence = estimate_ocr_confidence(clean_text)

            page_texts.append(clean_text)
            confidence_scores.append(confidence)

            print(f"✅ [PROCES] Strona {page_number}: {len(clean_text)} znaków, pewność: {confidence:.2f}")

        except Exception as e:
            print(f"❌ [PROCES] Błąd OCR strony {page_number}: {str(e)}")
            page_texts.append(f"[Błąd OCR dla strony {page_number}: {str(e)}]")
            confidence_scores.append(0.0)

        finally:
            # Usuń plik tymczasowy
            if os.path.exists(img_path):
                os.remove(img_path)

    # Połącz teksty stron
    text_all = ""
    for i, page_text in enumerate(page_texts, 1):
        text_all += f"\n\n=== Strona {i} ===\n\n{page_text}"

    text_all = text_all.strip()

    # Oblicz średnią pewność
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

    return text_all, avg_confidence


def save_ocr_results(doc_id: int, text_content: str, confidence: float,
                    original_filename: str, sygnatura: str, step: str) -> int:
    """Zapisuje wyniki OCR do pliku i bazy danych."""

    update_document_status(doc_id, "running", "Zapisywanie wyników", 0.9)

    # Zapisz tekst do pliku
    txt_filename = f"{uuid.uuid4().hex}.txt"
    txt_path = FILES_DIR / txt_filename
    txt_path.write_text(text_content, encoding="utf-8")

    print(f"💾 [PROCES] Zapisano tekst: {txt_filename} ({len(text_content)} znaków)")

    # Zapisz do bazy danych
    db_path = get_db_path()
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()

        # Utwórz wpis dla dokumentu TXT
        txt_original_name = f"{Path(original_filename).stem}.txt"
        now_iso = datetime.utcnow().isoformat()

        cursor.execute("""
            INSERT INTO document (
                sygnatura, doc_type, original_filename, stored_filename,
                step, ocr_status, ocr_parent_id, ocr_confidence,
                mime_type, content_type, upload_time, is_main,
                last_modified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sygnatura, "OCR TXT", txt_original_name, txt_filename,
            step, "done", doc_id, confidence,
            "text/plain", "document", now_iso, 0, now_iso
        ))

        txt_doc_id = cursor.lastrowid
        conn.commit()

        print(f"✅ [PROCES] Utworzono dokument TXT ID: {txt_doc_id}")

        return txt_doc_id


def embed_text_in_pdf(pdf_path: Path):
    """Osadza tekst w PDF używając ocrmypdf."""
    try:
        import subprocess
        import shutil

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_out:
            tmp_path = tmp_out.name

        print(f"📎 [PROCES] Uruchamiam ocrmypdf...")

        result = subprocess.run(
            ["ocrmypdf", "--skip-text", "--sidecar", "/dev/null", str(pdf_path), tmp_path],
            check=True, capture_output=True, text=True
        )

        # Zamień oryginalny plik
        shutil.move(tmp_path, str(pdf_path))

        print(f"✅ [PROCES] Osadzono tekst w PDF")
        return True

    except Exception as e:
        print(f"⚠️ [PROCES] Błąd osadzania tekstu w PDF: {str(e)}")
        return False


# ==================== FUNKCJE POMOCNICZE ====================

def get_db_path() -> Path:
    """Zwraca ścieżkę do bazy danych."""
    return Path(__file__).parent.parent.parent / "data.db"


def get_document_data(doc_id: int):
    """Pobiera dane dokumentu z bazy."""
    db_path = get_db_path()
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stored_filename, original_filename, mime_type, 
                   content_type, sygnatura, step 
            FROM document WHERE id = ?
        """, (doc_id,))
        return cursor.fetchone()


def update_document_status(doc_id: int, status: str, info: str, progress: float = None,
                          confidence: float = None, current_page: int = None,
                          total_pages: int = None):
    """Aktualizuje status dokumentu w bazie."""
    db_path = get_db_path()

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()

            # Przygotuj zapytanie w zależności od parametrów
            if progress is not None:
                if current_page is not None and total_pages is not None:
                    # Pełny update z postępem i stronami
                    query = """
                        UPDATE document SET 
                            ocr_status = ?, ocr_progress_info = ?, ocr_progress = ?,
                            ocr_current_page = ?, ocr_total_pages = ?
                    """
                    params = [status, info, progress, current_page, total_pages]
                else:
                    # Update z postępem ale bez stron
                    query = """
                        UPDATE document SET 
                            ocr_status = ?, ocr_progress_info = ?, ocr_progress = ?
                    """
                    params = [status, info, progress]
            else:
                # Podstawowy update bez postępu
                query = """
                    UPDATE document SET 
                        ocr_status = ?, ocr_progress_info = ?
                """
                params = [status, info]

            # Dodaj confidence jeśli podane
            if confidence is not None:
                query += ", ocr_confidence = ?"
                params.append(confidence)

            # Dodaj WHERE clause
            query += " WHERE id = ?"
            params.append(doc_id)

            cursor.execute(query, params)
            conn.commit()

    except Exception as e:
        print(f"❌ [PROCES] Błąd aktualizacji statusu: {e}")


# ==================== LEGACY COMPATIBILITY ====================

def update_progress_sqlite(doc_id: int, progress: float, info: str,
                          current_page: int = None, total_pages: int = None):
    """Legacy compatibility function."""
    update_document_status(doc_id, "running", info, progress,
                          current_page=current_page, total_pages=total_pages)


# DODAJ NA KONIEC pipeline.py - COMPATIBILITY WRAPPERS:

def run_ocr_pipeline(doc_id: int):
    """
    Legacy compatibility wrapper dla run_ocr_pipeline.
    Używane przez tasks/ocr/__init__.py i inne moduły.
    """
    try:
        print(f"🔄 [LEGACY] run_ocr_pipeline wywołane dla dokumentu {doc_id}")

        # Wywołaj nową implementację
        result = process_document_sync(doc_id)

        if result["success"]:
            print(f"✅ [LEGACY] OCR zakończony pomyślnie dla dokumentu {doc_id}")
        else:
            print(f"❌ [LEGACY] OCR failed dla dokumentu {doc_id}: {result.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"❌ [LEGACY] Błąd OCR pipeline dla dokumentu {doc_id}: {str(e)}")
        update_document_status(doc_id, "fail", f"Błąd: {str(e)}")
        raise


# Dla kompatybilności z innymi modułami OCR:
def process_document(doc_id, model=None, proc=None):
    """
    Legacy compatibility wrapper dla process_document.
    UWAGA: Ta funkcja jest synchroniczna i nie używa parametrów model/proc.
    """
    print(f"⚠️ [LEGACY] process_document wywołane - przekierowuję do process_document_sqlite")
    return process_document_sqlite(doc_id)


# Compatibility dla ocr_manager jeśli używa:
async def process_document_async(doc_id):
    """Legacy async wrapper."""
    print(f"⚠️ [LEGACY] process_document_async wywołane - przekierowuję do sync version")
    return process_document_sqlite(doc_id)


# Export głównych funkcji dla importów:
__all__ = [
    'process_document_sync',
    'process_document_sqlite',
    'run_ocr_pipeline',
    'process_document',
    'process_document_async',
    'update_document_status',
    'embed_text_in_pdf'
]

# ==================== POZOSTAŁE FUNKCJE (niezmienione) ====================

def aggressive_memory_cleanup():
    """Czyszczenie pamięci CUDA (niezmienione)."""
    import gc
    import torch

    with open("/tmp/ocr_debug.log", "a") as f:
        f.write(f"MEMORY_CLEANUP: Rozpoczynam agresywne czyszczenie pamięci\n")

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        collected = gc.collect()

        with open("/tmp/ocr_debug.log", "a") as f:
            f.write(f"MEMORY_CLEANUP: Zwolniono {collected} obiektów\n")


def embed_text_in_pdf_legacy(pdf_path):
    """Legacy function - przekieruj do nowej."""
    return embed_text_in_pdf(Path(pdf_path))