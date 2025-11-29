# tasks/image_pdf_converter.py
"""
Converts multiple images to a single multi-page PDF with EXIF rotation.
Used for iPhone mobile upload endpoint to combine photo sequences.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from fastapi import UploadFile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image_pdf_converter")

# Register HEIF/HEIC support for iPhone photos
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    logger.info("✓ HEIC/HEIF support registered (iPhone photos)")
except ImportError:
    logger.warning("⚠️  pillow-heif not installed - HEIC files will not be supported")
    logger.warning("   Install with: pip install pillow-heif")


@dataclass
class ConversionResult:
    """Result of image to PDF conversion."""
    success: bool
    pdf_path: Optional[Path] = None
    page_count: int = 0
    error_message: Optional[str] = None


class ImageToPDFConverter:
    """Converts multiple images to a single multi-page PDF."""

    # Configuration constants
    MAX_IMAGE_DIMENSION = 4096  # Prevent memory issues
    PDF_RESOLUTION_DPI = 100.0
    MAX_IMAGE_PIXELS = 178956970  # Prevent zip bombs

    def __init__(self):
        """Initialize converter with safety limits."""
        Image.MAX_IMAGE_PIXELS = self.MAX_IMAGE_PIXELS

    def _apply_exif_rotation(self, image: Image.Image) -> Image.Image:
        """
        Apply EXIF-based rotation to image.

        Uses ImageOps.exif_transpose() which handles all EXIF orientation tags.
        iPhone embeds EXIF Orientation tag in all photos.

        Args:
            image: PIL Image object

        Returns:
            Rotated image (or original if no EXIF or error)
        """
        try:
            rotated = ImageOps.exif_transpose(image)
            if rotated is not None:
                return rotated
            return image
        except Exception as e:
            logger.warning(f"EXIF rotation failed, using original orientation: {e}")
            return image

    def _prepare_image_for_pdf(self, image: Image.Image) -> Image.Image:
        """
        Prepare image for PDF conversion.

        Steps:
        1. Apply EXIF rotation
        2. Convert RGBA → RGB (PDF doesn't support transparency)
        3. Downscale if exceeds MAX_IMAGE_DIMENSION

        Args:
            image: PIL Image object

        Returns:
            Prepared image ready for PDF
        """
        # Step 1: Apply EXIF rotation
        image = self._apply_exif_rotation(image)

        # Step 2: Convert RGBA to RGB with white background
        if image.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            # Paste image on white background using alpha channel as mask
            if image.mode in ('RGBA', 'LA'):
                background.paste(image, mask=image.split()[-1])  # Use alpha channel
            else:
                background.paste(image)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # Step 3: Downscale if needed
        width, height = image.size
        if width > self.MAX_IMAGE_DIMENSION or height > self.MAX_IMAGE_DIMENSION:
            # Calculate new dimensions maintaining aspect ratio
            if width > height:
                new_width = self.MAX_IMAGE_DIMENSION
                new_height = int(height * (self.MAX_IMAGE_DIMENSION / width))
            else:
                new_height = self.MAX_IMAGE_DIMENSION
                new_width = int(width * (self.MAX_IMAGE_DIMENSION / height))

            logger.info(f"Downscaling image from {width}x{height} to {new_width}x{new_height}")
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return image

    def convert_images_to_pdf(
        self,
        image_paths: List[Path],
        output_path: Path
    ) -> ConversionResult:
        """
        Convert multiple images to a single multi-page PDF.

        Args:
            image_paths: List of paths to image files
            output_path: Path where PDF should be saved

        Returns:
            ConversionResult with success status and details
        """
        if not image_paths:
            return ConversionResult(
                success=False,
                error_message="No images provided for conversion"
            )

        try:
            processed_images = []

            # Process all images
            for idx, img_path in enumerate(image_paths):
                try:
                    logger.info(f"Processing image {idx + 1}/{len(image_paths)}: {img_path.name}")

                    # Open and prepare image
                    with Image.open(img_path) as img:
                        prepared = self._prepare_image_for_pdf(img.copy())
                        processed_images.append(prepared)

                except Exception as e:
                    logger.error(f"Failed to process image {img_path.name}: {e}")
                    return ConversionResult(
                        success=False,
                        error_message=f"Failed to process image '{img_path.name}': {str(e)}"
                    )

            if not processed_images:
                return ConversionResult(
                    success=False,
                    error_message="No images were successfully processed"
                )

            # Save as multi-page PDF
            logger.info(f"Creating PDF with {len(processed_images)} pages at {output_path}")

            first_image = processed_images[0]
            other_images = processed_images[1:] if len(processed_images) > 1 else []

            first_image.save(
                output_path,
                "PDF",
                resolution=self.PDF_RESOLUTION_DPI,
                save_all=True,
                append_images=other_images
            )

            logger.info(f"Successfully created PDF: {output_path}")

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                page_count=len(processed_images)
            )

        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            return ConversionResult(
                success=False,
                error_message=f"PDF conversion failed: {str(e)}"
            )

    async def convert_upload_files_to_pdf(
        self,
        files: List[UploadFile],
        output_path: Path
    ) -> ConversionResult:
        """
        Convert uploaded image files to a single multi-page PDF.

        Saves uploaded files to temporary directory, converts to PDF,
        then cleans up temporary files automatically.

        Args:
            files: List of FastAPI UploadFile objects
            output_path: Path where PDF should be saved

        Returns:
            ConversionResult with success status and details
        """
        logger.info(f"Converting {len(files)} images to multi-page PDF")

        # Use temporary directory for automatic cleanup
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            temp_image_paths = []

            try:
                # Save all uploaded files to temp directory
                for idx, file in enumerate(files):
                    # Generate safe temporary filename
                    suffix = Path(file.filename).suffix.lower()
                    temp_path = temp_dir_path / f"image_{idx:03d}{suffix}"

                    # Read and save file content
                    content = await file.read()
                    temp_path.write_bytes(content)
                    temp_image_paths.append(temp_path)

                # Convert images to PDF
                result = self.convert_images_to_pdf(temp_image_paths, output_path)

                if result.success:
                    logger.info(f"PDF created successfully: {result.page_count} pages")
                else:
                    logger.error(f"PDF conversion failed: {result.error_message}")

                # Temp files automatically cleaned up when context exits
                return result

            except Exception as e:
                logger.error(f"Failed to process uploaded files: {e}")
                return ConversionResult(
                    success=False,
                    error_message=f"Failed to process uploaded files: {str(e)}"
                )


# Create singleton instance
image_pdf_converter = ImageToPDFConverter()
