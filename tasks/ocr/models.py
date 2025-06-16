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
from transformers import AutoModelForVision2Seq, AutoProcessor

from .config import (
    DEFAULT_OCR_INSTRUCTION,
    DEVICE_STRATEGY as CFG_STRATEGY,
    GPU_MEM_LIMIT_GB,
    GPU_SELECT_MODE,
    OCR_MODEL_PATH,
    OCR_TIMEOUT_SECONDS,
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
        logger.error(f"Błąd _pick_best_gpu: {e}")
        return 0  # Fallback na GPU 0


# ---------------------------------------------------------------------------
#  Model + processor – singleton w pamięci procesu
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_once() -> Tuple[AutoModelForVision2Seq, AutoProcessor]:
    """Ładuje model OCR - raz na proces."""
    print(f"🔄 [OCR_MODELS] Ładowanie modelu w procesie PID={os.getpid()}")
    logger.info(f"🔄 [OCR_MODELS] Ładowanie modelu w procesie PID={os.getpid()}")

    try:
        # Sprawdź czy CUDA jest dostępna
        if not torch.cuda.is_available():
            raise Exception("CUDA nie jest dostępna!")

        print(f"🔍 [OCR_MODELS] CUDA dostępna, liczba GPU: {torch.cuda.device_count()}")
        logger.info(f"🔍 [OCR_MODELS] CUDA dostępna, liczba GPU: {torch.cuda.device_count()}")

        # Sprawdź czy to lokalny path czy Hugging Face Hub
        if "/" in OCR_MODEL_PATH and not Path(OCR_MODEL_PATH).exists():
            print(f"🌐 [OCR_MODELS] Model z Hugging Face Hub: {OCR_MODEL_PATH}")
            logger.info(f"Model z Hugging Face Hub: {OCR_MODEL_PATH}")

            # Sprawdź cache HF
            try:
                from transformers import AutoConfig
                print(f"🔍 [OCR_MODELS] Sprawdzam dostępność modelu...")
                config = AutoConfig.from_pretrained(OCR_MODEL_PATH)
                print(f"✅ [OCR_MODELS] Model dostępny w HF Hub")
            except Exception as e:
                raise Exception(f"Model niedostępny w HF Hub: {str(e)}")
        elif Path(OCR_MODEL_PATH).exists():
            print(f"📁 [OCR_MODELS] Model lokalny istnieje: {OCR_MODEL_PATH}")
        else:
            raise Exception(f"Model nie istnieje lokalnie ani w HF Hub: {OCR_MODEL_PATH}")

        strategy = CFG_STRATEGY

        if strategy == "single" and GPU_SELECT_MODE == "auto":
            gpu = _pick_best_gpu(GPU_MEM_LIMIT_GB)
            if gpu is None:
                logger.warning("Brak karty ≥%s GB – przełączam na device_map='auto'", GPU_MEM_LIMIT_GB)
                strategy = "auto"
                gpu = 0
        else:
            gpu = 0

        print(f"🔍 [OCR_MODELS] Wybrano GPU: {gpu}, strategy: {strategy}")

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

        params: Dict[str, Any] = {"torch_dtype": torch.float16, "trust_remote_code": True}
        if strategy == "single":
            params["device_map"] = gpu  # ← kluczowa linia
            params["max_memory"] = {gpu: f"{GPU_MEM_LIMIT_GB}GiB"}
        else:
            params["device_map"] = "auto"

        print(f"🔍 [OCR_MODELS] Parametry ładowania: {params}")
        logger.info("Ładowanie modelu z parametrami: %s", params)

        try:
            model = AutoModelForVision2Seq.from_pretrained(OCR_MODEL_PATH, **params).eval()
            print(f"✅ [OCR_MODELS] Model załadowany pomyślnie")
        except torch.cuda.OutOfMemoryError:
            print(f"⚠️ [OCR_MODELS] OOM - ponawiam z device_map='auto'")
            logger.warning("OOM – ponawiam z device_map='auto'")
            params.pop("max_memory", None)
            params["device_map"] = "auto"
            model = AutoModelForVision2Seq.from_pretrained(OCR_MODEL_PATH, **params).eval()

        processor = AutoProcessor.from_pretrained(OCR_MODEL_PATH)
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


def get_ocr_model() -> Tuple[AutoModelForVision2Seq, AutoProcessor]:
    """Publiczny interfejs do pobierania modelu OCR."""
    print(f"🔍 [OCR_MODELS] get_ocr_model wywołane w procesie PID={os.getpid()}")
    try:
        return _load_once()
    except Exception as e:
        print(f"❌ [OCR_MODELS] Błąd w get_ocr_model: {str(e)}")
        raise


# ---------------------------------------------------------------------------
#  OCR jednej strony
# ---------------------------------------------------------------------------

def _timeout_handler(_signum, _frame):
    raise TimeoutError("Timeout podczas generacji tekstu")


def process_image_to_text(
        image_path: str | Path,
        instruction: str = DEFAULT_OCR_INSTRUCTION,
        model=None,
        processor=None,
        skip_preprocessing=False,
):
    """Rozpoznaje tekst z obrazu i zwraca go jako string."""
    print(f"🔍 [OCR_MODELS] process_image_to_text wywołane dla: {image_path}")

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

    # Jeśli nie podano modelu lub procesora, załaduj je
    if model is None or processor is None:
        print(f"🔍 [OCR_MODELS] Ładowanie modelu i procesora...")
        try:
            model, processor = get_ocr_model()
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
        ).to(model.device)

        print(f"🔍 [OCR_MODELS] Model device: {model.device}, inputs device: {inputs['pixel_values'].device}")
        logger.debug("model=%s pixels=%s", model.device, inputs["pixel_values"].device)

        print(f"🔍 [OCR_MODELS] Rozpoczynam generację tekstu...")
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(OCR_TIMEOUT_SECONDS)
        try:
            logger.info("Instrukcja: %s", instruction)
            with torch.no_grad():
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
            error_msg = f"Timeout > {OCR_TIMEOUT_SECONDS} s – pominięto stronę"
            print(f"⏰ [OCR_MODELS] {error_msg}")
            logger.error(error_msg)
            return f"[Timeout OCR]"
        finally:
            signal.alarm(0)

        print(f"🔍 [OCR_MODELS] Dekodowanie wyników...")
        trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
        text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True)[0]

        print(f"✅ [OCR_MODELS] OCR zakończony, długość tekstu: {len(text)}")

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