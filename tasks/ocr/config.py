"""
Konfiguracja modułu OCR.
"""
import logging
import os
from pathlib import Path

# Stałe dla modelu OCR
DEFAULT_OCR_INSTRUCTION = "Extract all text from image. Text is in Polish."

# Wybór modelu OCR - zmień tutaj aby przełączyć model
OCR_MODEL_TYPE = "dots"  # "qwen" lub "dots"

# Ścieżki do modeli
QWEN_MODEL_PATH = "Qwen/Qwen2.5-VL-7B-Instruct"
DOTS_MODEL_PATH = "../dots.ocr/weights/DotsOCR"

# Aktywny model (dla kompatybilności wstecznej)
OCR_MODEL_PATH = QWEN_MODEL_PATH if OCR_MODEL_TYPE == "qwen" else DOTS_MODEL_PATH

MAX_NEW_TOKENS = 24000

# Konfiguracja logowania
LOG_DIR = os.getenv("OCR_LOG_DIR", "/var/log")
LOG_FILE = os.getenv("OCR_LOG_FILE", "ocr_runner.log")

# Upewnij się, że katalog logów istnieje
try:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    LOG_PATH = Path(LOG_DIR) / LOG_FILE
except PermissionError:
    # Jeśli nie mamy uprawnień, używamy katalogu tymczasowego
    LOG_DIR = "/tmp"
    LOG_PATH = Path(LOG_DIR) / LOG_FILE

# Konfiguracja loggera
def setup_logger():
    """Konfiguruje i zwraca logger dla modułu OCR."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger("ocr")
    logger.info(f"========== INICJALIZACJA MODUŁU OCR ==========")
    logger.info(f"Logi zapisywane do: {LOG_PATH}")
    return logger

logger = setup_logger()

# Ustawienia dla timeout'ów
DOTS_TIMEOUT_SECONDS = 200  # 
QWEN_TIMEOUT_SECONDS = 300  # 5 min dla Qwen
OCR_TIMEOUT_SECONDS = DOTS_TIMEOUT_SECONDS if OCR_MODEL_TYPE == "dots" else QWEN_TIMEOUT_SECONDS
WATCHDOG_TIMEOUT_SECONDS = 1800  # 30 minut na cały dokument

# Timeout dla fallback DOTS → QWEN (50% normalnego timeout dla DOTS)
DOTS_FALLBACK_TIMEOUT_SECONDS = 200

# Ustawienia dla preprocessingu
DPI = 300  # Rozdzielczość przy konwersji PDF -> obraz
MAX_IMAGE_DIMENSION = 2500
MIN_IMAGE_DIMENSION = 1000
# 'single'  → cały model na widoczną kartę (CUDA_VISIBLE_DEVICES)
# 'auto'    → HuggingFace rozdziela warstwy na wszystkie karty
DEVICE_STRATEGY = os.getenv("OCR_DEVICE_STRATEGY", "single").lower()

# Ile pamięci zostawiamy na GPU (GiB) – aby uniknąć OOM przy single
GPU_MEM_LIMIT_GB = int(os.getenv("OCR_GPU_MEM_LIMIT_GB", "22"))

GPU_SELECT_MODE  = os.getenv("OCR_GPU_SELECT", "auto").lower()
