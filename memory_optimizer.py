#!/usr/bin/env python3
"""
Memory Optimizer for OCR Image Processing
==========================================

This utility provides memory-optimized image processing functions that can help
prevent CUDA OOM errors by implementing smarter memory management strategies.

Features:
- Adaptive image resizing based on available GPU memory
- Progressive image loading and processing
- Memory-efficient preprocessing with fallback strategies
- GPU memory monitoring and cleanup
"""

import os
import sys
import gc
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import time

from PIL import Image, ImageOps
import numpy as np

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Try to import torch for GPU memory management
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Try to import our OCR modules
try:
    from tasks.ocr.config import MAX_IMAGE_DIMENSION, MIN_IMAGE_DIMENSION, logger
    from tasks.ocr.utils import aggressive_memory_cleanup, get_available_gpu_memory
    OCR_MODULES_AVAILABLE = True
except ImportError:
    OCR_MODULES_AVAILABLE = False
    MAX_IMAGE_DIMENSION = 1536
    MIN_IMAGE_DIMENSION = 1000
    

class MemoryOptimizer:
    """Memory-optimized image processing for OCR."""
    
    def __init__(self, gpu_memory_threshold_gb: float = 2.0):
        """
        Initialize memory optimizer.
        
        Args:
            gpu_memory_threshold_gb: Minimum free GPU memory required (GB)
        """
        self.gpu_memory_threshold = gpu_memory_threshold_gb * 1024 * 1024 * 1024  # Convert to bytes
        self.memory_history = []
        
    def get_optimal_dimensions(self, width: int, height: int, 
                             available_memory_gb: Optional[float] = None) -> Tuple[int, int]:
        """
        Calculate optimal image dimensions based on available memory.
        
        Args:
            width: Original image width
            height: Original image height
            available_memory_gb: Available GPU memory in GB
            
        Returns:
            Tuple of (optimal_width, optimal_height)
        """
        if available_memory_gb is None:
            available_memory_gb = self._get_available_gpu_memory_gb()
            
        # Conservative memory estimation
        # Assume we need ~50MB per megapixel for safe processing
        safe_megapixels = max(1.0, available_memory_gb * 20)  # Very conservative
        max_pixels = int(safe_megapixels * 1_000_000)
        
        current_pixels = width * height
        
        # If current image is within safe limits, use standard preprocessing
        if current_pixels <= max_pixels:
            return self._standard_resize(width, height)
            
        # Otherwise, calculate safe dimensions
        scale_factor = (max_pixels / current_pixels) ** 0.5
        
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)
        
        # Ensure minimum dimensions for OCR quality
        min_dimension = min(MIN_IMAGE_DIMENSION, 800)  # Reduce if necessary
        if min(new_width, new_height) < min_dimension:
            if new_width < new_height:
                scale_factor = min_dimension / new_width
            else:
                scale_factor = min_dimension / new_height
                
            new_width = int(new_width * scale_factor)
            new_height = int(new_height * scale_factor)
            
        return new_width, new_height
    
    def _standard_resize(self, width: int, height: int) -> Tuple[int, int]:
        """Apply standard preprocessing resize logic."""
        min_dimension = MIN_IMAGE_DIMENSION
        max_dimension = MAX_IMAGE_DIMENSION
        
        # Check if image is too small and needs upscaling
        if width < min_dimension or height < min_dimension:
            scale_factor = min_dimension / min(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            return new_width, new_height
            
        # Check if image is too large and needs downscaling
        elif width > max_dimension or height > max_dimension:
            scale_factor = max_dimension / max(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            return new_width, new_height
            
        return width, height
    
    def _get_available_gpu_memory_gb(self) -> float:
        """Get available GPU memory in GB."""
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return 1.0  # Conservative fallback
            
        try:
            free_mem, total_mem = torch.cuda.mem_get_info()
            return free_mem / (1024**3)
        except:
            return 1.0  # Conservative fallback
    
    def preprocess_image_safe(self, image_path: str, 
                            output_path: Optional[str] = None,
                            progressive: bool = True) -> str:
        """
        Safely preprocess image with memory optimization.
        
        Args:
            image_path: Path to input image
            output_path: Optional output path (temp file if None)
            progressive: Use progressive loading for large images
            
        Returns:
            Path to processed image
        """
        print(f"🔧 [OPTIMIZER] Processing: {image_path}")
        
        # Clean up memory before starting
        self._cleanup_memory()
        
        try:
            # Get image info without loading full image
            with Image.open(image_path) as img:
                original_size = img.size
                format_info = img.format
                mode_info = img.mode
                
            print(f"🔧 [OPTIMIZER] Original: {original_size[0]}x{original_size[1]} ({mode_info})")
            
            # Check available memory
            available_memory_gb = self._get_available_gpu_memory_gb()
            print(f"🔧 [OPTIMIZER] Available GPU memory: {available_memory_gb:.2f} GB")
            
            # Calculate optimal dimensions
            optimal_width, optimal_height = self.get_optimal_dimensions(
                original_size[0], original_size[1], available_memory_gb
            )
            
            print(f"🔧 [OPTIMIZER] Target: {optimal_width}x{optimal_height}")
            
            # Process image
            if progressive and self._should_use_progressive(original_size):
                processed_path = self._process_progressive(
                    image_path, (optimal_width, optimal_height), output_path
                )
            else:
                processed_path = self._process_standard(
                    image_path, (optimal_width, optimal_height), output_path
                )
                
            print(f"🔧 [OPTIMIZER] Processed: {processed_path}")
            return processed_path
            
        except Exception as e:
            print(f"❌ [OPTIMIZER] Error: {str(e)}")
            # Fallback to original path
            return image_path
    
    def _should_use_progressive(self, original_size: Tuple[int, int]) -> bool:
        """Determine if progressive loading should be used."""
        pixels = original_size[0] * original_size[1]
        return pixels > 10_000_000  # 10MP threshold
    
    def _process_progressive(self, image_path: str, target_size: Tuple[int, int],
                           output_path: Optional[str] = None) -> str:
        """Process large image progressively to save memory."""
        print(f"🔧 [OPTIMIZER] Using progressive processing")
        
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name
        
        try:
            # Open image with progressive loading
            with Image.open(image_path) as img:
                # Convert to RGB if necessary
                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize using high-quality algorithm
                img_resized = img.resize(target_size, Image.LANCZOS)
                
                # Save immediately to free memory
                img_resized.save(output_path, "PNG", optimize=True)
                
            # Clean up memory
            self._cleanup_memory()
            
            return output_path
            
        except Exception as e:
            print(f"❌ [OPTIMIZER] Progressive processing failed: {str(e)}")
            # Try fallback
            return self._process_fallback(image_path, target_size, output_path)
    
    def _process_standard(self, image_path: str, target_size: Tuple[int, int],
                         output_path: Optional[str] = None) -> str:
        """Process image using standard method."""
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name
        
        try:
            with Image.open(image_path) as img:
                # Convert to RGB if necessary
                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize if needed
                if img.size != target_size:
                    img = img.resize(target_size, Image.LANCZOS)
                
                # Save with optimization
                img.save(output_path, "PNG", optimize=True)
                
            return output_path
            
        except Exception as e:
            print(f"❌ [OPTIMIZER] Standard processing failed: {str(e)}")
            return self._process_fallback(image_path, target_size, output_path)
    
    def _process_fallback(self, image_path: str, target_size: Tuple[int, int],
                         output_path: Optional[str] = None) -> str:
        """Fallback processing with minimal memory usage."""
        print(f"🔧 [OPTIMIZER] Using fallback processing")
        
        if output_path is None:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                output_path = tmp.name
        
        try:
            # Use even smaller dimensions for fallback
            fallback_width = min(target_size[0], 1024)
            fallback_height = min(target_size[1], 1024)
            
            # Maintain aspect ratio
            original_ratio = target_size[0] / target_size[1]
            if fallback_width / fallback_height > original_ratio:
                fallback_width = int(fallback_height * original_ratio)
            else:
                fallback_height = int(fallback_width / original_ratio)
                
            with Image.open(image_path) as img:
                img = img.convert('RGB')
                img = img.resize((fallback_width, fallback_height), Image.LANCZOS)
                img.save(output_path, "PNG", quality=85)
                
            print(f"🔧 [OPTIMIZER] Fallback size: {fallback_width}x{fallback_height}")
            return output_path
            
        except Exception as e:
            print(f"❌ [OPTIMIZER] Fallback processing failed: {str(e)}")
            # Return original path as last resort
            return image_path
    
    def _cleanup_memory(self):
        """Clean up memory."""
        if OCR_MODULES_AVAILABLE:
            aggressive_memory_cleanup()
        elif TORCH_AVAILABLE and torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        gc.collect()
    
    def monitor_memory_usage(self, func, *args, **kwargs):
        """Monitor memory usage during function execution."""
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return func(*args, **kwargs)
        
        # Record initial state
        torch.cuda.synchronize()
        initial_memory = torch.cuda.memory_allocated()
        
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            
            # Record peak memory
            torch.cuda.synchronize()
            peak_memory = torch.cuda.max_memory_allocated()
            
            # Record final state
            final_memory = torch.cuda.memory_allocated()
            
            execution_time = time.time() - start_time
            
            # Log memory usage
            print(f"📊 [MEMORY] Initial: {initial_memory/1024/1024:.1f}MB")
            print(f"📊 [MEMORY] Peak: {peak_memory/1024/1024:.1f}MB")
            print(f"📊 [MEMORY] Final: {final_memory/1024/1024:.1f}MB")
            print(f"📊 [MEMORY] Used: {(peak_memory-initial_memory)/1024/1024:.1f}MB")
            print(f"📊 [MEMORY] Time: {execution_time:.2f}s")
            
            # Reset peak memory counter
            torch.cuda.reset_peak_memory_stats()
            
            return result
            
        except Exception as e:
            print(f"❌ [MEMORY] Function failed: {str(e)}")
            raise
    
    def create_memory_optimized_preprocessor(self):
        """Create a drop-in replacement for the standard preprocessor."""
        def optimized_preprocess_image(image_path: str) -> str:
            """Memory-optimized version of preprocess_image."""
            return self.preprocess_image_safe(image_path)
        
        return optimized_preprocess_image


def test_memory_optimization(image_path: str):
    """Test memory optimization on a specific image."""
    print(f"🧪 Testing memory optimization on: {image_path}")
    
    optimizer = MemoryOptimizer()
    
    # Test standard preprocessing
    print("\n--- Standard Preprocessing ---")
    if OCR_MODULES_AVAILABLE:
        from tasks.ocr.preprocessors import preprocess_image
        
        def test_standard():
            return preprocess_image(image_path)
        
        try:
            result_standard = optimizer.monitor_memory_usage(test_standard)
            print(f"✅ Standard result: {result_standard}")
        except Exception as e:
            print(f"❌ Standard preprocessing failed: {str(e)}")
            result_standard = None
    
    # Test optimized preprocessing
    print("\n--- Optimized Preprocessing ---")
    def test_optimized():
        return optimizer.preprocess_image_safe(image_path)
    
    try:
        result_optimized = optimizer.monitor_memory_usage(test_optimized)
        print(f"✅ Optimized result: {result_optimized}")
    except Exception as e:
        print(f"❌ Optimized preprocessing failed: {str(e)}")
        result_optimized = None
    
    # Compare file sizes
    if result_optimized and Path(result_optimized).exists():
        original_size = Path(image_path).stat().st_size
        optimized_size = Path(result_optimized).stat().st_size
        
        print(f"\n📊 File Size Comparison:")
        print(f"  Original: {original_size/1024/1024:.2f} MB")
        print(f"  Optimized: {optimized_size/1024/1024:.2f} MB")
        print(f"  Reduction: {(1-optimized_size/original_size)*100:.1f}%")
        
        # Clean up
        if result_optimized != image_path:
            try:
                Path(result_optimized).unlink()
            except:
                pass


def main():
    """Command line interface for memory optimizer."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Memory Optimizer for OCR Image Processing")
    parser.add_argument("image_path", help="Path to image file")
    parser.add_argument("--output", "-o", help="Output path for processed image")
    parser.add_argument("--test", action="store_true", help="Test memory optimization")
    parser.add_argument("--progressive", action="store_true", help="Force progressive processing")
    parser.add_argument("--memory-threshold", type=float, default=2.0, 
                       help="GPU memory threshold in GB (default: 2.0)")
    
    args = parser.parse_args()
    
    if not Path(args.image_path).exists():
        print(f"❌ Image file not found: {args.image_path}")
        return 1
    
    optimizer = MemoryOptimizer(args.memory_threshold)
    
    if args.test:
        test_memory_optimization(args.image_path)
    else:
        try:
            result = optimizer.preprocess_image_safe(
                args.image_path, 
                args.output,
                args.progressive
            )
            print(f"✅ Processed image saved to: {result}")
        except Exception as e:
            print(f"❌ Processing failed: {str(e)}")
            return 1
    
    return 0


if __name__ == "__main__":
    exit(main())