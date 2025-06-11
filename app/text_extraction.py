# app/text_extraction.py
"""
Moduł ekstraktowania tekstu z różnych typów dokumentów.
"""

import PyPDF2
from sqlmodel import Session, select
from pathlib import Path

from app.db import FILES_DIR, engine
from app.models import Document
from tasks.ocr.config import logger
import subprocess
import shutil

# Próba importu biblioteki python-docx
try:
    from docx import Document as DocxDocument

    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    import docx2txt
    HAS_DOCX2TXT = True
except ImportError:
    HAS_DOCX2TXT = False

# Cache dla wyekstraktowanych tekstów
extracted_text_cache = {}


def clear_text_cache(doc_id=None):
    """Czyści cache tekstów dla dokumentu lub całkowicie."""
    global extracted_text_cache
    if doc_id is None:
        # Wyczyść cały cache
        extracted_text_cache.clear()
        print(f"🧹 [TEXT_EXTRACTION] Wyczyszczono cały cache tekstów")
    else:
        # Wyczyść cache dla konkretnego dokumentu
        keys_to_remove = [k for k in extracted_text_cache.keys() if k.startswith(f"{doc_id}_")]
        for key in keys_to_remove:
            del extracted_text_cache[key]
        print(f"🧹 [TEXT_EXTRACTION] Wyczyszczono cache dla dokumentu {doc_id}")


def extract_text_from_pdf(file_path):
    """Wyciąga tekst z PDF używając PyPDF2."""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
    except Exception as e:
        logger.warning(f"Nie można wyciągnąć tekstu z PDF {file_path}: {str(e)}")
        return ""


def extract_text_from_word(file_path):
    """Wyciąga tekst z dokumentu Word - obsługuje wszystkie formaty."""

    # Metoda 1: Spróbuj jako .docx (nowy format)
    if HAS_DOCX:
        try:
            doc = DocxDocument(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            logger.info(f"✅ Pomyślnie odczytano .docx: {file_path}")
            return text.strip()
        except Exception as docx_error:
            logger.info(f"📄 Nie udało się odczytać jako .docx: {docx_error}")

    # Metoda 2: Spróbuj przez antiword (najlepsza dla starych .doc)
    if shutil.which('antiword'):  # Sprawdź czy antiword jest zainstalowany
        try:
            result = subprocess.run(
                ['antiword', '-t', str(file_path)],  # -t = plain text output
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=30  # Timeout 30 sekund
            )

            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                logger.info(f"✅ Pomyślnie odczytano przez antiword: {file_path} ({len(text)} znaków)")
                return text
            else:
                logger.info(f"📄 Antiword nie może odczytać: {file_path} (returncode: {result.returncode})")
        except subprocess.TimeoutExpired:
            logger.warning(f"⏱️ Antiword timeout dla: {file_path}")
        except Exception as antiword_error:
            logger.info(f"📄 Błąd antiword: {antiword_error}")
    else:
        logger.info("📄 Antiword nie jest zainstalowany - pomiń starsze pliki .doc")

    # Metoda 3: Spróbuj python-docx2txt (backup)
    if HAS_DOCX2TXT:
        try:
            text = docx2txt.process(file_path)
            if text and text.strip():
                logger.info(f"✅ Pomyślnie odczytano przez docx2txt: {file_path}")
                return text.strip()
        except Exception as doc_error:
            logger.info(f"📄 Nie udało się odczytać przez docx2txt: {doc_error}")

    # Metoda 4: Ostatnia szansa - catdoc (jeśli dostępny)
    if shutil.which('catdoc'):
        try:
            result = subprocess.run(
                ['catdoc', str(file_path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=30
            )

            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                logger.info(f"✅ Pomyślnie odczytano przez catdoc: {file_path}")
                return text
        except Exception as catdoc_error:
            logger.info(f"📄 Błąd catdoc: {catdoc_error}")

    # Jeśli nic nie zadziałało
    missing_tools = []
    if not HAS_DOCX: missing_tools.append("python-docx")
    if not HAS_DOCX2TXT: missing_tools.append("python-docx2txt")
    if not shutil.which('antiword'): missing_tools.append("antiword")

    error_msg = f"Nie można odczytać dokumentu Word. "
    if missing_tools:
        error_msg += f"Brakujące narzędzia: {', '.join(missing_tools)}"

    logger.warning(f"❌ {error_msg}: {file_path}")
    return f"[BŁĄD ODCZYTU] {error_msg}\n\nAby odczytać ten plik, zainstaluj: sudo apt-get install antiword"

def get_ocr_text_for_document(doc_id, session):
    """Pobiera tekst OCR dla danego dokumentu - NAJNOWSZY dokument OCR."""
    try:
        # ✅ POPRAWKA: Sortuj po upload_time DESC aby pobrać NAJNOWSZY dokument OCR
        ocr_txt_query = select(Document).where(
            Document.ocr_parent_id == doc_id,
            Document.doc_type == "OCR TXT"
        ).order_by(Document.upload_time.desc())  # NAJNOWSZY PIERWSZY

        ocr_txt = session.exec(ocr_txt_query).first()  # Teraz .first() bierze najnowszy

        if not ocr_txt:
            return ""

        # Debug log
        print(f"🔍 [TEXT_EXTRACTION] Pobrano OCR dokument ID={ocr_txt.id}, upload_time={ocr_txt.upload_time}")

        # Odczytaj tekst z pliku OCR
        ocr_file_path = FILES_DIR / ocr_txt.stored_filename
        if not ocr_file_path.exists():
            print(f"❌ [TEXT_EXTRACTION] Plik OCR nie istnieje: {ocr_file_path}")
            return ""

        encodings = ['utf-8', 'latin-1', 'cp1250']
        for encoding in encodings:
            try:
                text = ocr_file_path.read_text(encoding=encoding)
                print(f"✅ [TEXT_EXTRACTION] Odczytano OCR text ({len(text)} znaków) z encoding={encoding}")
                return text
            except UnicodeDecodeError:
                continue

        print(f"❌ [TEXT_EXTRACTION] Nie można odczytać pliku OCR z żadnym kodowaniem")
        return ""

    except Exception as e:
        print(f"❌ [TEXT_EXTRACTION] Błąd podczas odczytu OCR dla dokumentu {doc_id}: {str(e)}")
        logger.warning(f"Błąd podczas odczytu OCR dla dokumentu {doc_id}: {str(e)}")
        return ""


def get_document_text_content(document, session=None):
    """
    Zwraca tekstową zawartość dokumentu.
    Dla dokumentów z OCR sprawdza zarówno oryginalny plik jak i wyniki OCR.
    """
    cache_key = f"{document.id}_{document.stored_filename}_{document.last_modified or document.upload_time}"

    # Sprawdź cache
    if cache_key in extracted_text_cache:
        return extracted_text_cache[cache_key]

    file_path = FILES_DIR / document.stored_filename
    text_content = ""

    # Sprawdź czy plik istnieje
    if not file_path.exists():
        extracted_text_cache[cache_key] = ""
        return ""

    # Wyciągnij tekst z oryginalnego pliku
    if document.mime_type == 'application/pdf':
        text_content = extract_text_from_pdf(file_path)
    elif document.mime_type and 'word' in document.mime_type:
        text_content = extract_text_from_word(file_path)
    elif document.mime_type == 'text/plain' or document.doc_type == "OCR TXT":
        # Dla plików tekstowych i wyników OCR
        try:
            encodings = ['utf-8', 'latin-1', 'cp1250']
            for encoding in encodings:
                try:
                    text_content = file_path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
        except Exception as e:
            logger.warning(f"Nie można odczytać pliku tekstowego {file_path}: {str(e)}")

    # WAŻNE: Jeśli to dokument PDF/obrazek, sprawdź też czy ma wyniki OCR
    if document.mime_type in ['application/pdf'] or (document.mime_type and document.mime_type.startswith('image/')):
        if session is None:
            # Utwórz tymczasową sesję jeśli nie została przekazana
            with Session(engine) as temp_session:
                ocr_results = get_ocr_text_for_document(document.id, temp_session)
        else:
            ocr_results = get_ocr_text_for_document(document.id, session)

        # Dodaj wyniki OCR do tekstu (jeśli istnieją i nie są puste)
        if ocr_results and ocr_results.strip():
            text_content = f"{text_content}\n\n=== OCR RESULTS ===\n{ocr_results}".strip()

    # Zapisz w cache (max 2000 znaków aby nie zużywać za dużo pamięci)
    cached_text = text_content[:2000] if text_content else ""
    extracted_text_cache[cache_key] = cached_text

    return text_content


def get_text_preview(doc_id, max_length=None):
    """
    Pobiera tekst dokumentu dla podglądu.

    Args:
        doc_id: ID dokumentu
        max_length: Opcjonalne ograniczenie długości (None = bez ograniczeń)

    Returns:
        str: Tekst dokumentu
    """
    with Session(engine) as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return "Nie znaleziono dokumentu"

        try:
            text_path = FILES_DIR / doc.stored_filename
            if not text_path.exists():
                return "Plik tekstowy nie istnieje"

            # Próba odczytu z różnymi kodowaniami
            encodings = ['utf-8', 'latin-1', 'cp1250']
            for encoding in encodings:
                try:
                    # Odczytaj pełny tekst dokumentu
                    text = text_path.read_text(encoding=encoding)
                    if max_length and len(text) > max_length:
                        return text[:max_length] + "...\n[Skrócone - pobierz pełny tekst, aby zobaczyć więcej]"
                    return text
                except UnicodeDecodeError:
                    continue

            # Jeśli żadne kodowanie nie zadziałało
            return "Nie można odczytać tekstu - nieobsługiwane kodowanie znaków"
        except Exception as e:
            return f"Błąd podczas odczytu tekstu: {str(e)}"