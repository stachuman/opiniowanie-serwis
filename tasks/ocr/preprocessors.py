"""
Przetwarzanie wstępne dokumentów przed OCR.
Tryby:
- auto  : próba wykrycia zdjęcia dokumentu i użycie profilu 'photo', inaczej 'scan'
- photo : pipeline bez operacji morfologicznych wzmacniających; korekcja perspektywy
- scan  : pipeline dla płaskich skanów; black-hat ODEJMOWANY
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Tuple

import numpy as np
import cv2 as cv
from PIL import (
    Image,
    ImageOps,
    ImageFile,
)

# Umożliwia wczytywanie częściowo uszkodzonych/progresywnych JPEG
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Apply shared PIL pixel limit from utils (must happen before any Image.open)
from .utils import MAX_IMAGE_PIXELS_SAFE, rescale_oversized_pages
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_SAFE

from .config import logger, DPI, MAX_IMAGE_DIMENSION, MIN_IMAGE_DIMENSION

# =========================
# Ustawienia modułu
# =========================
DEFAULT_BINARIZE = False
DEFAULT_MODE = "auto"  # "auto" | "photo" | "scan"

# Minimalny akceptowalny dłuższy bok dla czytelnego tekstu (rekomendacja, nie wymuszamy)
RECOMMENDED_MIN_LONG_EDGE = 2200


# =============================================================================
# Pomocnicze: EXIF, skalowanie, porządkowanie punktów
# =============================================================================
def _exif_transpose_strip(image: Image.Image) -> Image.Image:
    """Zastosuj rotację wg EXIF i usuń EXIF z obiektu (kopiując same piksele)."""
    img = ImageOps.exif_transpose(image)
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))
    return clean


def _safe_downscale(image: Image.Image, target_long_edge: int | None) -> Image.Image:
    """Skaluje obraz w dół (bez upscalingu) tak, aby dłuższy bok nie przekraczał target_long_edge."""
    if not target_long_edge or not isinstance(target_long_edge, int):
        return image
    w, h = image.size
    long_edge = max(w, h)
    if long_edge <= target_long_edge:
        return image
    scale = target_long_edge / float(long_edge)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    return image.resize((new_w, new_h), Image.LANCZOS)


def _ensure_reasonable_dimensions(image: Image.Image) -> None:
    """Loguje ostrzeżenie, jeśli rozmiar obrazu jest niewielki jak na OCR."""
    w, h = image.size
    long_edge = max(w, h)
    if long_edge < RECOMMENDED_MIN_LONG_EDGE:
        logger.debug(
            "Long edge only %dpx (recommended %dpx for small fonts)",
            long_edge, RECOMMENDED_MIN_LONG_EDGE,
        )


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """Uporządkuj 4 punkty (tl, tr, br, bl)."""
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


# =============================================================================
# Detekcja dokumentu i korekcja perspektywy (dla zdjęć)
# =============================================================================
def detect_document_and_warp(bgr: np.ndarray) -> Tuple[np.ndarray, bool]:
    """
    Wyszukuje największy 4-punktowy kontur i wykonuje warp perspektywiczny.
    Zwraca (warped_bgr, True) w razie powodzenia; w przeciwnym razie (oryginał, False).
    """
    h, w = bgr.shape[:2]
    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    gray_blur = cv.GaussianBlur(gray, (5, 5), 0)

    edges = cv.Canny(gray_blur, 60, 180)
    k = cv.getStructuringElement(cv.MORPH_RECT, (5, 5))
    edges = cv.morphologyEx(edges, cv.MORPH_CLOSE, k, iterations=1)

    cnts, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return bgr, False

    cnts = sorted(cnts, key=cv.contourArea, reverse=True)
    img_area = float(h * w)

    for c in cnts[:5]:
        area = cv.contourArea(c)
        if area < 0.15 * img_area:  # ignoruj zbyt małe kontury
            continue

        peri = cv.arcLength(c, True)
        approx = cv.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) != 4:
            continue

        pts = approx.reshape(4, 2).astype(np.float32)
        src = _order_quad(pts)

        widthA = np.linalg.norm(src[2] - src[3])
        widthB = np.linalg.norm(src[1] - src[0])
        maxW = int(max(widthA, widthB))

        heightA = np.linalg.norm(src[1] - src[2])
        heightB = np.linalg.norm(src[0] - src[3])
        maxH = int(max(heightA, heightB))

        if maxW < 400 or maxH < 400:  # zbyt małe – raczej nie strona
            continue

        dst = np.array(
            [[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]], dtype=np.float32
        )
        M = cv.getPerspectiveTransform(src, dst)
        warped = cv.warpPerspective(bgr, M, (maxW, maxH), flags=cv.INTER_CUBIC)
        return warped, True

    return bgr, False


# =============================================================================
# Pipeline 'photo' (zdjęcia dokumentów)
# =============================================================================
def _pipeline_photo(bgr: np.ndarray, binarize: bool) -> np.ndarray:
    """Łagodny pipeline dla zdjęć: warp (jeśli możliwy), delikatna normalizacja, CLAHE, bilateral, warunkowe unsharp."""
    # Próba korekcji perspektywy
    rect, ok = detect_document_and_warp(bgr)
    if ok:
        bgr = rect

    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    # Normalizacja oświetlenia (łagodnie)
    sigma = max(7, int(0.03 * max(h, w)))  # ~3% dłuższego boku
    bg = cv.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)
    norm = cv.divide(gray, bg + 1, scale=128, dtype=cv.CV_8U)

    # Lokalny kontrast
    clahe = cv.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(norm)

    # Łagodne odszumianie krawędziowo-zachowawcze
    den = cv.bilateralFilter(cl, d=0, sigmaColor=10, sigmaSpace=3)

    # Warunkowe wyostrzenie (unikaj przeostrzenia)
    lap_var = cv.Laplacian(den, cv.CV_64F).var()
    if lap_var < 500:
        blur = cv.GaussianBlur(den, (0, 0), 0.8)
        den = cv.addWeighted(den, 1.4, blur, -0.4, 0)

    if binarize:
        if hasattr(cv, "ximgproc") and hasattr(cv.ximgproc, "niBlackThreshold"):
            out = cv.ximgproc.niBlackThreshold(den, 255, cv.THRESH_BINARY, blockSize=31, k=-0.2)
        else:
            out = cv.adaptiveThreshold(
                den, 255, cv.ADAPTIVE_THRESH_GAUSSIAN_C, cv.THRESH_BINARY, 31, 10
            )
        return out

    return den


# =============================================================================
# Pipeline 'scan' (płaskie skany)
# =============================================================================
def _pipeline_scan(bgr: np.ndarray, binarize: bool) -> np.ndarray:
    """Pipeline dla skanów: normalizacja, CLAHE, black-hat ODEJMOWANY, łagodny bilateral, stabilna polaryzacja."""
    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    # Normalizacja oświetlenia
    sigma = max(5, int(0.02 * max(h, w)))  # ~2% dłuższego boku
    bg = cv.GaussianBlur(gray, (0, 0), sigmaX=sigma, sigmaY=sigma)
    norm = cv.divide(gray, bg + 1, scale=128, dtype=cv.CV_8U)

    # Lokalny kontrast
    clahe = cv.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(norm)

    # Wzmocnienie pociągnięć – black-hat ODEJMOWANY
    ksz = max(3, int(round(0.005 * max(h, w))) | 1)  # ~0.5% dłuższego boku, nieparzysty
    k = cv.getStructuringElement(cv.MORPH_RECT, (ksz, ksz))
    bh = cv.morphologyEx(cl, cv.MORPH_BLACKHAT, k)
    cl2 = cv.subtract(cl, cv.convertScaleAbs(bh, alpha=0.7))

    # Łagodny bilateral
    den = cv.bilateralFilter(cl2, d=0, sigmaColor=12, sigmaSpace=3)

    # Stabilna polaryzacja (wybór wersji z jaśniejszym tłem)
    _, b_norm = cv.threshold(den, 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
    _, b_inv = cv.threshold(den, 0, 255, cv.THRESH_BINARY_INV + cv.THRESH_OTSU)
    choose_inv = (b_norm.mean() < b_inv.mean())

    oriented_gray = cv.bitwise_not(den) if choose_inv else den

    if binarize:
        out = b_inv if choose_inv else b_norm
        return out

    # Subtelny unsharp gdy warto
    lap = cv.Laplacian(oriented_gray, cv.CV_64F).var()
    std = oriented_gray.std()
    if lap > 50 and std < 70:
        blur = cv.GaussianBlur(oriented_gray, (0, 0), 0.8)
        oriented_gray = cv.addWeighted(oriented_gray, 1.6, blur, -0.6, 0)

    return oriented_gray


# =============================================================================
# Funkcja wysokiego poziomu: auto/photo/scan
# =============================================================================
def enhance_text_visibility(
    pil_img: Image.Image, binarize: bool = DEFAULT_BINARIZE, mode: str = DEFAULT_MODE
) -> Image.Image:
    """
    Poprawa widoczności tekstu. Zwraca obraz 8-bit (L).
    - mode="auto"  : spróbuje 'photo', jeśli wykryto stronę lub nierównomierne oświetlenie; inaczej 'scan'
    - mode="photo" : pipeline dla zdjęć
    - mode="scan"  : pipeline dla skanów
    """
    try:
        bgr = cv.cvtColor(np.array(pil_img.convert("RGB")), cv.COLOR_RGB2BGR)

        chosen = mode
        if mode == "auto":
            # Szybka próba: jeśli uda się perspektywa -> treat as photo
            _, ok = detect_document_and_warp(bgr)
            if ok:
                chosen = "photo"
            else:
                # Heurystyka: duży gradient oświetlenia => zdjęcie
                gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
                h, w = gray.shape[:2]
                big_sigma = max(9, int(0.05 * max(h, w)))  # 5% rozmiaru
                bg = cv.GaussianBlur(gray, (0, 0), sigmaX=big_sigma, sigmaY=big_sigma)
                illum_var_ratio = float(bg.std()) / (float(gray.std()) + 1e-6)
                chosen = "photo" if illum_var_ratio > 0.7 else "scan"

        if chosen == "photo":
            out = _pipeline_photo(bgr, binarize=binarize)
        elif chosen == "scan":
            out = _pipeline_scan(bgr, binarize=binarize)
        else:
            out = _pipeline_scan(bgr, binarize=binarize)  # bezpieczny fallback

        return Image.fromarray(out, mode="L")

    except Exception as e:
        try:
            logger.warning(f"enhance_text_visibility: błąd '{e}', zwracam oryginalny obraz (L).")
        except Exception:
            pass
        return pil_img.convert("L")


# =============================================================================
# API modułu
# =============================================================================
def preprocess_image(
    image_path: str | Path,
    skip_exif_rotation: bool = False,
    binarize: bool = DEFAULT_BINARIZE,
    mode: str = DEFAULT_MODE,
) -> str:
    """
    Przetwarza obraz do OCR.

    Args:
        image_path: ścieżka do obrazu wejściowego
        skip_exif_rotation: pomiń obrót wg EXIF
        binarize: True -> binarka; False -> skala szarości
        mode: "auto" | "photo" | "scan"

    Returns:
        ścieżka do przetworzonego pliku PNG (tymczasowego)
    """
    try:
        image_path = str(image_path)
        image = Image.open(image_path)
        original_size = image.size
        logger.debug("Preprocess %s size=%dx%d", image_path, original_size[0], original_size[1])

        # EXIF (rotacja + strip)
        if not skip_exif_rotation:
            try:
                image = _exif_transpose_strip(image)
                logger.debug("EXIF transpose applied")
            except Exception as e:
                logger.warning("EXIF transpose failed: %s", e)
        else:
            logger.debug("EXIF transpose skipped")

        # RGB dla spójności
        if image.mode == "RGBA":
            bg = Image.new("RGB", image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[3])
            image = bg
            logger.debug("RGBA -> RGB (white background)")
        elif image.mode != "RGB":
            image = image.convert("RGB")
            logger.debug("Converted to RGB")

        # Skalowanie w dół (bez upscalingu)
        before = image.size
        image = _safe_downscale(image, MAX_IMAGE_DIMENSION if isinstance(MAX_IMAGE_DIMENSION, int) else None)
        after = image.size
        if before != after:
            logger.debug("Scaled %s -> %s", before, after)
        else:
            logger.debug("Size unchanged: %s", after)

        _ensure_reasonable_dimensions(image)

        # Poprawa widoczności
        processed = image
        #processed = enhance_text_visibility(image, binarize=binarize, mode="scan")

        # Zapis do pliku tymczasowego
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            tmp_path = tmp_img.name

        final_size = processed.size
        processed.save(tmp_path, "PNG", optimize=True)
        logger.debug("Preprocessed: %s -> %s", final_size, tmp_path)

        return tmp_path

    except Exception as e:
        logger.error(f"[PREPROCESS] Błąd '{image_path}': {e}")
        # Fallback – zwróć oryginał
        return str(image_path)


def extract_pages_from_pdf(pdf_path: str | Path, max_batch_size: int = 5) -> List[List[str]]:
    """
    Konwertuje PDF na listy obrazów stron (PNG), pogrupowane w partie.
    """
    try:
        from pdf2image import convert_from_path

        pages = convert_from_path(str(pdf_path), dpi=DPI)
        total_pages = len(pages)
        logger.debug("PDF pages: %d (DPI=%d)", total_pages, DPI)

        # Safety check: rescale oversized pages to prevent decompression bomb errors
        pages = rescale_oversized_pages(pages, "PDF")

        batches: List[List[str]] = []
        for i in range(0, total_pages, max_batch_size):
            batch_pages = pages[i : i + max_batch_size]
            batch_paths: List[str] = []
            for j, img in enumerate(batch_pages):
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_path = tmp_img.name
                img.save(tmp_path, "PNG", optimize=True)
                batch_paths.append(tmp_path)
            batches.append(batch_paths)

        return batches

    except Exception as e:
        logger.error(f"[PDF] Błąd konwersji '{pdf_path}': {e}")
        return []


def preprocess_image_fragment(
    image: Image.Image,
    min_dimension: int = 300,
    binarize: bool = DEFAULT_BINARIZE,
    mode: str = DEFAULT_MODE,
) -> Image.Image:
    """
    Przetwarza fragment obrazu (np. wykadrowany region).
    - umiarkowany upscaling do min_dimension krótszego boku
    - ograniczenie dłuższego boku do ~połowy MAX_IMAGE_DIMENSION
    - ten sam pipeline co dla pełnych stron
    """
    try:
        # RGB dla spójności
        if image.mode == "RGBA":
            bg = Image.new("RGB", image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[3])
            image = bg
        elif image.mode != "RGB":
            image = image.convert("RGB")

        w, h = image.size
        # Upscale, jeśli bardzo mały fragment
        if min(w, h) < min_dimension:
            scale = float(min_dimension) / float(min(w, h))
            new_w, new_h = int(round(w * scale)), int(round(h * scale))
            image = image.resize((new_w, new_h), Image.BICUBIC)
            logger.info(f"[FRAGMENT] Upscale {w}x{h} -> {new_w}x{new_h}")

        # Downscale, jeśli zbyt duży fragment
        max_frag = (MAX_IMAGE_DIMENSION // 2) if isinstance(MAX_IMAGE_DIMENSION, int) else None
        if max_frag:
            w, h = image.size
            if max(w, h) > max_frag:
                scale = float(max_frag) / float(max(w, h))
                new_w, new_h = int(round(w * scale)), int(round(h * scale))
                image = image.resize((new_w, new_h), Image.LANCZOS)
                logger.info(f"[FRAGMENT] Downscale -> {new_w}x{new_h}")

        processed = enhance_text_visibility(image, binarize=binarize, mode=mode)
        return processed

    except Exception as e:
        logger.error(f"[FRAGMENT] Błąd przetwarzania fragmentu: {e}")
        try:
            return image.convert("L")
        except Exception:
            return image

