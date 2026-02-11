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
except RuntimeError:
    pass

# Disable CUDA before any torch imports
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'

# KRYTYCZNE: Rozwiązanie fragmentacji pamięci PyTorch CUDA
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

# Apply shared PIL pixel limit from utils (must happen before any Image.open)
from PIL import Image
from .utils import MAX_IMAGE_PIXELS_SAFE, rescale_oversized_pages
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_SAFE

import json
import math
import re
import uuid
import tempfile
import sqlite3
from datetime import datetime
from pathlib import Path

from app.db import FILES_DIR

# Importujemy funkcje z innych modułów OCR
from .config import logger
from .models import process_image_to_text, process_image_to_text_with_fallback, process_image_to_text_internal
from .orientation_detector import detect_and_correct_orientation
from .postprocessors import clean_ocr_text, estimate_ocr_confidence

# PDF builder constants
RENDER_DPI = 200          # Must match convert_from_path(dpi=200)
JPEG_QUALITY = 85         # JPEG compression quality for page images
PDF_FONT_PATH = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"


def ensure_cuda_cleanup():
    """Wymuś czyszczenie CUDA przed rozpoczęciem procesu."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            import gc
            gc.collect()
    except Exception:
        pass


def process_document_sync(doc_id: int, merge_pages: list[int] = None, email: str = None, email_option: str = "none") -> dict:
    """
    Główna funkcja OCR dla ProcessPoolExecutor.
    Używa tylko SQLite - bez SQLModel Session.

    Args:
        doc_id: Document ID to process
        merge_pages: Optional list of page numbers for merge mode
        email: Optional email to send results to
        email_option: Email option type: "none", "pdf_only", or "pdf_with_ocr"
    """
    try:
        if merge_pages:
            logger.info("[DOC %d] Start merge OCR, pages: %s", doc_id, merge_pages)
        else:
            logger.info("[DOC %d] Start OCR", doc_id)

        ensure_cuda_cleanup()

        result_id = process_document_sqlite(doc_id, merge_pages=merge_pages, email=email, email_option=email_option)

        logger.info("[DOC %d] Done, txt_doc_id=%s", doc_id, result_id)

        if email and email_option == "pdf_with_ocr":
            try:
                from app.email_service import email_service
                success = email_service.send_pdf_with_ocr_email(doc_id, email)
                if not success:
                    logger.warning("[DOC %d] Email send failed to %s", doc_id, email)
            except Exception as e:
                logger.warning("[DOC %d] Email error: %s", doc_id, e)
        elif email and email_option == "pdf_only":
            try:
                from app.email_service import email_service
                success = email_service.send_pdf_email(doc_id, email)
                if not success:
                    logger.warning("[DOC %d] Email send failed to %s", doc_id, email)
            except Exception as e:
                logger.warning("[DOC %d] Email error: %s", doc_id, e)

        return {"success": True, "doc_id": doc_id, "result_id": result_id}

    except Exception as e:
        error_msg = str(e)
        logger.error("[DOC %d] OCR failed: %s", doc_id, error_msg)

        # Zaktualizuj status na błąd
        update_document_status(doc_id, "fail", f"Błąd: {error_msg}")

        return {"success": False, "error": error_msg, "doc_id": doc_id}


def process_document_sqlite(doc_id: int, merge_pages: list[int] = None, email: str = None, email_option: str = "none") -> int:
    """
    Główna funkcja przetwarzania OCR używająca tylko SQLite.

    Args:
        doc_id: Document ID to process
        merge_pages: Optional list of page numbers for merge mode

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

    is_merge = merge_pages is not None and len(merge_pages) > 0

    if is_merge:
        update_document_status(doc_id, "running", f"Merge OCR: strony {merge_pages}", 0.0)
    else:
        update_document_status(doc_id, "running", "Inicjalizacja procesu OCR", 0.0)

    # Sprawdź czy plik istnieje
    file_path = FILES_DIR / stored_filename
    if not file_path.exists():
        raise Exception(f"Plik źródłowy nie istnieje: {file_path}")

    # Określ typ przetwarzania
    is_image = content_type == 'image' or (mime_type and mime_type.startswith('image/'))

    # Merge mode only works with PDFs
    if is_merge and is_image:
        raise Exception("Merge OCR jest dostępny tylko dla dokumentów PDF, nie dla obrazów")

    try:
        layout_data = None
        corrected_pages = None
        if is_image:
            # Przetwarzanie pojedynczego obrazu
            text_all, confidence_score, layout_data = process_single_image(doc_id, file_path, original_filename)
        elif is_merge:
            # Merge mode: process only selected pages (returns 3-tuple)
            text_all, confidence_score, layout_data = process_pdf_document_merge(
                doc_id, file_path, original_filename, merge_pages
            )
        else:
            # Przetwarzanie PDF (wielostronicowe) - returns 4-tuple with corrected_pages
            text_all, confidence_score, layout_data, corrected_pages = process_pdf_document(doc_id, file_path, original_filename, email=email, email_option=email_option)

        if mime_type == 'application/pdf' and not is_merge and corrected_pages:
            update_document_status(doc_id, "running", "Budowanie PDF z warstwą tekstową", 0.95)
            try:
                build_final_pdf(file_path, corrected_pages, layout_data)
                logger.info("[DOC %d] PDF built: text layer with %d blocks",
                           doc_id, sum(len(v) for v in (layout_data or {}).values()))
            except Exception as e:
                logger.warning("[DOC %d] build_final_pdf failed: %s", doc_id, e)

        # Zapisz wyniki do plików i bazy
        txt_doc_id = save_ocr_results(
            doc_id, text_all, confidence_score,
            original_filename, sygnatura, step,
            is_merge=is_merge,
            layout_data=layout_data
        )

        # Zaktualizuj status na done
        update_document_status(doc_id, "done", "OCR zakończony", 1.0, confidence_score)

        return txt_doc_id

    except Exception as e:
        error_msg = str(e)
        logger.error("[DOC %d] Processing error: %s", doc_id, error_msg)
        update_document_status(doc_id, "fail", f"Błąd: {error_msg}", 1.0)
        raise


def process_single_image(doc_id: int, file_path: Path, filename: str):
    """Przetwarzanie pojedynczego obrazu."""
    logger.debug("Single image: %s", filename)

    update_document_status(doc_id, "running", "Przygotowanie obrazu do OCR", 0.3)

    try:
        from .preprocessors import preprocess_image
        preprocessed_image_path = preprocess_image(str(file_path))

        page_text = None

        try:
            ocr_result = process_image_to_text_with_fallback(
                preprocessed_image_path,
                skip_preprocessing=True  # preprocessing już wykonany
            )
            # Handle dict result (DOTS layout mode) or plain string (QWEN)
            if isinstance(ocr_result, dict):
                page_text = ocr_result["text"]
                page_layout = ocr_result.get("layout")
            else:
                page_text = ocr_result
                page_layout = None
        except Exception as ocr_error:
            if "CUDA out of memory" in str(ocr_error) or "OutOfMemoryError" in str(ocr_error):
                logger.warning("GPU OOM for image, trying smaller size")
                
                # Spróbuj z mniejszym rozmiarem (75% oryginalnego)
                from .preprocessors import preprocess_image
                from .config import MAX_IMAGE_DIMENSION
                fallback_max_size = int(MAX_IMAGE_DIMENSION * 0.75)
                
                # Tymczasowo zmień maksymalny rozmiar
                original_max = MAX_IMAGE_DIMENSION
                import tasks.ocr.config as config_module
                config_module.MAX_IMAGE_DIMENSION = fallback_max_size
                
                try:
                    fallback_preprocessed = preprocess_image(str(file_path))
                    fallback_result = process_image_to_text_with_fallback(
                        fallback_preprocessed,
                        skip_preprocessing=True  # preprocessing już wykonany
                    )
                    if isinstance(fallback_result, dict):
                        page_text = fallback_result["text"]
                        page_layout = fallback_result.get("layout")
                    else:
                        page_text = fallback_result
                        page_layout = None
                    logger.debug("OOM fallback OK: %d chars", len(page_text) if page_text else 0)

                    # Oczyść fallback file
                    if fallback_preprocessed != str(file_path):
                        try:
                            Path(fallback_preprocessed).unlink()
                        except Exception:
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
            except Exception:
                pass

    except Exception as e:
        logger.error("Image OCR failed: %s", e, exc_info=True)
        raise

    update_document_status(doc_id, "running", "Czyszczenie tekstu", 0.8)

    # Oczyść tekst i oblicz pewność
    clean_text = clean_ocr_text(page_text)
    confidence = estimate_ocr_confidence(clean_text)

    logger.info("[DOC %d] Result: %d chars, confidence %.2f", doc_id, len(clean_text), confidence)

    # Build layout dict for single-page images
    layout_data = None
    if page_layout:
        layout_data = {"1": page_layout}

    return clean_text, confidence, layout_data


# ---------------------------------------------------------------------------
#  Worker initializer — pins GPU per worker and pre-loads model
# ---------------------------------------------------------------------------

_worker_gpu: int | None = None  # set once per worker process


def _init_worker(gpu_queue, model_lock):
    """Initialize a worker process: claim a GPU and pre-load the DOTS model.

    Called once per worker by ProcessPoolExecutor.  The lock serializes model
    loading so workers don't all hit disk at the same time.
    """
    global _worker_gpu
    _worker_gpu = gpu_queue.get()

    logger.debug("Worker PID %d claiming GPU %d", os.getpid(), _worker_gpu)

    with model_lock:
        try:
            from .models import get_ocr_model
            get_ocr_model(assigned_gpu=_worker_gpu)
        except Exception as e:
            logger.warning("Worker PID %d model pre-load failed on GPU %d: %s", os.getpid(), _worker_gpu, e)


def process_single_page_with_gpu(page_data: dict) -> dict:
    """
    Process single page in separate process with explicit GPU assignment.

    Args:
        page_data: {
            'img_path': str,
            'page_number': int,
            'doc_id': int,
            'total_pages': int,
            'assigned_gpu': int  (ignored if worker has pinned GPU)
        }

    Returns:
        dict: {
            'page_number': int,
            'text': str,
            'confidence': float,
            'success': bool,
            'error': str (if failed)
        }
    """
    img_path = page_data['img_path']
    page_number = page_data['page_number']
    doc_id = page_data['doc_id']
    # Use worker's pinned GPU if available, otherwise fall back to task assignment
    assigned_gpu = _worker_gpu if _worker_gpu is not None else page_data['assigned_gpu']

    try:
        logger.debug("[W:GPU%d] Page %d start (PID %d)", assigned_gpu, page_number, os.getpid())

        # OCR processing with explicitly assigned GPU.
        # no_fallback=True: don't try QWEN here — other GPUs are busy with
        # DOTS workers.  Failed pages are retried with QWEN after the parallel
        # batch finishes and all GPUs are free.
        ocr_result = process_image_to_text_with_fallback(
            img_path, assigned_gpu=assigned_gpu, no_fallback=True
        )

        # Handle dict result (DOTS layout mode) or plain string (QWEN)
        if isinstance(ocr_result, dict):
            page_text = ocr_result["text"]
            page_layout = ocr_result.get("layout")
        else:
            page_text = ocr_result
            page_layout = None

        clean_text = clean_ocr_text(page_text)
        confidence = estimate_ocr_confidence(clean_text)

        logger.info("[W:GPU%d] Page %d: %d chars, conf %.2f", assigned_gpu, page_number, len(clean_text), confidence)

        return {
            'page_number': page_number,
            'text': clean_text,
            'confidence': confidence,
            'layout': page_layout,
            'success': True,
            'error': None
        }
        
    except Exception as e:
        error_msg = f"Page {page_number} OCR error: {str(e)}"
        logger.error("[W:GPU%s] %s", assigned_gpu, error_msg)

        # Mark as retriable so the parallel orchestrator can retry with QWEN
        # after all DOTS workers finish and GPUs are free.
        return {
            'page_number': page_number,
            'text': f"[{error_msg}]",
            'confidence': 0.0,
            'success': False,
            'retriable': True,
            'error': str(e)
        }
        
    finally:
        # Cleanup temp file and GPU memory
        if os.path.exists(img_path):
            os.remove(img_path)
        ensure_cuda_cleanup()


def process_pages_parallel(doc_id: int, pages: list, gpu_ids: list[int], total_pages: int) -> tuple:
    """
    Process PDF pages in parallel using ProcessPoolExecutor with explicit GPU assignment.
    
    Args:
        doc_id: Document ID for progress tracking
        pages: List of PIL Image objects
        gpu_ids: List of GPU IDs to assign to workers
        total_pages: Total page count
        
    Returns:
        tuple: (combined_text, average_confidence)
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import multiprocessing
    import tempfile

    max_workers = len(gpu_ids)
    logger.info("[DOC %d] OCR: %d workers on GPUs %s", doc_id, max_workers, gpu_ids)

    # Pre-allocate results to maintain page order
    page_results = [None] * total_pages
    completed_count = 0

    # Prepare page data for worker processes
    page_tasks = []
    temp_files = []

    for page_number, img in enumerate(pages, 1):
        # Save page image to temporary file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            img_path = tmp_img.name
            temp_files.append(img_path)

        img.save(img_path, "PNG")

        # GPU will be assigned by worker, but keep round-robin as fallback
        assigned_gpu = gpu_ids[(page_number - 1) % len(gpu_ids)]

        page_tasks.append({
            'img_path': img_path,
            'page_number': page_number,
            'doc_id': doc_id,
            'total_pages': total_pages,
            'assigned_gpu': assigned_gpu
        })

        logger.debug("Page %d prepared for parallel", page_number)

    # Set up worker initializer: each worker claims one GPU and pre-loads model.
    # Lock serializes model loading to avoid disk I/O contention.
    manager = multiprocessing.Manager()
    gpu_queue = manager.Queue()
    model_lock = manager.Lock()
    for gid in gpu_ids:
        gpu_queue.put(gid)

    try:
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_init_worker,
            initargs=(gpu_queue, model_lock),
        ) as executor:
            # Submit all page tasks — workers already have model loaded
            future_to_page = {}
            for page_data in page_tasks:
                future = executor.submit(process_single_page_with_gpu, page_data)
                future_to_page[future] = page_data['page_number']
            
            # Collect results as they complete (out of order)
            for future in as_completed(future_to_page):
                page_number = future_to_page[future]
                
                try:
                    result = future.result()
                    page_results[page_number - 1] = result  # Store in correct position
                    completed_count += 1
                    
                    # Update progress - show completion count, not page number
                    progress = 0.2 + (0.7 * completed_count / total_pages)
                    update_document_status(
                        doc_id, "running",
                        f"Ukończono {completed_count}/{total_pages} stron (parallel)",
                        progress, current_page=completed_count, total_pages=total_pages
                    )
                    
                    if completed_count % 10 == 0 or completed_count == total_pages:
                        logger.info("[DOC %d] OCR: %d/%d pages done", doc_id, completed_count, total_pages)

                except Exception as e:
                    logger.error("Page %d failed: %s", page_number, e)
                    page_results[page_number - 1] = {
                        'page_number': page_number,
                        'text': f"[Błąd OCR dla strony {page_number}: {str(e)}]",
                        'confidence': 0.0,
                        'success': False,
                        'error': str(e)
                    }
                    completed_count += 1
    
    finally:
        # Cleanup all temporary files
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as cleanup_error:
                logger.debug("Cleanup error: %s", cleanup_error)

        # Shutdown manager (frees lock/queue resources)
        try:
            manager.shutdown()
        except Exception:
            pass
    
    # --- QWEN retry for failed pages ---
    # All DOTS workers are done; GPU memory from their processes is freed.
    # Retry failed pages sequentially with QWEN using all available GPUs.
    failed_indices = [
        i for i, r in enumerate(page_results)
        if r and not r['success'] and r.get('retriable')
    ]

    if failed_indices:
        from .config import QWEN_MODEL_PATH, QWEN_TIMEOUT_SECONDS, DEFAULT_OCR_INSTRUCTION

        logger.info("[DOC %d] QWEN retry: %d failed pages", doc_id, len(failed_indices))

        # Make sure GPU memory from worker processes is reclaimed
        ensure_cuda_cleanup()

        for idx in failed_indices:
            page_number = idx + 1
            pil_img = pages[idx]

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                retry_path = tmp_img.name

            try:
                pil_img.save(retry_path, "PNG")
                logger.debug("QWEN retry page %d", page_number)

                update_document_status(
                    doc_id, "running",
                    f"QWEN retry strony {page_number}/{total_pages}",
                    0.2 + (0.7 * completed_count / total_pages),
                    current_page=completed_count, total_pages=total_pages
                )

                # Go straight to QWEN — skip DOTS (it already failed).
                # assigned_gpu=None lets QWEN use device_map="auto" across
                # all GPUs, which are free now.
                ocr_result = process_image_to_text_internal(
                    image_path=retry_path,
                    instruction=DEFAULT_OCR_INSTRUCTION,
                    model_type="qwen",
                    model_path=QWEN_MODEL_PATH,
                    timeout_seconds=QWEN_TIMEOUT_SECONDS,
                    skip_preprocessing=True,  # pages already preprocessed
                    assigned_gpu=None,
                    request_layout=True,
                )

                if isinstance(ocr_result, dict):
                    page_text = ocr_result["text"]
                    page_layout = ocr_result.get("layout")
                else:
                    page_text = ocr_result
                    page_layout = None

                clean_text = clean_ocr_text(page_text)
                confidence = estimate_ocr_confidence(clean_text)

                page_results[idx] = {
                    'page_number': page_number,
                    'text': clean_text,
                    'confidence': confidence,
                    'layout': page_layout,
                    'success': True,
                    'error': None,
                }

                logger.info("[DOC %d] QWEN retry page %d: %d chars, conf %.2f",
                           doc_id, page_number, len(clean_text), confidence)

            except Exception as retry_err:
                logger.error("QWEN retry failed page %d: %s", page_number, retry_err)
                # Keep the original failure result

            finally:
                try:
                    if os.path.exists(retry_path):
                        os.remove(retry_path)
                except Exception:
                    pass
                ensure_cuda_cleanup()

    # Assemble results in correct page order
    page_texts = []
    confidence_scores = []
    all_layout_data = {}

    for result in page_results:
        if result:
            page_texts.append(result['text'])
            confidence_scores.append(result['confidence'])
            if result.get('layout'):
                all_layout_data[str(result['page_number'])] = result['layout']
        else:
            page_texts.append("[Błąd: brak wyniku OCR]")
            confidence_scores.append(0.0)

    # Combine text with page markers (same format as sequential)
    text_all = ""
    for i, page_text in enumerate(page_texts, 1):
        text_all += f"\n\n=== Strona {i} ===\n\n{page_text}"

    text_all = text_all.strip()

    # Calculate average confidence
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

    logger.info("[DOC %d] Result: %d chars, confidence %.2f", doc_id, len(text_all), avg_confidence)

    layout_dict = all_layout_data if all_layout_data else None
    return text_all, avg_confidence, layout_dict


def process_pages_sequential(doc_id: int, pages: list, total_pages: int) -> tuple:
    """
    Sequential page processing - extracted from original logic.
    Used as fallback when parallel processing not available.
    """
    logger.info("[DOC %d] OCR: sequential mode, %d pages", doc_id, total_pages)

    page_texts = []
    confidence_scores = []
    all_layout_data = {}

    for page_number, img in enumerate(pages, 1):
        logger.debug("Page %d/%d", page_number, total_pages)

        # Progress tracking (same as original)
        progress = 0.2 + (0.7 * page_number / total_pages)
        update_document_status(
            doc_id, "running",
            f"Przetwarzanie strony {page_number}/{total_pages}",
            progress, current_page=page_number, total_pages=total_pages
        )

        # Save to temp file (same as original)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            img_path = tmp_img.name

        try:
            img.save(img_path, "PNG")

            # OCR with layout support
            ocr_result = process_image_to_text_with_fallback(img_path)

            # Handle dict result (DOTS layout mode) or plain string (QWEN)
            if isinstance(ocr_result, dict):
                page_text = ocr_result["text"]
                page_layout = ocr_result.get("layout")
                if page_layout:
                    all_layout_data[str(page_number)] = page_layout
            else:
                page_text = ocr_result

            clean_text = clean_ocr_text(page_text)
            confidence = estimate_ocr_confidence(clean_text)

            page_texts.append(clean_text)
            confidence_scores.append(confidence)

            if page_number % 10 == 0 or page_number == total_pages:
                logger.info("[DOC %d] OCR: %d/%d pages done", doc_id, page_number, total_pages)

        except Exception as e:
            logger.error("Page %d error: %s", page_number, e)
            page_texts.append(f"[Błąd OCR dla strony {page_number}: {str(e)}]")
            confidence_scores.append(0.0)

        finally:
            if os.path.exists(img_path):
                os.remove(img_path)
            ensure_cuda_cleanup()

    # Assemble results (same as original)
    text_all = ""
    for i, page_text in enumerate(page_texts, 1):
        text_all += f"\n\n=== Strona {i} ===\n\n{page_text}"

    text_all = text_all.strip()
    avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0

    layout_dict = all_layout_data if all_layout_data else None
    return text_all, avg_confidence, layout_dict


def _correct_orientation_and_save(
    doc_id: int,
    pages: list,
    file_path: Path,
) -> list:
    """Apply ML orientation correction to pages and save corrected PDF.

    Args:
        doc_id: Document ID for logging
        pages: List of PIL Image objects
        file_path: Path to the PDF file (overwritten if corrections applied)

    Returns:
        List of corrected PIL Image objects (same length as input)
    """
    corrected_pages = []
    page_rotations = []
    page_skews = []

    for i, page_img in enumerate(pages, 1):
        try:
            corrected_img, rotation_degrees, skew_angle = detect_and_correct_orientation(page_img)
            corrected_pages.append(corrected_img)
            page_rotations.append(rotation_degrees)
            page_skews.append(skew_angle)
        except Exception as e:
            logger.warning("Orientation correction failed for page %d: %s", i, e)
            corrected_pages.append(page_img)
            page_rotations.append(0)
            page_skews.append(0.0)

    logger.debug("Page rotations: %s", page_rotations)
    logger.debug("Page skews: %s", page_skews)

    pages_rotated = sum(1 for d in page_rotations if d != 0)
    pages_deskewed = sum(1 for s in page_skews if s != 0.0)

    if pages_rotated or pages_deskewed:
        logger.info("[DOC %d] Orientation: %d rotated, %d deskewed (%d pages)",
                   doc_id, pages_rotated, pages_deskewed, len(pages))
        try:
            _save_quick_pdf(file_path, corrected_pages)
            logger.info("[DOC %d] Corrected PDF saved", doc_id)
        except Exception as e:
            logger.warning("[DOC %d] Failed to save corrected PDF: %s", doc_id, e)
    else:
        logger.debug("No rotation or deskewing needed")

    return corrected_pages


def process_pdf_document(doc_id: int, file_path: Path, filename: str, email: str = None, email_option: str = "none"):
    """
    Enhanced PDF processing with adaptive parallel/sequential page handling.
    """
    logger.info("[DOC %d] Start: %s (PDF)", doc_id, filename)

    update_document_status(doc_id, "running", "Konwersja PDF na obrazy", 0.1)

    # PDF conversion
    from pdf2image import convert_from_path
    pages = convert_from_path(str(file_path), dpi=200)
    total_pages = len(pages)

    update_document_status(doc_id, "running", f"Wykryto {total_pages} stron", 0.2, total_pages=total_pages)
    logger.info("[DOC %d] %d pages detected", doc_id, total_pages)

    # Safety check: rescale oversized pages to prevent decompression bomb errors
    pages = rescale_oversized_pages(pages, "PROCESS")

    # Apply ML orientation correction and save corrected PDF
    update_document_status(doc_id, "running", "Korekcja orientacji stron ML", 0.15)
    corrected_pages = _correct_orientation_and_save(doc_id, pages, file_path)
    pages = corrected_pages

    # Adaptive processing strategy with explicit GPU assignment
    available_gpu_ids = get_available_gpus_for_ocr()
    max_parallel_pages = min(len(available_gpu_ids), total_pages)

    logger.info("[DOC %d] GPUs: %d available %s", doc_id, len(available_gpu_ids), available_gpu_ids)

    if max_parallel_pages <= 1 or total_pages == 1:
        text_all, avg_confidence, layout_data = process_pages_sequential(doc_id, pages, total_pages)
    else:
        try:
            text_all, avg_confidence, layout_data = process_pages_parallel(doc_id, pages, available_gpu_ids[:max_parallel_pages], total_pages)
        except Exception as e:
            logger.warning("[DOC %d] Parallel failed, falling back to sequential: %s", doc_id, e)
            text_all, avg_confidence, layout_data = process_pages_sequential(doc_id, pages, total_pages)

    return text_all, avg_confidence, layout_data, corrected_pages


def process_pdf_document_merge(doc_id: int, file_path: Path, filename: str, merge_pages: list[int]):
    """
    Process only selected pages from PDF and merge with existing OCR results.

    Args:
        doc_id: Document ID
        file_path: Path to PDF file
        filename: Original filename
        merge_pages: List of page numbers to re-OCR

    Returns:
        Tuple of (combined_text, average_confidence)
    """
    logger.info("[DOC %d] Merge OCR: %s, pages %s", doc_id, filename, merge_pages)

    # Get existing OCR text
    existing_text = get_existing_ocr_text(doc_id)
    existing_pages = parse_ocr_pages(existing_text)

    logger.debug("Existing OCR pages: %s", sorted(existing_pages.keys()) if existing_pages else "none")

    update_document_status(doc_id, "running", "Konwersja PDF na obrazy", 0.1)

    # Convert PDF to images
    from pdf2image import convert_from_path
    all_page_images = convert_from_path(str(file_path), dpi=200)
    total_pages = len(all_page_images)

    # Safety check: rescale oversized pages to prevent decompression bomb errors
    all_page_images = rescale_oversized_pages(all_page_images, "MERGE")

    # Validate page selection
    invalid_pages = [p for p in merge_pages if p < 1 or p > total_pages]
    if invalid_pages:
        raise ValueError(f"Nieprawidłowe numery stron: {invalid_pages}. PDF ma {total_pages} stron.")

    update_document_status(
        doc_id, "running",
        f"Merge OCR: {len(merge_pages)} z {total_pages} stron",
        0.2, total_pages=total_pages
    )

    logger.debug("PDF has %d pages, processing: %s", total_pages, merge_pages)

    # Apply ML orientation correction only to selected pages (not all)
    selected_pages = []
    for p in merge_pages:
        page_img = all_page_images[p - 1]
        try:
            corrected_img, rotation_degrees, skew_angle = detect_and_correct_orientation(page_img)
            if rotation_degrees != 0 or skew_angle != 0.0:
                logger.info("[DOC %d] Merge page %d: rotated %d°, skew %.1f°",
                           doc_id, p, rotation_degrees, skew_angle)
            selected_pages.append((corrected_img, p))
        except Exception as e:
            logger.warning("Orientation correction failed for merge page %d: %s", p, e)
            selected_pages.append((page_img, p))

    # Process selected pages
    available_gpu_ids = get_available_gpus_for_ocr()
    if not available_gpu_ids:
        available_gpu_ids = [0]  # Fallback to GPU 0

    max_parallel = min(len(available_gpu_ids), len(selected_pages))

    new_page_texts = {}
    new_page_layouts = {}
    confidences = []
    temp_files = []

    # Save selected pages to temp files
    import tempfile
    page_tasks = []

    for img, page_num in selected_pages:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            img_path = tmp_img.name
            temp_files.append(img_path)

        img.save(img_path, "PNG")

        # Assign GPU in round-robin fashion
        idx = merge_pages.index(page_num)
        assigned_gpu = available_gpu_ids[idx % len(available_gpu_ids)]

        page_tasks.append({
            'img_path': img_path,
            'page_number': page_num,
            'doc_id': doc_id,
            'total_pages': total_pages,
            'assigned_gpu': assigned_gpu
        })

        logger.debug("Page %d → GPU %d", page_num, assigned_gpu)

    try:
        merge_count = len(merge_pages)

        if max_parallel <= 1 or len(selected_pages) == 1:
            # Sequential processing
            logger.debug("Merge: sequential processing")
            for idx, page_data in enumerate(page_tasks):
                page_num = page_data['page_number']
                current_merge_page = idx + 1
                progress = 0.2 + (0.7 * current_merge_page / merge_count)
                update_document_status(
                    doc_id, "running",
                    f"Merge: strona {current_merge_page}/{merge_count} (PDF str. {page_num})",
                    progress, current_page=current_merge_page, total_pages=merge_count
                )

                result = process_single_page_with_gpu(page_data)

                new_page_texts[page_num] = result['text']
                if result.get('layout'):
                    new_page_layouts[str(page_num)] = result['layout']
                if result.get('confidence'):
                    confidences.append(result['confidence'])

                logger.debug("Merge page %d done (%d/%d)", page_num, current_merge_page, merge_count)
        else:
            # Parallel processing
            logger.debug("Merge: parallel processing on %d GPUs", max_parallel)

            from concurrent.futures import ProcessPoolExecutor, as_completed

            with ProcessPoolExecutor(max_workers=max_parallel) as executor:
                futures = {
                    executor.submit(process_single_page_with_gpu, data): data['page_number']
                    for data in page_tasks
                }

                completed = 0
                for future in as_completed(futures):
                    page_num = futures[future]
                    try:
                        result = future.result()
                        new_page_texts[page_num] = result['text']
                        if result.get('layout'):
                            new_page_layouts[str(page_num)] = result['layout']
                        if result.get('confidence'):
                            confidences.append(result['confidence'])

                        completed += 1
                        progress = 0.2 + (0.7 * completed / merge_count)
                        update_document_status(
                            doc_id, "running",
                            f"Merge: {completed}/{merge_count} stron",
                            progress, current_page=completed, total_pages=merge_count
                        )

                        logger.debug("Merge page %d done (%d/%d)", page_num, completed, merge_count)

                    except Exception as e:
                        logger.error("Merge page %d error: %s", page_num, e)
                        new_page_texts[page_num] = f"[Błąd OCR strony {page_num}: {str(e)}]"

    finally:
        # Cleanup temp files
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception as cleanup_error:
                logger.debug("Cleanup error: %s", cleanup_error)

    # Merge: update existing pages with new OCR results
    merged_pages = existing_pages.copy()
    merged_pages.update(new_page_texts)

    logger.info("[DOC %d] Merged %d new pages with %d existing", doc_id, len(new_page_texts), len(existing_pages))

    # Reconstruct full text
    merged_text = reconstruct_ocr_text(merged_pages, total_pages)

    # Calculate average confidence for new pages only
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    layout_dict = new_page_layouts if new_page_layouts else None
    return merged_text, avg_confidence, layout_dict


def save_ocr_results(doc_id: int, text_content: str, confidence: float,
                    original_filename: str, sygnatura: str, step: str,
                    is_merge: bool = False, layout_data: dict = None) -> int:
    """Zapisuje wyniki OCR do pliku i bazy danych."""

    update_document_status(doc_id, "running", "Zapisywanie wyników", 0.9)

    # KRYTYCZNE: Walidacja tekstu przed zapisem
    if text_content is None:
        raise Exception("OCR zwrócił None - proces zakończony niepowodzeniem")

    if not isinstance(text_content, str):
        raise Exception(f"OCR zwrócił nieprawidłowy typ danych: {type(text_content)}")

    if len(text_content.strip()) == 0:
        raise Exception("OCR nie rozpoznał żadnego tekstu - obraz może być nieczytelny lub uszkodzony")

    db_path = get_db_path()

    # Merge mode: update existing OCR document
    if is_merge:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()

            # Find existing OCR document
            cursor.execute("""
                SELECT id, stored_filename FROM document
                WHERE ocr_parent_id = ? AND doc_type = 'ocr_txt'
                ORDER BY upload_time DESC LIMIT 1
            """, (doc_id,))

            existing = cursor.fetchone()

            if existing:
                txt_doc_id, txt_filename = existing
                txt_path = FILES_DIR / txt_filename

                # Update existing file
                txt_path.write_text(text_content, encoding="utf-8")

                # Save/update layout JSON alongside txt
                if layout_data:
                    _save_layout_json(txt_filename, layout_data, merge_existing=True)

                # Update metadata
                now_iso = datetime.utcnow().isoformat()
                cursor.execute("""
                    UPDATE document SET
                        ocr_confidence = ?,
                        last_modified = ?
                    WHERE id = ?
                """, (confidence, now_iso, txt_doc_id))

                conn.commit()

                logger.debug("Updated existing OCR doc ID: %d", txt_doc_id)

                # Clear cache
                try:
                    from app.text_extraction import clear_text_cache
                    clear_text_cache(doc_id)
                except Exception as e:
                    logger.warning("Cache clear error: %s", e)

                return txt_doc_id

        # If no existing OCR found in merge mode, fall through to create new

    # Standard mode: delete old and create new
    txt_filename = f"{uuid.uuid4().hex}.txt"
    txt_path = FILES_DIR / txt_filename
    txt_path.write_text(text_content, encoding="utf-8")

    # Save layout JSON alongside txt
    if layout_data:
        _save_layout_json(txt_filename, layout_data)

    logger.debug("Saved text: %s (%d chars)", txt_filename, len(text_content))

    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()

        # Usuń stare dokumenty OCR dla tego dokumentu

        # Pobierz stare dokumenty OCR
        cursor.execute("""
            SELECT id, stored_filename FROM document
            WHERE ocr_parent_id = ? AND doc_type = 'ocr_txt'
        """, (doc_id,))
        old_ocr_docs = cursor.fetchall()

        # Usuń stare pliki i rekordy (including layout JSON)
        for old_id, old_filename in old_ocr_docs:
            try:
                old_file_path = FILES_DIR / old_filename
                if old_file_path.exists():
                    old_file_path.unlink()
                # Also delete layout JSON
                old_layout_path = FILES_DIR / _layout_json_filename(old_filename)
                if old_layout_path.exists():
                    old_layout_path.unlink()
            except Exception as e:
                logger.warning("Error removing old OCR file %s: %s", old_filename, e)

        # Usuń stare rekordy z bazy
        cursor.execute("""
            DELETE FROM document
            WHERE ocr_parent_id = ? AND doc_type = 'ocr_txt'
        """, (doc_id,))

        if old_ocr_docs:
            logger.debug("Removed %d old OCR documents", len(old_ocr_docs))

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
            sygnatura, "ocr_txt", txt_original_name, txt_filename,
            step, "done", doc_id, confidence,
            "text/plain", "document", now_iso, 0, now_iso
        ))

        txt_doc_id = cursor.lastrowid
        conn.commit()

        logger.debug("Created new TXT doc ID: %d", txt_doc_id)

        # Wyczyść cache tekstów dla tego dokumentu
        try:
            from app.text_extraction import clear_text_cache
            clear_text_cache(doc_id)
        except Exception as e:
            logger.warning("Cache clear error: %s", e)

        return txt_doc_id


def _layout_json_filename(txt_filename: str) -> str:
    """Derive .layout.json filename from .txt filename.

    Example: 'abc123.txt' -> 'abc123.layout.json'
    """
    return txt_filename.rsplit('.', 1)[0] + '.layout.json'


def _save_layout_json(txt_filename: str, layout_data: dict, merge_existing: bool = False):
    """Save layout data as .layout.json alongside the .txt file.

    Args:
        txt_filename: The stored filename of the .txt file
        layout_data: Dict mapping page numbers (as strings) to lists of layout blocks
        merge_existing: If True, merge with existing layout JSON (for merge OCR mode)
    """
    layout_filename = _layout_json_filename(txt_filename)
    layout_path = FILES_DIR / layout_filename

    pages_dict = layout_data

    if merge_existing and layout_path.exists():
        try:
            existing = json.loads(layout_path.read_text(encoding="utf-8"))
            existing_pages = existing.get("pages", {})
            existing_pages.update(pages_dict)
            pages_dict = existing_pages
            logger.debug("Merged layout data with existing: %s", layout_filename)
        except Exception as e:
            logger.warning("Failed to merge existing layout: %s", e)

    output = {"pages": pages_dict}
    layout_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    logger.debug("Saved layout JSON: %s (%d pages)", layout_filename, len(pages_dict))



def _pil_image_to_jpeg_bytes(pil_img, quality: int = JPEG_QUALITY) -> bytes:
    """Convert a PIL Image to JPEG bytes for PDF embedding.

    Handles RGBA/P → RGB conversion with white background
    (same pattern as ImageToPDFConverter._prepare_image_for_pdf).
    """
    import io

    if pil_img.mode in ('RGBA', 'P', 'LA'):
        background = Image.new('RGB', pil_img.size, (255, 255, 255))
        if pil_img.mode == 'P':
            pil_img = pil_img.convert('RGBA')
        background.paste(pil_img, mask=pil_img.split()[-1] if 'A' in pil_img.mode else None)
        pil_img = background
    elif pil_img.mode != 'RGB':
        pil_img = pil_img.convert('RGB')

    buf = io.BytesIO()
    pil_img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def _save_quick_pdf(file_path: Path, corrected_pages: list) -> None:
    """Save orientation-corrected pages as JPEG-compressed PDF using PyMuPDF.

    This is the "early save" called BEFORE OCR — used for the email pdf_only path.
    Uses JPEG compression + PDF-level deflate for smaller file size.
    Atomic write via temp file + shutil.move.

    Args:
        file_path: Path to the original PDF file to replace
        corrected_pages: List of PIL Image objects (orientation-corrected pages)
    """
    import fitz  # PyMuPDF
    import shutil

    if not corrected_pages:
        raise ValueError("Cannot save PDF: corrected_pages list is empty")

    if not file_path.parent.exists():
        raise ValueError(f"Cannot save PDF: parent directory does not exist: {file_path.parent}")

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=".pdf",
        dir=file_path.parent,
        prefix=".tmp_quick_"
    )

    try:
        os.close(temp_fd)

        doc = fitz.open()

        for pil_img in corrected_pages:
            w_px, h_px = pil_img.size
            w_pt = w_px * 72 / RENDER_DPI
            h_pt = h_px * 72 / RENDER_DPI

            page = doc.new_page(width=w_pt, height=h_pt)
            jpeg_bytes = _pil_image_to_jpeg_bytes(pil_img)
            page.insert_image(fitz.Rect(0, 0, w_pt, h_pt), stream=jpeg_bytes)

        doc.save(temp_path, garbage=4, deflate=True)
        doc.close()

        shutil.move(temp_path, str(file_path))

    except Exception as e:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise Exception(
            f"Failed to save quick PDF to {file_path}: {e}. "
            f"Check disk space and file permissions."
        ) from e


# Debug flag imported from config
from .config import DEBUG_VISIBLE_TEXT_LAYER


def _overlay_invisible_text(page, blocks: list, page_w_pt: float, page_h_pt: float) -> int:
    """Overlay invisible selectable text on a PDF page from layout blocks.

    Inserts text line-by-line using insert_text (point-based), sizing the font
    to match the visual line height so the invisible text layer aligns with the
    visible scanned text.  This makes selection easy and accurate.

    Args:
        page: fitz.Page object
        blocks: List of layout block dicts with 'text', 'bbox', 'category'
        page_w_pt: Page width in PDF points
        page_h_pt: Page height in PDF points

    Returns:
        int: Number of text blocks successfully inserted
    """
    import fitz  # PyMuPDF

    font_path = PDF_FONT_PATH if os.path.exists(PDF_FONT_PATH) else None
    font_name = "lato" if font_path else "helv"

    # render_mode: 0=visible fill, 3=invisible
    render_mode = 0 if DEBUG_VISIBLE_TEXT_LAYER else 3

    # Calculate page-level minimum font size based on page dimensions
    # This ensures text is proportional to page size (important for large scanned images)
    # Target: ~0.4% of page height, with absolute bounds
    # Standard A4 at 72dpi (842pt height) → min ~3.4pt
    # Large scan at 300dpi (3500pt height) → min ~14pt
    page_min_fontsize = max(2.0, min(page_h_pt * 0.004, 6.0))  # 0.4% of height, capped at 6pt

    # Also calculate a "comfortable" font size for normal text (larger minimum)
    page_normal_min_fontsize = max(3.0, min(page_h_pt * 0.006, 8.0))  # 0.6% of height, capped at 8pt

    logger.debug("PDF text overlay: %dx%dpt, %d blocks, min_fs=%.1fpt",
                int(page_w_pt), int(page_h_pt), len(blocks), page_min_fontsize)

    inserted = 0

    for block_idx, block in enumerate(blocks):
        try:
            text = block.get("text", "").strip()
            if not text:
                continue

            category = block.get("category", "")
            if category == "Picture":
                continue

            pos = block.get("bbox")
            if not pos or len(pos) < 4:
                continue

            x0 = pos[0] * page_w_pt
            y0 = pos[1] * page_h_pt
            x1 = pos[2] * page_w_pt
            y1 = pos[3] * page_h_pt

            box_width = x1 - x0
            rect_h = y1 - y0

            if box_width < 2 or rect_h < 2:
                continue

            # Strip HTML tags FIRST (tables are returned as HTML by OCR models)
            if '<table' in text.lower() or '<tr' in text.lower() or '<td' in text.lower():
                original_len = len(text)
                # Extract text content from HTML table
                text = re.sub(r'<[^>]+>', ' ', text)  # Remove all HTML tags
                text = re.sub(r'\s+', ' ', text).strip()  # Normalize whitespace
                logger.debug("HTML stripped block %d: %dch -> %dch", block_idx, original_len, len(text))

            # Split text into lines - OCR newlines indicate visual line breaks
            lines = text.split('\n')
            lines = [ln for ln in lines if ln.strip()]
            if not lines:
                continue

            # Count visual lines from OCR (this reflects how text appeared in the image)
            visual_line_count = len(lines)

            # Flatten OCR text (remove excessive whitespace)
            flat_text = ' '.join(text.split())
            if not flat_text:
                continue

            rect = fitz.Rect(x0, y0, x1, y1)

            # Determine minimum font size based on category
            # Tables can use smaller font, normal text uses larger minimum
            min_fs = page_min_fontsize if category == "Table" else page_normal_min_fontsize

            # BALANCED APPROACH: Consider both box size AND text length
            #
            # Step 1: Calculate ideal font size from visual line height
            visual_line_height = rect_h / max(visual_line_count, 1)
            fs_from_height = visual_line_height  # No extra line spacing factor

            # Step 2: Estimate font size needed to fit text in the box
            # Average char width ≈ 0.43 * fontsize for Lato/Helvetica fonts
            # Total text width at fontsize fs = len(flat_text) * 0.43 * fs
            # Lines needed = text_width / box_width = len * 0.43 * fs / box_width
            # Height needed = lines_needed * fs * 1.0 (no extra line spacing)
            # For text to fit: height_needed <= rect_h
            # len * 0.43 * fs / box_width * fs * 1.0 <= rect_h
            # fs^2 <= rect_h * box_width / (len * 0.43)
            # fs <= sqrt(rect_h * box_width / (len * 0.43))

            text_len = max(len(flat_text), 1)
            fs_from_area = math.sqrt(rect_h * box_width / (text_len * 0.43))

            # Use the SMALLER of the two estimates (but not too small)
            fontsize = min(fs_from_height, fs_from_area)

            logger.debug("Block %d: h=%.1fpt w=%.1fpt chars=%d fs=%.1fpt",
                        block_idx, rect_h, box_width, text_len, fontsize)

            # For tables, reduce slightly
            if category == "Table":
                fontsize = fontsize * 0.85

            # Clamp to reasonable range
            fontsize = min(fontsize, rect_h * 0.9)  # not bigger than 90% of box height
            fontsize = max(fontsize, min_fs)  # use page-proportional minimum

            try:
                # Word-wrap text to fit within box width, then insert line by line
                text_color = (1, 0, 0) if DEBUG_VISIBLE_TEXT_LAYER else (0, 0, 0)

                # Estimate characters per line (avg char width ≈ 0.43 * fontsize for Lato/Helvetica)
                # Using 0.43 instead of 0.5 allows more chars per line, less aggressive wrapping
                avg_char_width = fontsize * 0.43
                chars_per_line = max(1, int(box_width / avg_char_width))

                # Word-wrap the text
                words = flat_text.split()
                wrapped_lines = []
                current_line = ""

                for word in words:
                    test_line = f"{current_line} {word}".strip() if current_line else word
                    if len(test_line) <= chars_per_line:
                        current_line = test_line
                    else:
                        if current_line:
                            wrapped_lines.append(current_line)
                        # If single word is longer than line, add it anyway
                        current_line = word

                if current_line:
                    wrapped_lines.append(current_line)

                # Insert each line (no height cutoff - include all text for selection)
                line_height = fontsize * 1.0  # No extra spacing between lines
                for line_idx, line_text in enumerate(wrapped_lines):
                    y_pos = y0 + fontsize + (line_idx * line_height)
                    insert_point = fitz.Point(x0, y_pos)
                    page.insert_text(
                        insert_point,
                        line_text,
                        fontsize=fontsize,
                        fontname=font_name,
                        fontfile=font_path,
                        render_mode=render_mode,
                        color=text_color,
                    )

            except Exception as e:
                logger.debug("Block %d insert_text failed: %s", block_idx, e)
                continue

            # Per-block detail removed — see DEBUG calc line above

            inserted += 1

        except Exception as block_err:
            logger.debug("Block overlay error: %s", block_err)
            continue

    return inserted


def build_final_pdf(file_path: Path, corrected_pages: list, layout_data: dict) -> None:
    """Build the final PDF with JPEG images + invisible selectable text layer.

    Called AFTER OCR completes. Replaces both _save_corrected_pdf and embed_text_in_pdf.
    If layout_data is None/empty, produces an image-only PDF (same as _save_quick_pdf).

    Args:
        file_path: Path to the PDF file to replace
        corrected_pages: List of PIL Image objects
        layout_data: Dict mapping page number strings to lists of layout blocks,
                     or None if no layout data available
    """
    import fitz  # PyMuPDF
    import shutil

    if not corrected_pages:
        raise ValueError("Cannot build PDF: corrected_pages list is empty")

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=".pdf",
        dir=file_path.parent,
        prefix=".tmp_final_"
    )

    try:
        os.close(temp_fd)

        doc = fitz.open()
        total_blocks_inserted = 0

        for page_idx, pil_img in enumerate(corrected_pages):
            page_num = page_idx + 1
            w_px, h_px = pil_img.size
            w_pt = w_px * 72 / RENDER_DPI
            h_pt = h_px * 72 / RENDER_DPI

            page = doc.new_page(width=w_pt, height=h_pt)

            # Embed page image as JPEG
            jpeg_bytes = _pil_image_to_jpeg_bytes(pil_img)
            page.insert_image(fitz.Rect(0, 0, w_pt, h_pt), stream=jpeg_bytes)

            # Overlay invisible text if layout data exists for this page
            if layout_data and str(page_num) in layout_data:
                blocks = layout_data[str(page_num)]
                if blocks:
                    logger.debug("Page %d: %dx%dpx, %d layout blocks", page_num, w_px, h_px, len(blocks))
                    inserted = _overlay_invisible_text(page, blocks, w_pt, h_pt)
                    total_blocks_inserted += inserted

        doc.save(temp_path, garbage=4, deflate=True)
        doc.close()

        shutil.move(temp_path, str(file_path))

        logger.debug("Final PDF saved: %d pages, %d text blocks", len(corrected_pages), total_blocks_inserted)

    except Exception as e:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise Exception(
            f"Failed to build final PDF at {file_path}: {e}. "
            f"Check disk space and file permissions."
        ) from e


# ==================== FUNKCJE POMOCNICZE ====================

def get_available_gpus_for_ocr() -> list[int]:
    """
    Get list of GPUs available for OCR processing with explicit GPU IDs.
    
    Returns:
        list[int]: List of GPU IDs that have sufficient memory
    """
    try:
        import torch
        import pynvml
        from tasks.ocr.config import GPU_MEM_LIMIT_GB
        
        available_gpu_ids = []
        
        if not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to GPU 0")
            return [0]  # Return GPU 0 as fallback

        gpu_limit = GPU_MEM_LIMIT_GB

        total_gpus = torch.cuda.device_count()
        
        pynvml.nvmlInit()
        
        for gpu_id in range(total_gpus):
            try:
                free, total = torch.cuda.mem_get_info(gpu_id)
                free_gb = free / (1024 ** 3)
                total_gb = total / (1024 ** 3)
                
                logger.debug("GPU %d: %.2fGB free / %.2fGB total", gpu_id, free_gb, total_gb)

                if free_gb >= gpu_limit:
                    available_gpu_ids.append(gpu_id)

            except Exception as gpu_error:
                logger.debug("Error checking GPU %d: %s", gpu_id, gpu_error)
                
        pynvml.nvmlShutdown()
        
        if not available_gpu_ids:
            logger.warning("No GPUs meet %dGB threshold, falling back to GPU 0", gpu_limit)
            return [0]

        logger.debug("Available GPUs: %s", available_gpu_ids)
        return available_gpu_ids

    except Exception as e:
        logger.warning("GPU selection error: %s, falling back to GPU 0", e)
        return [0]


def count_available_gpus_for_ocr() -> int:
    """
    Legacy function - returns count of available GPUs.
    """
    return len(get_available_gpus_for_ocr())


def get_db_path() -> Path:
    """Zwraca ścieżkę do bazy danych."""
    return Path(__file__).parent.parent.parent / "data.db"


def parse_page_selection(selection: str) -> list[int]:
    """
    Parse page selection string like "1,3,5-7" into sorted list [1, 3, 5, 6, 7].

    Args:
        selection: Page selection string (e.g., "1,3,5-7")

    Returns:
        Sorted list of page numbers

    Raises:
        ValueError: If selection format is invalid
    """
    if not selection or not selection.strip():
        raise ValueError("Pusty wybór stron")

    pages = set()

    for part in selection.split(','):
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            # Range: "5-7"
            range_parts = part.split('-')
            if len(range_parts) != 2:
                raise ValueError(f"Nieprawidłowy format zakresu: {part}")

            try:
                start = int(range_parts[0].strip())
                end = int(range_parts[1].strip())
            except ValueError:
                raise ValueError(f"Nieprawidłowe numery stron w zakresie: {part}")

            if start < 1 or end < 1:
                raise ValueError(f"Numery stron muszą być większe od 0: {part}")

            if start > end:
                raise ValueError(f"Początek zakresu większy od końca: {part}")

            pages.update(range(start, end + 1))
        else:
            # Single page: "3"
            try:
                page_num = int(part)
            except ValueError:
                raise ValueError(f"Nieprawidłowy numer strony: {part}")

            if page_num < 1:
                raise ValueError(f"Numer strony musi być większy od 0: {part}")

            pages.add(page_num)

    if not pages:
        raise ValueError("Nie podano żadnych stron")

    return sorted(pages)


def parse_ocr_pages(text: str) -> dict[int, str]:
    """
    Parse OCR text into page dictionary by splitting on page markers.

    Args:
        text: OCR text with page markers like "=== Strona X ==="

    Returns:
        Dictionary mapping page number to text content.
        If no markers found, returns {1: text} (treat as single page).
    """
    if not text or not text.strip():
        return {}

    # Pattern for page markers
    page_pattern = re.compile(r'^=== Strona (\d+) ===$', re.MULTILINE)

    # Find all page markers
    matches = list(page_pattern.finditer(text))

    if not matches:
        # No page markers found - treat entire text as page 1
        return {1: text.strip()}

    pages = {}

    for i, match in enumerate(matches):
        page_num = int(match.group(1))
        start_pos = match.end()

        # Find end position (next marker or end of text)
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(text)

        # Extract page text
        page_text = text[start_pos:end_pos].strip()
        pages[page_num] = page_text

    return pages


def reconstruct_ocr_text(pages: dict[int, str], total_pages: int) -> str:
    """
    Reconstruct full OCR text from page dictionary with proper markers.

    Args:
        pages: Dictionary mapping page number to text content
        total_pages: Total number of pages in document

    Returns:
        Combined text with page markers
    """
    if not pages:
        return ""

    result = []

    for page_num in range(1, total_pages + 1):
        page_text = pages.get(page_num, "")

        if page_num > 1:
            result.append("\n\n")

        result.append(f"=== Strona {page_num} ===\n\n")
        result.append(page_text)

    return ''.join(result).strip()


def get_existing_ocr_text(doc_id: int) -> str:
    """
    Get existing OCR text for a document.

    Args:
        doc_id: Source document ID

    Returns:
        OCR text content or empty string if not found
    """
    db_path = get_db_path()

    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()

        # Find OCR document for this source
        cursor.execute("""
            SELECT stored_filename FROM document
            WHERE ocr_parent_id = ? AND doc_type = 'ocr_txt'
            ORDER BY upload_time DESC LIMIT 1
        """, (doc_id,))

        result = cursor.fetchone()

        if not result:
            return ""

        # Read text file
        txt_path = FILES_DIR / result[0]
        if not txt_path.exists():
            return ""

        return txt_path.read_text(encoding="utf-8")


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
        logger.error("Status update error: %s", e)


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
        result = process_document_sync(doc_id)

        if not result["success"]:
            logger.error("[DOC %d] OCR failed: %s", doc_id, result.get('error', 'Unknown error'))

    except Exception as e:
        logger.error("[DOC %d] OCR pipeline error: %s", doc_id, e)
        update_document_status(doc_id, "fail", f"Błąd: {str(e)}")
        raise


# Dla kompatybilności z innymi modułami OCR:
def process_document(doc_id, model=None, proc=None):
    """
    Legacy compatibility wrapper dla process_document.
    UWAGA: Ta funkcja jest synchroniczna i nie używa parametrów model/proc.
    """
    logger.debug("Legacy process_document called, redirecting to process_document_sqlite")
    return process_document_sqlite(doc_id)


# Compatibility dla ocr_manager jeśli używa:
async def process_document_async(doc_id):
    """Legacy async wrapper."""
    logger.debug("Legacy process_document_async called, redirecting to sync version")
    return process_document_sqlite(doc_id)


# Export głównych funkcji dla importów:
__all__ = [
    'process_document_sync',
    'process_document_sqlite',
    'run_ocr_pipeline',
    'process_document',
    'process_document_async',
    'update_document_status',
    'build_final_pdf',
]
