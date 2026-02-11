"""
ML-based image orientation detection with multi-region ensemble voting.

Uses pretrained EfficientNetV2 model to detect orientation (0°, 90°, 180°, 270°)
and correct image rotation. Replaces EXIF-based rotation.

Model: DuarteBarbosa/deep-image-orientation-detection (PyTorch .pth format)
Base Accuracy: 98.82% on validation set
Architecture: EfficientNetV2-S with 4-class classification head

Enhancement: 9-region grid ensemble voting with safety margins
- Analyzes 3x3 grid with 5% margin on all sides (avoids background noise)
- Majority vote determines final orientation (5+ out of 9 needed)
- Maximum robustness for complex, ambiguous, or partially rotated documents
- Safety margins prevent interference from: iPhone photo backgrounds, scanner edges, shadows
- Covers all important document areas: corners, edges, and center
"""

from __future__ import annotations

import gc
import os
import torch
from functools import lru_cache
from typing import Tuple, Any
from PIL import Image
from torchvision import transforms
from pathlib import Path
import urllib.request

# Apply shared PIL pixel limit from utils
from .utils import MAX_IMAGE_PIXELS_SAFE
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_SAFE

try:
    import torchvision.models as models
except ImportError:
    models = None

try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

from .config import logger, DESKEW_MAX_ANGLE

# Orientation Detection Configuration
ORIENTATION_MODEL_URL = "https://huggingface.co/DuarteBarbosa/deep-image-orientation-detection/resolve/main/orientation_model_v2_0.9882.pth"
ORIENTATION_MODEL_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "orientation"
ORIENTATION_MODEL_PATH = ORIENTATION_MODEL_CACHE_DIR / "orientation_model_v2_0.9882.pth"

ORIENTATION_DETECTION_ENABLED = os.getenv("ORIENTATION_DETECTION_ENABLED", "true").lower() == "true"
ORIENTATION_GPU_MEM_THRESHOLD_GB = int(os.getenv("ORIENTATION_GPU_THRESHOLD_GB", "8"))
ORIENTATION_INFERENCE_TIMEOUT_SECONDS = int(os.getenv("ORIENTATION_TIMEOUT_SEC", "5"))
ORIENTATION_CONFIDENCE_THRESHOLD = float(os.getenv("ORIENTATION_MIN_CONFIDENCE", "0.7"))
ORIENTATION_INPUT_SIZE = 224  # EfficientNetV2 standard
ORIENTATION_GRID_MARGIN = 0.05  # 5% margin on each side to avoid background noise

# Region weights for weighted voting (9 regions in grid order)
# Center regions are more reliable than edges/corners
REGION_WEIGHTS = [
    1.0,  # top_left (corner)
    1.5,  # top_center (center column)
    1.0,  # top_right (corner)
    1.5,  # mid_left (center row)
    2.0,  # mid_center (MOST IMPORTANT)
    1.5,  # mid_right (center row)
    1.0,  # bot_left (corner)
    1.5,  # bot_center (center column)
    1.0,  # bot_right (corner)
]

# Deskewing configuration
DESKEW_ENABLED = os.getenv("DESKEW_ENABLED", "true").lower() == "true"
# DESKEW_MAX_ANGLE is imported from config.py - do not redefine here

# Class mapping: model output → rotation degrees
ORIENTATION_CLASS_TO_DEGREES = {
    0: 0,    # No rotation needed
    1: 90,   # Rotate 90° clockwise
    2: 180,  # Rotate 180°
    3: 270   # Rotate 270° clockwise (90° counter-clockwise)
}


def _download_model_if_needed():
    """Download orientation model from HuggingFace if not cached."""
    if ORIENTATION_MODEL_PATH.exists():
        logger.debug("Orientation model found in cache: %s", ORIENTATION_MODEL_PATH)
        return

    ORIENTATION_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Downloading orientation model (81MB)...")

    try:
        urllib.request.urlretrieve(ORIENTATION_MODEL_URL, ORIENTATION_MODEL_PATH)
        logger.info("Orientation model downloaded to %s", ORIENTATION_MODEL_PATH)
    except Exception as e:
        logger.error("Failed to download orientation model: %s", e)
        raise RuntimeError(f"Could not download orientation model: {e}")


def _pick_gpu_for_orientation(threshold_gb: int = 8) -> int | None:
    """
    Select GPU with at least threshold_gb free memory for orientation detection.

    Uses same logic as OCR models but with lower threshold (8GB vs 22GB).

    Args:
        threshold_gb: Minimum free GPU memory in GB

    Returns:
        GPU ID (int) or None if no suitable GPU found (fallback to CPU)
    """
    try:
        if not torch.cuda.is_available():
            logger.debug("CUDA not available, will use CPU for orientation")
            return None

        if not HAS_PYNVML:
            logger.debug("pynvml not available, using GPU 0 for orientation")
            return 0

        pynvml.nvmlInit()
        best_gpu = None
        best_free = 0.0
        best_perf = 0

        for i in range(torch.cuda.device_count()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            free, total = torch.cuda.mem_get_info(i)
            free_gb = free / (1024 ** 3)

            logger.debug("GPU %d: %.2fGB free", i, free_gb)

            if free_gb >= threshold_gb:
                performance = 1
                if (free_gb > best_free) or (free_gb == best_free and performance > best_perf):
                    best_gpu = i
                    best_free = free_gb
                    best_perf = performance

        pynvml.nvmlShutdown()

        if best_gpu is not None:
            logger.debug("Orientation model -> GPU %d (%.2fGB free)", best_gpu, best_free)
        else:
            logger.debug("No GPU with >=%dGB free, orientation model will use CPU", threshold_gb)

        return best_gpu
    except Exception as e:
        logger.error("GPU selection for orientation failed: %s", e)
        return None


@lru_cache(maxsize=2)
def _load_orientation_model(assigned_gpu: int = None, force_cpu: bool = False) -> Tuple[Any, str]:
    """
    Load orientation detection model (cached per process).

    Args:
        assigned_gpu: Explicit GPU ID (for parallel workers) or None (auto-select)
        force_cpu: Force CPU inference (fallback mode)

    Returns:
        Tuple of (model, device)
    """
    if models is None:
        raise ImportError("torchvision not available - cannot load orientation model")

    try:
        _download_model_if_needed()

        if force_cpu or not torch.cuda.is_available():
            device = "cpu"
        elif assigned_gpu is not None:
            device = f"cuda:{assigned_gpu}"
        else:
            gpu_id = _pick_gpu_for_orientation(ORIENTATION_GPU_MEM_THRESHOLD_GB)
            device = f"cuda:{gpu_id}" if gpu_id is not None else "cpu"

        logger.debug("Loading orientation model on %s (PID=%d)", device, os.getpid())

        model = models.efficientnet_v2_s(weights=None)
        num_features = model.classifier[1].in_features
        model.classifier[1] = torch.nn.Linear(num_features, 4)

        state_dict = torch.load(ORIENTATION_MODEL_PATH, map_location=device, weights_only=False)
        model.load_state_dict(state_dict)
        model.eval()

        if "cuda" in device:
            model = model.to(device)

        logger.info("Orientation model loaded on %s", device)
        return model, device

    except Exception as e:
        logger.error("Failed to load orientation model: %s", e, exc_info=True)
        raise


def _preprocess_for_orientation(image: Image.Image) -> torch.Tensor:
    """
    Preprocess image for orientation detection model.

    Steps:
    1. Convert to RGB (handle RGBA, grayscale, etc.)
    2. Resize to 224x224 (EfficientNetV2 input size)
    3. Normalize to ImageNet statistics
    4. Convert to tensor

    Args:
        image: PIL Image (any size, any mode)

    Returns:
        Preprocessed tensor ready for model input
    """
    # 1. RGB conversion
    if image.mode != 'RGB':
        image = image.convert('RGB')

    # 2. Standard ImageNet preprocessing for EfficientNetV2
    preprocess = transforms.Compose([
        transforms.Resize(256),  # Resize shorter edge to 256
        transforms.CenterCrop(224),  # Crop center 224x224
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],  # ImageNet mean
            std=[0.229, 0.224, 0.225]     # ImageNet std
        )
    ])

    tensor = preprocess(image)
    return tensor.unsqueeze(0)  # Add batch dimension [1, 3, 224, 224]


def _predict_orientation(tensor: torch.Tensor, model, device: str) -> Tuple[int, float]:
    """
    Run model inference to predict orientation.

    Args:
        tensor: Preprocessed image tensor
        model: Loaded orientation detection model
        device: Device string ("cpu" or "cuda:N")

    Returns:
        Tuple of (rotation_degrees, confidence)
    """
    with torch.no_grad():
        # Move tensor to same device as model
        tensor = tensor.to(device)

        # Run inference
        output = model(tensor)

        # Get probabilities
        probs = torch.softmax(output, dim=1)
        confidence, predicted_class = torch.max(probs, 1)

    # Map class to rotation degrees
    rotation_degrees = ORIENTATION_CLASS_TO_DEGREES[predicted_class.item()]
    confidence_value = confidence.item()

    return rotation_degrees, confidence_value


def _extract_region(image: Image.Image, region: str) -> Image.Image:
    """
    Extract a specific region from the image for orientation analysis.

    Uses 9-region grid with safety margins to avoid background noise.

    IMPORTANT: Adds 5% margin on all sides to avoid:
    - Background papers/objects in iPhone photos
    - Scanner bed edges and artifacts
    - Shadows and lighting issues
    - Document holders or other background elements

    Args:
        image: PIL Image
        region: One of "top_left", "top_center", "top_right",
                       "mid_left", "mid_center", "mid_right",
                       "bot_left", "bot_center", "bot_right"

    Returns:
        Cropped region as PIL Image
    """
    width, height = image.size

    # Add safety margin on all sides to avoid background noise
    # This avoids background noise in iPhone photos of documents
    margin_x = int(width * ORIENTATION_GRID_MARGIN)
    margin_y = int(height * ORIENTATION_GRID_MARGIN)

    # Calculate inner working area (excludes margin on all sides)
    inner_left = margin_x
    inner_right = width - margin_x
    inner_top = margin_y
    inner_bottom = height - margin_y

    inner_width = inner_right - inner_left
    inner_height = inner_bottom - inner_top

    # Define 3x3 grid boundaries within the inner area
    col_third = inner_width // 3
    row_third = inner_height // 3

    # Grid positions (row, col) -> (top, bottom, left, right)
    # All coordinates are relative to inner_left/inner_top
    grid = {
        # Top row
        "top_left":    (inner_top,                  inner_top + row_third,     inner_left,                    inner_left + col_third),
        "top_center":  (inner_top,                  inner_top + row_third,     inner_left + col_third,        inner_left + 2*col_third),
        "top_right":   (inner_top,                  inner_top + row_third,     inner_left + 2*col_third,      inner_right),
        # Middle row
        "mid_left":    (inner_top + row_third,      inner_top + 2*row_third,   inner_left,                    inner_left + col_third),
        "mid_center":  (inner_top + row_third,      inner_top + 2*row_third,   inner_left + col_third,        inner_left + 2*col_third),
        "mid_right":   (inner_top + row_third,      inner_top + 2*row_third,   inner_left + 2*col_third,      inner_right),
        # Bottom row
        "bot_left":    (inner_top + 2*row_third,    inner_bottom,              inner_left,                    inner_left + col_third),
        "bot_center":  (inner_top + 2*row_third,    inner_bottom,              inner_left + col_third,        inner_left + 2*col_third),
        "bot_right":   (inner_top + 2*row_third,    inner_bottom,              inner_left + 2*col_third,      inner_right),
    }

    if region not in grid:
        raise ValueError(f"Unknown region: {region}. Must be one of {list(grid.keys())}")

    top, bottom, left, right = grid[region]
    return image.crop((left, top, right, bottom))


def _is_region_empty(region_image: Image.Image, threshold: float = 0.95) -> bool:
    """
    Check if a region is mostly empty (blank/white) and should be skipped.

    Args:
        region_image: PIL Image of the region
        threshold: Fraction of pixels that must be near-white to consider empty (0.95 = 95%)

    Returns:
        True if region is empty/blank, False if it contains content
    """
    import numpy as np

    # Convert to grayscale and numpy array
    gray = np.array(region_image.convert('L'))

    # Count pixels that are very bright (>240 out of 255 = near white)
    bright_pixels = np.sum(gray > 240)
    total_pixels = gray.size

    # If >95% of pixels are near-white, consider it empty
    bright_ratio = bright_pixels / total_pixels
    return bright_ratio > threshold


def _preprocess_region_for_orientation(image: Image.Image, region: str) -> torch.Tensor:
    """
    Extract region and preprocess for orientation detection.

    Args:
        image: PIL Image (full image)
        region: Region to extract ("center", "top", "bottom")

    Returns:
        Preprocessed tensor ready for model input
    """
    # Extract the region
    region_image = _extract_region(image, region)

    # RGB conversion
    if region_image.mode != 'RGB':
        region_image = region_image.convert('RGB')

    # Standard ImageNet preprocessing for EfficientNetV2
    preprocess = transforms.Compose([
        transforms.Resize(256),  # Resize shorter edge to 256
        transforms.CenterCrop(224),  # Crop center 224x224
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],  # ImageNet mean
            std=[0.229, 0.224, 0.225]     # ImageNet std
        )
    ])

    tensor = preprocess(region_image)
    return tensor.unsqueeze(0)  # Add batch dimension [1, 3, 224, 224]


def _ensemble_vote_orientation(predictions: list) -> Tuple[int, float]:
    """
    Ensemble voting for orientation prediction from multiple regions.

    Uses weighted voting where center regions count more than edge/corner regions:
    - mid_center: 2 votes (most reliable, pure document content)
    - mid_left, mid_center, mid_right: 1.5 votes (reliable, central row)
    - top_center, bot_center: 1.5 votes (reliable, central column)
    - corners: 1 vote (less reliable, may have borders/shadows)

    Args:
        predictions: List of (rotation_degrees, confidence) tuples from each region
                    Order: [top_left, top_center, top_right, mid_left, mid_center,
                           mid_right, bot_left, bot_center, bot_right]

    Returns:
        Tuple of (final_rotation_degrees, average_confidence)
    """
    from collections import defaultdict

    # Weighted voting (skip None predictions from empty regions)
    weighted_votes = defaultdict(float)
    rotation_confidences = defaultdict(list)  # Track confidences per rotation

    for prediction, weight in zip(predictions, REGION_WEIGHTS):
        if prediction is None:  # Skip empty regions
            continue
        rotation, confidence = prediction
        weighted_votes[rotation] += weight
        rotation_confidences[rotation].append(confidence)

    # Ensure we have at least some predictions
    if not weighted_votes:
        # All regions were empty - fallback to 0° (no rotation)
        return 0, 0.0

    # Find max weighted vote count
    max_votes = max(weighted_votes.values())

    # Get all rotations with max votes (handles ties)
    tied_rotations = [rot for rot, votes in weighted_votes.items() if votes == max_votes]

    # If there's a tie, use average confidence as tiebreaker
    if len(tied_rotations) > 1:
        # Calculate average confidence for each tied rotation
        avg_confidences = {
            rot: sum(rotation_confidences[rot]) / len(rotation_confidences[rot])
            for rot in tied_rotations
        }
        # Choose rotation with highest average confidence
        winning_rotation = max(avg_confidences, key=avg_confidences.get)
    else:
        winning_rotation = tied_rotations[0]

    # Calculate average confidence from predictions that voted for winner
    avg_confidence = sum(rotation_confidences[winning_rotation]) / len(rotation_confidences[winning_rotation])

    return winning_rotation, avg_confidence


def _apply_rotation(image: Image.Image, degrees: int) -> Image.Image:
    """
    Apply rotation to image.

    Args:
        image: PIL Image
        degrees: Rotation degrees (0, 90, 180, 270)

    Returns:
        Rotated image
    """
    if degrees == 0:
        return image

    # PIL rotate is counter-clockwise, so negate
    # For 180°: expand doesn't matter (dimensions stay same), but using expand=True
    #           causes PIL to unnecessarily double the canvas size (bug)
    # For 90°/270°: expand=True is needed to swap width/height properly
    expand = (degrees == 90 or degrees == 270)

    # resample=Image.BICUBIC for high quality
    return image.rotate(-degrees, expand=expand, resample=Image.BICUBIC)


def _detect_and_correct_skew(image: Image.Image, max_angle: float = None) -> Tuple[Image.Image, float]:
    """
    Detect and correct small skew angles using Hough line detection.

    DOTS-friendly: Only corrects minor skews (±5°) that harm text line detection.
    Does NOT use binarization or morphological ops that would harm DOTS.

    Args:
        image: PIL Image to deskew
        max_angle: Maximum angle to correct (degrees). Default: from DESKEW_MAX_ANGLE config

    Returns:
        Tuple of (deskewed_image, angle_corrected):
            - deskewed_image: Image with skew corrected
            - angle_corrected: Angle that was corrected in degrees (0.0 if no correction)
    """
    # Use config value if not explicitly provided
    if max_angle is None:
        max_angle = DESKEW_MAX_ANGLE

    try:
        import cv2 as cv
        import numpy as np

        # Convert to grayscale for edge detection
        arr = np.array(image.convert('L'))

        # Edge detection using Canny
        # RULES.md: Keep it simple - use standard parameters
        edges = cv.Canny(arr, 50, 150, apertureSize=3)

        # Probabilistic Hough Line Transform - returns line segments with endpoints
        # This allows filtering by line length to detect only long text lines (not noise/edges)
        # Parameters:
        # - threshold: Higher value = only strong, clear lines (reduced false positives)
        # - minLineLength: Minimum line length in pixels (10% of image width = text lines)
        # - maxLineGap: Maximum gap between line segments to treat as single line

        height, width = arr.shape
        min_line_length = int(width * 0.10)  # At least 10% of page width = real text line
        max_line_gap = int(width * 0.02)     # Allow 2% gap to join broken text lines

        # Use higher threshold (100 instead of 50) to detect only strong, clear lines
        lines = cv.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi/180,
            threshold=100,
            minLineLength=min_line_length,
            maxLineGap=max_line_gap
        )

        if lines is None or len(lines) == 0:
            logger.debug("Deskew: no lines detected (min_length=%dpx)", min_line_length)
            return image, 0.0

        logger.debug("Deskew: %d line segments detected", len(lines))

        # Calculate angles for NEARLY HORIZONTAL lines only (text lines)
        # HoughLinesP returns [[x1, y1, x2, y2]] format
        # Calculate angle from endpoints: arctan2(dy, dx)
        angles = []
        line_lengths = []  # Track line lengths for diagnostics
        theta_values = []  # Track raw theta for diagnostics

        for line in lines:
            x1, y1, x2, y2 = line[0]

            # Calculate line length and angle
            length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            line_lengths.append(length)

            # Calculate angle in degrees (-90° to +90°)
            # 0° = horizontal, ±90° = vertical
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))

            # Normalize to 0-180° range for consistency with old code
            if angle < 0:
                theta_deg = 180 + angle  # -90 to 0 → 90 to 180
            else:
                theta_deg = angle  # 0 to 90 stays same

            theta_values.append(theta_deg)

            # Only consider nearly-horizontal lines (within ±25° of horizontal)
            # Wider range (±25° instead of ±15°) to catch real-world photo skew
            # Real iPhone photos have 1-5° natural skew that needs wider tolerance
            if theta_deg < 25 or theta_deg > 155:
                # Calculate skew angle relative to horizontal
                # theta near 0° → positive skew, theta near 180° → negative skew
                if theta_deg < 90:
                    skew_angle = theta_deg  # 0-25° range
                else:
                    skew_angle = theta_deg - 180  # 155-180° → -25 to 0° range

                angles.append(skew_angle)

        if line_lengths:
            logger.debug("Deskew line stats: avg=%.0fpx, max=%.0fpx, kept %d/%d horizontal",
                         np.mean(line_lengths), max(line_lengths), len(angles), len(theta_values))

        # RULES.md: Validate explicitly (Rule #3)
        if not angles:
            logger.debug("Deskew: no nearly-horizontal lines found")
            return image, 0.0

        median_angle = float(np.median(angles))
        std_angle = float(np.std(angles))

        logger.debug("Deskew: %d horizontal lines, median=%.2f°, std=%.2f°",
                      len(angles), median_angle, std_angle)

        # Only apply correction if skew is within correctable range
        if abs(median_angle) > max_angle:
            logger.debug("Deskew: %.2f° exceeds max ±%.0f°, skipping", median_angle, max_angle)
            return image, 0.0

        # Only rotate if skew > 0.3° (avoid unnecessary transformations)
        if abs(median_angle) > 0.3:
            # Rotate image to correct skew
            # arctan2(y2-y1, x2-x1) gives line slope in image coordinates (Y increases downward)
            # If median_angle is NEGATIVE (-4°): lines slope upward-right → text tilted counter-clockwise → need clockwise rotation
            # If median_angle is POSITIVE (+4°): lines slope downward-right → text tilted clockwise → need counter-clockwise rotation
            # PIL.Image.rotate() expects: positive = counter-clockwise, negative = clockwise
            # So we rotate by the SAME sign as detected angle (do NOT negate)
            correction_angle = median_angle

            width_before, height_before = image.size
            pixels_before = width_before * height_before
            logger.debug("Deskew: %.2f° detected, correcting", median_angle)

            # For small angle corrections, DON'T expand canvas (minimal edge cropping is acceptable)
            # This prevents image size from growing with each correction
            # expand=False means the output image keeps the same dimensions as input
            deskewed = image.rotate(
                correction_angle,
                expand=False,
                fillcolor='white',
                resample=Image.BICUBIC
            )

            width_after, height_after = deskewed.size
            pixels_after = width_after * height_after

            if pixels_after > pixels_before * 1.1:
                logger.warning("Deskew caused size growth: %d -> %d pixels, skipping", pixels_before, pixels_after)
                return image, 0.0

            return deskewed, median_angle
        else:
            logger.debug("Deskew: %.2f° below 0.3° threshold, skipping", median_angle)
            return image, 0.0

    except Exception as e:
        logger.warning("Deskew detection failed: %s", e)
        return image, 0.0


def _get_content_crop(image: Image.Image, crop_factor: float = 0.85) -> Image.Image:
    """
    Return center crop to avoid analyzing border areas.

    For images with rotation borders (common in iPhone photos rotated before upload),
    focuses analysis on actual content rather than empty border regions.

    Args:
        image: PIL Image to crop
        crop_factor: Fraction of image to keep (0.85 = keep 85%, skip 7.5% on each side)

    Returns:
        Center-cropped PIL Image for analysis only (original used for actual rotation)
    """
    width, height = image.size

    left = int(width * (1 - crop_factor) / 2)
    top = int(height * (1 - crop_factor) / 2)
    right = int(width * (1 + crop_factor) / 2)
    bottom = int(height * (1 + crop_factor) / 2)

    return image.crop((left, top, right, bottom))


def detect_and_correct_orientation(image: Image.Image, assigned_gpu: int = None, enable_deskew: bool = True) -> Tuple[Image.Image, int, float]:
    """
    Main API: Detect orientation and correct image rotation using 3-stage process.

    3-STAGE CORRECTION PROCESS:
    1. PRE-DESKEW: Fix large angles first (handles 45° rotated pages)
    2. ORIENTATION: Detect correct orientation (0°/90°/180°/270°) on straightened image
    3. POST-DESKEW: Final skew correction after rotation

    This approach handles arbitrarily rotated iPhone photos where the page is tilted
    at non-standard angles (e.g., 45°) that confuse the orientation model.

    IGNORES EXIF orientation data - always uses ML model.
    Uses 9-region grid ensemble voting for maximum accuracy:
    - Analyzes 3x3 grid covering entire page (9 independent samples)
    - Weighted voting (center=2.0x, edges=1.5x, corners=1.0x)
    - Confidence-based tiebreaker for tied votes
    - Extremely robust against local variations, ambiguous content, and edge cases
    - Covers all important areas: corners, edges, and center

    Args:
        image: PIL Image to analyze
        assigned_gpu: Optional explicit GPU ID (for parallel workers)
        enable_deskew: Whether to apply deskewing (default: True)

    Returns:
        Tuple of (corrected_image, rotation_degrees, total_skew_angle):
            - corrected_image: Correctly oriented and deskewed PIL Image
            - rotation_degrees: Rotation applied in degrees (0, 90, 180, or 270)
            - total_skew_angle: Total deskew correction (pre + post) in degrees
    """
    if not ORIENTATION_DETECTION_ENABLED:
        logger.debug("Orientation detection disabled via config")
        return image, 0, 0.0

    try:
        original_size = image.size
        pixels = original_size[0] * original_size[1]

        # Rescale oversized images
        MAX_IMAGE_PIXELS = 178956970
        if pixels > MAX_IMAGE_PIXELS:
            scale_factor = ((MAX_IMAGE_PIXELS * 0.9) / pixels) ** 0.5
            new_width = int(original_size[0] * scale_factor)
            new_height = int(original_size[1] * scale_factor)
            logger.warning("Image too large (%s pixels), rescaling to %dx%d", f"{pixels:,}", new_width, new_height)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 1. Pre-deskew
        pre_skew_angle = 0.0
        if DESKEW_ENABLED and enable_deskew:
            pre_deskewed_image, pre_skew_angle = _detect_and_correct_skew(image, max_angle=DESKEW_MAX_ANGLE)
            if pre_skew_angle != 0.0:
                logger.debug("Pre-deskew: %.2f°", pre_skew_angle)
                image = pre_deskewed_image

        # 2. Load model (cached)
        try:
            model, device = _load_orientation_model(assigned_gpu=assigned_gpu)
        except torch.cuda.OutOfMemoryError:
            logger.warning("Orientation CUDA OOM, falling back to CPU")
            model, device = _load_orientation_model(assigned_gpu=None, force_cpu=True)

        # 3. Center crop for analysis
        analysis_image = _get_content_crop(image, crop_factor=0.85)

        # 4. Multi-region ensemble prediction (9-region grid)
        regions = [
            "top_left", "top_center", "top_right",
            "mid_left", "mid_center", "mid_right",
            "bot_left", "bot_center", "bot_right"
        ]
        predictions = []

        for region in regions:
            region_image = _extract_region(analysis_image, region)

            if _is_region_empty(region_image):
                predictions.append(None)
                continue

            region_tensor = _preprocess_region_for_orientation(analysis_image, region)
            region_rotation, region_confidence = _predict_orientation(region_tensor, model, device)
            predictions.append((region_rotation, region_confidence))
            del region_tensor

        # 5. Ensemble voting
        rotation_degrees, confidence = _ensemble_vote_orientation(predictions)

        # Log voting details at DEBUG
        votes = [pred[0] if pred is not None else 'X' for pred in predictions]
        logger.debug("Orientation votes: %s -> %d° (conf %.1f%%)",
                      votes, rotation_degrees, confidence * 100)

        if confidence < ORIENTATION_CONFIDENCE_THRESHOLD:
            logger.warning("Low orientation confidence (%.1f%%)", confidence * 100)

        # 6. Apply rotation
        if rotation_degrees == 0:
            corrected_image = image
        else:
            corrected_image = _apply_rotation(image, rotation_degrees)

        # 7. Post-deskew
        post_skew_angle = 0.0
        if DESKEW_ENABLED and enable_deskew:
            post_deskewed_image, post_skew_angle = _detect_and_correct_skew(corrected_image, max_angle=DESKEW_MAX_ANGLE)
            if post_skew_angle != 0.0:
                logger.debug("Post-deskew: %.2f°", post_skew_angle)
                corrected_image = post_deskewed_image

        skew_angle = pre_skew_angle + post_skew_angle

        # 8. Cleanup
        del predictions
        gc.collect()
        if torch.cuda.is_available() and "cuda" in device:
            torch.cuda.empty_cache()

        # One-line INFO summary (only if something changed)
        if rotation_degrees != 0 or skew_angle != 0.0:
            parts = []
            if rotation_degrees != 0:
                parts.append(f"rotation={rotation_degrees}")
            if skew_angle != 0.0:
                parts.append(f"skew={skew_angle:.1f}")
            logger.info("Orientation: %s (conf %.0f%%)", ", ".join(parts), confidence * 100)

        return corrected_image, rotation_degrees, skew_angle

    except Exception as e:
        logger.error("Orientation detection failed: %s", e, exc_info=True)
        return image, 0, 0.0


# Export public API
__all__ = ['detect_and_correct_orientation', 'ORIENTATION_DETECTION_ENABLED']
