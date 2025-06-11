"""
Funkcje pomocnicze dla modułu OCR.
"""
# USUŃ to - spawn method już ustawiony w main.py!
# import multiprocessing
# multiprocessing.set_start_method('spawn',force=True)

import os
import tempfile
import torch
import gc
from pathlib import Path

from .config import logger

print(f"🔍 [OCR_UTILS] Importowano utils.py w procesie PID={os.getpid()}")

def ensure_dir_exists(directory):
    """
    Upewnia się, że katalog istnieje, tworząc go w razie potrzeby.

    Args:
        directory: Ścieżka do katalogu

    Returns:
        bool: True jeśli katalog istnieje lub został utworzony
    """
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Błąd podczas tworzenia katalogu {directory}: {str(e)}")
        return False

def create_temp_file(suffix=".txt"):
    """
    Tworzy tymczasowy plik z określonym rozszerzeniem.

    Args:
        suffix: Rozszerzenie pliku

    Returns:
        str: Ścieżka do utworzonego pliku
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_path = tmp_file.name
        return tmp_path
    except Exception as e:
        logger.error(f"Błąd podczas tworzenia pliku tymczasowego: {str(e)}")
        return None

def clean_temp_files(file_paths):
    """
    Usuwa tymczasowe pliki.

    Args:
        file_paths: Lista ścieżek do plików
    """
    for path in file_paths:
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except Exception as e:
            logger.error(f"Błąd podczas usuwania pliku {path}: {str(e)}")

def clean_gpu_memory():
    """
    Zwalnia pamięć GPU.
    """
    print(f"🧹 [OCR_UTILS] Czyszczenie pamięci GPU...")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

def get_available_gpu_memory():
    """
    Zwraca informację o dostępnej pamięci GPU.

    Returns:
        dict: Informacje o pamięci GPU
    """
    if not torch.cuda.is_available():
        return {"available": False}

    try:
        device = torch.cuda.current_device()
        total_memory = torch.cuda.get_device_properties(device).total_memory
        allocated_memory = torch.cuda.memory_allocated(device)
        free_memory = total_memory - allocated_memory

        return {
            "available": True,
            "device": torch.cuda.get_device_name(device),
            "total_gb": total_memory / (1024**3),
            "allocated_gb": allocated_memory / (1024**3),
            "free_gb": free_memory / (1024**3)
        }
    except Exception as e:
        logger.error(f"Błąd podczas pobierania informacji o pamięci GPU: {str(e)}")
        return {"available": False, "error": str(e)}

def aggressive_memory_cleanup():
    """
    Bardziej agresywne czyszczenie pamięci.
    """
    print(f"🧹 [OCR_UTILS] Agresywne czyszczenie pamięci...")

    # Standardowe czyszczenie CUDA
    if torch.cuda.is_available():
        # Wyświetl informacje o pamięci przed czyszczeniem
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024)
            reserved = torch.cuda.memory_reserved() / (1024 * 1024)
            print(f"🔍 [OCR_UTILS] Przed czyszczeniem - Allocated: {allocated:.2f}MB, Reserved: {reserved:.2f}MB")

            with open("/tmp/ocr_debug.log", "a") as f:
                f.write(f"MEMORY: Przed czyszczeniem - Allocated: {allocated:.2f}MB, Reserved: {reserved:.2f}MB\n")
        except:
            pass

        # Próba zwolnienia pamięci CUDA
        torch.cuda.empty_cache()

        # Dodatkowe czyszczenie
        import gc
        collected = gc.collect()

        # Wyświetl informacje po czyszczeniu
        try:
            allocated_after = torch.cuda.memory_allocated() / (1024 * 1024)
            reserved_after = torch.cuda.memory_reserved() / (1024 * 1024)
            print(f"✅ [OCR_UTILS] Po czyszczeniu - Allocated: {allocated_after:.2f}MB, Reserved: {reserved_after:.2f}MB, GC: {collected}")

            with open("/tmp/ocr_debug.log", "a") as f:
                f.write(f"MEMORY: Po czyszczeniu - Allocated: {allocated_after:.2f}MB, Reserved: {reserved_after:.2f}MB, GC objects: {collected}\n")
        except:
            pass