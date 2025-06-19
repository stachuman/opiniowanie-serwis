#!/usr/bin/env python3
"""
Migration script to convert old document types to new code-based system

This script converts existing documents from old string-based doc_type values
to new code-based values as defined in app/config/document_types.py

Usage:
    python app/migrations/migrate_document_types.py [--dry-run]
"""

import sys
import os
from pathlib import Path

# Add app root to path
app_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_root))

from sqlmodel import Session, select
from app.db import engine
from app.models import Document
from app.config.document_types import DocumentTypeConfig


def migrate_document_types(dry_run=False):
    """
    Migrate old document type values to new code-based system
    
    Args:
        dry_run (bool): If True, only show what would be changed without actually changing it
    """
    print("🔄 Starting document type migration...")
    
    # Get legacy mapping
    legacy_mapping = DocumentTypeConfig.get_legacy_name_to_code_mapping()
    
    print(f"📋 Legacy mapping: {legacy_mapping}")
    
    with Session(engine) as session:
        # Find documents with old doc_type values
        documents_query = select(Document).where(Document.doc_type.is_not(None))
        documents = session.exec(documents_query).all()
        
        changes_made = 0
        total_documents = len(documents)
        
        print(f"📊 Found {total_documents} documents with doc_type set")
        
        for doc in documents:
            old_value = doc.doc_type
            
            # Skip if already using new code format
            if DocumentTypeConfig.get_type_by_code(old_value):
                continue
                
            # Try to find mapping
            if old_value in legacy_mapping:
                new_value = legacy_mapping[old_value]
                
                if dry_run:
                    print(f"🔍 Document {doc.id}: '{old_value}' -> '{new_value}' (DRY RUN)")
                else:
                    doc.doc_type = new_value
                    session.add(doc)
                    print(f"✅ Document {doc.id}: '{old_value}' -> '{new_value}'")
                
                changes_made += 1
            else:
                print(f"⚠️  Document {doc.id}: Unknown doc_type '{old_value}' - needs manual review")
        
        if not dry_run and changes_made > 0:
            session.commit()
            print(f"💾 Committed {changes_made} changes to database")
        elif dry_run:
            print(f"🔍 DRY RUN: Would change {changes_made} documents")
        else:
            print("✨ No changes needed")
    
    print("✅ Migration completed!")
    return changes_made


def rollback_document_types(dry_run=False):
    """
    Rollback document types from codes back to legacy names
    
    Args:
        dry_run (bool): If True, only show what would be changed without actually changing it
    """
    print("🔄 Starting document type rollback...")
    
    # Get reverse mapping
    reverse_mapping = DocumentTypeConfig.get_code_to_legacy_name_mapping()
    
    print(f"📋 Reverse mapping: {reverse_mapping}")
    
    with Session(engine) as session:
        # Find documents with new code values
        documents_query = select(Document).where(Document.doc_type.is_not(None))
        documents = session.exec(documents_query).all()
        
        changes_made = 0
        total_documents = len(documents)
        
        print(f"📊 Found {total_documents} documents with doc_type set")
        
        for doc in documents:
            old_value = doc.doc_type
            
            # Try to find reverse mapping
            if old_value in reverse_mapping:
                new_value = reverse_mapping[old_value]
                
                if dry_run:
                    print(f"🔍 Document {doc.id}: '{old_value}' -> '{new_value}' (DRY RUN)")
                else:
                    doc.doc_type = new_value
                    session.add(doc)
                    print(f"✅ Document {doc.id}: '{old_value}' -> '{new_value}'")
                
                changes_made += 1
            else:
                print(f"ℹ️  Document {doc.id}: doc_type '{old_value}' already in legacy format")
        
        if not dry_run and changes_made > 0:
            session.commit()
            print(f"💾 Committed {changes_made} changes to database")
        elif dry_run:
            print(f"🔍 DRY RUN: Would change {changes_made} documents")
        else:
            print("✨ No changes needed")
    
    print("✅ Rollback completed!")
    return changes_made


def show_document_type_stats():
    """Show current document type statistics"""
    print("📊 Current document type statistics:")
    
    with Session(engine) as session:
        documents_query = select(Document).where(Document.doc_type.is_not(None))
        documents = session.exec(documents_query).all()
        
        type_counts = {}
        for doc in documents:
            doc_type = doc.doc_type
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        
        print(f"📋 Total documents with doc_type: {len(documents)}")
        
        for doc_type, count in sorted(type_counts.items()):
            # Check if it's a new code
            config_type = DocumentTypeConfig.get_type_by_code(doc_type)
            if config_type:
                print(f"  ✅ {doc_type} ({config_type.name}): {count} documents")
            else:
                print(f"  ⚠️  {doc_type}: {count} documents (legacy format)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate document types to new code-based system")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without making changes")
    parser.add_argument("--rollback", action="store_true", help="Rollback codes to legacy names")
    parser.add_argument("--stats", action="store_true", help="Show current document type statistics")
    
    args = parser.parse_args()
    
    if args.stats:
        show_document_type_stats()
    elif args.rollback:
        rollback_document_types(args.dry_run)
    else:
        migrate_document_types(args.dry_run)