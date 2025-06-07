# app/routes/__init__.py
"""
Pakiet routerów dla Court Workflow.
"""

from .opinions import router as opinions_router
from .documents import router as documents_router
from .updates import router as updates_router

__all__ = ["opinions_router", "documents_router", "updates_router"]
