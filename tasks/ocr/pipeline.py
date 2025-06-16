"""
Główny pipeline przetwarzania OCR.
CZYSTA WERSJA - tylko SQLite, bez SQLModel Session.
POPRAWKA: Fix dla CUDA multiprocessing
"""

# KRITYCZNE: Ustaw spawn method PRZED wszystkimi innymi importami
import sys
import os

# Force spawn method dla multiprocessing - musi być PRZED torch
try:
    import multiprocessing as mp
    if mp.get_start_method(allow_none=True) != 'spawn':
        mp.set_start_method('spawn', force=True)
        print("🔧 [PROCES] Ustawiono spawn method dla multiprocessing")
except RuntimeError as e:
    # Jeśli spawn już ustawiony
    print(f"🔧 [PROCES] Multiprocessing method już ustawiony: {e}")

# Disable CUDA before any torch imports
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'

# KRYTYCZNE: Rozwiązanie fragmentacji pamięci PyTorch CUDA
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

import uuid
import tempfile
import sqlite3
from datetime import datetime
from pathlib import Path

from app.db import FILES_DIR

# Importujemy funkcje z innych modułów OCR
from .models import process_image_to_text
from .postprocessors import clean_ocr_text, estimate_ocr_confidence


def ensure_cuda_cleanup():
    """Wymuś czyszczenie CUDA przed rozpoczęciem procesu."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            # Force garbage collection
            import gc
            gc.collect()
            print("🧹 [PROCES] CUDA cache wyczyszczony")
    except Exception as e:
        print(f"⚠️ [PROCES] Błąd czyszczenia CUDA: {e}")


def process_document_sync(doc_id: int) -> dict:
    """
    Główna funkcja OCR dla ProcessPoolExecutor.
    Używa tylko SQLite - bez SQLModel Session.
    """
    try:
        print(f"🔄 [PROCES] Rozpoczynam OCR dla dokumentu {doc_id}")

        # Wyczyść CUDA na początku procesu
        ensure_cuda_cleanup()

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

    # Wyczyść CUDA przed OCR
    ensure_cuda_cleanup()

    # Debug: Sprawdź czy plik istnieje
    print(f"🔍 [PROCES] Sprawdzam plik: {file_path}")
    print(f"🔍 [PROCES] Plik istnieje: {file_path.exists()}")
    print(f"🔍 [PROCES] Rozmiar pliku: {file_path.stat().st_size if file_path.exists() else 'N/A'}")

    try:
        # Preprocessing obrazu przed OCR
        from .preprocessors import preprocess_image
        print(f"🔍 [PROCES] Preprocessing obrazu...")
        preprocessed_image_path = preprocess_image(str(file_path))
        print(f"🔍 [PROCES] Obraz po preprocessingu: {preprocessed_image_path}")
        
        # OCR obrazu z fallback na mniejszy rozmiar w przypadku błędu pamięci
        print(f"🔍 [PROCES] Wywołuję process_image_to_text...")
        page_text = None
        
        try:
            page_text = process_image_to_text(preprocessed_image_path)
            print(f"🔍 [PROCES] OCR zwrócił: {len(page_text)} znaków")
            print(f"🔍 [PROCES] Pierwsze 100 znaków: {page_text[:100]}")
        except Exception as ocr_error:
            # Sprawdź czy to błąd pamięci CUDA
            if "CUDA out of memory" in str(ocr_error) or "OutOfMemoryError" in str(ocr_error):
                print(f"⚠️ [PROCES] Błąd pamięci GPU, próbuję mniejszy rozmiar obrazu...")
                
                # Spróbuj z mniejszym rozmiarem (75% oryginalnego)
                from .preprocessors import preprocess_image
                from .config import MAX_IMAGE_DIMENSION
                fallback_max_size = int(MAX_IMAGE_DIMENSION * 0.75)
                
                print(f"🔍 [PROCES] Fallback preprocessing z max rozmiarem: {fallback_max_size}px")
                
                # Tymczasowo zmień maksymalny rozmiar
                original_max = MAX_IMAGE_DIMENSION
                import tasks.ocr.config as config_module
                config_module.MAX_IMAGE_DIMENSION = fallback_max_size
                
                try:
                    fallback_preprocessed = preprocess_image(str(file_path))
                    page_text = process_image_to_text(fallback_preprocessed)
                    print(f"✅ [PROCES] Fallback OCR zakończony pomyślnie: {len(page_text)} znaków")
                    
                    # Oczyść fallback file
                    if fallback_preprocessed != str(file_path):
                        try:
                            Path(fallback_preprocessed).unlink()
                        except:
                            pass
                finally:
                    # Przywróć oryginalny maksymalny rozmiar
                    config_module.MAX_IMAGE_DIMENSION = original_max
            
            # Jeśli nadal błąd lub inny typ błędu, przekaż go dalej
            if page_text is None:
                raise ocr_error
        
        # Oczyść plik tymczasowy po preprocessingu jeśli został utworzony
        if preprocessed_image_path != str(file_path):
            try:
                Path(preprocessed_image_path).unlink()
                print(f"🧹 [PROCES] Usunięto tymczasowy plik: {preprocessed_image_path}")
            except Exception as cleanup_e:
                print(f"⚠️ [PROCES] Nie udało się usunąć pliku tymczasowego: {cleanup_e}")
                
    except Exception as e:
        print(f"❌ [PROCES] Błąd w process_image_to_text: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

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

            # Wyczyść CUDA przed każdą stroną
            ensure_cuda_cleanup()

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

            # Wyczyść pamięć po każdej stronie
            ensure_cuda_cleanup()

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

        # ✅ NOWE: Usuń stare dokumenty OCR dla tego dokumentu
        print(f"🧹 [PROCES] Usuwam stare dokumenty OCR dla doc_id={doc_id}")

        # Pobierz stare dokumenty OCR
        cursor.execute("""
            SELECT id, stored_filename FROM document 
            WHERE ocr_parent_id = ? AND doc_type = 'OCR TXT'
        """, (doc_id,))
        old_ocr_docs = cursor.fetchall()

        # Usuń stare pliki i rekordy
        for old_id, old_filename in old_ocr_docs:
            try:
                old_file_path = FILES_DIR / old_filename
                if old_file_path.exists():
                    old_file_path.unlink()
                    print(f"🗑️ [PROCES] Usunięto stary plik OCR: {old_filename}")
            except Exception as e:
                print(f"⚠️ [PROCES] Błąd usuwania starego pliku {old_filename}: {e}")

        # Usuń stare rekordy z bazy
        cursor.execute("""
            DELETE FROM document 
            WHERE ocr_parent_id = ? AND doc_type = 'OCR TXT'
        """, (doc_id,))

        if old_ocr_docs:
            print(f"🗑️ [PROCES] Usunięto {len(old_ocr_docs)} starych dokumentów OCR")

        # Utwórz wpis dla nowego dokumentu TXT
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

        print(f"✅ [PROCES] Utworzono nowy dokument TXT ID: {txt_doc_id}")

        # ✅ NOWE: Wyczyść cache tekstów dla tego dokumentu
        try:
            from app.text_extraction import clear_text_cache
            clear_text_cache(doc_id)
        except Exception as e:
            print(f"⚠️ [PROCES] Błąd czyszczenia cache: {e}")

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