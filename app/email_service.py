# app/email_service.py
"""
Email service for sending documents from iPhone uploads.
Uses Gmail SMTP to send PDF documents with optional OCR text.
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from pathlib import Path
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select
from app.db import engine, FILES_DIR
from app.models import Document
from app.config.email_config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    EMAIL_FROM,
    SERVER_URL,
    EMAIL_SUBJECT_PDF,
    EMAIL_SUBJECT_OCR,
    EMAIL_BODY_PREFIX,
    EMAIL_BODY_PDF_TEMPLATE,
    EMAIL_BODY_OCR_TEMPLATE,
)

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending document emails."""

    @staticmethod
    def _send_email(
        to_email: str,
        subject: str,
        body: str,
        attachment_path: Optional[Path] = None,
        attachment_name: Optional[str] = None
    ) -> bool:
        """
        Send email via Gmail SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Email body (plain text)
            attachment_path: Optional path to PDF attachment
            attachment_name: Optional name for attachment

        Returns:
            True if email sent successfully, False otherwise
        """
        # Validate SMTP password is configured
        if not SMTP_PASSWORD:
            logger.error("SMTP_PASSWORD not configured in email_config.py")
            return False

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = EMAIL_FROM
            msg['To'] = to_email
            msg['Subject'] = subject

            # Add body
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            # Add PDF attachment if provided
            if attachment_path and attachment_path.exists():
                with open(attachment_path, 'rb') as f:
                    pdf_attachment = MIMEApplication(f.read(), _subtype='pdf')
                    pdf_attachment.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=attachment_name or attachment_path.name
                    )
                    msg.attach(pdf_attachment)

            # Connect to Gmail SMTP server
            logger.info(f"Connecting to {SMTP_HOST}:{SMTP_PORT}...")
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()  # Upgrade to secure connection

            # Login
            logger.info(f"Logging in as {SMTP_USER}...")
            server.login(SMTP_USER, SMTP_PASSWORD)

            # Send email
            logger.info(f"Sending email to {to_email}...")
            server.send_message(msg)
            server.quit()

            logger.info(f"✅ Email sent successfully to {to_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ SMTP authentication failed: {e}")
            logger.error("   Make sure SMTP_PASSWORD is a valid Gmail App Password")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP error sending email: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error sending email: {e}", exc_info=True)
            return False

    @staticmethod
    def send_pdf_email(document_id: int, to_email: str) -> bool:
        """
        Send PDF document via email immediately after upload.

        Args:
            document_id: ID of the PDF document
            to_email: Recipient email address

        Returns:
            True if email sent successfully, False otherwise
        """
        logger.info(f"📧 Preparing to send PDF email for document #{document_id} to {to_email}")

        with Session(engine) as session:
            doc = session.get(Document, document_id)
            if not doc:
                logger.error(f"Document #{document_id} not found")
                return False

            # Get PDF file path
            pdf_path = FILES_DIR / doc.stored_filename
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return False

            # Build document URL
            document_url = f"{SERVER_URL}/document/{document_id}/pdf-viewer"

            # Format upload time
            upload_time = doc.upload_time.strftime("%Y-%m-%d %H:%M:%S") if doc.upload_time else "N/A"

            # Build email body
            body = EMAIL_BODY_PDF_TEMPLATE.format(
                prefix=EMAIL_BODY_PREFIX,
                filename=doc.original_filename,
                upload_time=upload_time,
                document_url=document_url
            )

            # Build subject
            subject = EMAIL_SUBJECT_PDF.format(filename=doc.original_filename)

            # Send email
            return EmailService._send_email(
                to_email=to_email,
                subject=subject,
                body=body,
                attachment_path=pdf_path,
                attachment_name=doc.original_filename
            )

    @staticmethod
    def send_pdf_with_ocr_email(document_id: int, to_email: str) -> bool:
        """
        Send PDF document with OCR text via email after OCR completes.

        Args:
            document_id: ID of the PDF document
            to_email: Recipient email address

        Returns:
            True if email sent successfully, False otherwise
        """
        logger.info(f"📧 Preparing to send PDF+OCR email for document #{document_id} to {to_email}")

        with Session(engine) as session:
            doc = session.get(Document, document_id)
            if not doc:
                logger.error(f"Document #{document_id} not found")
                return False

            # Get PDF file path
            pdf_path = FILES_DIR / doc.stored_filename
            if not pdf_path.exists():
                logger.error(f"PDF file not found: {pdf_path}")
                return False

            # Get OCR text from child document
            ocr_txt_query = select(Document).where(
                Document.ocr_parent_id == document_id,
                Document.doc_type == "ocr_txt"
            )
            ocr_txt_doc = session.exec(ocr_txt_query).first()

            # Get OCR text content
            ocr_text = "Brak tekstu OCR"
            if ocr_txt_doc:
                ocr_file_path = FILES_DIR / ocr_txt_doc.stored_filename
                if ocr_file_path.exists():
                    try:
                        ocr_text = ocr_file_path.read_text(encoding='utf-8')
                    except Exception as e:
                        logger.error(f"Failed to read OCR text: {e}")
                        ocr_text = f"Błąd odczytu OCR: {str(e)}"

            # Build document URL
            document_url = f"{SERVER_URL}/document/{document_id}/pdf-viewer"

            # Format upload time
            upload_time = doc.upload_time.strftime("%Y-%m-%d %H:%M:%S") if doc.upload_time else "N/A"

            # Build email body
            body = EMAIL_BODY_OCR_TEMPLATE.format(
                prefix=EMAIL_BODY_PREFIX,
                filename=doc.original_filename,
                upload_time=upload_time,
                document_url=document_url,
                ocr_text=ocr_text
            )

            # Build subject
            subject = EMAIL_SUBJECT_OCR.format(filename=doc.original_filename)

            # Send email
            return EmailService._send_email(
                to_email=to_email,
                subject=subject,
                body=body,
                attachment_path=pdf_path,
                attachment_name=doc.original_filename
            )


# Singleton instance
email_service = EmailService()
