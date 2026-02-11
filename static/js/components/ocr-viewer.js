/**
 * Wspólny komponent OCR Viewer
 * Zunifikuje kod z pdf_view_with_selection.html i image_view_with_selection.html
 */

class OcrViewer {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        if (!this.container) {
            throw new Error(`Container ${containerId} not found`);
        }

        // Konfiguracja
        this.config = {
            docId: options.docId,
            docType: options.docType || 'pdf', // 'pdf' lub 'image'
            documentHasFullOcr: options.documentHasFullOcr || false,
            parentId: options.parentId || null,
            ...options
        };

        // Stan aplikacji
        this.state = {
            selectionMode: false, // toggled by "rozpoznaj fragment" button
            isSelecting: false,
            startX: 0,
            startY: 0,
            endX: 0,
            endY: 0,
            currentPage: 1,
            totalPages: 1,
            scale: 1.5,
            pageRendering: false,
            pageNumPending: null,
            ocrText: {}, // Cache tekstu OCR per strona
            fullOcrText: null, // Pełny tekst OCR (wszystkie strony)
            layoutCache: {}, // Cache layout data per page
            currentFullPageOcr: null,
            currentViewport: null, // Dla PDF
            rotation: 0 // Kąt obrotu obrazu (0, 90, 180, 270)
        };

        // Elementy DOM
        this.elements = {};

        // Stan tekstu
        this.textState = {
            originalText: ''
        };

        this.init();
    }

    /**
     * Inicjalizacja komponentu
     */
    async init() {
        this.setupDOM();
        this.bindEvents();

        if (this.config.docType === 'pdf') {
            await this.initPdfViewer();
        } else {
            await this.initImageViewer();
        }

    }

    /**
     * Konfiguracja struktury DOM
     */
    setupDOM() {
        // Znajdź kluczowe elementy
        this.elements = {
            imageContainer: this.container.querySelector('#imageContainer') || this.container.querySelector('#pdfContainer'),
            canvas: this.container.querySelector('#pdfCanvas') || this.container.querySelector('#mainImage'),
            textOverlayLayer: this.container.querySelector('#textOverlayLayer'),
            selectionOverlay: this.container.querySelector('#selectionOverlay'),
            ocrLoader: this.container.querySelector('#ocrLoader'),
            textDisplay: this.container.querySelector('#textDisplay'),
            copyFullBtn: this.container.querySelector('#copyFullBtn'),

            // PDF specific
            prevPageBtn: this.container.querySelector('#prevPage'),
            nextPageBtn: this.container.querySelector('#nextPage'),
            pageInfo: this.container.querySelector('#pageInfo'),
            
            // Rotation controls
            rotateLeftBtn: document.querySelector('#rotateLeft'),
            rotateRightBtn: document.querySelector('#rotateRight'),
            resetRotationBtn: document.querySelector('#resetRotation')
        };

        // Sprawdź czy wszystkie wymagane elementy istnieją
        const required = ['imageContainer', 'canvas', 'textDisplay'];
        for (const key of required) {
            if (!this.elements[key]) {
                console.warn(`Element ${key} not found in container`);
            }
        }
    }

    /**
     * Bindowanie event handlerów
     */
    bindEvents() {
        // Zaznaczanie fragmentów
        if (this.elements.imageContainer) {
            this.elements.imageContainer.addEventListener('mousedown', this.handleMouseDown.bind(this));
            this.elements.imageContainer.addEventListener('mousemove', this.handleMouseMove.bind(this));
            this.elements.imageContainer.addEventListener('mouseup', this.handleMouseUp.bind(this));
        }

        // Nawigacja PDF
        if (this.elements.prevPageBtn) {
            this.elements.prevPageBtn.addEventListener('click', this.prevPage.bind(this));
        }
        if (this.elements.nextPageBtn) {
            this.elements.nextPageBtn.addEventListener('click', this.nextPage.bind(this));
        }

        // Kopiowanie tekstu - obsługiwane przez clipboard.js globalnie przez data-copy-target
        // Przycisk ma atrybut data-copy-target="#textDisplay"

        // Rotation controls
        if (this.elements.rotateLeftBtn) {
            this.elements.rotateLeftBtn.addEventListener('click', () => this.rotateImage(-90));
        }
        if (this.elements.rotateRightBtn) {
            this.elements.rotateRightBtn.addEventListener('click', () => this.rotateImage(90));
        }
        if (this.elements.resetRotationBtn) {
            this.elements.resetRotationBtn.addEventListener('click', () => this.resetRotation());
        }

        // Skróty klawiszowe
        document.addEventListener('keydown', this.handleKeyboard.bind(this));

        // Resize
        window.addEventListener('resize', this.handleResize.bind(this));
    }

    /**
     * Inicjalizacja PDF viewer
     */
    async initPdfViewer() {
        if (typeof pdfjsLib === 'undefined') {
            console.error('PDF.js not loaded');
            return;
        }

        try {
            const pdfUrl = `/document/${this.config.docId}/preview`;
            this.pdfDoc = await pdfjsLib.getDocument(pdfUrl).promise;
            this.state.totalPages = this.pdfDoc.numPages;

            this.updatePageInfo();
            await this.renderPage(1);

        } catch (error) {
            console.error('Error loading PDF:', error);
            this.showError('Nie udało się załadować PDF');
        }
    }

    /**
     * Inicjalizacja Image viewer
     */
    async initImageViewer() {
        if (this.elements.canvas && this.elements.canvas.tagName === 'IMG') {
            this.elements.canvas.onload = () => {
                this.setupImageInteraction();
                // DODANE: Załaduj OCR po załadowaniu obrazu
                this.loadPageOcr(1);
            };

            if (this.elements.canvas.complete) {
                this.setupImageInteraction();
                // DODANE: Załaduj OCR jeśli obraz już jest załadowany
                this.loadPageOcr(1);
            }
        } else {
            // DODANE: Fallback - załaduj OCR nawet jeśli nie ma elementu canvas
            setTimeout(() => {
                this.loadPageOcr(1);
            }, 100);
        }
    }

    /**
     * Konfiguracja interakcji z obrazem
     */
    setupImageInteraction() {
        if (this.elements.imageContainer) {
            this.elements.imageContainer.style.display = 'flex';
            this.elements.imageContainer.style.justifyContent = 'center';
            this.elements.imageContainer.style.alignItems = 'flex-start';
        }
    }

    /**
     * Renderowanie strony PDF
     */
    async renderPage(num) {
  if (!this.pdfDoc) return;

  this.state.pageRendering = true;

  try {
    const page = await this.pdfDoc.getPage(num);
    const viewport = page.getViewport({scale: this.state.scale});
    this.state.currentViewport = viewport;

    // Ustaw wymiary canvas
    const canvas = this.elements.canvas;
    canvas.height = viewport.height;
    canvas.width = viewport.width;

    // Renderuj
    const ctx = canvas.getContext('2d');
    const renderContext = {
      canvasContext: ctx,
      viewport: viewport
    };

    await page.render(renderContext).promise;

    this.state.pageRendering = false;
    this.state.currentPage = num;

    if (this.state.pageNumPending !== null) {
      this.renderPage(this.state.pageNumPending);
      this.state.pageNumPending = null;
    }

    this.updatePageInfo();
    await this.loadPageOcr(num);

    // Render selectable text overlay from layout data
    this.renderTextOverlay(num);

    // NOWE: Synchronizuj przewijanie tekstu z aktualną stroną
    this.syncTextScrollWithPage(num);

  } catch (error) {
    console.error('Error rendering page:', error);
    this.state.pageRendering = false;
  }
}

syncTextScrollWithPage(pageNumber) {
  // Sprawdź czy PdfViewerManager istnieje i ma funkcję synchronizacji
  if (window.pdfViewerManager && typeof window.pdfViewerManager.scrollToPageInText === 'function') {
    // Krótkie opóźnienie żeby tekst zdążył się załadować
    setTimeout(() => {
      window.pdfViewerManager.scrollToPageInText(pageNumber);
    }, 300);
  }
}

    /**
     * Nawigacja - poprzednia strona
     */
    prevPage() {
  if (this.state.currentPage <= 1) return;

  if (this.state.pageRendering) {
    this.state.pageNumPending = this.state.currentPage - 1;
  } else {
    this.renderPage(this.state.currentPage - 1);
  }
  this.hideSelection();
}

nextPage() {
  if (this.state.currentPage >= this.state.totalPages) return;

  if (this.state.pageRendering) {
    this.state.pageNumPending = this.state.currentPage + 1;
  } else {
    this.renderPage(this.state.currentPage + 1);
  }
  this.hideSelection();
}


    /**
     * Aktualizacja informacji o stronie
     */
    updatePageInfo() {
        if (this.elements.pageInfo) {
            this.elements.pageInfo.textContent = `Strona ${this.state.currentPage} z ${this.state.totalPages}`;
        }
    }

    /**
     * Toggle selection mode for fragment OCR
     */
    setSelectionMode(on) {
        this.state.selectionMode = on;
        const container = this.elements.imageContainer;
        if (container) {
            container.style.cursor = on ? 'crosshair' : '';
        }
        // Update button state
        const btn = document.getElementById('fragmentOcrBtn');
        if (btn) {
            btn.classList.toggle('active', on);
            btn.classList.toggle('btn-outline-warning', !on);
            btn.classList.toggle('btn-warning', on);
        }
    }

    /**
     * Obsługa rozpoczęcia zaznaczania
     */
    handleMouseDown(e) {
        if (!this.state.selectionMode) return;
        e.preventDefault();
        this.state.isSelecting = true;

        const coords = this.calculateCoordinates(e.clientX, e.clientY);
        this.state.startX = coords.x;
        this.state.startY = coords.y;

        this.hideSelection();
    }

    /**
     * Obsługa przeciągania zaznaczenia
     */
    handleMouseMove(e) {
        if (!this.state.isSelecting) return;

        const coords = this.calculateCoordinates(e.clientX, e.clientY);
        this.state.endX = coords.x;
        this.state.endY = coords.y;

        this.updateSelectionDisplay();
    }

    /**
     * Obsługa zakończenia zaznaczania
     */
    handleMouseUp(e) {
        if (!this.state.isSelecting) return;

        this.state.isSelecting = false;

        const coords = this.calculateCoordinates(e.clientX, e.clientY);
        this.state.endX = coords.x;
        this.state.endY = coords.y;

        // Sprawdź czy zaznaczenie jest wystarczająco duże
        if (Math.abs(this.state.endX - this.state.startX) < 10 ||
            Math.abs(this.state.endY - this.state.startY) < 10) {
            this.hideSelection();
            return;
        }

        this.performOcrSelection();
    }

    /**
     * Przeliczanie współrzędnych
     */
    calculateCoordinates(clientX, clientY) {
        const canvas = this.elements.canvas;
        const rect = canvas.getBoundingClientRect();

        if (this.config.docType === 'pdf') {
            // Dla PDF uwzględnij skalowanie canvas
            const scaleX = canvas.width / rect.width;
            const scaleY = canvas.height / rect.height;

            const canvasX = (clientX - rect.left) * scaleX;
            const canvasY = (clientY - rect.top) * scaleY;

            return {
                x: canvasX,
                y: canvasY
            };
        } else {
            // Dla obrazów - zwracamy surowe współrzędne w układzie przeglądarki
            // Transformacja dla OCR będzie wykonana później w performOcrSelection()
            let imageX = clientX - rect.left;
            let imageY = clientY - rect.top;

            console.log(`🔍 DEBUG calculateCoordinates - rotation: ${this.state.rotation}°`);
            console.log(`  Mouse: (${clientX}, ${clientY}), Rect: (${rect.left}, ${rect.top})`);
            console.log(`  ImageXY w układzie przeglądarki: (${imageX}, ${imageY})`);

            return {
                x: Math.max(0, Math.min(rect.width, imageX)),
                y: Math.max(0, Math.min(rect.height, imageY))
            };
        }
    }

    /**
     * Aktualizacja wyświetlania zaznaczenia
     */
    updateSelectionDisplay() {
        if (!this.elements.selectionOverlay) return;

        const canvas = this.elements.canvas;
        let left, top, width, height;

        if (this.config.docType === 'pdf') {
            const rect = canvas.getBoundingClientRect();
            const cssScaleX = rect.width / canvas.width;
            const cssScaleY = rect.height / canvas.height;

            left = Math.min(this.state.startX, this.state.endX) * cssScaleX;
            top = Math.min(this.state.startY, this.state.endY) * cssScaleY;
            width = Math.abs(this.state.endX - this.state.startX) * cssScaleX;
            height = Math.abs(this.state.endY - this.state.startY) * cssScaleY;
        } else {
            // Dla obrazów - współrzędne są relative do obrazu, ale overlay jest relative do wrapper
            // Pobierz pozycje elementów
            const rect = canvas.getBoundingClientRect();
            const wrapper = canvas.parentElement; // imageWrapper
            const wrapperRect = wrapper.getBoundingClientRect();
            
            // Offset obrazu względem wrapper (gdy obraz jest wyśrodkowany w wrapper)
            const offsetX = rect.left - wrapperRect.left;
            const offsetY = rect.top - wrapperRect.top;
            
            // Współrzędne mouse + offset obrazu = pozycja w wrapper
            left = Math.min(this.state.startX, this.state.endX) + offsetX;
            top = Math.min(this.state.startY, this.state.endY) + offsetY;
            width = Math.abs(this.state.endX - this.state.startX);
            height = Math.abs(this.state.endY - this.state.startY);
            
            console.log(`🔍 Image offset in wrapper: (${offsetX}, ${offsetY})`);
            console.log(`🔍 Final overlay position: (${left}, ${top}) ${width}x${height}, rotation: ${this.state.rotation}°`);
        }

        // WAŻNE: Pozycjonowanie względem imageWrapper, nie kontenera!
        this.elements.selectionOverlay.style.left = `${left}px`;
        this.elements.selectionOverlay.style.top = `${top}px`;
        this.elements.selectionOverlay.style.width = `${width}px`;
        this.elements.selectionOverlay.style.height = `${height}px`;
        this.elements.selectionOverlay.style.display = 'block';
    }

    /**
     * Ukrywa zaznaczenie
     */
    hideSelection() {
        if (this.elements.selectionOverlay) {
            this.elements.selectionOverlay.style.display = 'none';
        }
    }

    /**
     * Wykonuje OCR na zaznaczonym fragmencie
     */
    async performOcrSelection() {
        this.setSelectionMode(false);
        this.showLoader('Rozpoznawanie tekstu fragmentu...');

        try {
            // Oblicz znormalizowane współrzędne (0-1)
            const canvas = this.elements.canvas;
            const rect = canvas.getBoundingClientRect(); // Zawsze pobierz rect
            let normCoords;

            if (this.config.docType === 'pdf') {
                normCoords = {
                    x1: Math.min(this.state.startX, this.state.endX) / canvas.width,
                    y1: Math.min(this.state.startY, this.state.endY) / canvas.height,
                    x2: Math.max(this.state.startX, this.state.endX) / canvas.width,
                    y2: Math.max(this.state.startY, this.state.endY) / canvas.height
                };
            } else {
                // Debug info dla obrazów
                console.log('🔍 DEBUG - Image selection coordinates:');
                console.log('  Canvas getBoundingClientRect:', rect);
                console.log('  Canvas naturalWidth/Height:', canvas.naturalWidth, 'x', canvas.naturalHeight);
                console.log('  Mouse coords:', this.state.startX, this.state.startY, '->', this.state.endX, this.state.endY);
                console.log('  Rotation:', this.state.rotation);
                
                normCoords = {
                    x1: Math.min(this.state.startX, this.state.endX) / rect.width,
                    y1: Math.min(this.state.startY, this.state.endY) / rect.height,
                    x2: Math.max(this.state.startX, this.state.endX) / rect.width,
                    y2: Math.max(this.state.startY, this.state.endY) / rect.height
                };
                
                console.log('  Normalized coords:', normCoords);
            }

            // UPROSZCZONE: Wyślij surowe współrzędne + rotację do backend
            console.log(`🔍 Wysyłanie surowych współrzędnych do backend z rotacją ${this.state.rotation}°`);
            console.log(`🔍 Normalized coords:`, normCoords);
            
            // Backend sam obsłuży transformację współrzędnych
            let finalCoords = normCoords;

            const data = {
                page: this.state.currentPage,
                x1: finalCoords.x1,
                y1: finalCoords.y1,
                x2: finalCoords.x2,
                y2: finalCoords.y2,
                rotation: this.state.rotation, // Wyślij informację o obrocie
                // DODANE: Wyślij informację o rozmiarach obrazu które frontend widzi
                frontend_image_width: canvas.naturalWidth || rect.width,
                frontend_image_height: canvas.naturalHeight || rect.height,
                display_width: rect.width,
                display_height: rect.height,
                skip_pdf_embed: true
            };

            const result = await window.apiClient.ocrSelection(this.config.docId, data);

            this.hideLoader();

            if (result.success) {
                this.showFragmentResult(result.text);
            } else {
                throw new Error(result.error || 'Nie udało się rozpoznać tekstu');
            }

        } catch (error) {
            this.hideLoader();
            this.showFragmentResult(`Błąd: ${error.message}`);
        }
    }

    /**
     * Pokazuje wynik OCR fragmentu
     */
    showFragmentResult(text) {
        window.modalManager.showFragmentText(text, () => this.addToFullText(text));
    }

    /**
     * Parsuje pełny tekst OCR na poszczególne strony
     * Rozdziela po markerach === Strona X ===
     */
    parseOcrPages(fullText) {
        const pages = {};
        const pattern = /^=== Strona (\d+) ===$/gm;
        let match, lastIndex = 0, lastPage = null;

        while ((match = pattern.exec(fullText)) !== null) {
            if (lastPage !== null) {
                pages[lastPage] = fullText.substring(lastIndex, match.index).trim();
            }
            lastPage = parseInt(match[1]);
            lastIndex = match.index + match[0].length;
        }
        if (lastPage !== null) {
            pages[lastPage] = fullText.substring(lastIndex).trim();
        }
        // Fallback: jeśli nie znaleziono markerów, cały tekst = strona 1
        if (Object.keys(pages).length === 0 && fullText.trim()) {
            pages[1] = fullText.trim();
        }
        return pages;
    }

    /**
     * Aktualizuje cache OCR dla wszystkich stron
     * Parsuje pełny tekst na poszczególne strony po markerach === Strona X ===
     */
    updateOcrCacheForAllPages(text) {
        // Parsuj tekst na strony
        this.state.ocrText = this.parseOcrPages(text);

        // Zachowaj pełny tekst
        this.state.fullOcrText = text;
        this.state.currentFullPageOcr = text;

        const pageCount = Object.keys(this.state.ocrText).length;
        console.log(`OCR cache zaktualizowany: ${pageCount} stron sparsowanych`);
    }

    /**
     * Dodaje tekst fragmentu do pełnego tekstu
     */
    async addToFullText(fragmentText) {
        const currentFullText = this.elements.textDisplay.textContent;

        let newFullText;
        if (currentFullText && currentFullText.trim() && !currentFullText.includes('Brak pełnego OCR')) {
            newFullText = currentFullText + '\n\n--- Dodany fragment ---\n' + fragmentText;
        } else {
            newFullText = fragmentText;
        }

        try {
            // ZMIANA: Najpierw aktualizuj wyświetlanie
            this.updateDisplayText(newFullText);

            // ZMIANA: Automatycznie zapisz na serwer
            const result = await window.apiClient.updateOcrText(this.config.docId, newFullText);

            if (result.success) {
                // ZMIANA: Zaktualizuj cache dla WSZYSTKICH stron (nie tylko bieżącej)
                this.updateOcrCacheForAllPages(newFullText);

                // ZMIANA: Powiadom TextEditor o zmianach (jeśli istnieje)
                if (window.textEditor) {
                    window.textEditor.setText(newFullText);
                    // Oznacz jako zapisane (bez zmian)
                    window.textEditor.state.textChanged = false;
                    window.textEditor.state.originalText = newFullText;
                }

                window.alertManager.showOcrSuccess(
                    'Fragment dodany i zapisany automatycznie',
                    result.ocr_doc_id,
                    this.config.docId,
                    this.config.parentId
                );
            } else {
                throw new Error(result.error || 'Nieznany błąd');
            }

        } catch (error) {
            // W przypadku błędu, cofnij zmianę w wyświetlaniu
            this.updateDisplayText(currentFullText);
            window.alertManager.error('Nie udało się zapisać tekstu: ' + error.message);
        }
    }

    /**
     * Ładuje OCR dla strony
     */
    async loadPageOcr(page) {
        // Cache hit — fullOcrText was already fetched (strict null check: "" is valid)
        if (this.state.fullOcrText !== null) {
            const pageText = this.state.ocrText[page] || '';
            this.updateDisplayText(pageText);
            return;
        }

        this.showTextLoader();

        try {
            // Always try to sync with server first
            const serverSyncSuccess = await this.syncWithServer();

            if (!serverSyncSuccess) {
                if (this.config.documentHasFullOcr) {
                    // OCR done but no text file yet — try full-page OCR
                    await this.performFullPageOcr(page);
                } else {
                    this.setupInitialMessage();
                }
            }
        } catch (error) {
            console.error('Error loading page OCR:', error);
            this.showTextError('Nie udało się załadować tekstu OCR');
        }
    }

    /**
     * Wykonuje OCR dla całej strony
     */
    async performFullPageOcr(page) {
        const data = {
            page: page,
            x1: 0, y1: 0, x2: 1, y2: 1
        };

        try {
            const result = await window.apiClient.ocrSelection(this.config.docId, data);

            if (result.success) {
                this.state.ocrText[page] = result.text;
                this.state.currentFullPageOcr = result.text;
                this.updateDisplayText(result.text);
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            this.showTextError('Nie udało się pobrać tekstu OCR: ' + error.message);
        }
    }

    

    /**
     * Synchronizacja z serwerem
     */
    /**
     * Synchronizacja z serwerem z lepszym cache management
     * ZMIENIONA WERSJA - aktualizuje cache dla wszystkich stron
     */
    async syncWithServer() {
        try {
            const result = await window.apiClient.getOcrText(this.config.docId);

            if (result.success && (result.has_ocr || result.has_text)) {
                const text = result.text || '';

                this.updateOcrCacheForAllPages(text);

                // Wyświetl tekst tylko bieżącej strony
                const pageText = this.state.ocrText[this.state.currentPage] || '';
                console.log(`syncWithServer: strona ${this.state.currentPage}, pageText=${pageText.length} znaków (fullText=${text.length})`);
                this.updateDisplayText(pageText);

                if (text.trim()) {
                    window.alertManager.showSyncInfo();
                }
                return true;
            }
            return false;
        } catch (error) {
            console.warn('Nie udało się zsynchronizować z serwerem:', error);
            return false;
        }
    }

    /**
     * Aktualizuje wyświetlany tekst
     */
    updateDisplayText(text) {
        this.elements.textDisplay.textContent = text;
        this.textState.originalText = text;
    }

    // === UI HELPERS ===

    /**
     * Pokazuje loader
     */
    showLoader(message = 'Ładowanie...') {
        if (this.elements.ocrLoader) {
            this.elements.ocrLoader.querySelector('div:last-child').textContent = message;
            this.elements.ocrLoader.classList.remove('d-none');
        }
    }

    /**
     * Ukrywa loader
     */
    hideLoader() {
        if (this.elements.ocrLoader) {
            this.elements.ocrLoader.classList.add('d-none');
        }
    }

    /**
     * Pokazuje loader tekstu
     */
    showTextLoader() {
        if (this.elements.textDisplay) {
            this.elements.textDisplay.innerHTML = `
        <div class="d-flex justify-content-center">
          <div class="spinner-border text-secondary" role="status">
            <span class="visually-hidden">Ładowanie...</span>
          </div>
        </div>
      `;
        }
    }

    /**
     * Pokazuje błąd tekstu
     */
    showTextError(message) {
        if (this.elements.textDisplay) {
            this.elements.textDisplay.innerHTML = `
        <div class="alert alert-warning">
          <i class="bi bi-exclamation-triangle-fill me-2"></i>
          ${message}
        </div>
      `;
        }
    }

    /**
     * Konfiguruje komunikat początkowy
     */
    setupInitialMessage() {
        if (this.elements.textDisplay) {
            this.elements.textDisplay.innerHTML = `
        <div class="alert alert-secondary">
          <i class="bi bi-info-circle-fill me-2"></i>
          Brak pełnego OCR dla tego dokumentu. Zaznacz fragment tekstu na dokumencie,
          aby rozpoznać wybrany obszar.
        </div>
      `;
        }
    }

    /**
     * Pokazuje błąd
     */
    showError(message) {
        window.alertManager.error(message);
    }

    /**
     * Obsługa klawiatury
     */
    handleKeyboard(e) {
        // Podstawowe skróty klawiszowe (bez edycji)
        // W przyszłości można tutaj dodać inne skróty
    }

    /**
     * Obsługa resize okna
     */
    handleResize() {
        this.hideSelection();
        // Re-render text overlay with new dimensions
        if (this.config.docType === 'pdf' && this.state.currentPage) {
            this.renderTextOverlay(this.state.currentPage);
        }
    }

    // === TEXT OVERLAY FUNCTIONS ===

    /**
     * Render selectable text overlay from OCR layout data
     */
    async renderTextOverlay(pageNum) {
        if (!this.elements.textOverlayLayer) return;
        if (this.config.docType !== 'pdf') return;

        // Clear existing overlay
        this.clearTextOverlay();

        try {
            // Check cache first
            let blocks = this.state.layoutCache[pageNum];

            if (!blocks) {
                // Fetch layout data for this page
                const result = await window.apiClient.getOcrLayout(this.config.docId, pageNum);

                if (!result.success || !result.has_layout) {
                    return; // No layout data available - graceful degradation
                }

                blocks = result.blocks;
                this.state.layoutCache[pageNum] = blocks;
            }

            if (!blocks || blocks.length === 0) return;

            // Get canvas display dimensions
            const canvas = this.elements.canvas;
            const rect = canvas.getBoundingClientRect();
            const displayW = rect.width;
            const displayH = rect.height;

            // Position the overlay to match canvas
            const overlay = this.elements.textOverlayLayer;
            overlay.style.width = displayW + 'px';
            overlay.style.height = displayH + 'px';

            // Offset overlay to match canvas position within container
            const container = this.elements.imageContainer;
            const containerRect = container.getBoundingClientRect();
            overlay.style.left = (rect.left - containerRect.left) + 'px';
            overlay.style.top = (rect.top - containerRect.top) + 'px';

            // Create span elements for each text block
            for (const block of blocks) {
                if (block.category === 'Picture' || !block.text) continue;

                const bbox = block.bbox; // [x1, y1, x2, y2] normalized 0-1
                const x = bbox[0] * displayW;
                const y = bbox[1] * displayH;
                const w = (bbox[2] - bbox[0]) * displayW;
                const h = (bbox[3] - bbox[1]) * displayH;

                if (w < 2 || h < 2) continue; // Skip tiny blocks

                const span = document.createElement('span');
                span.textContent = block.text;
                span.style.left = x + 'px';
                span.style.top = y + 'px';
                span.style.width = w + 'px';
                span.style.height = h + 'px';
                span.style.fontSize = Math.max(6, Math.min(h * 0.85, 24)) + 'px';

                overlay.appendChild(span);
            }

        } catch (error) {
            console.error('Error rendering text overlay:', error);
            // Graceful degradation - continue without overlay
        }
    }

    /**
     * Clear the text overlay layer
     */
    clearTextOverlay() {
        if (this.elements.textOverlayLayer) {
            this.elements.textOverlayLayer.innerHTML = '';
        }
    }

    // === ROTATION FUNCTIONS ===

    /**
     * Obraca obraz o podany kąt
     */
    rotateImage(degrees) {
        this.state.rotation = (this.state.rotation + degrees) % 360;
        if (this.state.rotation < 0) {
            this.state.rotation += 360;
        }
        
        console.log(`Obrót obrazu: ${this.state.rotation}°`);
        this.applyRotation();
        this.hideSelection(); // Ukryj zaznaczenie po obrocie
        this.clearTextOverlay(); // Clear overlay on rotation
    }

    /**
     * Resetuje obrót obrazu
     */
    resetRotation() {
        this.state.rotation = 0;
        console.log('Reset obrotu obrazu');
        this.applyRotation();
        this.hideSelection();
        this.clearTextOverlay();
    }

    /**
     * Aplikuje CSS transform dla obrotu
     */
    applyRotation() {
        if (this.elements.canvas) {
            this.elements.canvas.style.transform = `rotate(${this.state.rotation}deg)`;
            this.elements.canvas.style.transition = 'transform 0.3s ease';
            
            // KRYTYCZNE: NIE obracaj selection overlay!
            // Overlay powinien pozostać w układzie współrzędnych przeglądarki
            // Transformacja współrzędnych odbywa się w calculateCoordinates()
            if (this.elements.selectionOverlay) {
                this.elements.selectionOverlay.style.transform = 'none';
                this.elements.selectionOverlay.style.transformOrigin = 'top left';
            }
            
            // Aktualizuj wrapper jeśli potrzeba dostosować rozmiary
            const wrapper = this.elements.canvas.parentElement;
            if (wrapper && (this.state.rotation === 90 || this.state.rotation === 270)) {
                // Dla obrotów 90° i 270° może potrzeba dodatkowych dostosowań
                wrapper.style.display = 'flex';
                wrapper.style.alignItems = 'center';
                wrapper.style.justifyContent = 'center';
            }
        }
    }

    /**
     * Konwertuje współrzędne z uwzględnieniem obrotu (legacy - używana w backend)
     */
    convertCoordinatesForRotation(x, y, width, height) {
        let newX = x, newY = y;
        
        switch (this.state.rotation) {
            case 90:
                newX = y;
                newY = 1 - x;
                break;
            case 180:
                newX = 1 - x;
                newY = 1 - y;
                break;
            case 270:
                newX = 1 - y;
                newY = x;
                break;
            default: // 0 degrees
                break;
        }
        
        return { x: newX, y: newY };
    }

    /**
     * UPROSZCZONA transformacja współrzędnych - wyślij rotację do backend
     */
    transformBrowserToImageCoords(x, y) {
        // UPROSZCZENIE: Nie robimy skomplikowanych transformacji
        // Wysyłamy surowe współrzędne + informację o rotacji do backend
        // Backend sam obsłuży rotację przy crop obrazu
        
        console.log(`🔍 SIMPLE transform: (${x}, ${y}) with rotation ${this.state.rotation}°`);
        
        // Zwracamy surowe współrzędne - backend obsłuży rotację
        return { x: x, y: y };
    }

    // === PUBLIC API ===

    /**
     * Odświeża widok
     */
    refresh() {
        if (this.config.docType === 'pdf') {
            this.renderPage(this.state.currentPage);
        } else {
            this.loadPageOcr(1);
        }
    }

    /**
     * Niszczy komponent
     */
    destroy() {
        // Usuń event listenery
        document.removeEventListener('keydown', this.handleKeyboard);
        window.removeEventListener('resize', this.handleResize);

        // Wyczyść stan
        this.state = {};
        this.elements = {};
    }
}

// Export globalny
window.OcrViewer = OcrViewer;

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
    module.exports = OcrViewer;
}
