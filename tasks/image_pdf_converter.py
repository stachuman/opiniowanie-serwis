# tasks/image_pdf_converter.py
"""
Converts multiple images/videos to a single multi-page PDF (RAW - no correction).

Used for iPhone mobile upload endpoint to combine photo/video sequences.
Supports: .jpg, .jpeg, .png, .heic (images) and .mov, .mp4 (videos - extracts first frame)

WORKFLOW:
1. Images/videos → RAW PDF (NO orientation/deskew correction)
2. OCR Pipeline → 3-stage correction (PRE-DESKEW → ORIENTATION → POST-DESKEW)
3. OCR Pipeline → Save corrected PDF (can be sent to iPhone)
4. OCR Pipeline → Process corrected pages

This prevents double-processing and ensures correction happens once in the pipeline.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageOps
from fastapi import UploadFile
from tasks.ocr.utils import extract_frame_from_video, MAX_IMAGE_PIXELS_SAFE

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
    """Converts multiple images/videos to a single multi-page PDF (RAW - no correction).

    Creates RAW PDF without orientation or deskew correction.
    Correction is applied later in the OCR pipeline (3-stage process).

    Supports image formats: .jpg, .jpeg, .png, .heic
    Supports video formats: .mov, .mp4 (extracts first frame using ffmpeg)
    """

    # Configuration constants
    MAX_IMAGE_DIMENSION = 4096  # Prevent memory issues
    PDF_RESOLUTION_DPI = 100.0

    def __init__(self):
        """Initialize converter with safety limits."""
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS_SAFE

    def _apply_ml_orientation_correction(self, image: Image.Image) -> Image.Image:
        """
        NO-OP: Orientation correction removed from PDF creation step.

        Workflow change: PDFs are created WITHOUT orientation/deskew correction.
        Correction happens later in the OCR pipeline (3-stage process).

        This prevents double-processing and ensures correction happens in one place:
        1. iPhone → Raw PDF (no correction)
        2. Pipeline → Apply 3-stage correction (PRE-DESKEW → ORIENTATION → POST-DESKEW)
        3. OCR → Process corrected pages

        Args:
            image: PIL Image object

        Returns:
            Original image (unchanged)
        """
        # RULES.md Rule #1: Keep it simple - correction happens in pipeline, not here
        logger.info("Skipping orientation correction during PDF creation (handled in OCR pipeline)")
        return image

    def _prepare_image_for_pdf(self, image: Image.Image) -> Image.Image:
        """
        Prepare image for PDF conversion (RAW - no correction).

        Steps:
        1. SKIP orientation correction (handled in OCR pipeline)
        2. Convert RGBA → RGB (PDF doesn't support transparency)
        3. Downscale if exceeds MAX_IMAGE_DIMENSION

        Args:
            image: PIL Image object

        Returns:
            Prepared image ready for PDF
        """
        # Step 1: SKIP ML orientation correction (happens in OCR pipeline)
        # No correction applied here - PDF is created as-is
        # image = self._apply_ml_orientation_correction(image)  # REMOVED

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
        Convert multiple images/videos to a single multi-page PDF.

        For video files (.mov, .mp4), extracts first frame using ffmpeg.

        Args:
            image_paths: List of paths to image or video files
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
            extracted_frames = []  # Track extracted frames for cleanup

            # Process all images/videos
            for idx, img_path in enumerate(image_paths):
                try:
                    logger.info(f"Processing file {idx + 1}/{len(image_paths)}: {img_path.name}")

                    # Check if file is a video (MOV/MP4)
                    file_ext = img_path.suffix.lower()
                    if file_ext in {'.mov', '.mp4'}:
                        # Extract first frame from video
                        logger.info(f"  → Video file detected, extracting first frame...")
                        frame_path = extract_frame_from_video(img_path)
                        extracted_frames.append(frame_path)  # Track for cleanup
                        img_path = frame_path  # Use extracted frame

                    # Open and prepare image
                    with Image.open(img_path) as img:
                        prepared = self._prepare_image_for_pdf(img.copy())
                        processed_images.append(prepared)

                except Exception as e:
                    logger.error(f"Failed to process file {img_path.name}: {e}")
                    # Clean up extracted frames on error
                    for frame in extracted_frames:
                        frame.unlink(missing_ok=True)
                    return ConversionResult(
                        success=False,
                        error_message=f"Failed to process file '{img_path.name}': {str(e)}"
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

            # Clean up extracted video frames
            for frame in extracted_frames:
                frame.unlink(missing_ok=True)
                logger.info(f"  → Cleaned up extracted frame: {frame.name}")

            return ConversionResult(
                success=True,
                pdf_path=output_path,
                page_count=len(processed_images)
            )

        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            # Clean up extracted frames on error
            for frame in extracted_frames:
                frame.unlink(missing_ok=True)
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
