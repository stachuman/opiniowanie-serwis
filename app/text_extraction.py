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

# Próba importu biblioteki python-docx
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

# Cache dla wyekstraktowanych tekstów
extracted_text_cache = {}

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
    """Wyciąga tekst z dokumentu Word używając python-docx."""
    if not HAS_DOCX:
        logger.warning("Brak biblioteki DOCX")
        return ""
    
    try:
        doc = DocxDocument(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text.strip()
    except Exception as e:
        logger.warning(f"Nie można wyciągnąć tekstu z Word {file_path}: {str(e)}")
        return ""

def get_ocr_text_for_document(doc_id, session):
    """Pobiera tekst OCR dla danego dokumentu."""
    try:
        # Sprawdź czy istnieje dokument OCR TXT powiązany z tym dokumentem
        ocr_txt_query = select(Document).where(
            Document.ocr_parent_id == doc_id,
            Document.doc_type == "OCR TXT"
        )
        ocr_txt = session.exec(ocr_txt_query).first()
        
        if not ocr_txt:
            return ""
        
        # Odczytaj tekst z pliku OCR
        ocr_file_path = FILES_DIR / ocr_txt.stored_filename
        if not ocr_file_path.exists():
            return ""
        
        encodings = ['utf-8', 'latin-1', 'cp1250']
        for encoding in encodings:
            try:
                return ocr_file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return ""
    except Exception as e:
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
