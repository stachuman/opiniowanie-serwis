#!/usr/bin/env python3
"""
Comprehensive Image Diagnostic Tool for OCR Memory Issues
=========================================================

This script analyzes image files to identify potential causes of CUDA OOM errors.
It examines image properties, memory requirements, and provides optimization suggestions.

Usage:
    python image_diagnostic.py <image_path>
    python image_diagnostic.py --analyze-all  # Analyze all large JPGs in files/
    python image_diagnostic.py --test-memory <image_path>  # Test memory usage during processing
"""

import os
import sys
import argparse
import gc
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import tempfile

# PIL imports
from PIL import Image, ExifTags, ImageStat
from PIL.ExifTags import TAGS

# Memory analysis
import psutil
import numpy as np

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Try to import torch for GPU memory analysis
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("⚠️ PyTorch not available - GPU memory analysis disabled")

# Try to import our OCR modules
try:
    from tasks.ocr.config import MAX_IMAGE_DIMENSION, MIN_IMAGE_DIMENSION
    from tasks.ocr.preprocessors import preprocess_image
    from tasks.ocr.utils import aggressive_memory_cleanup, get_available_gpu_memory
    OCR_MODULES_AVAILABLE = True
except ImportError as e:
    OCR_MODULES_AVAILABLE = False
    print(f"⚠️ OCR modules not available: {e}")
    MAX_IMAGE_DIMENSION = 1536
    MIN_IMAGE_DIMENSION = 1000


class ImageDiagnostic:
    """Comprehensive image analysis for OCR memory optimization."""
    
    def __init__(self):
        self.results = {}
        
    def analyze_image(self, image_path: str) -> Dict:
        """Perform comprehensive analysis of an image file."""
        print(f"\n🔍 Analyzing image: {image_path}")
        
        if not Path(image_path).exists():
            return {"error": f"File not found: {image_path}"}
            
        try:
            # Basic file info
            file_info = self._get_file_info(image_path)
            
            # Open image for analysis
            with Image.open(image_path) as img:
                # Basic image properties
                basic_props = self._get_basic_properties(img)
                
                # EXIF data analysis
                exif_info = self._analyze_exif_data(img)
                
                # Color profile analysis
                color_info = self._analyze_color_profile(img)
                
                # Memory requirements
                memory_analysis = self._analyze_memory_requirements(img)
                
                # Compression analysis
                compression_info = self._analyze_compression(img, image_path)
                
                # OCR preprocessing simulation
                preprocessing_info = self._simulate_preprocessing(img)
                
            # GPU memory analysis
            gpu_info = self._analyze_gpu_memory()
            
            # Recommendations
            recommendations = self._generate_recommendations(
                file_info, basic_props, memory_analysis, gpu_info
            )
            
            return {
                "file_info": file_info,
                "basic_properties": basic_props,
                "exif_data": exif_info,
                "color_profile": color_info,
                "memory_analysis": memory_analysis,
                "compression_info": compression_info,
                "preprocessing_info": preprocessing_info,
                "gpu_info": gpu_info,
                "recommendations": recommendations
            }
            
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}
    
    def _get_file_info(self, image_path: str) -> Dict:
        """Get basic file system information."""
        path = Path(image_path)
        stat = path.stat()
        
        return {
            "path": str(path),
            "size_bytes": stat.st_size,
            "size_mb": stat.st_size / (1024 * 1024),
            "size_human": self._format_bytes(stat.st_size),
            "modified": stat.st_mtime
        }
    
    def _get_basic_properties(self, img: Image.Image) -> Dict:
        """Extract basic image properties."""
        return {
            "format": img.format,
            "mode": img.mode,
            "size": img.size,
            "width": img.width,
            "height": img.height,
            "has_transparency": img.mode in ('RGBA', 'LA') or 'transparency' in img.info,
            "is_animated": getattr(img, 'is_animated', False),
            "n_frames": getattr(img, 'n_frames', 1)
        }
    
    def _analyze_exif_data(self, img: Image.Image) -> Dict:
        """Analyze EXIF data for potential issues."""
        exif_info = {
            "has_exif": False,
            "orientation": None,
            "camera_info": {},
            "gps_info": {},
            "problematic_tags": [],
            "large_tags": []
        }
        
        try:
            exif = img.getexif()
            if exif:
                exif_info["has_exif"] = True
                
                # Check for orientation
                if 274 in exif:  # Orientation tag
                    exif_info["orientation"] = exif[274]
                
                # Analyze all EXIF tags
                for tag_id, value in exif.items():
                    try:
                        tag_name = TAGS.get(tag_id, tag_id)
                        
                        # Check for large values that might cause memory issues
                        if isinstance(value, (bytes, str)) and len(str(value)) > 1000:
                            exif_info["large_tags"].append({
                                "tag": tag_name,
                                "size": len(str(value))
                            })
                        
                        # Check for camera info
                        if tag_name in ['Make', 'Model', 'Software']:
                            exif_info["camera_info"][tag_name] = str(value)
                            
                    except Exception as e:
                        exif_info["problematic_tags"].append({
                            "tag_id": tag_id,
                            "error": str(e)
                        })
                        
        except Exception as e:
            exif_info["exif_error"] = str(e)
            
        return exif_info
    
    def _analyze_color_profile(self, img: Image.Image) -> Dict:
        """Analyze color profile and bit depth."""
        color_info = {
            "mode": img.mode,
            "bands": len(img.getbands()) if hasattr(img, 'getbands') else 0,
            "has_icc_profile": 'icc_profile' in img.info,
            "palette_size": None,
            "bit_depth": None
        }
        
        # Check for palette
        if hasattr(img, 'palette') and img.palette:
            color_info["palette_size"] = len(img.palette.getdata()[1])
        
        # Estimate bit depth
        if img.mode == 'L':
            color_info["bit_depth"] = 8
        elif img.mode == 'RGB':
            color_info["bit_depth"] = 24
        elif img.mode == 'RGBA':
            color_info["bit_depth"] = 32
        elif img.mode == 'P':
            color_info["bit_depth"] = 8  # palette
        elif img.mode == 'CMYK':
            color_info["bit_depth"] = 32
            
        # ICC profile size
        if color_info["has_icc_profile"]:
            icc_data = img.info.get('icc_profile', b'')
            color_info["icc_profile_size"] = len(icc_data)
            
        return color_info
    
    def _analyze_memory_requirements(self, img: Image.Image) -> Dict:
        """Calculate memory requirements for different operations."""
        width, height = img.size
        pixels = width * height
        
        # Bytes per pixel for different modes
        bytes_per_pixel = {
            'L': 1, '1': 1, 'P': 1,
            'RGB': 3, 'RGBA': 4,
            'CMYK': 4, 'YCbCr': 3,
            'LAB': 3, 'HSV': 3
        }
        
        bpp = bytes_per_pixel.get(img.mode, 3)
        
        # Raw image memory
        raw_memory = pixels * bpp
        
        # PIL operations typically need 2-3x memory
        pil_memory = raw_memory * 2.5
        
        # Tensor memory (float32)
        tensor_memory_f32 = pixels * 4  # 4 bytes per float32
        tensor_memory_f16 = pixels * 2  # 2 bytes per float16
        
        # OCR preprocessing memory (considering potential upscaling)
        max_dim = max(width, height)
        scale_factor = MAX_IMAGE_DIMENSION / max_dim if max_dim > MAX_IMAGE_DIMENSION else 1.0
        if min(width, height) < MIN_IMAGE_DIMENSION:
            scale_factor = max(scale_factor, MIN_IMAGE_DIMENSION / min(width, height))
            
        scaled_pixels = int(pixels * (scale_factor ** 2))
        preprocessing_memory = scaled_pixels * 4 * 2.5  # RGB + overhead
        
        return {
            "dimensions": f"{width} x {height}",
            "total_pixels": pixels,
            "bytes_per_pixel": bpp,
            "raw_memory_bytes": raw_memory,
            "raw_memory_mb": raw_memory / (1024 * 1024),
            "pil_memory_mb": pil_memory / (1024 * 1024),
            "tensor_f32_mb": tensor_memory_f32 / (1024 * 1024),
            "tensor_f16_mb": tensor_memory_f16 / (1024 * 1024),
            "scale_factor": scale_factor,
            "scaled_pixels": scaled_pixels,
            "preprocessing_mb": preprocessing_memory / (1024 * 1024),
            "estimated_peak_gpu_mb": (preprocessing_memory + tensor_memory_f16 * 3) / (1024 * 1024)  # Model + input + output
        }
    
    def _analyze_compression(self, img: Image.Image, image_path: str) -> Dict:
        """Analyze image compression and artifacts."""
        compression_info = {
            "format": img.format,
            "quality_estimate": None,
            "compression_artifacts": False,
        }
        
        # JPEG quality estimation (approximate)
        if img.format == 'JPEG':
            try:
                # Try to get quality from PIL
                quality = img.info.get('quality', None)
                if quality:
                    compression_info["quality_estimate"] = quality
                    
                # Analyze compression artifacts using image statistics
                stat = ImageStat.Stat(img)
                # High variance in pixel values might indicate artifacts
                if hasattr(stat, 'var'):
                    variance = sum(stat.var) / len(stat.var)
                    compression_info["pixel_variance"] = variance
                    compression_info["compression_artifacts"] = variance > 10000  # Threshold
                    
            except Exception as e:
                compression_info["analysis_error"] = str(e)
                
        return compression_info
    
    def _simulate_preprocessing(self, img: Image.Image) -> Dict:
        """Simulate OCR preprocessing to predict issues."""
        preprocessing_info = {
            "original_size": img.size,
            "would_be_resized": False,
            "target_size": img.size,
            "memory_increase_factor": 1.0,
            "preprocessing_safe": True
        }
        
        width, height = img.size
        max_dim = max(width, height)
        min_dim = min(width, height)
        
        # Check if resizing would occur
        if max_dim > MAX_IMAGE_DIMENSION or min_dim < MIN_IMAGE_DIMENSION:
            preprocessing_info["would_be_resized"] = True
            
            # Calculate new dimensions
            if max_dim > MAX_IMAGE_DIMENSION:
                scale_factor = MAX_IMAGE_DIMENSION / max_dim
            else:
                scale_factor = MIN_IMAGE_DIMENSION / min_dim
                
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            preprocessing_info["target_size"] = (new_width, new_height)
            preprocessing_info["memory_increase_factor"] = scale_factor ** 2
            
        # Check if preprocessing is safe
        target_pixels = preprocessing_info["target_size"][0] * preprocessing_info["target_size"][1]
        estimated_memory_mb = target_pixels * 4 * 2.5 / (1024 * 1024)  # Conservative estimate
        
        preprocessing_info["estimated_memory_mb"] = estimated_memory_mb
        preprocessing_info["preprocessing_safe"] = estimated_memory_mb < 500  # 500MB threshold
        
        return preprocessing_info
    
    def _analyze_gpu_memory(self) -> Dict:
        """Analyze available GPU memory."""
        gpu_info = {"available": False}
        
        if TORCH_AVAILABLE and torch.cuda.is_available():
            try:
                device_count = torch.cuda.device_count()
                gpu_info["available"] = True
                gpu_info["device_count"] = device_count
                gpu_info["devices"] = []
                
                for i in range(device_count):
                    props = torch.cuda.get_device_properties(i)
                    free_mem, total_mem = torch.cuda.mem_get_info(i)
                    
                    device_info = {
                        "id": i,
                        "name": props.name,
                        "total_memory_gb": total_mem / (1024**3),
                        "free_memory_gb": free_mem / (1024**3),
                        "used_memory_gb": (total_mem - free_mem) / (1024**3),
                        "memory_utilization": (total_mem - free_mem) / total_mem * 100
                    }
                    gpu_info["devices"].append(device_info)
                    
            except Exception as e:
                gpu_info["error"] = str(e)
                
        # Also check system memory
        virtual_mem = psutil.virtual_memory()
        gpu_info["system_memory"] = {
            "total_gb": virtual_mem.total / (1024**3),
            "available_gb": virtual_mem.available / (1024**3),
            "used_percent": virtual_mem.percent
        }
        
        return gpu_info
    
    def _generate_recommendations(self, file_info: Dict, basic_props: Dict, 
                                memory_analysis: Dict, gpu_info: Dict) -> List[str]:
        """Generate optimization recommendations."""
        recommendations = []
        
        # File size recommendations
        if file_info["size_mb"] > 10:
            recommendations.append(f"⚠️ Large file size ({file_info['size_human']}) - consider pre-compression")
            
        # Dimension recommendations
        width, height = basic_props["size"]
        if width * height > 4000 * 4000:
            recommendations.append(f"⚠️ Very high resolution ({width}x{height}) - preprocessing will resize significantly")
            
        # Memory recommendations
        if memory_analysis["estimated_peak_gpu_mb"] > 8000:
            recommendations.append(f"🚨 High GPU memory requirement (~{memory_analysis['estimated_peak_gpu_mb']:.0f}MB) - likely to cause OOM")
        elif memory_analysis["estimated_peak_gpu_mb"] > 4000:
            recommendations.append(f"⚠️ Moderate GPU memory requirement (~{memory_analysis['estimated_peak_gpu_mb']:.0f}MB) - monitor usage")
            
        # Color mode recommendations
        if basic_props["mode"] not in ['RGB', 'L']:
            recommendations.append(f"⚠️ Unusual color mode ({basic_props['mode']}) - may cause conversion overhead")
            
        # GPU-specific recommendations
        if gpu_info["available"] and gpu_info["devices"]:
            for device in gpu_info["devices"]:
                if device["free_memory_gb"] < 2:
                    recommendations.append(f"🚨 Low GPU memory on device {device['id']} ({device['free_memory_gb']:.1f}GB free)")
                elif device["free_memory_gb"] < 4:
                    recommendations.append(f"⚠️ Limited GPU memory on device {device['id']} ({device['free_memory_gb']:.1f}GB free)")
                    
        # Optimization suggestions
        if memory_analysis["scale_factor"] > 1.5:
            recommendations.append("💡 Image will be significantly upscaled - consider using higher resolution source")
        elif memory_analysis["scale_factor"] < 0.5:
            recommendations.append("💡 Image will be significantly downscaled - consider pre-resizing")
            
        if not recommendations:
            recommendations.append("✅ Image appears to be suitable for OCR processing")
            
        return recommendations
    
    def test_memory_usage(self, image_path: str) -> Dict:
        """Test actual memory usage during image processing."""
        print(f"\n🧪 Testing memory usage for: {image_path}")
        
        if not OCR_MODULES_AVAILABLE:
            return {"error": "OCR modules not available for memory testing"}
            
        # Record initial memory state
        initial_gpu_mem = None
        if TORCH_AVAILABLE and torch.cuda.is_available():
            initial_gpu_mem = torch.cuda.memory_allocated()
            aggressive_memory_cleanup()
            
        initial_sys_mem = psutil.Process().memory_info().rss
        
        try:
            # Test preprocessing
            print("  📊 Testing preprocessing...")
            preprocessed_path = preprocess_image(image_path)
            
            # Check memory after preprocessing
            after_preprocess_gpu = None
            if TORCH_AVAILABLE and torch.cuda.is_available():
                after_preprocess_gpu = torch.cuda.memory_allocated()
                
            after_preprocess_sys = psutil.Process().memory_info().rss
            
            # Clean up
            if preprocessed_path != image_path:
                try:
                    Path(preprocessed_path).unlink()
                except:
                    pass
                    
            if TORCH_AVAILABLE and torch.cuda.is_available():
                aggressive_memory_cleanup()
                
            final_gpu_mem = None
            if TORCH_AVAILABLE and torch.cuda.is_available():
                final_gpu_mem = torch.cuda.memory_allocated()
                
            final_sys_mem = psutil.Process().memory_info().rss
            
            return {
                "success": True,
                "initial_gpu_mb": initial_gpu_mem / (1024*1024) if initial_gpu_mem else None,
                "after_preprocess_gpu_mb": after_preprocess_gpu / (1024*1024) if after_preprocess_gpu else None,
                "final_gpu_mb": final_gpu_mem / (1024*1024) if final_gpu_mem else None,
                "gpu_peak_usage_mb": (after_preprocess_gpu - initial_gpu_mem) / (1024*1024) if after_preprocess_gpu and initial_gpu_mem else None,
                "initial_sys_mb": initial_sys_mem / (1024*1024),
                "after_preprocess_sys_mb": after_preprocess_sys / (1024*1024),
                "final_sys_mb": final_sys_mem / (1024*1024),
                "sys_peak_usage_mb": (after_preprocess_sys - initial_sys_mem) / (1024*1024),
                "preprocessed_path": preprocessed_path
            }
            
        except Exception as e:
            return {"error": f"Memory test failed: {str(e)}"}
    
    def print_analysis(self, analysis: Dict):
        """Print analysis results in a formatted way."""
        if "error" in analysis:
            print(f"❌ Error: {analysis['error']}")
            return
            
        print("\n" + "="*80)
        print("IMAGE DIAGNOSTIC REPORT")
        print("="*80)
        
        # File info
        file_info = analysis["file_info"]
        print(f"\n📄 FILE INFORMATION:")
        print(f"  Path: {file_info['path']}")
        print(f"  Size: {file_info['size_human']} ({file_info['size_mb']:.2f} MB)")
        
        # Basic properties
        props = analysis["basic_properties"]
        print(f"\n🖼️ IMAGE PROPERTIES:")
        print(f"  Format: {props['format']}")
        print(f"  Mode: {props['mode']}")
        print(f"  Dimensions: {props['width']} x {props['height']} pixels")
        print(f"  Total pixels: {props['width'] * props['height']:,}")
        
        # Memory analysis
        mem = analysis["memory_analysis"]
        print(f"\n💾 MEMORY ANALYSIS:")
        print(f"  Raw image memory: {mem['raw_memory_mb']:.1f} MB")
        print(f"  PIL processing memory: {mem['pil_memory_mb']:.1f} MB")
        print(f"  Preprocessing memory: {mem['preprocessing_mb']:.1f} MB")
        print(f"  Estimated peak GPU usage: {mem['estimated_peak_gpu_mb']:.1f} MB")
        
        # GPU info
        gpu = analysis["gpu_info"]
        if gpu["available"]:
            print(f"\n🎮 GPU INFORMATION:")
            for device in gpu["devices"]:
                print(f"  Device {device['id']}: {device['name']}")
                print(f"    Total: {device['total_memory_gb']:.1f} GB")
                print(f"    Free: {device['free_memory_gb']:.1f} GB")
                print(f"    Used: {device['used_memory_gb']:.1f} GB ({device['memory_utilization']:.1f}%)")
        
        # EXIF data
        exif = analysis["exif_data"]
        if exif["has_exif"]:
            print(f"\n📷 EXIF DATA:")
            if exif["orientation"]:
                print(f"  Orientation: {exif['orientation']}")
            if exif["camera_info"]:
                for key, value in exif["camera_info"].items():
                    print(f"  {key}: {value}")
            if exif["large_tags"]:
                print(f"  Large EXIF tags: {len(exif['large_tags'])}")
                for tag in exif["large_tags"]:
                    print(f"    {tag['tag']}: {tag['size']} bytes")
                    
        # Preprocessing info
        preproc = analysis["preprocessing_info"]
        print(f"\n🔧 PREPROCESSING ANALYSIS:")
        print(f"  Will be resized: {preproc['would_be_resized']}")
        if preproc["would_be_resized"]:
            print(f"  Original size: {preproc['original_size']}")
            print(f"  Target size: {preproc['target_size']}")
            print(f"  Memory factor: {preproc['memory_increase_factor']:.2f}x")
        print(f"  Estimated memory: {preproc['estimated_memory_mb']:.1f} MB")
        print(f"  Preprocessing safe: {preproc['preprocessing_safe']}")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        for rec in analysis["recommendations"]:
            print(f"  {rec}")
            
        print("\n" + "="*80)
    
    def _format_bytes(self, bytes_val: int) -> str:
        """Format bytes in human readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"


def find_large_images(directory: str = "files", min_size_mb: float = 5.0) -> List[str]:
    """Find large image files in the specified directory."""
    files_dir = Path(directory)
    if not files_dir.exists():
        print(f"❌ Directory not found: {files_dir}")
        return []
        
    large_images = []
    min_size_bytes = min_size_mb * 1024 * 1024
    
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.tiff', '*.bmp']:
        for image_path in files_dir.glob(ext):
            if image_path.stat().st_size >= min_size_bytes:
                large_images.append(str(image_path))
                
    return sorted(large_images, key=lambda x: Path(x).stat().st_size, reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Image Diagnostic Tool for OCR Memory Issues")
    parser.add_argument("image_path", nargs="?", help="Path to image file to analyze")
    parser.add_argument("--analyze-all", action="store_true", help="Analyze all large images in files/")
    parser.add_argument("--test-memory", action="store_true", help="Test actual memory usage during processing")
    parser.add_argument("--min-size", type=float, default=5.0, help="Minimum size in MB for --analyze-all (default: 5.0)")
    parser.add_argument("--output", help="Save analysis to JSON file")
    
    args = parser.parse_args()
    
    diagnostic = ImageDiagnostic()
    
    if args.analyze_all:
        print("🔍 Finding large images...")
        large_images = find_large_images(min_size_mb=args.min_size)
        
        if not large_images:
            print(f"No images found larger than {args.min_size} MB")
            return
            
        print(f"Found {len(large_images)} large images:")
        for img_path in large_images:
            size_mb = Path(img_path).stat().st_size / (1024 * 1024)
            print(f"  {img_path} ({size_mb:.1f} MB)")
            
        for img_path in large_images:
            analysis = diagnostic.analyze_image(img_path)
            diagnostic.print_analysis(analysis)
            
            if args.test_memory:
                memory_test = diagnostic.test_memory_usage(img_path)
                print(f"\n🧪 MEMORY TEST RESULTS:")
                if "error" in memory_test:
                    print(f"  ❌ Error: {memory_test['error']}")
                else:
                    if memory_test["gpu_peak_usage_mb"]:
                        print(f"  GPU peak usage: {memory_test['gpu_peak_usage_mb']:.1f} MB")
                    print(f"  System peak usage: {memory_test['sys_peak_usage_mb']:.1f} MB")
                    
    elif args.image_path:
        analysis = diagnostic.analyze_image(args.image_path)
        diagnostic.print_analysis(analysis)
        
        if args.test_memory:
            memory_test = diagnostic.test_memory_usage(args.image_path)
            print(f"\n🧪 MEMORY TEST RESULTS:")
            if "error" in memory_test:
                print(f"  ❌ Error: {memory_test['error']}")
            else:
                if memory_test["gpu_peak_usage_mb"]:
                    print(f"  GPU peak usage: {memory_test['gpu_peak_usage_mb']:.1f} MB")
                print(f"  System peak usage: {memory_test['sys_peak_usage_mb']:.1f} MB")
                
        # Save to JSON if requested
        if args.output:
            import json
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2, default=str)
            print(f"\n💾 Analysis saved to: {args.output}")
            
    else:
        parser.print_help()


if __name__ == "__main__":
    main()