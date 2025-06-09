# app/routes/__init__.py
"""
Moduł zawierający wszystkie routery aplikacji.
"""

from .opinions import router as opinions_router
from .documents import router as documents_router  
from .updates import router as updates_router
from .upload import router as upload_router
from .preview import router as preview_router
from .ocr import router as ocr_router

__all__ = [
    "opinions_router",
    "documents_router",
    "updates_router",
    "upload_router",
    "preview_router",
    "ocr_router"
]