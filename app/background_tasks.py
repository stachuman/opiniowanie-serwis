# POPRAWKA background_tasks.py - OCR w osobnym procesie

import asyncio
import logging
from typing import Dict, List, Set
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp

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
        # Użyj max 2 procesy dla OCR żeby nie przeciążyć serwera
        max_workers = min(2, mp.cpu_count())
        ocr_executor = ProcessPoolExecutor(max_workers=max_workers)
        logger.info(f"Utworzono ProcessPoolExecutor dla OCR z {max_workers} procesami")
    return ocr_executor


async def enqueue_ocr_task(doc_id: int):
    """Dodaje zadanie OCR do kolejki."""
    # Sprawdź czy dokument nie jest już przetwarzany
    if doc_id in active_tasks["ocr"]:
        logger.info(f"Dokument {doc_id} jest już w kolejce OCR - pomijam")
        return

    # Dodaj do aktywnych zadań
    active_tasks["ocr"].add(doc_id)

    # Dodaj do kolejki
    await task_queues["ocr"].put(doc_id)
    logger.info(f"Dodano dokument {doc_id} do kolejki OCR")

    # Natychmiast oddaj kontrolę do pętli zdarzeń
    await asyncio.sleep(0)


def remove_active_task(queue_name: str, task_id: int):
    """Usuwa zadanie z listy aktywnych po zakończeniu."""
    if task_id in active_tasks.get(queue_name, set()):
        active_tasks[queue_name].remove(task_id)
        logger.info(f"Usunięto zadanie {task_id} z aktywnych zadań {queue_name}")


# ✅ NOWE: Synchroniczna funkcja OCR dla ProcessPool
def run_ocr_in_process(doc_id: int) -> dict:
    """
    Synchroniczna funkcja OCR uruchamiana w osobnym procesie.
    UWAGA: Ta funkcja nie może używać asyncio ani SQLModel Session!
    """
    try:
        logger.info(f"🔄 [PROCES] Rozpoczynam OCR dla dokumentu {doc_id}")

        # ✅ UŻYJ NOWEJ SYNC FUNKCJI z pipeline.py
        from tasks.ocr.pipeline import process_document_sync

        # Wywołaj nową sync wrapper function
        result = process_document_sync(doc_id)

        if result["success"]:
            logger.info(f"✅ [PROCES] OCR zakończony dla dokumentu {doc_id}")
        else:
            logger.error(f"❌ [PROCES] OCR failed dla dokumentu {doc_id}: {result.get('error', 'Unknown error')}")

        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ [PROCES] Globalny błąd OCR dla dokumentu {doc_id}: {error_msg}")
        return {"success": False, "error": error_msg, "doc_id": doc_id}


# ✅ POPRAWIONY: Asynchroniczny worker OCR
async def ocr_worker():
    """Worker przetwarzający zadania OCR z kolejki - UŻYWA OSOBNYCH PROCESÓW."""
    logger.info("🚀 Uruchomiono asynchroniczny worker OCR")

    while True:
        try:
            # Pobierz dokument z kolejki (z krótkim timeoutem)
            try:
                doc_id = await asyncio.wait_for(task_queues["ocr"].get(), timeout=0.1)
            except asyncio.TimeoutError:
                # Brak zadań w kolejce - oddaj kontrolę do pętli zdarzeń
                await asyncio.sleep(0.1)
                continue

            logger.info(f"📤 Przekazuję dokument {doc_id} do procesu OCR")

            # ✅ URUCHOM OCR W OSOBNYM PROCESIE (nie blokuje event loop!)
            loop = asyncio.get_event_loop()
            executor = get_ocr_executor()

            # Uruchom OCR w osobnym procesie asynchronicznie
            ocr_future = loop.run_in_executor(executor, run_ocr_in_process, doc_id)

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
    # Uruchom worker OCR
    asyncio.create_task(ocr_worker())
    logger.info("🚀 Uruchomiono workery zadań w tle z ProcessPoolExecutor")


# ✅ NOWE: Cleanup przy wyłączaniu
async def cleanup_background_workers():
    """Zamyka executor przy wyłączaniu aplikacji."""
    global ocr_executor
    if ocr_executor:
        ocr_executor.shutdown(wait=True)
        logger.info("🛑 Zamknięto ProcessPoolExecutor")