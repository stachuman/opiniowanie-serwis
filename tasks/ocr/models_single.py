# USUŃ to - spawn method już ustawiony w main.py!
# import multiprocessing
# multiprocessing.set_start_method('spawn',force=True)

import os, torch
from functools import lru_cache
from transformers import AutoModelForVision2Seq, AutoProcessor
from .config import OCR_MODEL_PATH, logger
import pynvml
from .config import (
    GPU_MEM_LIMIT_GB
)

print(f"🔍 [OCR_MODELS_SINGLE] Importowano models_single.py w procesie PID={os.getpid()}")

# wyłącz FA2 (stabilność)
os.environ["FLASH_ATTENTION_FORCE_DISABLED"] = "1"


def get_gpu_performance(handle):
    try:
        cuda_cores = 10496  # RTX 3090 has 10496 CUDA cores; adjust if your model varies significantly
        clock_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
        return cuda_cores * clock_mhz
    except Exception as e:
        print(f"❌ [OCR_MODELS_SINGLE] Błąd get_gpu_performance: {e}")
        return 0


def _pick_best_gpu(threshold_gb: int) -> int | None:
    try:
        pynvml.nvmlInit()
        best_gpu = None
        best_free = 0.0
        best_perf = 0

        for i in range(torch.cuda.device_count()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            free, _ = torch.cuda.mem_get_info(i)
            free_gb = free / (1024 ** 3)

            if free_gb >= threshold_gb:
                performance = get_gpu_performance(handle)

                if (free_gb > best_free) or (free_gb == best_free and performance > best_perf):
                    best_gpu = i
                    best_free = free_gb
                    best_perf = performance

        pynvml.nvmlShutdown()
        return best_gpu
    except Exception as e:
        print(f"❌ [OCR_MODELS_SINGLE] Błąd _pick_best_gpu: {e}")
        logger.error(f"Błąd _pick_best_gpu: {e}")
        return 0  # Fallback na GPU 0


@lru_cache(maxsize=1)
def get_model():
    """Ładuje model OCR - raz na proces (legacy interface)."""
    print(f"🔄 [OCR_MODELS_SINGLE] get_model wywołane w procesie PID={os.getpid()}")
    logger.info(f"🔄 [OCR_MODELS_SINGLE] get_model wywołane w procesie PID={os.getpid()}")

    try:
        # Sprawdź czy CUDA jest dostępna
        if not torch.cuda.is_available():
            raise Exception("CUDA nie jest dostępna!")

        print(f"🔍 [OCR_MODELS_SINGLE] CUDA dostępna, liczba GPU: {torch.cuda.device_count()}")

        gpu = _pick_best_gpu(GPU_MEM_LIMIT_GB)
        if gpu is None:
            print(f"⚠️ [OCR_MODELS_SINGLE] Nie znaleziono GPU z ≥{GPU_MEM_LIMIT_GB}GB, używam GPU 0")
            gpu = 0

        device = "cuda:" + str(gpu)
        print(f"🔍 [OCR_MODELS_SINGLE] Wybrano device: {device}")

        # Sprawdź ścieżkę modelu
        from pathlib import Path
        if not Path(OCR_MODEL_PATH).exists():
            raise Exception(f"Model nie istnieje w ścieżce: {OCR_MODEL_PATH}")

        print(f"🔍 [OCR_MODELS_SINGLE] Model path istnieje: {OCR_MODEL_PATH}")
        logger.info(f"OLD get_model! Loading to {device}")

        print(f"🔄 [OCR_MODELS_SINGLE] Ładowanie modelu...")
        model = AutoModelForVision2Seq.from_pretrained(
            OCR_MODEL_PATH,
            torch_dtype=torch.float16
        ).to(device).eval()

        print(f"🔄 [OCR_MODELS_SINGLE] Ładowanie procesora...")
        proc = AutoProcessor.from_pretrained(OCR_MODEL_PATH)

        print(f"✅ [OCR_MODELS_SINGLE] Model załadowany pomyślnie na {device}")
        logger.info(f"OCR model loaded once on {device}")

        return model, proc

    except Exception as e:
        error_msg = f"Błąd ładowania modelu OCR (single): {str(e)}"
        print(f"❌ [OCR_MODELS_SINGLE] {error_msg}")
        logger.error(error_msg)

        # Dodaj stack trace
        import traceback
        traceback.print_exc()

        raise Exception(f"Nie można załadować modelu OCR (single): {str(e)}")