# app/config/email_config.py
"""
Email configuration for sending documents from iPhone uploads.
"""

# ==================== EMAIL SETTINGS ====================

# Default recipient email (used if not provided by iPhone Shortcut)
DEFAULT_EMAIL = "cgpsmapper@gmail.com"

# Gmail SMTP configuration
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # TLS port
SMTP_USER = "cgpsmapper@gmail.com"
SMTP_PASSWORD = "ggkx nqhz chhs iyjf"  # TODO: Add Gmail App Password here

# Email sender details
EMAIL_FROM = "Dokumentacja sądowa <cgpsmapper@gmail.com>"

# Server URL for document links (no trailing slash)
SERVER_URL = "http://192.168.1.218"

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
