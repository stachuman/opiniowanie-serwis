# app/document_utils.py
"""
Moduł narzędzi i funkcji pomocniczych dla dokumentów.
"""

import mimetypes
import pathlib
from fastapi import HTTPException
from pathlib import Path

# Próba importu biblioteki python-magic dla dokładnego wykrywania MIME type
try:
    import magic
    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

# Dodanie obsługiwanych typów plików
ALLOWED_EXTENSIONS = {
    # PDFy
    '.pdf': 'application/pdf',
    # Obrazy
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.tif': 'image/tiff',
    '.tiff': 'image/tiff',
    '.bmp': 'image/bmp',
    '.webp': 'image/webp',
    # Dokumenty tekstowe
    '.txt': 'text/plain',
    # Dokumenty Word
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

STEP_ICON = {
    "k1": "bi bi-exclamation-triangle-fill text-danger",
    "k2": "bi bi-exclamation-circle-fill text-warning",
    "k3": "bi bi-check-circle-fill text-success",
    "k4": "bi bi-archive-fill text-secondary",
}

def detect_mime_type(file_path):
    """
    Wykrywa faktyczny MIME type pliku na podstawie jego zawartości.
    Używa biblioteki python-magic jeśli jest dostępna, w przeciwnym razie
    bazuje na rozszerzeniu pliku.
    
    Args:
        file_path: Ścieżka do pliku
    
    Returns:
        str: MIME type pliku
    """
    # Jeśli mamy bibliotekę python-magic, używamy jej
    if HAS_MAGIC:
        try:
            mime = magic.Magic(mime=True)
            detected_mime = mime.from_file(str(file_path))
            return detected_mime
        except Exception as e:
            print(f"Błąd wykrywania MIME type: {e}")
            # W przypadku błędu, używamy fallbacku
            pass
    
    # Fallback - używamy rozszerzenia pliku
    suffix = file_path.suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return ALLOWED_EXTENSIONS[suffix]
    
    # Ostatecznie próbujemy użyć mimetypes
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        return mime_type
    
    # Domyślnie zwróć application/octet-stream
    return 'application/octet-stream'

def check_file_extension(filename: str):
    """Sprawdź czy rozszerzenie pliku jest dozwolone."""
    suffix = pathlib.Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(ALLOWED_EXTENSIONS.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Niedozwolony typ pliku. Dozwolone typy: {allowed}"
        )
    return suffix

def is_image_file(filename: str) -> bool:
    """Sprawdza czy plik jest obrazem na podstawie rozszerzenia."""
    suffix = pathlib.Path(filename).suffix.lower()
    image_extensions = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
    return suffix in image_extensions

def is_pdf_file(filename: str) -> bool:
    """Sprawdza czy plik jest PDF na podstawie rozszerzenia."""
    return pathlib.Path(filename).suffix.lower() == '.pdf'

def is_word_file(filename: str) -> bool:
    """Sprawdza czy plik jest dokumentem Word na podstawie rozszerzenia."""
    suffix = pathlib.Path(filename).suffix.lower()
    return suffix in {'.doc', '.docx'}

def is_text_file(filename: str) -> bool:
    """Sprawdza czy plik jest plikiem tekstowym na podstawie rozszerzenia."""
    return pathlib.Path(filename).suffix.lower() == '.txt'

def get_content_type_from_mime(mime_type: str) -> str:
    """
    Określa content_type na podstawie MIME type.
    
    Args:
        mime_type: MIME type pliku
        
    Returns:
        str: content_type ('document', 'image', 'opinion')
    """
    if not mime_type:
        return "document"
    
    if mime_type.startswith('image/'):
        return "image"
    elif 'word' in mime_type:
        return "opinion"
    else:
        return "document"

def format_file_size(size_bytes: int) -> str:
    """
    Formatuje rozmiar pliku w czytelnej formie.
    
    Args:
        size_bytes: Rozmiar w bajtach
        
    Returns:
        str: Sformatowany rozmiar (np. "1.5 MB")
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    size_index = 0
    size = float(size_bytes)
    
    while size >= 1024.0 and size_index < len(size_names) - 1:
        size /= 1024.0
        size_index += 1
    
    return f"{size:.1f} {size_names[size_index]}"
