# tasks/opinion_manager.py
"""
Manager for opinion-specific operations.
Handles deletion of empty opinias and validation logic.
"""

import logging
from dataclasses import dataclass
from typing import Optional, List

from sqlmodel import Session, select

from app.db import engine, FILES_DIR
from app.models import Document


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("opinion_manager")


# Custom exceptions
class ValidationError(Exception):
    """Raised when validation fails with specific actionable message."""
    pass


class DeletionError(Exception):
    """Raised when file deletion fails."""
    pass


@dataclass
class DeleteOpinionResult:
    """Result of deleting an opinion."""
    success: bool
    deleted_files_count: int = 0
    error_message: Optional[str] = None


@dataclass
class OpinionValidationResult:
    """Result of validating if opinion can be deleted."""
    can_delete: bool
    reason: str
    user_documents: List[Document]
    system_documents: List[Document]


class OpinionManager:
    """Manager for all opinion-specific operations."""

    @staticmethod
    def validate_opinia_can_be_deleted(opinia_id: int) -> OpinionValidationResult:
        """
        Validates if opinia can be deleted.

        An opinia can be deleted if:
        - It exists and is a main document
        - It has no user-uploaded attachments
        - System files (OCR TXT, archived versions) can exist and will be cascade-deleted

        Args:
            opinia_id: ID of the opinia to validate

        Returns:
            OpinionValidationResult with details about what can/cannot be deleted

        Raises:
            ValidationError: If opinia doesn't exist or isn't main document
        """
        with Session(engine) as session:
            opinia = session.get(Document, opinia_id)

            if not opinia:
                raise ValidationError(f"Opinia {opinia_id} not found")

            if not opinia.is_main:
                raise ValidationError(
                    f"Document {opinia_id} is not an opinia. "
                    f"Only main documents (opinias) can be deleted via this endpoint."
                )

            # Get all children
            all_children = session.exec(
                select(Document)
                .where(Document.parent_id == opinia_id)
                .order_by(Document.upload_time.desc())
            ).all()

            # Separate user documents from system-generated files
            # Include both new codes and legacy names for backward compatibility
            system_doc_types = [
                'ocr_txt', 'archiwalna_wersja',  # New codes
                'OCR TXT', 'Archiwalna wersja'   # Legacy names
            ]

            user_docs = []
            system_docs = []

            for doc in all_children:
                # Safely check doc_type (handle None or empty string)
                doc_type = (doc.doc_type or '').strip()

                if doc_type in system_doc_types:
                    system_docs.append(doc)
                else:
                    # Everything else is a user document (including empty/None doc_type)
                    user_docs.append(doc)

            # Can delete if no user documents
            if len(user_docs) > 0:
                # Build detailed error message
                doc_names = [d.original_filename for d in user_docs[:3]]
                msg = f"Opinia contains {len(user_docs)} document(s): {', '.join(doc_names)}"
                if len(user_docs) > 3:
                    msg += f" and {len(user_docs) - 3} more"
                msg += ". Move or delete them first."

                return OpinionValidationResult(
                    can_delete=False,
                    reason=msg,
                    user_documents=user_docs,
                    system_documents=system_docs
                )

            # Can delete - build warning message about system files
            if system_docs:
                msg = f"Will cascade-delete {len(system_docs)} system file(s): "
                sys_names = [d.doc_type for d in system_docs[:3]]
                msg += ", ".join(sys_names)
                if len(system_docs) > 3:
                    msg += f" and {len(system_docs) - 3} more"
            else:
                msg = "Opinia is empty and can be deleted"

            return OpinionValidationResult(
                can_delete=True,
                reason=msg,
                user_documents=[],
                system_documents=system_docs
            )

    @staticmethod
    def delete_empty_opinia(opinia_id: int) -> DeleteOpinionResult:
        """
        Deletes an empty opinia and cascade-deletes its system files.

        IMPORTANT: Must call validate_opinia_can_be_deleted() first and check can_delete!
        This function assumes validation already passed.

        Args:
            opinia_id: ID of the opinia to delete

        Returns:
            DeleteOpinionResult with count of deleted files

        Raises:
            DeletionError: If file deletion fails
            ValidationError: If validation was not performed or failed
        """
        # Re-validate to ensure state hasn't changed
        validation = OpinionManager.validate_opinia_can_be_deleted(opinia_id)

        if not validation.can_delete:
            raise ValidationError(
                f"Cannot delete opinia: {validation.reason}"
            )

        deleted_files = 0

        with Session(engine) as session:
            opinia = session.get(Document, opinia_id)

            # Delete physical file for opinia (fail fast if filesystem issue)
            stored_file = FILES_DIR / opinia.stored_filename
            try:
                if stored_file.exists():
                    stored_file.unlink()
                    deleted_files += 1
                    logger.info(f"Deleted opinia file: {stored_file}")
            except OSError as e:
                raise DeletionError(
                    f"Cannot delete file {opinia.stored_filename}: {e}. "
                    f"Fix filesystem permissions before retrying."
                )

            # Cascade-delete system files (OCR TXT, archived versions)
            for sys_doc in validation.system_documents:
                sys_file = FILES_DIR / sys_doc.stored_filename
                try:
                    if sys_file.exists():
                        sys_file.unlink()
                        deleted_files += 1
                        logger.info(f"Deleted system file: {sys_file}")
                except OSError as e:
                    # Log but don't fail - system files are less critical
                    logger.warning(f"Could not delete system file {sys_file}: {e}")

                # Delete system document record
                session.delete(sys_doc)
                logger.info(f"Deleted system document record: {sys_doc.id} ({sys_doc.doc_type})")

            # Delete opinia record last
            session.delete(opinia)
            session.commit()

            logger.info(
                f"Successfully deleted opinia {opinia_id} and {len(validation.system_documents)} "
                f"system documents ({deleted_files} files removed)"
            )

            return DeleteOpinionResult(
                success=True,
                deleted_files_count=deleted_files
            )


# Create singleton instance
opinion_manager = OpinionManager()
