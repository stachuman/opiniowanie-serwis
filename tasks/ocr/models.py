from __future__ import annotations

# USUŃ to - spawn method już ustawiony w main.py!
# import multiprocessing
# multiprocessing.set_start_method('spawn',force=True)

import gc
import os
import signal
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple
import pynvml

import torch
from transformers import AutoModelForVision2Seq, AutoModelForCausalLM, AutoProcessor
from PIL import ImageFile

# Enable loading of truncated/progressive JPEG images
ImageFile.LOAD_TRUNCATED_IMAGES = True

from .config import (
    DEFAULT_OCR_INSTRUCTION,
    DEVICE_STRATEGY as CFG_STRATEGY,
    GPU_MEM_LIMIT_GB,
    GPU_SELECT_MODE,
    OCR_MODEL_PATH,
    OCR_MODEL_TYPE,
    OCR_TIMEOUT_SECONDS,
    DOTS_FALLBACK_TIMEOUT_SECONDS,
    DOTS_TIMEOUT_SECONDS,
    QWEN_TIMEOUT_SECONDS,
    QWEN_MODEL_PATH,
    DOTS_MODEL_PATH,
    MAX_NEW_TOKENS,
    logger,
)

# Wyłączamy globalnie Flash‑Attention 2 – znany source segfaultów na Ampere
os.environ["FLASH_ATTENTION_FORCE_DISABLED"] = "1"

# KRYTYCZNE: Rozwiązanie fragmentacji pamięci PyTorch CUDA
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

print(f"🔍 [OCR_MODELS] Importowano models.py w procesie PID={os.getpid()}")


class TimeoutError(Exception):
    """Sygnalizuje przekroczenie limitu czasu generacji jednej strony."""


# ---------------------------------------------------------------------------
#  Wybór najlepszej karty GPU (tryb single)
# ---------------------------------------------------------------------------


def get_gpu_performance(handle):
    try:
        pynvml.nvmlInit()
        cuda_cores = 10496  # RTX 3090 has 10496 CUDA cores; adjust if your model varies significantly
        clock_mhz = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
        logger.info(f"MHz {clock_mhz} ")
        return cuda_cores * clock_mhz
    except Exception as e:
        logger.error(f"Błąd get_gpu_performance: {e}")
        return 0


def _pick_best_gpu(threshold_gb: int) -> int | None:
    try:
        pynvml.nvmlInit()
        best_gpu = None
        best_free = 0.0
        best_perf = 0

        logger.info(f"🔍 [GPU_SELECT] Szukam GPU z ≥{threshold_gb}GB wolnej pamięci...")
        
        for i in range(torch.cuda.device_count()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            free, total = torch.cuda.mem_get_info(i)
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            used_gb = total_gb - free_gb
            
            logger.info(f"🔍 [GPU_SELECT] GPU {i}: {free_gb:.2f}GB wolne / {total_gb:.2f}GB total ({used_gb:.2f}GB użyte)")

            if free_gb >= threshold_gb:
                performance = get_gpu_performance(handle)
                logger.info(f"✅ [GPU_SELECT] GPU {i} spełnia kryterium (≥{threshold_gb}GB), performance: {performance}")

                if (free_gb > best_free) or (free_gb == best_free and performance > best_perf):
                    best_gpu = i
                    best_free = free_gb
                    best_perf = performance
                    logger.info(f"🏆 [GPU_SELECT] GPU {i} to nowy kandydat ({free_gb:.2f}GB)")
            else:
                logger.info(f"❌ [GPU_SELECT] GPU {i} nie spełnia kryterium ({free_gb:.2f}GB < {threshold_gb}GB)")

        pynvml.nvmlShutdown()
        
        if best_gpu is not None:
            logger.info(f"🎯 [GPU_SELECT] Wybrano GPU {best_gpu} z {best_free:.2f}GB wolnej pamięci")
        else:
            logger.info(f"⚠️ [GPU_SELECT] Nie znaleziono GPU z ≥{threshold_gb}GB wolnej pamięci")
            
        return best_gpu
    except Exception as e:
        logger.error(f"Błąd _pick_best_gpu: {e}")
        return None  # FIX: Return None instead of 0 to trigger fallback logic


# ---------------------------------------------------------------------------
#  Model + processor – singleton w pamięci procesu
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_once(model_type: str, model_path: str, assigned_gpu: int = None) -> Tuple[Any, AutoProcessor]:
    """Ładuje model OCR - raz na proces, z cache bazującym na typie modelu."""
    print(f"🔄 [OCR_MODELS] Ładowanie modelu {model_type} w procesie PID={os.getpid()}")
    logger.info(f"🔄 [OCR_MODELS] Ładowanie modelu {model_type} w procesie PID={os.getpid()}")

    try:
        # Sprawdź czy CUDA jest dostępna
        if not torch.cuda.is_available():
            raise Exception("CUDA nie jest dostępna!")

        print(f"🔍 [OCR_MODELS] CUDA dostępna, liczba GPU: {torch.cuda.device_count()}")
        logger.info(f"🔍 [OCR_MODELS] CUDA dostępna, liczba GPU: {torch.cuda.device_count()}")

        # Sprawdź czy to lokalny path czy Hugging Face Hub
        if "/" in model_path and not Path(model_path).exists():
            print(f"🌐 [OCR_MODELS] Model z Hugging Face Hub: {model_path}")
            logger.info(f"Model z Hugging Face Hub: {model_path}")

            # Sprawdź cache HF
            try:
                from transformers import AutoConfig
                print(f"🔍 [OCR_MODELS] Sprawdzam dostępność modelu...")
                config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
                print(f"✅ [OCR_MODELS] Model dostępny w HF Hub")
            except Exception as e:
                raise Exception(f"Model niedostępny w HF Hub: {str(e)}")
        elif Path(model_path).exists():
            print(f"📁 [OCR_MODELS] Model lokalny istnieje: {model_path}")
        else:
            raise Exception(f"Model nie istnieje lokalnie ani w HF Hub: {model_path}")

        strategy = CFG_STRATEGY
        
        # Model-aware device strategy
        if assigned_gpu is not None:
            print(f"🎯 [OCR_MODELS] Using explicitly assigned GPU: {assigned_gpu}")
            gpu = assigned_gpu
            
            # DOTS: Single GPU (can fit on one GPU)
            # QWEN: Multi-GPU (needs distribution across multiple GPUs)
            if model_type == "dots":
                strategy = "single"  # Force single GPU for DOTS
                print(f"🔍 [OCR_MODELS] DOTS model: forcing single GPU strategy")
            else:
                strategy = "auto"  # Allow multi-GPU for QWEN
                print(f"🔍 [OCR_MODELS] QWEN model: allowing multi-GPU strategy")
        else:
            # Original GPU selection logic for main process
            if strategy == "single" and GPU_SELECT_MODE == "auto":
                gpu = _pick_best_gpu(GPU_MEM_LIMIT_GB)
                if gpu is None:
                    logger.warning("Brak karty ≥%s GB – przełączam na device_map='auto'", GPU_MEM_LIMIT_GB)
                    strategy = "auto"
                    gpu = 0
            else:
                gpu = 0

        print(f"🔍 [OCR_MODELS] Wybrano GPU: {gpu}, strategy: {strategy}, model: {model_type}")

        # Sprawdź pamięć GPU przed ładowaniem
        try:
            free_mem, total_mem = torch.cuda.mem_get_info(gpu)
            free_gb = free_mem / (1024 ** 3)
            total_gb = total_mem / (1024 ** 3)
            print(f"🔍 [OCR_MODELS] GPU {gpu} pamięć: {free_gb:.2f}GB / {total_gb:.2f}GB dostępne")

            if free_gb < 8.0:  # Model 7B potrzebuje ~14GB ale sprawdzamy minimum
                print(f"⚠️ [OCR_MODELS] UWAGA: Mało pamięci GPU ({free_gb:.2f}GB), model może nie załadować się")
        except Exception as e:
            print(f"⚠️ [OCR_MODELS] Nie można sprawdzić pamięci GPU: {e}")

        # Parametry ładowania modelu
        if model_type == "dots":
            # DOTS model parametry - force single GPU to avoid device conflicts
            params: Dict[str, Any] = {
                "attn_implementation": "flash_attention_2",
                "torch_dtype": torch.bfloat16,
                "trust_remote_code": True,
                "device_map": f"cuda:{gpu}",  # Force single GPU for DOTS
                "max_memory": {gpu: f"{GPU_MEM_LIMIT_GB}GiB"}
            }
            print(f"🔍 [OCR_MODELS] DOTS forced to single GPU: cuda:{gpu}")
        else:
            # Qwen model parametry  
            params: Dict[str, Any] = {"torch_dtype": torch.float16, "trust_remote_code": True}
            
            if strategy == "single":
                params["device_map"] = f"cuda:{gpu}"
                params["max_memory"] = {gpu: f"{GPU_MEM_LIMIT_GB}GiB"}
                print(f"🔍 [OCR_MODELS] QWEN single GPU mode: cuda:{gpu}")
            else:
                params["device_map"] = "auto"
                print(f"🔍 [OCR_MODELS] QWEN multi-GPU mode: device_map=auto")

        print(f"🔍 [OCR_MODELS] Parametry ładowania: {params}")
        logger.info("Ładowanie modelu z parametrami: %s", params)

        try:
            if model_type == "dots":
                model = AutoModelForCausalLM.from_pretrained(model_path, **params).eval()
            else:
                model = AutoModelForVision2Seq.from_pretrained(model_path, **params).eval()
            print(f"✅ [OCR_MODELS] Model załadowany pomyślnie")
        except torch.cuda.OutOfMemoryError:
            print(f"⚠️ [OCR_MODELS] OOM - ponawiam z device_map='auto'")
            logger.warning("OOM – ponawiam z device_map='auto'")
            params.pop("max_memory", None)
            params["device_map"] = "auto"
            if model_type == "dots":
                model = AutoModelForCausalLM.from_pretrained(model_path, **params).eval()
            else:
                model = AutoModelForVision2Seq.from_pretrained(model_path, **params).eval()

        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        print(f"✅ [OCR_MODELS] Processor załadowany pomyślnie")

        logger.info(f"✅ [OCR_MODELS] Model i processor załadowane w procesie PID={os.getpid()}")
        return model, processor

    except Exception as e:
        error_msg = f"Błąd ładowania modelu OCR: {str(e)}"
        print(f"❌ [OCR_MODELS] {error_msg}")
        logger.error(error_msg)

        # Dodaj stack trace
        import traceback
        traceback.print_exc()

        raise Exception(f"Nie można załadować modelu OCR: {str(e)}")


def get_ocr_model(assigned_gpu: int = None) -> Tuple[Any, AutoProcessor]:
    """Publiczny interfejs do pobierania modelu OCR."""
    print(f"🔍 [OCR_MODELS] get_ocr_model wywołane w procesie PID={os.getpid()}")
    if assigned_gpu is not None:
        print(f"🎯 [OCR_MODELS] Using explicitly assigned GPU: {assigned_gpu}")
    try:
        # Import current config values to get the most up-to-date configuration
        from .config import OCR_MODEL_TYPE, OCR_MODEL_PATH
        print(f"🔍 [OCR_MODELS] Current config: {OCR_MODEL_TYPE} @ {OCR_MODEL_PATH}")
        return _load_once(OCR_MODEL_TYPE, OCR_MODEL_PATH, assigned_gpu)
    except Exception as e:
        print(f"❌ [OCR_MODELS] Błąd w get_ocr_model: {str(e)}")
        raise


# ---------------------------------------------------------------------------
#  OCR jednej strony
# ---------------------------------------------------------------------------

def _timeout_handler(_signum, _frame):
    raise TimeoutError("Timeout podczas generacji tekstu")


def process_image_to_text_with_fallback(
        image_path: str | Path,
        instruction: str = DEFAULT_OCR_INSTRUCTION,
        skip_preprocessing=False,
        assigned_gpu: int = None,
):
    """
    Rozpoznaje tekst z obrazu z fallback DOTS → QWEN.
    
    1. Próbuje DOTS z skróconym timeout (50% normalnego)
    2. Jeśli DOTS timeout → automatycznie przełącza na QWEN
    3. Każdy obraz zaczyna od DOTS (brak trwałego stanu fallback)
    """
    print(f"🔍 [OCR_MODELS] process_image_to_text_with_fallback dla: {image_path}")
    
    # Zawsze zacznij od DOTS jeśli to domyślny model
    if OCR_MODEL_TYPE == "dots":
        print(f"🎯 [OCR_MODELS] Próbuję DOTS z timeout {DOTS_FALLBACK_TIMEOUT_SECONDS}s")
        
        try:
            # Próbuj DOTS z skróconym timeout
            result = process_image_to_text_internal(
                image_path=image_path,
                instruction=instruction,
                model_type="dots",
                model_path=DOTS_MODEL_PATH,
                timeout_seconds=DOTS_FALLBACK_TIMEOUT_SECONDS,
                skip_preprocessing=skip_preprocessing,
                assigned_gpu=assigned_gpu
            )
            print(f"✅ [OCR_MODELS] DOTS zakończony pomyślnie: {len(result)} znaków")
            return result
            
        except TimeoutError as timeout_err:
            print(f"⏰ [OCR_MODELS] DOTS timeout po {DOTS_FALLBACK_TIMEOUT_SECONDS}s - przełączam na QWEN")
            logger.warning(f"DOTS timeout - fallback na QWEN dla obrazu: {image_path}")
            print(f"🔄 [OCR_MODELS] Timeout error details: {str(timeout_err)}")
            
            # Fallback na QWEN
            try:
                result = process_image_to_text_internal(
                    image_path=image_path,
                    instruction=instruction,
                    model_type="qwen",
                    model_path=QWEN_MODEL_PATH,
                    timeout_seconds=QWEN_TIMEOUT_SECONDS,
                    skip_preprocessing=skip_preprocessing,
                    assigned_gpu=assigned_gpu
                )
                print(f"✅ [OCR_MODELS] QWEN fallback zakończony pomyślnie: {len(result)} znaków")
                return result
                
            except Exception as qwen_error:
                print(f"❌ [OCR_MODELS] QWEN fallback także nieudany: {str(qwen_error)}")
                logger.error(f"QWEN fallback failed: {str(qwen_error)}")
                # Return meaningful error instead of crashing
                return f"[Błąd OCR: DOTS timeout po {DOTS_FALLBACK_TIMEOUT_SECONDS}s, QWEN fallback także nieudany: {str(qwen_error)}]"
        
        except Exception as dots_error:
            # Inny błąd niż timeout - nie próbuj fallback
            print(f"❌ [OCR_MODELS] DOTS błąd (nie timeout): {str(dots_error)}")
            raise
    
    else:
        # Dla QWEN jako domyślny model - użyj normalnej funkcji
        print(f"🎯 [OCR_MODELS] Używam QWEN (domyślny model)")
        return process_image_to_text(
            image_path=image_path,
            instruction=instruction,
            skip_preprocessing=skip_preprocessing,
            assigned_gpu=assigned_gpu
        )


def process_image_to_text_internal(
        image_path: str | Path,
        instruction: str,
        model_type: str,
        model_path: str,
        timeout_seconds: int,
        skip_preprocessing=False,
        assigned_gpu: int = None,
):
    """Wewnętrzna funkcja OCR z określonym modelem i timeout."""
    print(f"🔍 [OCR_MODELS] process_image_to_text_internal: {model_type} @ {image_path}")
    
    # Import current values
    from .config import OCR_MODEL_TYPE, OCR_MODEL_PATH, OCR_TIMEOUT_SECONDS
    
    # Tymczasowo ustaw model type i path
    original_model_type = OCR_MODEL_TYPE
    original_model_path = OCR_MODEL_PATH
    original_timeout = OCR_TIMEOUT_SECONDS
    
    try:
        # Zmień konfigurację tymczasowo
        import tasks.ocr.config as config_module
        config_module.OCR_MODEL_TYPE = model_type
        config_module.OCR_MODEL_PATH = model_path
        config_module.OCR_TIMEOUT_SECONDS = timeout_seconds
        
        # Wyczyść cache modelu żeby załadować nowy model
        _load_once.cache_clear()
        print(f"🔍 [OCR_MODELS] Cache cleared for model switch")
        
        # Uruchom OCR z nową konfiguracją
        result = process_image_to_text_core(
            image_path=image_path,
            instruction=instruction,
            timeout_seconds=timeout_seconds,
            skip_preprocessing=skip_preprocessing,
            assigned_gpu=assigned_gpu
        )
        
        return result
        
    finally:
        # Przywróć oryginalną konfigurację
        config_module.OCR_MODEL_TYPE = original_model_type
        config_module.OCR_MODEL_PATH = original_model_path
        config_module.OCR_TIMEOUT_SECONDS = original_timeout
        
        # Wyczyść cache po zmianie modelu z powrotem
        _load_once.cache_clear()
        print(f"🔍 [OCR_MODELS] Cache cleared after config restoration")


def process_image_to_text(
        image_path: str | Path,
        instruction: str = DEFAULT_OCR_INSTRUCTION,
        model=None,
        processor=None,
        skip_preprocessing=False,
        assigned_gpu: int = None,
):
    """Rozpoznaje tekst z obrazu i zwraca go jako string."""
    try:
        return process_image_to_text_core(
            image_path=image_path,
            instruction=instruction,
            timeout_seconds=OCR_TIMEOUT_SECONDS,
            skip_preprocessing=skip_preprocessing,
            assigned_gpu=assigned_gpu
        )
    except TimeoutError as e:
        # For backwards compatibility, return timeout as text
        print(f"⏰ [OCR_MODELS] process_image_to_text timeout: {str(e)}")
        return f"[Timeout OCR]"


def process_image_to_text_core(
        image_path: str | Path,
        instruction: str = DEFAULT_OCR_INSTRUCTION,
        timeout_seconds: int = OCR_TIMEOUT_SECONDS,
        skip_preprocessing=False,
        assigned_gpu: int = None,
):
    """Podstawowa funkcja OCR - wydzielona logika z process_image_to_text."""
    print(f"🔍 [OCR_MODELS] process_image_to_text_core dla: {image_path} (timeout: {timeout_seconds}s)")
    
    # Dostosuj instrukcję dla modelu DOTS
    #if OCR_MODEL_TYPE == "dots":
    #    instruction = "Extract the text content from this image. Language is Polish."

    # Agresywne czyszczenie pamięci przed rozpoczęciem OCR
    from .utils import aggressive_memory_cleanup, get_available_gpu_memory
    aggressive_memory_cleanup()
    
    # Sprawdź dostępną pamięć GPU
    gpu_info = get_available_gpu_memory()
    if gpu_info.get("available", False):
        free_memory_gb = gpu_info.get("free_memory", 0) / 1024  # Convert MB to GB
        print(f"🔍 [OCR_MODELS] Dostępna pamięć GPU: {free_memory_gb:.2f} GB")
        
        if free_memory_gb < 2.0:  # Obniżamy próg do 2GB
            print(f"⚠️ [OCR_MODELS] Mało pamięci GPU: {free_memory_gb:.2f} GB - będzie wolniej ale spróbujemy")

    try:
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        error_msg = f"Nie można zaimportować qwen_vl_utils: {str(e)}"
        print(f"❌ [OCR_MODELS] {error_msg}")
        raise Exception(error_msg)

    # Załaduj model i processor
    print(f"🔍 [OCR_MODELS] Ładowanie modelu i procesora...")
    try:
        model, processor = get_ocr_model(assigned_gpu=assigned_gpu)
        print(f"✅ [OCR_MODELS] Model i processor załadowane")
    except Exception as e:
        error_msg = f"Błąd ładowania modelu: {str(e)}"
        print(f"❌ [OCR_MODELS] {error_msg}")
        return f"[Błąd ładowania modelu: {str(e)}]"

    if isinstance(image_path, Path):
        image_path = str(image_path)

    # Sprawdź czy plik obrazu istnieje
    if not Path(image_path).exists():
        error_msg = f"Plik obrazu nie istnieje: {image_path}"
        print(f"❌ [OCR_MODELS] {error_msg}")
        return f"[Błąd: {error_msg}]"
    
    # KRYTYCZNE: Preprocessing obrazu PRZED wysłaniem do modelu OCR
    # To zmniejsza obraz z 4032x3024 do 1536x1152 i obsługuje EXIF rotation
    # Dla fragmentów może być pominięty
    if not skip_preprocessing:
        print(f"🔧 [OCR_MODELS] Preprocessing obrazu przed OCR...")
        from .preprocessors import preprocess_image
        
        try:
            preprocessed_image_path = preprocess_image(image_path)
            print(f"✅ [OCR_MODELS] Preprocessing zakończony: {preprocessed_image_path}")
            
            # Inteligentny fallback - jeśli preprocessing się nie udał, użyj oryginału
            if preprocessed_image_path == image_path:
                print(f"⚠️ [OCR_MODELS] Preprocessing nie zmienił obrazu - używam oryginału")
            else:
                # Użyj przetworzonego obrazu dla OCR
                image_path = preprocessed_image_path
                print(f"🔧 [OCR_MODELS] Używam przetworzonego obrazu dla OCR")
                
        except Exception as e:
            print(f"⚠️ [OCR_MODELS] Błąd preprocessing, używam oryginału: {e}")
            # Kontynuuj z oryginalnym obrazem
    else:
        print(f"🔧 [OCR_MODELS] Pominięto preprocessing (skip_preprocessing=True)")
        preprocessed_image_path = str(image_path)

    try:
        if OCR_MODEL_TYPE == "dots":
            # DOTS format (without system message)
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_path},
                        {"type": "text", "text": instruction},
                    ],
                },
            ]
        else:
            # Qwen format (with system message)
            messages = [
                {
                    "role": "system",
                    "content": [{"type": "text", "text": "You are OCR system for text recognition."}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image_path},
                        {"type": "text", "text": instruction},
                    ],
                },
            ]

        print(f"🔍 [OCR_MODELS] Przetwarzanie wiadomości...")
        text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)

        print(f"🔍 [OCR_MODELS] Przygotowywanie inputs...")
        inputs = processor(
            text=[text_prompt],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )

        # Handle device placement for inputs
        if OCR_MODEL_TYPE == "dots":
            # DOTS model - get device from model parameters
            try:
                target_device = next(model.parameters()).device
                inputs = inputs.to(target_device)
                print(f"🔍 [OCR_MODELS] DOTS inputs moved to: {target_device}")
            except Exception as device_error:
                print(f"⚠️ [OCR_MODELS] DOTS device placement failed: {device_error}")
                # Fallback to cuda:0
                target_device = "cuda:0"
                inputs = inputs.to(target_device)
                print(f"🔍 [OCR_MODELS] DOTS fallback to: {target_device}")
        else:
            # Qwen model - handle multi-GPU device placement
            try:
                # Try to get the device of the first parameter (works for single GPU)
                if hasattr(model, 'device'):
                    target_device = model.device
                else:
                    # For multi-GPU models, get device of first parameter
                    target_device = next(model.parameters()).device
                
                inputs = inputs.to(target_device)
                print(f"🔍 [OCR_MODELS] Qwen inputs moved to device: {target_device}")
                
            except Exception as device_error:
                print(f"⚠️ [OCR_MODELS] Device placement issue: {device_error}")
                # For multi-GPU models with device_map="auto", don't move inputs
                # The model will handle device placement internally
                print(f"🔍 [OCR_MODELS] Using auto device placement for multi-GPU")

        print(f"🔍 [OCR_MODELS] Rozpoczynam generację tekstu...")
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            logger.info("Instrukcja: %s", instruction)
            with torch.no_grad():
                if OCR_MODEL_TYPE == "dots":
                    # DOTS-specific generation parameters - optimized for speed without limiting output
                    gen_ids = model.generate(
                        **inputs,
                        max_new_tokens=MAX_NEW_TOKENS,  # Keep full capacity for large texts
                        do_sample=False,  # Deterministic output
                        num_beams=1,  # Faster than beam search
                        early_stopping=True,
                        pad_token_id=processor.tokenizer.eos_token_id,
                        eos_token_id=processor.tokenizer.eos_token_id,
                        use_cache=True,  # Enable KV cache for speed
                    )
                else:
                    # Qwen generation parameters
                    gen_ids = model.generate(
                        **inputs,
                        max_new_tokens=MAX_NEW_TOKENS
                        # eos_token_id=processor.tokenizer.eos_token_id,
                        # pad_token_id=processor.tokenizer.pad_token_id,
                    )
            print(f"✅ [OCR_MODELS] Generacja zakończona pomyślnie")
        except torch.cuda.OutOfMemoryError as oom_error:
            # Fallback mechanism - try with smaller image if OOM occurs
            print(f"🚨 [OCR_MODELS] CUDA OOM podczas generacji: {str(oom_error)}")
            logger.error(f"CUDA OOM podczas generacji: {str(oom_error)}")
            
            # Spróbuj z mniejszym obrazem (75% oryginalnego rozmiaru po preprocessing)
            try:
                print(f"🔧 [OCR_MODELS] Próba fallback z mniejszym obrazem...")
                from .utils import aggressive_memory_cleanup
                aggressive_memory_cleanup()
                
                # Przeskaluj obraz do 75% rozmiaru
                from PIL import Image as PILImage
                with PILImage.open(image_path) as img:
                    original_size = img.size
                    new_size = (int(original_size[0] * 0.75), int(original_size[1] * 0.75))
                    img_resized = img.resize(new_size, PILImage.LANCZOS)
                    
                    # Zapisz zmniejszony obraz
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                        fallback_path = tmp_img.name
                    img_resized.save(fallback_path, "PNG")
                    
                print(f"🔧 [OCR_MODELS] Fallback - zmniejszono z {original_size} do {new_size}")
                
                # Przygotuj inputs dla mniejszego obrazu
                fallback_messages = [
                    {
                        "role": "system",
                        "content": [{"type": "text", "text": "You are OCR system for text recognition."}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": fallback_path},
                            {"type": "text", "text": instruction},
                        ],
                    },
                ]
                
                fallback_text_prompt = processor.apply_chat_template(fallback_messages, tokenize=False, add_generation_prompt=True)
                fallback_image_inputs, fallback_video_inputs = process_vision_info(fallback_messages)
                
                fallback_inputs = processor(
                    text=[fallback_text_prompt],
                    images=fallback_image_inputs,
                    videos=fallback_video_inputs,
                    padding=True,
                    return_tensors="pt",
                ).to(model.device)
                
                # Próba generacji z mniejszym obrazem
                with torch.no_grad():
                    gen_ids = model.generate(
                        **fallback_inputs,
                        max_new_tokens=MAX_NEW_TOKENS
                    )
                print(f"✅ [OCR_MODELS] Fallback zakończony pomyślnie")
                
                # Usuń tymczasowy plik
                try:
                    Path(fallback_path).unlink()
                except:
                    pass
                    
            except Exception as fallback_error:
                print(f"❌ [OCR_MODELS] Fallback też się nie udał: {str(fallback_error)}")
                logger.error(f"Fallback też się nie udał: {str(fallback_error)}")
                return f"[Błąd OCR: CUDA out of memory. Tried to allocate memory for image processing. Both original and fallback attempts failed.]"
        except TimeoutError:
            error_msg = f"Timeout > {timeout_seconds} s – pominięto stronę"
            print(f"⏰ [OCR_MODELS] {error_msg}")
            logger.error(error_msg)
            raise TimeoutError(error_msg)  # Re-raise to allow fallback logic to catch it
        finally:
            signal.alarm(0)

        print(f"🔍 [OCR_MODELS] Dekodowanie wyników...")
        try:
            if OCR_MODEL_TYPE == "dots":
                # DOTS-specific decoding
                trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
                text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                print(f"🔍 [OCR_MODELS] DOTS decoded text length: {len(text)}")
                
                # Additional validation for DOTS output
                if len(text.strip()) == 0:
                    print(f"⚠️ [OCR_MODELS] DOTS returned empty text, trying different decode...")
                    # Try alternative decoding
                    full_text = processor.batch_decode(gen_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                    # Find the part after the instruction
                    if "Extract the text content from this image." in full_text:
                        text = full_text.split("Extract the text content from this image.")[-1].strip()
                        print(f"🔍 [OCR_MODELS] Alternative decode found: {len(text)} chars")
            else:
                # Qwen decoding
                trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
                text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True)[0]

            print(f"✅ [OCR_MODELS] OCR zakończony, długość tekstu: {len(text)}")
            
            # Debug: Show first 200 characters of result
            if len(text) > 0:
                preview = text[:200].replace('\n', '\\n')
                print(f"🔍 [OCR_MODELS] Preview: {preview}...")
            else:
                print(f"⚠️ [OCR_MODELS] WARNING: Empty text result!")
                
        except Exception as decode_error:
            print(f"❌ [OCR_MODELS] Błąd dekodowania: {str(decode_error)}")
            logger.error(f"Błąd dekodowania: {str(decode_error)}")
            return f"[Błąd dekodowania OCR: {str(decode_error)}]"

        # cleanup RAM i GPU memory
        del inputs, gen_ids, image_inputs, video_inputs
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()  # Synchronizacja CUDA
            
        # Dodatkowe czyszczenie pamięci
        from .utils import aggressive_memory_cleanup
        aggressive_memory_cleanup()
        
        # Usuń tymczasowy plik z preprocessing jeśli istnieje  
        try:
            if not skip_preprocessing and 'preprocessed_image_path' in locals() and preprocessed_image_path != image_path:
                Path(preprocessed_image_path).unlink()
                print(f"🧹 [OCR_MODELS] Usunięto tymczasowy plik: {preprocessed_image_path}")
        except Exception as cleanup_error:
            print(f"⚠️ [OCR_MODELS] Nie udało się usunąć tymczasowego pliku: {cleanup_error}")

        return text.strip()

    except TimeoutError:
        # Re-raise TimeoutError to allow fallback logic to handle it
        raise
    except Exception as e:
        error_msg = f"Błąd podczas OCR: {str(e)}"
        print(f"❌ [OCR_MODELS] {error_msg}")
        logger.error(error_msg)

        # Dodaj stack trace
        import traceback
        traceback.print_exc()

        return f"[Błąd OCR: {str(e)}]"


# ---------------------------------------------------------------------------
#  Zwalnianie zasobów (legacy helper)
# ---------------------------------------------------------------------------

def clean_resources(*resources: Any) -> None:
    for r in resources:
        if r is not None:
            del r
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
