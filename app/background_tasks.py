# POPRAWKA background_tasks.py - OCR w osobnym procesie
# FIX dla CUDA multiprocessing

import os
import sys

# KRITYCZNE: Ustaw spawn method i CUDA settings PRZED wszystkimi importami
try:
    import multiprocessing as mp

    if mp.get_start_method(allow_none=True) != 'spawn':
        mp.set_start_method('spawn', force=True)
        print("🔧 [BACKGROUND] Ustawiono spawn method dla multiprocessing")
except RuntimeError as e:
    print(f"🔧 [BACKGROUND] Multiprocessing method już ustawiony: {e}")

# CUDA environment settings
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
os.environ['TORCH_USE_CUDA_DSA'] = '1'

import asyncio
import logging
from typing import Dict, List, Set
from concurrent.futures import ProcessPoolExecutor

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("background_tasks")

# Globalne kolejki zadań
task_queues: Dict[str, asyncio.Queue] = {
    "ocr": asyncio.Queue(),
    "notifications": asyncio.Queue(),
}

# Aktualnie przetwarzane zadania (dla deduplicji)
active_tasks: Dict[str, Set[int]] = {
    "ocr": set(),
}

# ✅ NOWE: Process Pool dla OCR
ocr_executor = None


def get_ocr_executor():
    """Lazy initialization of ProcessPoolExecutor."""
    global ocr_executor
    if ocr_executor is None:
        # Sprawdź aktualną metodę multiprocessing
        current_method = mp.get_start_method()
        logger.info(f"🔧 [BACKGROUND] Multiprocessing method: {current_method}")

        if current_method != 'spawn':
            logger.warning(
                f"⚠️ [BACKGROUND] UWAGA: Używam '{current_method}' zamiast 'spawn' - może powodować problemy z CUDA")

        # PARALLEL OCR: Sequential document processing for optimal GPU utilization
        # Each document uses all available GPUs for parallel page processing
        max_workers = 1
        ocr_executor = ProcessPoolExecutor(max_workers=max_workers)
        logger.info(
            f"✅ [BACKGROUND] Utworzono ProcessPoolExecutor dla OCR z {max_workers} procesami (method: {current_method})")
    return ocr_executor


async def enqueue_ocr_task(doc_id: int, merge_pages: list = None, email: str = None, email_option: str = "none"):
    """
    Dodaje zadanie OCR do kolejki.

    Args:
        doc_id: Document ID to process
        merge_pages: Optional list of page numbers for merge mode
        email: Optional email to send results to after OCR completes
        email_option: Email option type: "none", "pdf_only", or "pdf_with_ocr"
    """
    # Sprawdź czy dokument nie jest już przetwarzany
    if doc_id in active_tasks["ocr"]:
        logger.info(f"Dokument {doc_id} jest już w kolejce OCR - pomijam")
        return

    # Dodaj do aktywnych zadań
    active_tasks["ocr"].add(doc_id)

    # Dodaj do kolejki jako tuple (doc_id, merge_pages, email, email_option)
    task_data = (doc_id, merge_pages, email, email_option)
    await task_queues["ocr"].put(task_data)

    if merge_pages:
        logger.info(f"Dodano dokument {doc_id} do kolejki OCR (merge: strony {merge_pages})")
    else:
        logger.info(f"Dodano dokument {doc_id} do kolejki OCR")

    # Natychmiast oddaj kontrolę do pętli zdarzeń
    await asyncio.sleep(0)


def remove_active_task(queue_name: str, task_id: int):
    """Usuwa zadanie z listy aktywnych po zakończeniu."""
    if task_id in active_tasks.get(queue_name, set()):
        active_tasks[queue_name].remove(task_id)
        logger.info(f"Usunięto zadanie {task_id} z aktywnych zadań {queue_name}")


# ✅ NOWE: Synchroniczna funkcja OCR dla ProcessPool
def run_ocr_in_process(task_data: tuple) -> dict:
    """
    Synchroniczna funkcja OCR uruchamiana w osobnym procesie.
    UWAGA: Ta funkcja nie może używać asyncio ani SQLModel Session!

    Args:
        task_data: Tuple of (doc_id, merge_pages, email, email_option) where merge_pages, email, and email_option can be None/default
    """
    # Unpack task data
    doc_id, merge_pages, email, email_option = task_data

    try:
        if merge_pages:
            logger.info(f"🔄 [PROCES] Rozpoczynam merge OCR dla dokumentu {doc_id}, strony: {merge_pages}")
        else:
            logger.info(f"🔄 [PROCES] Rozpoczynam OCR dla dokumentu {doc_id}")

        # Sprawdź środowisko w procesie worker
        current_method = mp.get_start_method()
        logger.info(f"🔧 [PROCES] Worker multiprocessing method: {current_method}")

        # ✅ UŻYJ NOWEJ SYNC FUNKCJI z pipeline.py
        from tasks.ocr.pipeline import process_document_sync

        # Wywołaj nową sync wrapper function z merge_pages, email, and email_option
        result = process_document_sync(doc_id, merge_pages=merge_pages, email=email, email_option=email_option)

        if result["success"]:
            logger.info(f"✅ [PROCES] OCR zakończony dla dokumentu {doc_id}")
        else:
            logger.error(f"❌ [PROCES] OCR failed dla dokumentu {doc_id}: {result.get('error', 'Unknown error')}")

        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ [PROCES] Globalny błąd OCR dla dokumentu {doc_id}: {error_msg}")

        # Dodaj stack trace dla debugowania
        import traceback
        traceback.print_exc()

        return {"success": False, "error": error_msg, "doc_id": doc_id}

    finally:
        # Free GPU memory so all GPUs are available for the next OCR task
        try:
            from tasks.ocr.models import cleanup_models
            cleanup_models()
        except Exception as cleanup_err:
            logger.warning(f"GPU cleanup error: {cleanup_err}")


# ✅ POPRAWIONY: Asynchroniczny worker OCR
async def ocr_worker():
    """Worker przetwarzający zadania OCR z kolejki - UŻYWA OSOBNYCH PROCESÓW."""
    logger.info("🚀 Uruchomiono asynchroniczny worker OCR")

    while True:
        try:
            # Pobierz zadanie z kolejki (z krótkim timeoutem)
            try:
                task_data = await asyncio.wait_for(task_queues["ocr"].get(), timeout=0.1)
            except asyncio.TimeoutError:
                # Brak zadań w kolejce - oddaj kontrolę do pętli zdarzeń
                await asyncio.sleep(0.1)
                continue

            # Unpack task data
            doc_id, merge_pages, email, email_option = task_data

            if merge_pages:
                logger.info(f"📤 Przekazuję dokument {doc_id} do procesu OCR (merge: strony {merge_pages})")
            else:
                logger.info(f"📤 Przekazuję dokument {doc_id} do procesu OCR")

            # ✅ URUCHOM OCR W OSOBNYM PROCESIE (nie blokuje event loop!)
            loop = asyncio.get_event_loop()
            executor = get_ocr_executor()

            # Uruchom OCR w osobnym procesie asynchronicznie
            ocr_future = loop.run_in_executor(executor, run_ocr_in_process, task_data)

            # ✅ NIE CZEKAJ na wynik - uruchom fire-and-forget
            asyncio.create_task(_handle_ocr_result(ocr_future, doc_id))

            # Oznacz zadanie jako pobrane z kolejki
            task_queues["ocr"].task_done()

            # Oddaj kontrolę do pętli zdarzeń
            await asyncio.sleep(0)

        except Exception as e:
            logger.error(f"❌ Błąd w workerze OCR: {str(e)}")
            await asyncio.sleep(1)


# ✅ NOWE: Handler dla rezultatu OCR
async def _handle_ocr_result(ocr_future, doc_id: int):
    """Obsługuje wynik OCR z osobnego procesu."""
    try:
        # Czekaj na wynik z procesu
        result = await ocr_future

        if result["success"]:
            logger.info(f"✅ OCR sukces dla dokumentu {doc_id}")
        else:
            logger.error(f"❌ OCR błąd dla dokumentu {doc_id}: {result.get('error', 'Nieznany błąd')}")

    except Exception as e:
        logger.error(f"❌ Błąd obsługi wyniku OCR dla dokumentu {doc_id}: {str(e)}")
    finally:
        # Usuń z aktywnych zadań
        remove_active_task("ocr", doc_id)


# ✅ POPRAWIONA: Funkcja startująca workery
async def start_background_workers():
    """Uruchamia wszystkie workery zadań w tle."""
    # Sprawdź konfigurację przed uruchomieniem
    logger.info(f"🔧 [BACKGROUND] Sprawdzam konfigurację multiprocessing...")
    current_method = mp.get_start_method()
    logger.info(f"🔧 [BACKGROUND] Aktualny multiprocessing method: {current_method}")

    if current_method == 'spawn':
        logger.info("✅ [BACKGROUND] Multiprocessing poprawnie skonfigurowany dla CUDA")
    else:
        logger.warning(
            f"⚠️ [BACKGROUND] UWAGA: Multiprocessing używa '{current_method}' - może powodować problemy z CUDA")

    # Uruchom worker OCR
    asyncio.create_task(ocr_worker())
    logger.info("🚀 Uruchomiono workery zadań w tle z ProcessPoolExecutor")


# ✅ NOWE: Cleanup przy wyłączaniu
async def cleanup_background_workers():
    """Zamyka executor przy wyłączaniu aplikacji."""
    global ocr_executor
    if ocr_executor:
        logger.info("🛑 Zamykam ProcessPoolExecutor...")
        ocr_executor.shutdown(wait=True)
        logger.info("🛑 Zamknięto ProcessPoolExecutor")
    else:
        logger.info("🛑 ProcessPoolExecutor już zamknięty")
