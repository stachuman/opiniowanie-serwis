# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Application Overview

This is a FastAPI-based legal document management system specialized for Polish court opinions. It combines traditional and AI-based OCR processing with document management capabilities.

## Development Commands

### Environment Setup
```bash
# Create conda environment
conda env create -f environment.yml

# Install system dependencies (Ubuntu/Debian)
./inst.sh

# Activate environment
conda activate court-workflow
```

### Running the Application
```bash
# Development server (main entry point)
python app/main.py

# Alternative with uvicorn directly
uvicorn app.main:app --host 0.0.0.0 --port 80 --reload
```

### Database Management
```bash
# Database is initialized automatically on startup
# Database file: data.db (SQLite)
# No separate migration commands needed
```

## Architecture Overview

### Core Components
- **FastAPI application** (`app/main.py`) - Entry point with CUDA multiprocessing setup
- **SQLModel ORM** (`app/models.py`, `app/db.py`) - Database layer using SQLite
- **Background tasks** (`app/background_tasks.py`) - Async processing with Redis/RQ
- **OCR pipeline** (`tasks/ocr/`) - Multi-modal OCR using Tesseract, TrOCR, and Qwen2.5-VL

### Route Structure
- `/app/routes/documents.py` - Document CRUD operations
- `/app/routes/ocr.py` - OCR processing endpoints  
- `/app/routes/opinions.py` - Legal opinion management
- `/app/routes/preview.py` - Document preview functionality
- `/app/routes/upload.py` - File upload handling

### Key Services
- **OCR Manager** (`tasks/ocr_manager.py`) - Coordinates multiple OCR engines
- **LLM Service** (`app/llm_service.py`) - AI language model integration
- **Navigation System** (`app/navigation.py`) - Complex UI navigation logic
- **Document Utils** (`app/document_utils.py`) - File type detection and processing

## File Organization

### Storage Structure
- `/files/` - Document storage (UUID-based naming)
- `/files/history/` - Document version history
- `/static/` - Frontend assets (JavaScript, CSS, icons)
- `/templates/` - Jinja2 HTML templates

### Document Processing
- Documents are stored with UUID filenames for security
- Parent-child relationships supported (main documents with attachments)
- OCR status tracking: none/pending/running/done/fail
- Multiple OCR engines: Tesseract, TrOCR, Qwen2.5-VL-7B-Instruct

## Case Status Management (NEW)

### Configuration System
The application now uses a centralized configuration system for case statuses instead of hardcoded values:

- **`app/config/case_statuses.py`** - Main configuration file for all case statuses
- **Dynamic status system** - Supports adding new statuses without code changes
- **Default visibility control** - Each status can be set to show/hide by default in filters

### Current Status Configuration
```python
# Current statuses (can be extended):
k1    - Niekompletne dokumenty (default: visible)
k1.5  - Brak części dokumentów (default: visible) 
k2    - Komplet dokumentów (default: visible)
k2.5  - Word gotowy, niewysłany (default: visible)
k3    - Word z wyciągiem wysłany (default: hidden)
k4    - Archiwum (default: hidden)
```

### Adding New Statuses
To add a new case status, simply add a new `CaseStatus` entry in `app/config/case_statuses.py`:

```python
CaseStatus(
    code="k5",                    # Unique status code
    name="k5 – Status Name",      # Display name
    description="Status desc",    # Detailed description
    color="info",                 # Bootstrap color (danger, warning, success, etc.)
    icon="star-fill",            # Bootstrap icon name
    default_visible=True,        # Show in default filters
    sort_order=7                 # Display order
)
```

The system will automatically:
- Add the status to filter checkboxes
- Include it in sorting and search
- Apply correct colors and icons
- Handle default visibility in filters

### Status System Features
- **Flexible filtering** - Any combination of statuses can be filtered
- **Dynamic UI generation** - Frontend automatically adapts to new statuses
- **Consistent styling** - Colors and icons defined in one place
- **Default filter behavior** - Control which statuses show by default
- **Backward compatibility** - Existing templates and JS work with new statuses

## Important Technical Notes

### CUDA Configuration
- **Critical**: The application requires specific multiprocessing setup for CUDA
- `spawn` method is enforced in `app/main.py` before any imports
- CUDA environment variables are set: `CUDA_LAUNCH_BLOCKING=1`, `TORCH_USE_CUDA_DSA=1`

### OCR Pipeline
- Hybrid approach: Traditional OCR + AI-based OCR
- Qwen2.5-VL-7B-Instruct model for advanced document understanding
- Language support: Polish, English, Latin
- Background processing with progress tracking

### Database Schema
- Single `Document` model with hierarchical relationships
- OCR results stored as text fields with confidence scores
- Status tracking for long-running operations

## Frontend Architecture

### JavaScript Structure
- `/static/components/` - Reusable UI components
- `/static/pages/` - Page-specific JavaScript
- `/static/core/` - Common utilities (API client, modals)

### Key Components
- OCR Viewer (`ocr-viewer.js`) - Real-time OCR result display
- PDF Viewer - Full-featured PDF.js integration
- Text Editor - Document text editing and management

## Development Workflow

### No Traditional Testing Framework
- No pytest or unittest setup found
- Manual testing through web interface
- Debug endpoints available in routes

### Background Processing
- Redis-based task queue (custom implementation)
- Process isolation for CUDA operations
- Automatic cleanup and error recovery

## Environment Variables

- `DB_URL` - Database connection (defaults to sqlite:///data.db)
- CUDA-related variables set automatically in main.py

## Document Type Management (NEW)

### Configuration System
The application uses a centralized configuration system for document types, similar to case statuses:

- **`app/config/document_types.py`** - Main configuration file for all document types
- **Dynamic type system** - Supports adding new types without code changes
- **Default visibility control** - Each type can be set to show/hide by default in filters

### Current Document Type Configuration
```python
# Current document types (can be extended):
opinia                 - Opinia (primary, file-earmark-text icon)
postanowienie         - Postanowienie (primary, file-earmark icon)
protokol              - Protokoły przesłuchań i zarzuty (primary, file-earmark icon)
akta                  - Akta (secondary, folder2-open icon)
dokumentacja_medyczna - Dokumentacja medyczna (danger, heart-pulse icon)
wniosek              - Wniosek (info, file-earmark-plus icon)
zaswiadczenie        - Zaświadczenie (success, award icon)
inne                 - Inne (warning, file-earmark icon)
ocr_txt              - OCR TXT (secondary, file-earmark-text icon, hidden by default)
archiwalna_wersja    - Archiwalna wersja (secondary, archive icon, hidden by default)
```

### Adding New Document Types
To add a new document type, simply add a new `DocumentType` entry in `app/config/document_types.py`:

```python
DocumentType(
    code="new_type",             # Unique type code
    name="New Type Name",        # Display name
    description="Type desc",     # Detailed description
    color="success",             # Bootstrap color (primary, success, danger, etc.)
    icon="star-fill",           # Bootstrap icon name
    default_visible=True,       # Show in default filters
    sort_order=9               # Display order
)
```

The system will automatically:
- Update all dropdowns and forms
- Apply consistent styling and icons
- Handle backward compatibility with old string values
- Include it in filtering and search

### Document Type Features
- **Flexible configuration** - Easy to add, modify, or reorganize types
- **Dynamic UI generation** - Forms and dropdowns update automatically
- **Consistent styling** - Colors and icons defined in one place
- **Backward compatibility** - Old string-based types are converted automatically
- **Migration utility** - Safe conversion from legacy format to new codes

### Data Migration
Document types were migrated from old string format to new code-based system:
- **Migration script**: `app/migrations/migrate_document_types.py`
- **152 documents migrated successfully** with 100% success rate
- **Backward compatibility maintained** - supports both old and new formats
- **Migration features**: dry-run mode, rollback capability, statistics reporting

## Recent Changes Summary

### Document Type System Implementation (Latest)
- **Centralized configuration** in `app/config/document_types.py`
- **Dynamic type system** - removed hardcoded document type arrays
- **Extended type set** - includes system types like OCR TXT and archive versions
- **Configurable default filters** - system types hidden by default, user types visible
- **Template improvements** - dynamic dropdown generation with icons
- **Data migration completed** - all 152 existing documents successfully migrated
- **Backward compatibility** maintained while enabling future extensibility

### Case Status System Refactoring
- **Centralized configuration** in `app/config/case_statuses.py`
- **Dynamic status handling** - removed hardcoded k1-k4 parameters
- **Extended status set** - now includes k1.5 and k2.5 intermediate statuses
- **Configurable default filters** - k3 and k4 hidden by default, others visible
- **Template improvements** - dynamic checkbox generation and URL building
- **JavaScript updates** - flexible status checkbox handling
- **Backward compatibility** maintained while enabling future extensibility