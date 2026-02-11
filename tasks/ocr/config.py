"""
Konfiguracja modułu OCR.
"""
import logging
import os
from pathlib import Path

# Stałe dla modelu OCR
DEFAULT_OCR_INSTRUCTION = "Extract all text from image. Text is in Polish."

# Layout OCR instruction - returns JSON with bounding boxes + text (DOTS only)
LAYOUT_OCR_INSTRUCTION = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""

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
OCR_LOG_LEVEL = os.getenv("OCR_LOG_LEVEL", "INFO").upper()

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
    logger = logging.getLogger("ocr")
    logger.setLevel(getattr(logging, OCR_LOG_LEVEL, logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s PID%(process)d %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )
        fh = logging.FileHandler(LOG_PATH)
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)

    logger.debug("OCR logger initialized (level=%s, file=%s)", OCR_LOG_LEVEL, LOG_PATH)
    return logger

logger = setup_logger()

# Ustawienia dla timeout'ów
DOTS_TIMEOUT_SECONDS = 300  # 
QWEN_TIMEOUT_SECONDS = 300  # 5 min dla Qwen
OCR_TIMEOUT_SECONDS = DOTS_TIMEOUT_SECONDS if OCR_MODEL_TYPE == "dots" else QWEN_TIMEOUT_SECONDS
WATCHDOG_TIMEOUT_SECONDS = 1800  # 30 minut na cały dokument

# Timeout dla fallback DOTS → QWEN (50% normalnego timeout dla DOTS)
DOTS_FALLBACK_TIMEOUT_SECONDS = 300

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

# ========== ORIENTATION DETECTION CONFIGURATION ==========
# ML-based image orientation detection (replaces EXIF)
# Model: DuarteBarbosa/deep-image-orientation-detection (EfficientNetV2)
# Accuracy: 98.82% on validation set

# Model path and feature flag
ORIENTATION_MODEL_PATH = "DuarteBarbosa/deep-image-orientation-detection"
ORIENTATION_DETECTION_ENABLED = os.getenv("ORIENTATION_DETECTION_ENABLED", "true").lower() == "true"

# GPU memory threshold (8GB for orientation model vs 22GB for OCR models)
ORIENTATION_GPU_MEM_THRESHOLD_GB = int(os.getenv("ORIENTATION_GPU_THRESHOLD_GB", "8"))

# Inference timeout (max time per image)
ORIENTATION_INFERENCE_TIMEOUT_SECONDS = int(os.getenv("ORIENTATION_TIMEOUT_SEC", "5"))

# Minimum confidence threshold
ORIENTATION_CONFIDENCE_THRESHOLD = float(os.getenv("ORIENTATION_MIN_CONFIDENCE", "0.7"))

# Input size for EfficientNetV2
ORIENTATION_INPUT_SIZE = 224

# Class mapping: model output → rotation degrees
ORIENTATION_CLASS_TO_DEGREES = {
    0: 0,    # No rotation needed
    1: 90,   # Rotate 90° clockwise
    2: 180,  # Rotate 180°
    3: 270   # Rotate 270° clockwise (90° counter-clockwise)
}

# Deskewing configuration (small angle correction)
DESKEW_ENABLED = os.getenv("DESKEW_ENABLED", "true").lower() == "true"
DESKEW_MAX_ANGLE = 50.0  # Maximum skew angle to correct (degrees)

# ========== PDF TEXT LAYER CONFIGURATION ==========
# Debug: make text layer visible (red text) for testing alignment
# Set to True to see where text is positioned on the PDF
DEBUG_VISIBLE_TEXT_LAYER = False # Set to True for debugging text layer positioning
