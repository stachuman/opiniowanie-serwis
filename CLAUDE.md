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