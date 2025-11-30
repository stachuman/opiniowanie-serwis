# app/config/email_config.py
"""
Email configuration for sending documents from iPhone uploads.

SECURITY: Credentials loaded from environment variables.
Set these before running:
  export SMTP_USER="your-email@gmail.com"
  export SMTP_PASSWORD="your-app-password"
  export DEFAULT_EMAIL="recipient@example.com"
  export SERVER_URL="http://your-server-ip"
"""

import os

# ==================== EMAIL SETTINGS ====================

# Default recipient email (used if not provided by iPhone Shortcut)
# SECURITY: Load from environment variable
DEFAULT_EMAIL = os.getenv("DEFAULT_EMAIL", "your-email@example.com")

# Gmail SMTP configuration
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # TLS port

# SECURITY: Credentials from environment variables (NEVER commit these!)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Validation: Check if credentials are set
if not SMTP_USER or not SMTP_PASSWORD:
    import warnings
    warnings.warn(
        "⚠️  SMTP credentials not set! Email functionality will not work. "
        "Set SMTP_USER and SMTP_PASSWORD environment variables.",
        RuntimeWarning
    )

# Email sender details
EMAIL_FROM = f"Dokumentacja sądowa <{SMTP_USER}>"

# Server URL for document links (no trailing slash)
# SECURITY: Load from environment variable
SERVER_URL = os.getenv("SERVER_URL", "http://localhost")

# ==================== EMAIL TEMPLATES ====================

# Subject templates
EMAIL_SUBJECT_PDF = "Nowy dokument PDF - {filename}"
EMAIL_SUBJECT_OCR = "Dokument PDF z rozpoznanym tekstem - {filename}"

# Email body prefix (custom text at the beginning)
EMAIL_BODY_PREFIX = """Witaj,

Nowy dokument został przesłany z iPhone.

"""

# Email body for PDF only
EMAIL_BODY_PDF_TEMPLATE = """{prefix}
Nazwa pliku: {filename}
Data przesłania: {upload_time}

Podgląd dokumentu:
{document_url}

PDF w załączniku.

---
Wiadomość wygenerowana automatycznie przez Court System
"""

# Email body for PDF with OCR
EMAIL_BODY_OCR_TEMPLATE = """{prefix}
Nazwa pliku: {filename}
Data przesłania: {upload_time}

Podgląd dokumentu:
{document_url}

Rozpoznany tekst OCR:
{ocr_text}

PDF w załączniku.

---
Wiadomość wygenerowana automatycznie przez Court System
"""

# ==================== EMAIL OPTIONS ====================

# Valid email delivery options
EMAIL_OPTIONS = {
    "none": "Nie wysyłaj emaila",
    "pdf_only": "Wyślij tylko PDF",
    "pdf_with_ocr": "Wyślij PDF + tekst OCR (po zakończeniu OCR)"
}
