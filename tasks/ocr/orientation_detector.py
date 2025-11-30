"""
ML-based image orientation detection.

Uses pretrained EfficientNetV2 model to detect orientation (0°, 90°, 180°, 270°)
and correct image rotation. Replaces EXIF-based rotation.

Model: DuarteBarbosa/deep-image-orientation-detection (PyTorch .pth format)
Accuracy: 98.82% on validation set
Architecture: EfficientNetV2-S with 4-class classification head
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

try:
    import torchvision.models as models
except ImportError:
    print("⚠️  torchvision not available - orientation detection will not work")
    models = None

try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    print("⚠️  pynvml not available - will use simpler GPU selection")
    HAS_PYNVML = False

from .config import logger

# Orientation Detection Configuration
ORIENTATION_MODEL_URL = "https://huggingface.co/DuarteBarbosa/deep-image-orientation-detection/resolve/main/orientation_model_v2_0.9882.pth"
ORIENTATION_MODEL_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "orientation"
ORIENTATION_MODEL_PATH = ORIENTATION_MODEL_CACHE_DIR / "orientation_model_v2_0.9882.pth"

ORIENTATION_DETECTION_ENABLED = os.getenv("ORIENTATION_DETECTION_ENABLED", "true").lower() == "true"
ORIENTATION_GPU_MEM_THRESHOLD_GB = int(os.getenv("ORIENTATION_GPU_THRESHOLD_GB", "8"))
ORIENTATION_INFERENCE_TIMEOUT_SECONDS = int(os.getenv("ORIENTATION_TIMEOUT_SEC", "5"))
ORIENTATION_CONFIDENCE_THRESHOLD = float(os.getenv("ORIENTATION_MIN_CONFIDENCE", "0.7"))
ORIENTATION_INPUT_SIZE = 224  # EfficientNetV2 standard

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
        logger.info(f"✅ [ORIENTATION] Model found in cache: {ORIENTATION_MODEL_PATH}")
        return

    # Create cache directory
    ORIENTATION_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"📥 [ORIENTATION] Downloading model from {ORIENTATION_MODEL_URL}")
    print(f"📥 [ORIENTATION] Downloading model (81MB)... This may take a minute.")

    try:
        urllib.request.urlretrieve(ORIENTATION_MODEL_URL, ORIENTATION_MODEL_PATH)
        logger.info(f"✅ [ORIENTATION] Model downloaded to {ORIENTATION_MODEL_PATH}")
        print(f"✅ [ORIENTATION] Model downloaded successfully!")
    except Exception as e:
        logger.error(f"Failed to download orientation model: {e}")
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
            logger.info("🔍 [ORIENTATION] CUDA not available, will use CPU")
            return None

        if not HAS_PYNVML:
            # Fallback: use simple GPU 0 selection
            logger.info("🔍 [ORIENTATION] pynvml not available, using GPU 0 by default")
            return 0

        pynvml.nvmlInit()
        best_gpu = None
        best_free = 0.0
        best_perf = 0

        logger.info(f"🔍 [ORIENTATION] Looking for GPU with ≥{threshold_gb}GB free memory...")

        for i in range(torch.cuda.device_count()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)

            free, total = torch.cuda.mem_get_info(i)
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            used_gb = total_gb - free_gb

            print(f"🔍 [ORIENTATION] GPU {i}: {free_gb:.2f}GB free / {total_gb:.2f}GB total ({used_gb:.2f}GB used)")

            if free_gb >= threshold_gb:
                # Simple performance metric (can use same as OCR models if needed)
                performance = 1  # Placeholder

                print(f"✅ [ORIENTATION] GPU {i} meets threshold (≥{threshold_gb}GB)")

                if (free_gb > best_free) or (free_gb == best_free and performance > best_perf):
                    best_gpu = i
                    best_free = free_gb
                    best_perf = performance
                    print(f"🏆 [ORIENTATION] GPU {i} is new candidate ({best_free:.2f}GB)")
            else:
                print(f"❌ [ORIENTATION] GPU {i} below threshold ({free_gb:.2f}GB < {threshold_gb}GB)")

        pynvml.nvmlShutdown()

        if best_gpu is not None:
            logger.info(f"🎯 [ORIENTATION] Selected GPU {best_gpu} with {best_free:.2f}GB free memory")
            print(f"🎯 [ORIENTATION] Selected GPU {best_gpu} with {best_free:.2f}GB free memory")
        else:
            logger.info(f"⚠️ [ORIENTATION] No GPU with ≥{threshold_gb}GB free memory, will use CPU")
            print(f"⚠️ [ORIENTATION] No GPU with ≥{threshold_gb}GB free memory, will use CPU")

        return best_gpu
    except Exception as e:
        logger.error(f"Error in _pick_gpu_for_orientation: {e}")
        print(f"❌ [ORIENTATION] GPU selection error: {e}")
        return None  # Fallback to CPU


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

    print(f"🔄 [ORIENTATION] Loading orientation model in process PID={os.getpid()}")
    logger.info(f"🔄 [ORIENTATION] Loading orientation model in process PID={os.getpid()}")

    try:
        # Download model if needed
        _download_model_if_needed()

        # Determine device
        if force_cpu or not torch.cuda.is_available():
            device = "cpu"
            print(f"🔍 [ORIENTATION] Using CPU (forced: {force_cpu}, CUDA available: {torch.cuda.is_available()})")
        elif assigned_gpu is not None:
            device = f"cuda:{assigned_gpu}"
            print(f"🎯 [ORIENTATION] Using explicitly assigned GPU: {assigned_gpu}")
        else:
            # Auto-select GPU
            gpu_id = _pick_gpu_for_orientation(ORIENTATION_GPU_MEM_THRESHOLD_GB)
            if gpu_id is not None:
                device = f"cuda:{gpu_id}"
                print(f"🎯 [ORIENTATION] Auto-selected GPU: {gpu_id}")
            else:
                device = "cpu"
                print(f"🔍 [ORIENTATION] Falling back to CPU")

        logger.info(f"Loading orientation model on device: {device}")

        # Load EfficientNetV2-S architecture
        print(f"📥 [ORIENTATION] Creating EfficientNetV2-S architecture...")
        model = models.efficientnet_v2_s(weights=None)  # No pretrained weights, we load custom

        # Modify final classifier for 4 classes (0°, 90°, 180°, 270°)
        num_features = model.classifier[1].in_features
        model.classifier[1] = torch.nn.Linear(num_features, 4)

        # Load trained weights
        print(f"📥 [ORIENTATION] Loading trained weights from {ORIENTATION_MODEL_PATH}...")
        state_dict = torch.load(ORIENTATION_MODEL_PATH, map_location=device, weights_only=False)
        model.load_state_dict(state_dict)

        # Set to evaluation mode
        model.eval()

        # Move model to device
        if "cuda" in device:
            model = model.to(device)
            print(f"✅ [ORIENTATION] Model loaded on {device}")
        else:
            print(f"✅ [ORIENTATION] Model loaded on CPU")

        logger.info(f"Orientation model successfully loaded on {device}")

        return model, device

    except Exception as e:
        logger.error(f"Failed to load orientation model: {e}")
        print(f"❌ [ORIENTATION] Model loading failed: {e}")
        import traceback
        traceback.print_exc()
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
    # expand=True ensures no cropping
    # resample=Image.BICUBIC for high quality
    return image.rotate(-degrees, expand=True, resample=Image.BICUBIC)


def detect_and_correct_orientation(image: Image.Image, assigned_gpu: int = None) -> Image.Image:
    """
    Main API: Detect orientation and correct image rotation using ML model.

    IGNORES EXIF orientation data - always uses ML model.
    Detects 4 orientations: 0°, 90°, 180°, 270°

    Args:
        image: PIL Image to analyze
        assigned_gpu: Optional explicit GPU ID (for parallel workers)

    Returns:
        Correctly oriented PIL Image
    """
    # Check if feature is enabled
    if not ORIENTATION_DETECTION_ENABLED:
        logger.info("🔍 [ORIENTATION] Feature disabled via config, skipping")
        print("🔍 [ORIENTATION] Feature disabled via config, skipping")
        return image

    try:
        # Log input image info
        original_size = image.size
        original_mode = image.mode
        print(f"🔄 [ORIENTATION] Input: {original_size[0]}x{original_size[1]}, mode={original_mode}")

        # 1. Preprocess image
        tensor = _preprocess_for_orientation(image)
        print(f"🔄 [ORIENTATION] Preprocessed to tensor: {tuple(tensor.shape)}")

        # 2. Load model (cached)
        try:
            model, device = _load_orientation_model(assigned_gpu=assigned_gpu)
        except torch.cuda.OutOfMemoryError:
            # Retry on CPU if GPU OOM
            logger.warning("🔄 [ORIENTATION] CUDA OOM, falling back to CPU")
            print("⚠️  [ORIENTATION] CUDA OOM, retrying on CPU...")
            model, device = _load_orientation_model(assigned_gpu=None, force_cpu=True)

        # 3. Predict orientation
        rotation_degrees, confidence = _predict_orientation(tensor, model, device)

        print(f"🔄 [ORIENTATION] Predicted: {rotation_degrees}° (confidence: {confidence:.2%})")
        logger.info(f"Orientation detected: {rotation_degrees}° (confidence: {confidence:.2%})")

        # Log low confidence warning
        if confidence < ORIENTATION_CONFIDENCE_THRESHOLD:
            logger.warning(f"Low confidence ({confidence:.2%}) for orientation detection")
            print(f"⚠️  [ORIENTATION] Low confidence ({confidence:.2%}), but applying rotation anyway")

        # 4. Apply rotation
        if rotation_degrees == 0:
            print(f"✅ [ORIENTATION] No rotation needed")
            return image

        rotated = _apply_rotation(image, rotation_degrees)
        rotated_size = rotated.size
        print(f"✅ [ORIENTATION] Rotated {rotation_degrees}°: {rotated_size[0]}x{rotated_size[1]}")
        logger.info(f"Applied rotation: {rotation_degrees}°, new size: {rotated_size}")

        # 5. Cleanup
        del tensor
        gc.collect()
        if torch.cuda.is_available() and "cuda" in device:
            torch.cuda.empty_cache()

        return rotated

    except Exception as e:
        # Never crash - return original image on any error
        logger.error(f"ML orientation detection failed: {e}", exc_info=True)
        print(f"❌ [ORIENTATION] Detection failed: {e}")
        print(f"⚠️  [ORIENTATION] Returning original image (no rotation)")

        # Import traceback for debugging
        import traceback
        traceback.print_exc()

        return image


# Export public API
__all__ = ['detect_and_correct_orientation', 'ORIENTATION_DETECTION_ENABLED']
