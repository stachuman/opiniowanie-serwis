# app/email_queue.py
"""
In-memory queue for pending email notifications.
Stores email addresses for documents waiting for OCR completion.
No database storage required.
"""

from typing import Dict, Optional

# In-memory storage: {document_id: email_address}
_pending_email_notifications: Dict[int, str] = {}


def register_email_notification(document_id: int, email: str) -> None:
    """
    Register an email to be sent when OCR completes for a document.

    Args:
        document_id: Document ID
        email: Email address to notify
    """
    _pending_email_notifications[document_id] = email
    print(f"📧 Registered email notification for document #{document_id}: {email}")


def get_pending_email(document_id: int) -> Optional[str]:
    """
    Get pending email for a document (if any).

    Args:
        document_id: Document ID

    Returns:
        Email address or None if no notification registered
    """
    return _pending_email_notifications.get(document_id)


def clear_email_notification(document_id: int) -> None:
    """
    Clear email notification after it's been sent.

    Args:
        document_id: Document ID
    """
    if document_id in _pending_email_notifications:
        email = _pending_email_notifications.pop(document_id)
        print(f"📧 Cleared email notification for document #{document_id}: {email}")


def get_all_pending() -> Dict[int, str]:
    """Get all pending email notifications (for debugging)."""
    return _pending_email_notifications.copy()
