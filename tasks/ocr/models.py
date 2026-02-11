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
    LAYOUT_OCR_INSTRUCTION,
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

logger.debug("models.py imported in PID=%d", os.getpid())


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
        logger.debug("GPU clock: %d MHz", clock_mhz)
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

            free, total = torch.cuda.mem_get_info(i)
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)

            logger.debug("GPU %d: %.2fGB free / %.2fGB total", i, free_gb, total_gb)

            if free_gb >= threshold_gb:
                performance = get_gpu_performance(handle)
                if (free_gb > best_free) or (free_gb == best_free and performance > best_perf):
                    best_gpu = i
                    best_free = free_gb
                    best_perf = performance

        pynvml.nvmlShutdown()

        if best_gpu is not None:
            logger.debug("Selected GPU %d (%.2fGB free)", best_gpu, best_free)
        else:
            logger.debug("No GPU with >=%dGB free", threshold_gb)
            
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
    logger.info("Loading %s model (PID=%d)", model_type, os.getpid())

    try:
        if not torch.cuda.is_available():
            raise Exception("CUDA nie jest dostępna!")

        logger.debug("CUDA available, %d GPUs", torch.cuda.device_count())

        # Check model availability
        if "/" in model_path and not Path(model_path).exists():
            logger.debug("Model from HF Hub: %s", model_path)
            try:
                from transformers import AutoConfig
                AutoConfig.from_pretrained(model_path, trust_remote_code=True)
            except Exception as e:
                raise Exception(f"Model niedostępny w HF Hub: {str(e)}")
        elif not Path(model_path).exists():
            raise Exception(f"Model nie istnieje lokalnie ani w HF Hub: {model_path}")

        strategy = CFG_STRATEGY

        # Model-aware device strategy
        if assigned_gpu is not None:
            gpu = assigned_gpu
            strategy = "single"
            logger.debug("%s -> single GPU cuda:%d", model_type.upper(), gpu)
        else:
            if strategy == "single" and GPU_SELECT_MODE == "auto":
                gpu = _pick_best_gpu(GPU_MEM_LIMIT_GB)
                if gpu is None:
                    logger.warning("No GPU >=%dGB free, using device_map='auto'", GPU_MEM_LIMIT_GB)
                    strategy = "auto"
                    gpu = 0
            else:
                gpu = 0

        logger.debug("GPU=%d, strategy=%s, model=%s", gpu, strategy, model_type)

        # Check GPU memory
        try:
            free_mem, total_mem = torch.cuda.mem_get_info(gpu)
            free_gb = free_mem / (1024 ** 3)
            logger.debug("GPU %d: %.2fGB free", gpu, free_gb)
            if free_gb < 8.0:
                logger.warning("Low GPU memory (%.2fGB), model may fail to load", free_gb)
        except Exception:
            pass

        # Build load params
        if model_type == "dots":
            params: Dict[str, Any] = {
                "attn_implementation": "flash_attention_2",
                "torch_dtype": torch.bfloat16,
                "trust_remote_code": True,
                "device_map": f"cuda:{gpu}",
                "max_memory": {gpu: f"{GPU_MEM_LIMIT_GB}GiB"}
            }
        else:
            params: Dict[str, Any] = {"torch_dtype": torch.float16, "trust_remote_code": True}
            if strategy == "single":
                params["device_map"] = f"cuda:{gpu}"
                params["max_memory"] = {gpu: f"{GPU_MEM_LIMIT_GB}GiB"}
            else:
                params["device_map"] = "auto"

        logger.debug("Load params: %s", params)

        try:
            if model_type == "dots":
                model = AutoModelForCausalLM.from_pretrained(model_path, **params).eval()
            else:
                model = AutoModelForVision2Seq.from_pretrained(model_path, **params).eval()
        except torch.cuda.OutOfMemoryError:
            if assigned_gpu is not None:
                logger.error("OOM on assigned GPU %d (parallel mode, cannot spread)", assigned_gpu)
                raise
            logger.warning("OOM, retrying with device_map='auto'")
            params.pop("max_memory", None)
            params["device_map"] = "auto"
            if model_type == "dots":
                model = AutoModelForCausalLM.from_pretrained(model_path, **params).eval()
            else:
                model = AutoModelForVision2Seq.from_pretrained(model_path, **params).eval()

        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)

        logger.info("%s model loaded on GPU %d (PID=%d)", model_type.upper(), gpu, os.getpid())
        return model, processor

    except Exception as e:
        logger.error("Model load failed: %s", e, exc_info=True)
        raise Exception(f"Nie można załadować modelu OCR: {str(e)}")


def get_ocr_model(assigned_gpu: int = None) -> Tuple[Any, AutoProcessor]:
    """Publiczny interfejs do pobierania modelu OCR."""
    logger.debug("get_ocr_model called (PID=%d, gpu=%s)", os.getpid(), assigned_gpu)
    try:
        from .config import OCR_MODEL_TYPE, OCR_MODEL_PATH
        return _load_once(OCR_MODEL_TYPE, OCR_MODEL_PATH, assigned_gpu)
    except Exception as e:
        logger.error("get_ocr_model failed: %s", e)
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
        no_fallback: bool = False,
):
    """
    Rozpoznaje tekst z obrazu z fallback DOTS → QWEN.
    
    1. Próbuje DOTS z skróconym timeout (50% normalnego)
    2. Jeśli DOTS timeout → automatycznie przełącza na QWEN
    3. Każdy obraz zaczyna od DOTS (brak trwałego stanu fallback)
    """
    logger.debug("OCR with fallback: %s", image_path)

    if OCR_MODEL_TYPE == "dots":
        try:
            result = process_image_to_text_internal(
                image_path=image_path,
                instruction=instruction,
                model_type="dots",
                model_path=DOTS_MODEL_PATH,
                timeout_seconds=DOTS_FALLBACK_TIMEOUT_SECONDS,
                skip_preprocessing=skip_preprocessing,
                assigned_gpu=assigned_gpu
            )
            result_len = len(result["text"]) if isinstance(result, dict) else len(result)
            logger.debug("DOTS OK: %d chars", result_len)
            return result

        except TimeoutError as timeout_err:
            if no_fallback:
                logger.debug("DOTS timeout (no_fallback) — will retry later")
                raise

            logger.warning("DOTS timeout after %ds, falling back to QWEN: %s",
                           DOTS_FALLBACK_TIMEOUT_SECONDS, image_path)

            try:
                result = process_image_to_text_internal(
                    image_path=image_path,
                    instruction=instruction,
                    model_type="qwen",
                    model_path=QWEN_MODEL_PATH,
                    timeout_seconds=QWEN_TIMEOUT_SECONDS,
                    skip_preprocessing=skip_preprocessing,
                    assigned_gpu=assigned_gpu,
                    request_layout=True,
                )
                result_len = len(result["text"]) if isinstance(result, dict) else len(result)
                logger.info("QWEN fallback OK: %d chars", result_len)
                return result

            except Exception as qwen_error:
                logger.error("QWEN fallback also failed: %s", qwen_error)
                return f"[Błąd OCR: DOTS timeout po {DOTS_FALLBACK_TIMEOUT_SECONDS}s, QWEN fallback także nieudany: {str(qwen_error)}]"

        except torch.cuda.OutOfMemoryError as oom_err:
            if no_fallback:
                logger.debug("DOTS OOM (no_fallback) — will retry later")
                raise

            logger.warning("DOTS OOM, falling back to QWEN: %s", image_path)

            try:
                torch.cuda.empty_cache()
                gc.collect()
            except Exception:
                pass

            try:
                result = process_image_to_text_internal(
                    image_path=image_path,
                    instruction=instruction,
                    model_type="qwen",
                    model_path=QWEN_MODEL_PATH,
                    timeout_seconds=QWEN_TIMEOUT_SECONDS,
                    skip_preprocessing=skip_preprocessing,
                    assigned_gpu=assigned_gpu,
                    request_layout=True,
                )
                result_len = len(result["text"]) if isinstance(result, dict) else len(result)
                logger.info("QWEN fallback (OOM) OK: %d chars", result_len)
                return result
            except Exception as qwen_error:
                logger.error("QWEN fallback (OOM) also failed: %s", qwen_error)
                raise

        except Exception as dots_error:
            logger.error("DOTS error (non-recoverable): %s", dots_error)
            raise

    else:
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
        request_layout: bool = False,
):
    """Wewnętrzna funkcja OCR z określonym modelem i timeout.

    Passes model_type/model_path directly to process_image_to_text_core
    so the LRU cache in _load_once can hold multiple models simultaneously
    without needing cache_clear().
    """
    logger.debug("OCR internal: %s @ %s", model_type, image_path)

    return process_image_to_text_core(
        image_path=image_path,
        instruction=instruction,
        timeout_seconds=timeout_seconds,
        skip_preprocessing=skip_preprocessing,
        assigned_gpu=assigned_gpu,
        request_layout=request_layout,
        model_type=model_type,
        model_path=model_path,
    )


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
            assigned_gpu=assigned_gpu,
            model_type=OCR_MODEL_TYPE,
            model_path=OCR_MODEL_PATH,
        )
    except TimeoutError as e:
        logger.warning("OCR timeout: %s", e)
        return f"[Timeout OCR]"


def process_image_to_text_core(
        image_path: str | Path,
        instruction: str = DEFAULT_OCR_INSTRUCTION,
        timeout_seconds: int = OCR_TIMEOUT_SECONDS,
        skip_preprocessing=False,
        assigned_gpu: int = None,
        request_layout: bool = False,
        model_type: str = None,
        model_path: str = None,
):
    """Podstawowa funkcja OCR - wydzielona logika z process_image_to_text.

    Args:
        model_type: Explicit model type ("dots" or "qwen"). Falls back to
                    config default when None.
        model_path: Explicit model path. Falls back to config default when None.

    Returns:
        For layout mode: dict {"text": str, "layout": list[dict]}
        For QWEN or fallback: str (plain text)
    """
    # Resolve model_type / model_path — use explicit values if provided,
    # otherwise fall back to current config (backwards compat).
    if model_type is None or model_path is None:
        import tasks.ocr.config as _cfg
        if model_type is None:
            model_type = _cfg.OCR_MODEL_TYPE
        if model_path is None:
            model_path = _cfg.OCR_MODEL_PATH

    current_model_type = model_type

    logger.debug("OCR core: %s (timeout=%ds, model=%s)", image_path, timeout_seconds, current_model_type)

    use_layout_mode = (
        (current_model_type == "dots" and instruction == DEFAULT_OCR_INSTRUCTION)
        or request_layout
    )
    if use_layout_mode:
        instruction = LAYOUT_OCR_INSTRUCTION
        logger.debug("Layout mode enabled")

    try:
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        raise Exception(f"Nie można zaimportować qwen_vl_utils: {str(e)}")

    try:
        model, processor = _load_once(current_model_type, model_path, assigned_gpu)
    except Exception as e:
        logger.error("Model load failed: %s", e)
        return f"[Błąd ładowania modelu: {str(e)}]"

    if isinstance(image_path, Path):
        image_path = str(image_path)

    # Sprawdź czy plik obrazu istnieje
    if not Path(image_path).exists():
        return f"[Błąd: Plik obrazu nie istnieje: {image_path}]"
    
    # KRYTYCZNE: Preprocessing obrazu PRZED wysłaniem do modelu OCR
    # To zmniejsza obraz z 4032x3024 do 1536x1152 i obsługuje EXIF rotation
    # Dla fragmentów może być pominięty
    if not skip_preprocessing:
        from .preprocessors import preprocess_image
        try:
            preprocessed_image_path = preprocess_image(image_path)
            if preprocessed_image_path != image_path:
                image_path = preprocessed_image_path
        except Exception as e:
            logger.debug("Preprocessing failed, using original: %s", e)
    else:
        preprocessed_image_path = str(image_path)

    try:
        if current_model_type == "dots":
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

        text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = processor(
            text=[text_prompt],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )

        # Device placement for inputs
        if current_model_type == "dots":
            try:
                target_device = next(model.parameters()).device
                inputs = inputs.to(target_device)
            except Exception:
                inputs = inputs.to("cuda:0")
        else:
            try:
                target_device = model.device if hasattr(model, 'device') else next(model.parameters()).device
                inputs = inputs.to(target_device)
            except Exception:
                pass  # multi-GPU auto placement

        logger.debug("Starting generation (%s)", current_model_type)
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            with torch.no_grad():
                if current_model_type == "dots":
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
            logger.debug("Generation complete")
        except torch.cuda.OutOfMemoryError as oom_error:
            logger.error("CUDA OOM during generation (%s)", current_model_type)

            # Try with 75% smaller image
            try:
                from .utils import aggressive_memory_cleanup
                aggressive_memory_cleanup()

                from PIL import Image as PILImage
                with PILImage.open(image_path) as img:
                    original_size = img.size
                    new_size = (int(original_size[0] * 0.75), int(original_size[1] * 0.75))
                    img_resized = img.resize(new_size, PILImage.LANCZOS)

                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                        fallback_path = tmp_img.name
                    img_resized.save(fallback_path, "PNG")

                logger.debug("OOM fallback: resized %s -> %s", original_size, new_size)

                if current_model_type == "dots":
                    fallback_messages = [
                        {"role": "user", "content": [
                            {"type": "image", "image": fallback_path},
                            {"type": "text", "text": instruction},
                        ]},
                    ]
                else:
                    fallback_messages = [
                        {"role": "system", "content": [{"type": "text", "text": "You are OCR system for text recognition."}]},
                        {"role": "user", "content": [
                            {"type": "image", "image": fallback_path},
                            {"type": "text", "text": instruction},
                        ]},
                    ]

                fallback_text_prompt = processor.apply_chat_template(fallback_messages, tokenize=False, add_generation_prompt=True)
                fallback_image_inputs, fallback_video_inputs = process_vision_info(fallback_messages)

                fallback_inputs = processor(
                    text=[fallback_text_prompt],
                    images=fallback_image_inputs,
                    videos=fallback_video_inputs,
                    padding=True,
                    return_tensors="pt",
                )

                if current_model_type == "dots":
                    try:
                        target_device = next(model.parameters()).device
                    except Exception:
                        target_device = "cuda:0"
                    fallback_inputs = fallback_inputs.to(target_device)
                else:
                    try:
                        target_device = model.device if hasattr(model, 'device') else next(model.parameters()).device
                        fallback_inputs = fallback_inputs.to(target_device)
                    except Exception:
                        pass

                with torch.no_grad():
                    if current_model_type == "dots":
                        gen_ids = model.generate(
                            **fallback_inputs,
                            max_new_tokens=MAX_NEW_TOKENS,
                            do_sample=False,
                            num_beams=1,
                            early_stopping=True,
                            pad_token_id=processor.tokenizer.eos_token_id,
                            eos_token_id=processor.tokenizer.eos_token_id,
                            use_cache=True,
                        )
                    else:
                        gen_ids = model.generate(
                            **fallback_inputs,
                            max_new_tokens=MAX_NEW_TOKENS
                        )
                logger.debug("OOM fallback generation succeeded")

                try:
                    Path(fallback_path).unlink()
                except Exception:
                    pass

            except Exception as fallback_error:
                logger.error("OOM fallback also failed: %s", fallback_error)
                raise torch.cuda.OutOfMemoryError(
                    "CUDA out of memory. Both original and 75% fallback attempts failed."
                ) from fallback_error
        except TimeoutError:
            error_msg = f"Timeout > {timeout_seconds} s"
            logger.error(error_msg)
            raise TimeoutError(error_msg)
        finally:
            signal.alarm(0)

        try:
            if current_model_type == "dots":
                trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
                text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]

                if len(text.strip()) == 0:
                    logger.debug("DOTS empty output, trying alternative decode")
                    full_text = processor.batch_decode(gen_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                    if "Extract the text content from this image." in full_text:
                        text = full_text.split("Extract the text content from this image.")[-1].strip()
            else:
                trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
                text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True)[0]

            logger.debug("OCR result: %d chars", len(text))

            if len(text) == 0:
                logger.warning("Empty OCR result")

        except Exception as decode_error:
            logger.error("Decode error: %s", decode_error)
            return f"[Błąd dekodowania OCR: {str(decode_error)}]"

        # cleanup RAM i GPU memory
        del inputs, gen_ids, image_inputs, video_inputs
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        try:
            if not skip_preprocessing and 'preprocessed_image_path' in locals() and preprocessed_image_path != image_path:
                Path(preprocessed_image_path).unlink()
        except Exception:
            pass

        if use_layout_mode:
            layout_data = _parse_layout_response(text.strip(), image_path)
            if layout_data is not None:
                return layout_data
            logger.debug("Layout parsing failed, trying plain text extraction")
            extracted = _extract_text_from_json(text.strip())
            if extracted is not None:
                return extracted

        return text.strip()

    except TimeoutError:
        raise
    except Exception as e:
        logger.error("OCR failed: %s", e, exc_info=True)
        return f"[Błąd OCR: {str(e)}]"


# ---------------------------------------------------------------------------
#  Layout response parsing (DOTS layout mode)
# ---------------------------------------------------------------------------

def _extract_text_from_json(raw_text: str) -> str | None:
    """Last-resort extraction of text content from JSON that layout parsing couldn't handle.

    Handles multiple QWEN output formats:
    - Category format: {"Category": ["[bbox] text"], ...}  (may have duplicate keys)
    - Numbered-dict format: {"1": {"text_content": "..."}, ...}
    """
    import json
    import re

    clean = _strip_markdown_code_block(raw_text)

    # --- Fast path: standard json.loads for numbered-dict format ---
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            text_parts = []
            for val in parsed.values():
                if isinstance(val, dict) and "text_content" in val:
                    t = val["text_content"]
                    if t:
                        text_parts.append(t)
            if text_parts:
                result = "\n".join(text_parts)
                logger.debug("Extracted %d chars from numbered-dict JSON", len(result))
                return result
    except (json.JSONDecodeError, ValueError):
        pass

    # --- Slow path: object_pairs_hook for duplicate-key formats (category) ---
    try:
        pairs = json.loads(clean, object_pairs_hook=lambda p: p)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(pairs, list) or not pairs:
        return None

    bbox_re = re.compile(r'^\[[\d,\s]+\]\s*(.*)')
    text_parts = []

    for key, val in pairs:
        # Numbered-dict via object_pairs_hook (nested dicts become list of tuples)
        if isinstance(val, list) and val and isinstance(val[0], tuple):
            val_dict = dict(val)
            if "text_content" in val_dict:
                t = val_dict["text_content"]
                if t:
                    text_parts.append(t)
                continue
        # Category format: {"Category": ["[bbox] text", ...]}
        if isinstance(val, list):
            for entry in val:
                if not isinstance(entry, str):
                    continue
                m = bbox_re.match(entry)
                if m:
                    text_parts.append(m.group(1))
                else:
                    text_parts.append(entry)

    if not text_parts:
        return None

    result = "\n".join(text_parts)
    logger.debug("Extracted %d chars from unparsed JSON", len(result))
    return result


def _parse_qwen_category_format(raw_text: str, image_path: str | Path) -> dict | None:
    """Parse QWEN category format with duplicate keys.

    Format: {"Category": ["[x1,y1,x2,y2] text content"], ...}
    Standard json.loads loses duplicate keys (e.g. multiple "Text" entries).
    We re-parse with object_pairs_hook to preserve them all.

    Returns:
        dict {"text": plain_text, "layout": [{"bbox": [...], "category": str, "text": str}]}
        or None if parsing fails.
    """
    import json
    import re
    from PIL import Image as PILImage

    try:
        pairs = json.loads(raw_text, object_pairs_hook=lambda p: p)
    except json.JSONDecodeError:
        return None

    if not isinstance(pairs, list) or not pairs:
        return None

    # Verify this looks like category format: list of (str, list) tuples
    # Entries may have bbox "[x,y,x,y] text" or just plain text
    bbox_re = re.compile(r'^\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]\s*(.*)')

    first_key, first_val = pairs[0]
    if not isinstance(first_key, str) or not isinstance(first_val, list):
        return None
    if not first_val or not isinstance(first_val[0], str):
        return None

    first_entry = first_val[0].strip()
    has_bbox = bbox_re.match(first_entry) is not None

    # Get image dimensions for bbox normalization (needed for has_bbox case)
    with PILImage.open(image_path) as img:
        img_w, img_h = img.size

    # Count total entries for vertical distribution (when no bbox)
    total_entries = sum(len(entries) for _, entries in pairs if isinstance(entries, list))

    layout_blocks = []
    text_parts = []
    entry_idx = 0

    for category, entries in pairs:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue

            entry_text = entry.strip()
            if not entry_text:
                continue

            if has_bbox:
                # Parse bbox from entry
                m = bbox_re.match(entry_text)
                if not m:
                    entry_idx += 1
                    continue
                x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                cell_text = m.group(5).strip()

                norm_bbox = [
                    max(0.0, min(1.0, x1 / img_w)),
                    max(0.0, min(1.0, y1 / img_h)),
                    max(0.0, min(1.0, x2 / img_w)),
                    max(0.0, min(1.0, y2 / img_h)),
                ]
            else:
                # No bbox - distribute text blocks vertically across the page
                cell_text = entry_text
                # Calculate vertical position for this entry
                y_start = (entry_idx / max(total_entries, 1)) * 0.9 + 0.02
                y_end = ((entry_idx + 1) / max(total_entries, 1)) * 0.9 + 0.02
                # Use full width with small margins
                norm_bbox = [0.02, y_start, 0.98, min(y_end, 0.98)]

            block = {"bbox": norm_bbox, "category": category}
            if category != "Picture" and cell_text:
                block["text"] = cell_text
                text_parts.append(cell_text)
            layout_blocks.append(block)
            entry_idx += 1

    if not layout_blocks:
        return None

    plain_text = "\n\n".join(text_parts)
    logger.debug("Layout parsed (QWEN-category): %d blocks, %d chars", len(layout_blocks), len(plain_text))
    return {"text": plain_text, "layout": layout_blocks}


def _strip_markdown_code_block(text: str) -> str:
    """Strip markdown code block wrappers from model output.

    QWEN often wraps JSON in ```json ... ``` or prefixes with 'json'.
    """
    import re
    stripped = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    m = re.match(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', stripped, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Strip bare 'json' prefix (e.g. "json\n{...}" or "json {...")
    m = re.match(r'^json\s*\n', stripped, re.IGNORECASE)
    if m:
        return stripped[m.end():]
    return stripped


def _detect_qwen_dict_format(parsed: dict, clean_text: str, image_path) -> tuple:
    """Detect and extract cells from various QWEN dict output formats.

    Formats handled:
    - Numbered-dict: {"1": {"bbox_2d": [...], "text_content": "..."}, ...}
    - Nested page:   {"Page": {"Layout Elements": [{...}, ...]}}
    - Any dict with a single key whose value is a list of cell dicts

    Returns:
        (cells, is_qwen_format) or (None, False) if not recognized.
    """

    def _is_cell_list(lst):
        """Check if a list looks like QWEN layout cells."""
        if not isinstance(lst, list) or not lst:
            return False
        first = lst[0]
        return isinstance(first, dict) and ("bbox_2d" in first or "text_content" in first)

    # Numbered-dict: {"1": {"bbox_2d": ..., "text_content": ...}, "2": {...}}
    first_val = next(iter(parsed.values()))
    if isinstance(first_val, dict) and ("bbox_2d" in first_val or "text_content" in first_val):
        cells = list(parsed.values())
        logger.debug("QWEN numbered-dict format: %d cells", len(cells))
        return cells, True

    for key, val in parsed.items():
        if isinstance(val, list) and _is_cell_list(val):
            logger.debug("QWEN nested format (key=%r): %d cells", key, len(val))
            return val, True
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list) and _is_cell_list(sub_val):
                    logger.debug("QWEN nested format (keys=%r/%r): %d cells", key, sub_key, len(sub_val))
                    return sub_val, True

    return None, False


def _parse_layout_response(raw_text: str, image_path: str | Path) -> dict | None:
    """Parse layout JSON response into structured data with normalized bboxes.

    Handles three formats:
    - DOTS: flat list  [{"bbox": [x1,y1,x2,y2], "category": str, "text": str}, ...]
    - QWEN-Layouts:    {"Layouts": [{"bbox_2d": [x1,y1,x2,y2], "category": str, "text_content": str}, ...]}
    - QWEN-category:   {"Category": ["[x1,y1,x2,y2] text"], ...}  (duplicate keys!)

    Returns:
        dict {"text": plain_text, "layout": [{"bbox": [x1,y1,x2,y2], "category": str, "text": str}]}
        where bbox coordinates are normalized to 0-1 range.
        Returns None if parsing fails.
    """
    import json
    import re
    from PIL import Image as PILImage

    # Strip markdown code block wrappers (QWEN often wraps JSON in ```json ... ```)
    clean_text = _strip_markdown_code_block(raw_text)

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError as e:
        logger.debug("Layout JSON parse failed: %s", e)
        return None

    try:
        # Detect format and normalize to a flat list of cells
        cells = None
        is_qwen_format = False

        if isinstance(parsed, list) and len(parsed) > 0:
            # DOTS format: flat list of cells
            cells = parsed
            logger.debug("DOTS layout format: %d cells", len(cells))
        elif isinstance(parsed, dict) and "Layouts" in parsed:
            # QWEN format: {"Layouts": [...]}
            raw_layouts = parsed["Layouts"]
            if isinstance(raw_layouts, list) and len(raw_layouts) > 0:
                cells = raw_layouts
                is_qwen_format = True
                logger.debug("QWEN Layouts format: %d cells", len(cells))
        elif isinstance(parsed, dict) and len(parsed) > 0:
            # Try to find a list of layout cells from various QWEN dict formats
            cells, is_qwen_format = _detect_qwen_dict_format(parsed, clean_text, image_path)
            if cells is not None:
                pass  # detected by helper
            else:
                # QWEN category format: {"Category": ["[x1,y1,x2,y2] text"], ...}
                # Has duplicate keys — re-parse preserving all pairs.
                result = _parse_qwen_category_format(clean_text, image_path)
                if result:
                    return result

        if not cells:
            if isinstance(parsed, dict):
                logger.debug("Unrecognized layout dict, keys: %s", list(parsed.keys())[:5])
            else:
                logger.debug("Unrecognized layout format: %s", type(parsed).__name__)
            return None

        # Load original image to get dimensions for coordinate conversion
        with PILImage.open(image_path) as img:
            img_w, img_h = img.size

        if not is_qwen_format:
            # DOTS: apply post_process_cells for coordinate correction
            try:
                import sys
                _dots_parent = str(Path(__file__).resolve().parent)
                if _dots_parent not in sys.path:
                    sys.path.insert(0, _dots_parent)
                from dots_ocr.utils.layout_utils import post_process_cells
                with PILImage.open(image_path) as input_img:
                    input_w, input_h = input_img.size

                cells = post_process_cells(
                    PILImage.open(image_path),
                    cells,
                    input_w,
                    input_h,
                )
                logger.debug("DOTS post-processed: %d cells", len(cells))
            except Exception as pp_err:
                logger.debug("post_process_cells failed: %s", pp_err)

            # Re-read dimensions after post-processing
            with PILImage.open(image_path) as img:
                img_w, img_h = img.size

        # Normalize bbox coordinates to 0-1 range and build layout blocks
        layout_blocks = []
        text_parts = []

        for cell in cells:
            if is_qwen_format:
                # QWEN keys: bbox_2d, text_content
                bbox = cell.get("bbox_2d", [0, 0, 0, 0])
                category = cell.get("category", "Text")
                cell_text = cell.get("text_content", "")
            else:
                # DOTS keys: bbox, text
                bbox = cell.get("bbox", [0, 0, 0, 0])
                category = cell.get("category", "Text")
                cell_text = cell.get("text", "")

            if len(bbox) < 4:
                continue

            # Normalize to 0-1
            norm_bbox = [
                max(0.0, min(1.0, bbox[0] / img_w)),
                max(0.0, min(1.0, bbox[1] / img_h)),
                max(0.0, min(1.0, bbox[2] / img_w)),
                max(0.0, min(1.0, bbox[3] / img_h)),
            ]

            block = {
                "bbox": norm_bbox,
                "category": category,
            }
            if category != "Picture" and cell_text:
                block["text"] = cell_text
                text_parts.append(cell_text)

            layout_blocks.append(block)

        plain_text = "\n\n".join(text_parts)

        fmt_name = "QWEN" if is_qwen_format else "DOTS"
        logger.debug("Layout parsed (%s): %d blocks, %d chars", fmt_name, len(layout_blocks), len(plain_text))
        return {"text": plain_text, "layout": layout_blocks}

    except Exception as e:
        logger.debug("Layout processing error: %s", e)
        return None


# ---------------------------------------------------------------------------
#  Zwalnianie zasobów (legacy helper)
# ---------------------------------------------------------------------------

def cleanup_models() -> None:
    """Clear cached OCR models and free GPU memory.

    Called after each OCR task to release VRAM so all GPUs remain
    available for the next run.
    """
    _load_once.cache_clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("GPU memory released (PID=%d)", os.getpid())


def clean_resources(*resources: Any) -> None:
    for r in resources:
        if r is not None:
            del r
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
