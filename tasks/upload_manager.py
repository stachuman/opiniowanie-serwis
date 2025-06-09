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
            run_ocr: bool = False
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
            await UploadManager._enqueue_ocr_documents_nonblocking(uploaded_docs)

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
    def create_empty_opinion(
            sygnatura: Optional[str],
            doc_type: str,
            step: str = "k1"
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
    async def _enqueue_ocr_documents_nonblocking(doc_ids: List[int]):
        """
        Asynchronicznie wstawia dokumenty do kolejki OCR bez blokowania.
        """
        from app.background_tasks import enqueue_ocr_task

        for doc_id in doc_ids:
            try:
                with Session(engine) as session:
                    doc = session.get(Document, doc_id)
                    if doc and doc.ocr_status == "pending":
                        await enqueue_ocr_task(doc_id)
                        await asyncio.sleep(0)  # Oddaj kontrolę
            except Exception as e:
                print(f"Błąd podczas dodawania dokumentu {doc_id} do kolejki OCR: {str(e)}")
                continue


# Stwórz singleton instance
upload_manager = UploadManager()