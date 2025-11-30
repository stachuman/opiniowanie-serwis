# tasks/upload_manager.py
"""
Manager dla operacji upload i tworzenia dokumentów.
Zawiera całą logikę biznesową przeniesioną z routes/upload.py.
"""

import asyncio
import uuid
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from fastapi import UploadFile, HTTPException
from sqlmodel import Session

from app.db import engine, FILES_DIR
from app.models import Document
from app.document_utils import (
    detect_mime_type,
    check_file_extension,
    get_content_type_from_mime
)
from tasks.image_pdf_converter import image_pdf_converter


@dataclass
class UploadResult:
    """Wynik operacji upload."""
    success: bool
    uploaded_doc_ids: List[int]
    redirect_url: str
    error_message: Optional[str] = None
    has_ocr_docs: bool = False
    ocr_count: int = 0


class UploadManager:
    """Manager dla wszystkich operacji upload."""

    @staticmethod
    async def create_opinions_from_files(files: List[UploadFile]) -> UploadResult:
        """
        Tworzy nowe opinie z przesłanych plików Word.
        Logika z routes/upload.py -> upload()
        """
        uploaded_docs = []

        with Session(engine) as session:
            for file in files:
                # Sprawdzenie rozszerzenia pliku
                suffix = check_file_extension(file.filename)

                # Dla opinii akceptujemy tylko pliki Word
                if suffix.lower() not in ['.doc', '.docx']:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Opinie muszą być w formacie Word (.doc, .docx). Przesłano: {suffix}"
                    )

                # Generowanie unikalnej nazwy pliku
                unique_name = f"{uuid.uuid4().hex}{suffix}"
                dest = FILES_DIR / unique_name

                # Zapisanie pliku
                with dest.open("wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                # Wykrywanie właściwego MIME typu pliku
                actual_mime_type = detect_mime_type(dest)

                # Zapisanie do bazy danych jako dokument główny
                doc = Document(
                    original_filename=file.filename,
                    stored_filename=unique_name,
                    step="k1",  # Nowe opinie zaczynają od k1
                    ocr_status="none",  # Word nie wymaga OCR
                    is_main=True,  # Oznacz jako dokument główny
                    content_type="opinion",
                    mime_type=actual_mime_type,
                    doc_type="Opinia",
                    creator=None  # TODO: current_user gdy będzie system użytkowników
                )
                session.add(doc)
                session.commit()
                uploaded_docs.append(doc.id)

        # Określ URL przekierowania
        if len(uploaded_docs) == 1:
            redirect_url = f"/opinion/{uploaded_docs[0]}"
        else:
            redirect_url = "/"

        return UploadResult(
            success=True,
            uploaded_doc_ids=uploaded_docs,
            redirect_url=redirect_url
        )

    @staticmethod
    async def add_documents_to_opinion(
            opinion_id: int,
            files: List[UploadFile],
            doc_type: str,
            run_ocr: bool = False,
            email: Optional[str] = None
    ) -> UploadResult:
        """
        Dodaje dokumenty do istniejącej opinii.
        Logika z routes/upload.py -> upload_to_opinion()
        """
        # Sprawdź czy opinia istnieje
        with Session(engine) as session:
            opinion = session.get(Document, opinion_id)
            if not opinion or not opinion.is_main:
                raise HTTPException(status_code=404, detail="Nie znaleziono opinii")

        uploaded_docs = []
        has_ocr_docs = False

        # Przetwarzanie wgranych plików
        for file in files:
            # Sprawdzenie rozszerzenia pliku
            suffix = check_file_extension(file.filename)

            # Generowanie unikalnej nazwy pliku
            unique_name = f"{uuid.uuid4().hex}{suffix}"
            dest = FILES_DIR / unique_name

            # Zapisanie pliku
            content = await file.read()
            with open(dest, "wb") as buffer:
                buffer.write(content)

            # Wykrywanie właściwego MIME typu pliku
            actual_mime_type = detect_mime_type(dest)

            # Określanie content_type na podstawie MIME type
            content_type = get_content_type_from_mime(actual_mime_type)

            # Jeśli to nowy dokument główny, nie powiązuj go z obecną opinią
            is_main = content_type == "opinion" and doc_type == "Opinia"
            parent_id = None if is_main else opinion_id

            # Ustal właściwy status OCR
            ocr_status = "none"
            if run_ocr and content_type != "opinion":
                ocr_status = "pending"
                has_ocr_docs = True

            # Zapisanie do bazy danych
            with Session(engine) as session:
                # Pobierz aktualną opinię dla sygnatura
                opinion = session.get(Document, opinion_id)

                new_doc = Document(
                    sygnatura=opinion.sygnatura,
                    doc_type=doc_type,
                    original_filename=file.filename,
                    stored_filename=unique_name,
                    step="k1" if is_main else opinion.step,
                    ocr_status=ocr_status,
                    parent_id=parent_id,
                    is_main=is_main,
                    content_type=content_type,
                    mime_type=actual_mime_type,
                    creator=None,  # TODO: current_user
                    upload_time=datetime.now()
                )
                session.add(new_doc)
                session.commit()
                uploaded_docs.append(new_doc.id)

        # Uruchom OCR dla wgranych dokumentów w tle
        if has_ocr_docs:
            await UploadManager._enqueue_ocr_documents_nonblocking(uploaded_docs, email=email)

        # Przygotuj URL przekierowania z odpowiednim komunikatem
        redirect_url = f"/opinion/{opinion_id}"
        if has_ocr_docs:
            redirect_url += f"?ocr_started=true&count={len(uploaded_docs)}"

        return UploadResult(
            success=True,
            uploaded_doc_ids=uploaded_docs,
            redirect_url=redirect_url,
            has_ocr_docs=has_ocr_docs,
            ocr_count=len([doc_id for doc_id in uploaded_docs if has_ocr_docs])
        )

    @staticmethod
    async def create_quick_ocr_documents(files: List[UploadFile]) -> UploadResult:
        """
        Tworzy dokumenty dla szybkiego OCR bez wiązania z opinią.
        Logika z routes/upload.py -> quick_ocr()
        """
        uploaded_docs = []

        # Utwórz lub pobierz specjalną "opinię" dla dokumentów niezwiązanych
        special_opinion_id = await UploadManager._get_or_create_unassigned_container()

        # Przetwarzanie wgranych plików
        for file in files:
            # Sprawdzenie rozszerzenia pliku
            suffix = check_file_extension(file.filename)

            # Ignorujemy pliki Word w szybkim OCR
            if suffix.lower() in ['.doc', '.docx']:
                continue

            # Generowanie unikalnej nazwy pliku
            unique_name = f"{uuid.uuid4().hex}{suffix}"
            dest = FILES_DIR / unique_name

            # Zapisanie pliku
            content = await file.read()
            with open(dest, "wb") as buffer:
                buffer.write(content)

            # Wykrywanie właściwego MIME typu pliku
            actual_mime_type = detect_mime_type(dest)

            # Określanie content_type na podstawie MIME type
            content_type = get_content_type_from_mime(actual_mime_type)

            # Zapisanie do bazy danych
            with Session(engine) as session:
                new_doc = Document(
                    doc_type="Dokument OCR",
                    original_filename=file.filename,
                    stored_filename=unique_name,
                    step="k1",
                    ocr_status="pending",  # Automatycznie uruchom OCR
                    parent_id=special_opinion_id,
                    is_main=False,
                    content_type=content_type,
                    mime_type=actual_mime_type,
                    creator=None,
                    upload_time=datetime.now()
                )
                session.add(new_doc)
                session.commit()
                uploaded_docs.append(new_doc.id)

        # Uruchom OCR dla wszystkich dokumentów
        await UploadManager._enqueue_ocr_documents_nonblocking(uploaded_docs)

        return UploadResult(
            success=True,
            uploaded_doc_ids=uploaded_docs,
            redirect_url="/documents",
            has_ocr_docs=True,
            ocr_count=len(uploaded_docs)
        )

    @staticmethod
    async def create_mobile_upload(
        files: List[UploadFile],
        email: Optional[str] = None
    ) -> UploadResult:
        """
        Creates a new Opinia from mobile PDF or image upload(s) with automatic OCR.

        Supports two modes:
        1. Single PDF upload (backward compatible)
        2. Multiple images → combined into single multi-page PDF

        Strategy: One Opinia per upload with timestamp name.
        Reuses existing create_empty_opinion and add_documents_to_opinion logic.

        Args:
            files: List of PDF or image files from mobile device
            email: Optional email to notify when OCR completes (for pdf_with_ocr option)

        Returns:
            UploadResult with opinion_id and document_id
        """
        if email:
            print(f"📧 [UPLOAD_MANAGER] Email parameter received: {email}")

        if not files or len(files) == 0:
            raise HTTPException(
                status_code=400,
                detail="No files provided. Upload at least 1 PDF or image."
            )

        # Validation: max 50 files
        if len(files) > 50:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files ({len(files)}). Maximum 50 images per upload."
            )

        # Step 1: Detect upload type and validate
        upload_type = await UploadManager._detect_mobile_upload_type(files)

        # Step 2: Get final PDF (either directly or from image conversion)
        if upload_type == "single_pdf":
            # Existing flow: single PDF upload
            final_file = files[0]
            pdf_filename = final_file.filename

        elif upload_type == "multiple_images":
            # New flow: convert images to PDF
            # Generate unique PDF filename
            unique_pdf_name = f"{uuid.uuid4().hex}.pdf"
            pdf_path = FILES_DIR / unique_pdf_name

            # Convert images to PDF
            result = await image_pdf_converter.convert_upload_files_to_pdf(files, pdf_path)

            if not result.success:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to convert images to PDF: {result.error_message}"
                )

            # Wrap PDF path as UploadFile for existing flow
            pdf_filename = f"Combined_{len(files)}_images.pdf"

            # Create UploadFile-like object from converted PDF
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

            # Create a temporary file-like object
            import io
            final_file = UploadFile(
                filename=pdf_filename,
                file=io.BytesIO(pdf_content)
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported upload type: {upload_type}"
            )

        # Generate timestamp-based opinion name
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        opinion_name = f"Mobile Upload {timestamp}"

        # Step 3: Create empty opinion using existing function
        opinion_result = UploadManager.create_empty_opinion(
            sygnatura=None,
            doc_type="opinia",
            step="k1",
            note="Auto-created from mobile upload"
        )

        if not opinion_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create opinion: {opinion_result.error_message}"
            )

        opinion_id = opinion_result.uploaded_doc_ids[0]

        # Update opinion name to include timestamp
        with Session(engine) as session:
            opinion = session.get(Document, opinion_id)
            if opinion:
                opinion.original_filename = opinion_name
                session.add(opinion)
                session.commit()

        # Step 4: Add PDF document to opinion using existing function
        doc_result = await UploadManager.add_documents_to_opinion(
            opinion_id=opinion_id,
            files=[final_file],
            doc_type="protokol",  # Default type for mobile uploads
            run_ocr=True,  # Always run OCR for mobile uploads
            email=email  # Pass email for pdf_with_ocr option
        )

        if not doc_result.success:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload document: {doc_result.error_message}"
            )

        # Combine results: [opinion_id, document_id]
        all_doc_ids = [opinion_id] + doc_result.uploaded_doc_ids

        return UploadResult(
            success=True,
            uploaded_doc_ids=all_doc_ids,
            redirect_url=f"/opinion/{opinion_id}",
            has_ocr_docs=True,
            ocr_count=1
        )

    @staticmethod
    async def _detect_mobile_upload_type(files: List[UploadFile]) -> str:
        """
        Detects mobile upload type and validates files.

        Returns:
            "single_pdf" or "multiple_images"

        Raises:
            HTTPException: If validation fails
        """
        # Get file extensions
        extensions = []
        for file in files:
            if not file.filename:
                raise HTTPException(status_code=400, detail="All files must have filenames")

            suffix = check_file_extension(file.filename)
            extensions.append(suffix.lower())

        # Check for single PDF
        if len(files) == 1 and extensions[0] == '.pdf':
            return "single_pdf"

        # Check for multiple images
        image_extensions = {'.jpg', '.jpeg', '.png', '.heic'}

        # All must be images
        if all(ext in image_extensions for ext in extensions):
            # Validate image files can be opened
            await UploadManager._validate_image_files(files)
            return "multiple_images"

        # Mixed types or unsupported
        if '.pdf' in extensions:
            raise HTTPException(
                status_code=400,
                detail="Mixed file types not supported. Upload either: (1) single PDF, or (2) multiple images."
            )

        # Unsupported file type
        unsupported = [ext for ext in extensions if ext not in image_extensions and ext != '.pdf']
        if unsupported:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {unsupported[0]}. Allowed: .pdf, .jpg, .jpeg, .png, .heic"
            )

        raise HTTPException(
            status_code=400,
            detail="Invalid file combination. Upload either: (1) single PDF, or (2) multiple images."
        )

    @staticmethod
    async def _validate_image_files(files: List[UploadFile]):
        """
        Validates that all files are valid images.

        Raises:
            HTTPException: If any image is invalid or corrupted
        """
        from PIL import Image
        import tempfile

        # Register HEIF/HEIC support for iPhone photos
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass  # HEIC support not available, but JPEG/PNG will still work

        for idx, file in enumerate(files):
            try:
                # Read file content
                content = await file.read()

                # Reset file pointer for later use
                await file.seek(0)

                # Check file size (max 20MB per image)
                max_size = 20 * 1024 * 1024  # 20MB
                if len(content) > max_size:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image {idx + 1} ('{file.filename}') exceeds 20MB limit"
                    )

                if len(content) == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image {idx + 1} ('{file.filename}') is empty"
                    )

                # Validate image can be opened by Pillow
                with tempfile.NamedTemporaryFile(delete=True) as tmp:
                    tmp.write(content)
                    tmp.flush()

                    # Try to open and verify image
                    with Image.open(tmp.name) as img:
                        img.verify()  # Throws if corrupted

            except HTTPException:
                raise  # Re-raise HTTP exceptions
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image {idx + 1} ('{file.filename}') is corrupted or invalid: {str(e)}"
                )

    @staticmethod
    def create_empty_opinion(
            sygnatura: Optional[str],
            doc_type: str,
            step: str = "k1",
            note: Optional[str] = None  # DODANE: parametr note
    ) -> UploadResult:
        """
        Tworzy pustą opinię bez dokumentu.
        Logika z routes/upload.py -> create_empty_opinion()
        """
        # Generowanie unikalnej nazwy dla "pustego" dokumentu
        unique_name = f"{uuid.uuid4().hex}.empty"

        with Session(engine) as session:
            # Utworzenie nowej opinii w bazie danych
            opinion = Document(
                original_filename="Nowa opinia",
                stored_filename=unique_name,
                step=step,
                ocr_status="none",
                is_main=True,
                content_type="opinion",
                doc_type=doc_type,
                sygnatura=sygnatura,
                note=note.strip() if note else None,  # DODANE: zapisanie notatki
                creator=None  # TODO: current_user
            )
            session.add(opinion)
            session.commit()
            opinion_id = opinion.id

        return UploadResult(
            success=True,
            uploaded_doc_ids=[opinion_id],
            redirect_url=f"/opinion/{opinion_id}"
        )
    @staticmethod
    async def _get_or_create_unassigned_container() -> int:
        """
        Pobiera lub tworzy specjalną opinię-kontener dla dokumentów niezwiązanych.
        """
        from sqlmodel import select

        with Session(engine) as session:
            # Sprawdź czy istnieje specjalna opinia dla dokumentów niezwiązanych
            special_opinion_query = select(Document).where(
                Document.is_main == True,
                Document.doc_type == "Dokumenty niezwiązane z opiniami"
            )
            special_opinion = session.exec(special_opinion_query).first()

            # Jeśli nie istnieje, utwórz ją
            if not special_opinion:
                special_opinion = Document(
                    original_filename="Dokumenty niezwiązane z opiniami",
                    stored_filename=f"{uuid.uuid4().hex}.empty",
                    step="k1",
                    ocr_status="none",
                    is_main=True,
                    content_type="container",  # Specjalny typ dla kontenera dokumentów
                    doc_type="Dokumenty niezwiązane z opiniami",
                    sygnatura="UNASSIGNED",
                    creator=None
                )
                session.add(special_opinion)
                session.commit()
                return special_opinion.id
            else:
                return special_opinion.id

    @staticmethod
    async def _enqueue_ocr_documents_nonblocking(doc_ids: List[int], email: Optional[str] = None):
        """
        Asynchronicznie wstawia dokumenty do kolejki OCR bez blokowania.

        Args:
            doc_ids: List of document IDs to process
            email: Optional email to send when OCR completes
        """
        from app.background_tasks import enqueue_ocr_task

        if email:
            print(f"📧 [UPLOAD_MANAGER] Passing email to OCR queue: {email}")

        for doc_id in doc_ids:
            try:
                with Session(engine) as session:
                    doc = session.get(Document, doc_id)
                    if doc and doc.ocr_status == "pending":
                        await enqueue_ocr_task(doc_id, email=email)
                        if email:
                            print(f"📧 [UPLOAD_MANAGER] Enqueued OCR task for doc {doc_id} with email {email}")
                        await asyncio.sleep(0)  # Oddaj kontrolę
            except Exception as e:
                print(f"Błąd podczas dodawania dokumentu {doc_id} do kolejki OCR: {str(e)}")
                continue


# Stwórz singleton instance
upload_manager = UploadManager()