"""
Funkcje pomocnicze dla modułu OCR.
"""
# USUŃ to - spawn method już ustawiony w main.py!
# import multiprocessing
# multiprocessing.set_start_method('spawn',force=True)

import os
import subprocess
import sys
import tempfile
import torch
import gc
from pathlib import Path

from PIL import Image
from .config import logger

# ---------------------------------------------------------------------------
#  Shared constants
# ---------------------------------------------------------------------------

# Safe upper bound for PIL image loading (500M pixels ≈ 22360 x 22360).
# Set once here; every module that needs it imports and applies this value.
MAX_IMAGE_PIXELS_SAFE = 500_000_000

# Apply immediately so any Image.open() in this process respects the limit.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_SAFE

logger.debug("utils.py imported in PID=%d", os.getpid())

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
    logger.debug("Cleaning GPU memory")
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
    logger.debug("Aggressive memory cleanup started")

    if torch.cuda.is_available():
        try:
            allocated = torch.cuda.memory_allocated() / (1024 * 1024)
            reserved = torch.cuda.memory_reserved() / (1024 * 1024)
            logger.debug("Before cleanup — Allocated: %.2fMB, Reserved: %.2fMB", allocated, reserved)
        except Exception:
            pass

        torch.cuda.empty_cache()
        collected = gc.collect()

        try:
            allocated_after = torch.cuda.memory_allocated() / (1024 * 1024)
            reserved_after = torch.cuda.memory_reserved() / (1024 * 1024)
            logger.debug("After cleanup — Allocated: %.2fMB, Reserved: %.2fMB, GC: %d", allocated_after, reserved_after, collected)
        except Exception:
            pass


# ---------------------------------------------------------------------------
#  Shared helpers — video frame extraction & page rescaling
# ---------------------------------------------------------------------------

def extract_frame_from_video(video_path: Path) -> Path:
    """
    Extract first frame from a video file using ffmpeg.

    Args:
        video_path: Path to video file (MOV/MP4)

    Returns:
        Path to extracted JPEG frame

    Raises:
        Exception: If frame extraction fails
    """
    output_path = video_path.parent / f"{video_path.stem}_frame.jpg"

    # Locate ffmpeg — prefer the conda-env copy over the system one.
    conda_prefix = os.environ.get('CONDA_PREFIX')
    ffmpeg_path = None

    # Method 1: CONDA_PREFIX
    if conda_prefix:
        candidate = os.path.join(conda_prefix, 'bin', 'ffmpeg')
        if os.path.exists(candidate):
            ffmpeg_path = candidate

    # Method 2: infer from Python executable path
    if not ffmpeg_path:
        python_path = sys.executable
        if 'conda' in python_path or 'envs' in python_path:
            env_bin_dir = os.path.dirname(python_path)
            candidate = os.path.join(env_bin_dir, 'ffmpeg')
            if os.path.exists(candidate):
                ffmpeg_path = candidate

    # Method 3: hardcoded court-workflow path
    if not ffmpeg_path:
        candidate = '/root/miniconda3/envs/court-workflow/bin/ffmpeg'
        if os.path.exists(candidate):
            ffmpeg_path = candidate

    # Fallback: PATH lookup
    if not ffmpeg_path:
        ffmpeg_path = 'ffmpeg'

    cmd = [
        ffmpeg_path,
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        str(output_path)
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )

        if not output_path.exists():
            raise Exception("Frame extraction failed: output file not created")

        logger.info("Video frame extracted: %s", video_path.name)
        return output_path

    except subprocess.TimeoutExpired:
        raise Exception("Video frame extraction timeout (30s)")
    except subprocess.CalledProcessError as e:
        raise Exception(f"ffmpeg error: {e.stderr}")
    except Exception as e:
        raise Exception(f"Frame extraction failed: {str(e)}")


def rescale_oversized_pages(pages: list, label: str = "RESCALE") -> list:
    """
    Rescale pages whose pixel count exceeds PIL's default decompression-bomb
    threshold (178 956 970 pixels).  This prevents errors when the pages are
    later processed by libraries that use the default limit.

    The *loading* limit (MAX_IMAGE_PIXELS_SAFE = 500M) is set higher so that
    pdf2image / PIL can open the pages in the first place; this function then
    brings them back within the safe processing range.

    Args:
        pages: List of PIL Image objects.
        label: Log prefix for print messages (e.g. "PROCESS", "MERGE", "PDF").

    Returns:
        New list with oversized pages replaced by rescaled copies.
    """
    PIL_DEFAULT_LIMIT = 178956970  # PIL's built-in decompression-bomb threshold

    rescaled = []
    for i, page in enumerate(pages, 1):
        width, height = page.size
        pixels = width * height

        if pixels > PIL_DEFAULT_LIMIT:
            scale_factor = ((PIL_DEFAULT_LIMIT * 0.9) / pixels) ** 0.5
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)

            logger.warning("Page %d too large: %dx%d (%s pixels), rescaling to %dx%d",
                           i, width, height, f"{pixels:,}", new_width, new_height)

            rescaled_page = page.resize((new_width, new_height), Image.Resampling.LANCZOS)
            rescaled.append(rescaled_page)
        else:
            rescaled.append(page)

    return rescaled