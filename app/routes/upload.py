# app/routes/upload.py - REFACTORED VERSION
"""
Endpointy związane z uploadowaniem dokumentów i tworzeniem opinii.
REFAKTORYZACJA: Logika biznesowa przeniesiona do tasks/upload_manager.py
"""

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from datetime import datetime
from typing import List
from pydantic import BaseModel

# Lokalne importy
from app.db import engine, BASE_DIR
from app.models import Document
from app.document_utils import ALLOWED_EXTENSIONS
from app.navigation import build_form_navigation, BreadcrumbBuilder

# Import konfiguracji typów dokumentów
from app.config.document_types import document_type_config

# Import managera z tasks
from tasks.upload_manager import upload_manager

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ==================== REQUEST MODELS ====================

class Base64ImageBatch(BaseModel):
    """Request model for Base64 batch upload from iPhone."""
    images: List[str]  # Base64-encoded image data (can be single string or array)
    filenames: List[str]  # Original filenames (can be single string or array)

    class Config:
        json_schema_extra = {
            "example": {
                "images": ["/9j/4AAQSkZJRg...", "iVBORw0KGgo..."],
                "filenames": ["photo1.jpg", "photo2.png"]
            }
        }

    @classmethod
    def validate(cls, values):
        """Allow single values to be converted to lists for iPhone compatibility."""
        # This will be handled by the endpoint itself
        return values


# ==================== ENDPOINTY UPLOAD OPINII ====================

@router.get("/upload", name="upload_form")
def upload_form(request: Request):
    """Formularz uploadowania nowych opinii."""
    allowed_types = ", ".join(ALLOWED_EXTENSIONS.keys())

    # Zbuduj nawigację dla formularza upload
    navigation = build_form_navigation(request, "Dodaj nową opinię", "upload")

    context = {
        "request": request,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("upload.html", context)


@router.post("/upload", name="upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    """Dodawanie nowych głównych dokumentów (opinii) - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.create_opinions_from_files(files)

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)


# ==================== ENDPOINTY TWORZENIA PUSTYCH OPINII ====================

@router.get("/create_empty_opinion", name="create_empty_opinion_form")
def create_empty_opinion_form(request: Request):
    """Formularz tworzenia nowej pustej opinii."""

    # Zbuduj nawigację dla formularza create
    navigation = build_form_navigation(request, "Utwórz pustą opinię", "create")
    
    # Pobierz typy dokumentów z konfiguracji
    document_types = document_type_config.get_all_types()

    context = {
        "request": request,
        "document_types": document_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("create_empty_opinion.html", context)


@router.post("/create_empty_opinion", name="create_empty_opinion")
def create_empty_opinion(
        request: Request,
        sygnatura: str | None = Form(None),
        doc_type: str = Form(...),
        step: str = Form("k1"),
        note: str | None = Form(None)  # DODANE: parametr note
):
    """Utworzenie nowej pustej opinii bez dokumentu - REFACTORED."""

    # Deleguj całą logikę do managera
    result = upload_manager.create_empty_opinion(sygnatura, doc_type, step, note)  # DODANE: przekazanie note

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)

# ==================== ENDPOINTY SZYBKIEGO OCR ====================

@router.get("/quick_ocr", name="quick_ocr_form")
def quick_ocr_form(request: Request):
    """Formularz do szybkiego OCR dokumentów bez przypisywania do opinii."""
    allowed_types = ", ".join([k for k in ALLOWED_EXTENSIONS.keys()
                               if k not in ['.doc', '.docx']])

    # Zbuduj nawigację dla formularza OCR
    navigation = build_form_navigation(request, "Szybki OCR", "ocr")

    context = {
        "request": request,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("quick_ocr.html", context)


@router.post("/quick_ocr", name="quick_ocr")
async def quick_ocr(request: Request, files: list[UploadFile] = File(...)):
    """Szybki OCR - dodawanie dokumentów bez wiązania z opinią - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.create_quick_ocr_documents(files)

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)


# ==================== MOBILE API ENDPOINT ====================

@router.post("/api/upload/mobile", name="api_mobile_upload")
async def api_mobile_upload(files: list[UploadFile] = File(...)):
    """
    Mobile-friendly API endpoint for uploading files from iPhone.

    Supports two modes:
    1. Single PDF upload (backward compatible)
    2. Multiple images → automatically combined into single multi-page PDF

    Automatically:
    - Creates new Opinia with timestamp name
    - Uploads/converts files to PDF
    - Queues OCR processing

    Returns JSON with document details for mobile consumption.
    """

    # Delegate to upload manager for mobile upload (handles validation)
    result = await upload_manager.create_mobile_upload(files)

    if result.success:
        # Determine if multiple images were converted
        image_count = len(files) if len(files) > 1 else None

        # Build debug info about received files
        debug_files = [
            {
                "filename": file.filename,
                "content_type": file.content_type,
                "size_bytes": file.size if hasattr(file, 'size') else "unknown"
            }
            for file in files
        ]

        # Return JSON response for mobile
        return {
            "success": True,
            "opinion_id": result.uploaded_doc_ids[0] if result.uploaded_doc_ids else None,
            "document_id": result.uploaded_doc_ids[1] if len(result.uploaded_doc_ids) > 1 else None,
            "ocr_queued": result.has_ocr_docs,
            "image_count": image_count,
            "message": f"Upload successful. {f'{image_count} images combined into PDF. ' if image_count else ''}OCR processing started.",
            "preview_url": result.redirect_url,
            "debug": {
                "files_received": len(files),
                "files_list": debug_files
            }
        }
    else:
        raise HTTPException(status_code=500, detail=result.error_message)


@router.post("/api/upload/mobile/batch", name="api_mobile_upload_batch")
async def api_mobile_upload_batch(request: Request):
    """
    Base64 batch upload endpoint for iPhone Shortcuts.

    Accepts multiple Base64-encoded images in JSON format and combines them
    into a single multi-page PDF with automatic OCR processing.

    This endpoint solves iPhone Shortcuts limitation where multipart/form-data
    cannot send arrays of files.

    Request body:
    {
        "images": ["base64_string_1", "base64_string_2", ...],
        "filenames": ["IMG_0001.jpg", "IMG_0002.jpg", ...]
    }

    Validation:
    - 1-50 images required
    - Arrays must have equal length
    - Supported formats: .jpg, .jpeg, .png, .heic
    - Max 30MB per Base64 string (~22MB original image)

    Returns JSON with opinion and document IDs.
    """
    import base64
    import tempfile
    from pathlib import Path
    from fastapi import UploadFile
    import io

    # Parse JSON body manually to handle iPhone Shortcuts format
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    # DEBUG: Log raw received data
    print("=" * 80)
    print(f"📦 BASE64 BATCH UPLOAD RECEIVED")
    print(f"   Raw body type: {type(body)}")
    print(f"   Raw body keys: {body.keys() if isinstance(body, dict) else 'N/A'}")

    # Extract images and filenames, handling both string and list formats
    raw_images = body.get("images")
    raw_filenames = body.get("filenames")

    # Extract email parameters (optional)
    email = body.get("email")  # Optional: email address (defaults to config if not provided)
    email_option = body.get("email_option", "none")  # none/pdf_only/pdf_with_ocr

    # Convert to lists if single values (iPhone Shortcuts compatibility)
    # iPhone Shortcuts concatenates multiple items with newlines when using "Get Name" or "Base64 Encode"
    if isinstance(raw_images, str):
        # Split on newlines to handle multiple images concatenated by iPhone
        images = [img.strip() for img in raw_images.split('\n') if img.strip()]
        print(f"   ⚠️  'images' was a string, split by newlines into {len(images)} element(s)")
    elif isinstance(raw_images, list):
        images = raw_images
    else:
        raise HTTPException(status_code=400, detail=f"'images' must be a string or list, got {type(raw_images)}")

    if isinstance(raw_filenames, str):
        # Split on newlines to handle multiple filenames concatenated by iPhone
        filenames = [fn.strip() for fn in raw_filenames.split('\n') if fn.strip()]
        print(f"   ⚠️  'filenames' was a string, split by newlines into {len(filenames)} element(s)")
    elif isinstance(raw_filenames, list):
        filenames = raw_filenames
    else:
        raise HTTPException(status_code=400, detail=f"'filenames' must be a string or list, got {type(raw_filenames)}")

    # Apply default email from config if not provided
    from app.config.email_config import DEFAULT_EMAIL, EMAIL_OPTIONS
    if not email and email_option != "none":
        email = DEFAULT_EMAIL
        print(f"   ⚠️  No email provided, using default: {email}")

    # Validate email option
    if email_option not in EMAIL_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid email_option: '{email_option}'. Valid options: {list(EMAIL_OPTIONS.keys())}"
        )

    print(f"   Images: {len(images)}")
    print(f"   Filenames: {len(filenames)}")
    print(f"   Files: {', '.join(filenames[:5])}{' ...' if len(filenames) > 5 else ''}")
    print(f"   Email: {email or 'None'}")
    print(f"   Email option: {email_option}")
    print("=" * 80)

    # Validation: array lengths must match
    if len(images) != len(filenames):
        raise HTTPException(
            status_code=400,
            detail=f"Array length mismatch: {len(images)} images but {len(filenames)} filenames"
        )

    # Validation: file count
    if len(images) == 0:
        raise HTTPException(
            status_code=400,
            detail="No images provided. Upload at least 1 image."
        )

    if len(images) > 50:
        raise HTTPException(
            status_code=400,
            detail=f"Too many images ({len(images)}). Maximum 50 images per upload."
        )

    # Validation: file extensions
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.heic'}
    for filename in filenames:
        ext = Path(filename).suffix.lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext} in '{filename}'. Allowed: .jpg, .jpeg, .png, .heic"
            )

    # Decode Base64 and create UploadFile objects
    upload_files = []
    max_size = 30 * 1024 * 1024  # 30MB Base64 string (~22MB original)

    for idx, (b64_data, filename) in enumerate(zip(images, filenames)):
        try:
            # Validate Base64 string size
            if len(b64_data) > max_size:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {idx + 1} ('{filename}') Base64 data exceeds 30MB limit"
                )

            # Decode Base64 to bytes
            try:
                image_bytes = base64.b64decode(b64_data, validate=True)
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {idx + 1} ('{filename}') has invalid Base64 encoding: {str(e)}"
                )

            # Validate decoded size (max ~22MB original)
            if len(image_bytes) > 22 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {idx + 1} ('{filename}') exceeds 22MB after decoding"
                )

            if len(image_bytes) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {idx + 1} ('{filename}') is empty after decoding"
                )

            # Create UploadFile from decoded bytes
            file_obj = io.BytesIO(image_bytes)
            upload_file = UploadFile(
                filename=filename,
                file=file_obj
            )
            upload_files.append(upload_file)

        except HTTPException:
            raise  # Re-raise HTTP exceptions
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to process image {idx + 1} ('{filename}'): {str(e)}"
            )

    # Delegate to existing upload manager (reuses all validation and conversion logic)
    print(f"🔄 Processing {len(upload_files)} decoded images...")
    result = await upload_manager.create_mobile_upload(
        upload_files,
        email=email if email_option == "pdf_with_ocr" else None
    )

    if result.success:
        image_count = len(upload_files)
        document_id = result.uploaded_doc_ids[1] if len(result.uploaded_doc_ids) > 1 else None
        print(f"✅ Base64 batch upload successful: Opinion #{result.uploaded_doc_ids[0]}, Document #{document_id}")

        # Handle email sending based on email_option
        email_sent = False
        if email and email_option == "pdf_only" and document_id:
            print(f"📧 Sending PDF email to {email}...")
            from app.email_service import email_service
            email_sent = email_service.send_pdf_email(document_id, email)
            if email_sent:
                print(f"✅ PDF email sent to {email}")
            else:
                print(f"❌ Failed to send PDF email to {email}")

        elif email and email_option == "pdf_with_ocr" and document_id:
            print(f"📧 PDF+OCR email will be sent to {email} after OCR completes")
            # Email will be passed to OCR process via background task parameter
            # (already queued with email in background_tasks.py)

        print("=" * 80)

        return {
            "success": True,
            "opinion_id": result.uploaded_doc_ids[0] if result.uploaded_doc_ids else None,
            "document_id": document_id,
            "ocr_queued": result.has_ocr_docs,
            "image_count": image_count,
            "email_sent": email_sent,
            "email_pending": email_option == "pdf_with_ocr",
            "message": f"Upload successful. {image_count} images combined into PDF. OCR processing started.",
            "preview_url": result.redirect_url
        }
    else:
        print(f"❌ Base64 batch upload failed: {result.error_message}")
        print("=" * 80)
        raise HTTPException(status_code=500, detail=result.error_message)


# ==================== ENDPOINTY UPLOADU DO OPINII ====================

@router.get("/opinion/{doc_id}/upload", name="upload_to_opinion_form")
def upload_to_opinion_form(request: Request, doc_id: int):
    """Formularz dodawania dokumentów do opinii."""
    with Session(engine) as session:
        opinion = session.get(Document, doc_id)
        if not opinion or not opinion.is_main:
            raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        # Zbuduj nawigację
        breadcrumbs = (BreadcrumbBuilder(request)
                       .add_home()
                       .add_opinion(opinion)
                       .add_current("Dodaj dokumenty", "plus-circle")
                       .build())

        navigation = {
            'breadcrumbs': breadcrumbs,
            'page_title': f"Dodaj dokumenty do opinii: {opinion.sygnatura or opinion.original_filename}",
            'page_actions': [],
            'context_info': []
        }

    allowed_types = ", ".join(ALLOWED_EXTENSIONS.keys())
    
    # Pobierz typy dokumentów z konfiguracji
    document_types = document_type_config.get_all_types()

    context = {
        "request": request,
        "opinion": opinion,
        "document_types": document_types,
        "allowed_types": allowed_types,
        "current_year": datetime.now().year,
        "page_type": "upload_form",
        **navigation
    }

    return templates.TemplateResponse("upload_to_opinion.html", context)


@router.post("/opinion/{doc_id}/upload", name="upload_to_opinion")
async def upload_to_opinion(request: Request, doc_id: int,
                            doc_type: str = Form(...),
                            files: list[UploadFile] = File(...),
                            run_ocr: bool = Form(False)):
    """Dodawanie dokumentów do opinii - REFACTORED."""

    # Deleguj całą logikę do managera
    result = await upload_manager.add_documents_to_opinion(
        opinion_id=doc_id,
        files=files,
        doc_type=doc_type,
        run_ocr=run_ocr
    )

    if result.success:
        return RedirectResponse(result.redirect_url, status_code=303)
    else:
        raise HTTPException(status_code=400, detail=result.error_message)