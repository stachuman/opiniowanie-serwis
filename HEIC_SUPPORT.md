# HEIC Support for iPhone Photos

## Summary

✅ **HEIC format is now fully supported** for iPhone photo uploads!

## What Changed

### 1. Added Dependency
- **Package:** `pillow-heif`
- **Purpose:** Enables Pillow to read HEIC/HEIF image files (iPhone's native photo format)
- **Location:** Added to `environment.yml`

### 2. Automatic Registration
- HEIF support is automatically registered when the image converter module loads
- File: `tasks/image_pdf_converter.py`
- Graceful fallback if package not installed (warning logged)

### 3. Installation

**For new environments:**
```bash
conda env create -f environment.yml
```

**For existing environments:**
```bash
pip install pillow-heif
```

## Supported Formats

After installation, the following image formats are supported:
- ✅ **JPEG** (.jpg, .jpeg)
- ✅ **PNG** (.png)
- ✅ **HEIC** (.heic) - iPhone native format
- ✅ **HEIF** (.heif) - HEIC variant

## How It Works

1. **iPhone takes photos** in HEIC format (default)
2. **Shortcuts encodes** HEIC to Base64
3. **Server receives** Base64 data
4. **pillow-heif decodes** HEIC to RGB
5. **Converter processes** like any other image:
   - Applies EXIF rotation
   - Converts to RGB (if needed)
   - Downscales if >4096px
   - Combines into multi-page PDF

## Verification

Check if HEIC support is active:

```python
from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()

# Check registered formats
supported = Image.registered_extensions()
print('.heic' in supported)  # Should print: True
```

## Server Startup

When the server starts, you'll see:
```
✓ HEIC/HEIF support registered (iPhone photos)
```

Or if not installed:
```
⚠️  pillow-heif not installed - HEIC files will not be supported
   Install with: pip install pillow-heif
```

## Benefits

- 📱 **Native iPhone format** - No need to convert HEIC to JPEG on iPhone
- 💾 **Smaller files** - HEIC is ~50% smaller than JPEG at same quality
- 🎨 **Better quality** - HEIC preserves more detail than JPEG
- ⚡ **Faster upload** - Smaller files = faster Base64 encoding and network transfer

## Testing

Use the test script with HEIC files:
```bash
# If you have HEIC files
python3 test_batch_upload.py http://192.168.1.218
```

The converter will automatically handle HEIC just like JPEG/PNG.

## Notes

- HEIC files are automatically converted to RGB during PDF generation
- EXIF orientation data is preserved and applied
- Transparency (if any) is converted to white background
- No quality loss during HEIC → PDF conversion

## Troubleshooting

**Error: "cannot identify image file"**
- Ensure `pillow-heif` is installed
- Check server logs for HEIC registration message

**HEIC files not uploading:**
- Verify file extension validation accepts `.heic`
- Check Base64 encoding is correct (no line breaks)
- Ensure file size < 22MB before encoding

## Documentation Updated

- ✅ `environment.yml` - Added pillow-heif dependency
- ✅ `tasks/image_pdf_converter.py` - Added HEIF registration
- ✅ `INSTRUKCJA_SKROT_IPHONE.md` - Updated features list
