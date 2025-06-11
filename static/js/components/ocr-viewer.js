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
            ocrText: {}, // Cache tekstu OCR dla stron
            currentFullPageOcr: null,
            currentViewport: null // Dla PDF
        };

        // Elementy DOM
        this.elements = {};

        // Edytor tekstu
        this.textEditor = {
            isEditMode: false,
            originalTextBeforeEdit: '',
            originalText: '',
            textChanged: false
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

        this.setupTextEditor();
    }

    /**
     * Konfiguracja struktury DOM
     */
    setupDOM() {
        // Znajdź kluczowe elementy
        this.elements = {
            imageContainer: this.container.querySelector('#imageContainer') || this.container.querySelector('#pdfContainer'),
            canvas: this.container.querySelector('#pdfCanvas') || this.container.querySelector('#mainImage'),
            selectionOverlay: this.container.querySelector('#selectionOverlay'),
            ocrLoader: this.container.querySelector('#ocrLoader'),
            textDisplay: this.container.querySelector('#textDisplay'),
            textEditor: this.container.querySelector('#textEditor'),
            textEditArea: this.container.querySelector('#textEditArea'),
            toggleEditBtn: this.container.querySelector('#toggleEditMode'),
            saveChangesBtn: this.container.querySelector('#saveChangesBtn'),
            copyFullBtn: this.container.querySelector('#copyFullBtn'),

            // PDF specific
            prevPageBtn: this.container.querySelector('#prevPage'),
            nextPageBtn: this.container.querySelector('#nextPage'),
            pageInfo: this.container.querySelector('#pageInfo')
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

        // Edytor tekstu
        if (this.elements.toggleEditBtn) {
            this.elements.toggleEditBtn.addEventListener('click', this.toggleEditMode.bind(this));
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
            this.elements.imageContainer.style.alignItems = 'center';
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

        } catch (error) {
            console.error('Error rendering page:', error);
            this.state.pageRendering = false;
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

    /**
     * Nawigacja - następna strona
     */
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
     * Obsługa rozpoczęcia zaznaczania
     */
    handleMouseDown(e) {
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
            // Dla obrazów
            const imageX = clientX - rect.left;
            const imageY = clientY - rect.top;

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
        const rect = canvas.getBoundingClientRect();

        let left, top, width, height;

        if (this.config.docType === 'pdf') {
            const cssScaleX = rect.width / canvas.width;
            const cssScaleY = rect.height / canvas.height;

            left = Math.min(this.state.startX, this.state.endX) * cssScaleX;
            top = Math.min(this.state.startY, this.state.endY) * cssScaleY;
            width = Math.abs(this.state.endX - this.state.startX) * cssScaleX;
            height = Math.abs(this.state.endY - this.state.startY) * cssScaleY;
        } else {
            left = Math.min(this.state.startX, this.state.endX);
            top = Math.min(this.state.startY, this.state.endY);
            width = Math.abs(this.state.endX - this.state.startX);
            height = Math.abs(this.state.endY - this.state.startY);
        }

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
        this.showLoader('Rozpoznawanie tekstu fragmentu...');

        try {
            // Oblicz znormalizowane współrzędne (0-1)
            const canvas = this.elements.canvas;
            let normCoords;

            if (this.config.docType === 'pdf') {
                normCoords = {
                    x1: Math.min(this.state.startX, this.state.endX) / canvas.width,
                    y1: Math.min(this.state.startY, this.state.endY) / canvas.height,
                    x2: Math.max(this.state.startX, this.state.endX) / canvas.width,
                    y2: Math.max(this.state.startY, this.state.endY) / canvas.height
                };
            } else {
                const rect = canvas.getBoundingClientRect();
                normCoords = {
                    x1: Math.min(this.state.startX, this.state.endX) / rect.width,
                    y1: Math.min(this.state.startY, this.state.endY) / rect.height,
                    x2: Math.max(this.state.startX, this.state.endX) / rect.width,
                    y2: Math.max(this.state.startY, this.state.endY) / rect.height
                };
            }

            const data = {
                page: this.state.currentPage,
                x1: normCoords.x1,
                y1: normCoords.y1,
                x2: normCoords.x2,
                y2: normCoords.y2,
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
     * Aktualizuje cache OCR dla wszystkich stron
     * NOWA FUNKCJA - zapewnia spójność między stronami
     */
    updateOcrCacheForAllPages(text) {
        // Wyczyść stary cache
        this.state.ocrText = {};

        // Ustaw ten sam tekst dla wszystkich stron (1 do totalPages)
        for (let i = 1; i <= this.state.totalPages; i++) {
            this.state.ocrText[i] = text;
        }

        // Zaktualizuj również referencję do pełnego tekstu
        this.state.currentFullPageOcr = text;

        console.log(`OCR cache zaktualizowany dla ${this.state.totalPages} stron`);
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
        // ZMIANA: Sprawdź cache, ale tylko jeśli jest aktualny
        if (this.state.ocrText[page] && this.state.currentFullPageOcr) {
            this.updateDisplayText(this.state.ocrText[page]);
            return;
        }

        if (!this.config.documentHasFullOcr) {
            this.setupInitialMessage();
            return;
        }

        this.showTextLoader();

        try {
            // ZMIANA: Zawsze synchronizuj z serwerem przy pierwszym ładowaniu strony
            const serverSyncSuccess = await this.syncWithServer();

            if (!serverSyncSuccess) {
                // Wykonaj OCR dla całej strony jako fallback
                await this.performFullPageOcr(page);
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

            if (result.success && result.has_ocr && result.text.trim()) {
                // ZMIANA: Aktualizuj cache dla wszystkich stron
                this.updateOcrCacheForAllPages(result.text);

                // Aktualizuj wyświetlanie
                this.updateDisplayText(result.text);

                // ZMIANA: Powiadom TextEditor (jeśli istnieje)
                if (window.textEditor) {
                    window.textEditor.setText(result.text);
                }

                window.alertManager.showSyncInfo();
                return true;
            }
            return false;
        } catch (error) {
            console.warn('Nie udało się zsynchronizować z serwerem:', error);
            return false;
        }
    }

    // === TEXT EDITOR METHODS ===

    /**
     * Konfiguracja edytora tekstu
     */
    setupTextEditor() {
        this.setupTextChangeMonitoring();
    }

    /**
     * Przełączanie trybu edycji
     */
    toggleEditMode() {
        if (!this.textEditor.isEditMode) {
            this.enterEditMode();
        } else {
            this.exitEditMode(false);
        }
    }

    /**
     * Wejście w tryb edycji
     */
    enterEditMode() {
        const currentText = this.elements.textDisplay.textContent || '';
        this.textEditor.originalTextBeforeEdit = currentText;

        this.elements.textEditArea.value = currentText;
        this.elements.textDisplay.classList.add('d-none');
        this.elements.textEditor.classList.remove('d-none');

        this.elements.toggleEditBtn.innerHTML = '<i class="bi bi-eye"></i> Podgląd';
        this.elements.toggleEditBtn.classList.remove('btn-outline-info');
        this.elements.toggleEditBtn.classList.add('btn-outline-warning');

        this.textEditor.isEditMode = true;
        this.elements.textEditArea.focus();
    }

    /**
     * Wyjście z trybu edycji
     */
    exitEditMode(autoSave = false) {
        if (autoSave) {
            const editedText = this.elements.textEditArea.value;
            this.updateDisplayText(editedText);
        }

        this.elements.textDisplay.classList.remove('d-none');
        this.elements.textEditor.classList.add('d-none');

        this.elements.toggleEditBtn.innerHTML = '<i class="bi bi-pencil"></i> Edytuj';
        this.elements.toggleEditBtn.classList.remove('btn-outline-warning');
        this.elements.toggleEditBtn.classList.add('btn-outline-info');

        this.textEditor.isEditMode = false;
    }

    /**
     * Monitorowanie zmian tekstu
     */
    setupTextChangeMonitoring() {
        if (!this.elements.textDisplay) return;

        const observer = new MutationObserver(() => {
            this.checkForTextChanges();
        });

        observer.observe(this.elements.textDisplay, {
            childList: true,
            subtree: true,
            characterData: true
        });
    }

    /**
     * Sprawdza zmiany w tekście
     */
    checkForTextChanges() {
        const currentText = this.elements.textDisplay.textContent;

        if (currentText !== this.textEditor.originalText) {
            if (!this.textEditor.textChanged) {
                this.textEditor.textChanged = true;
                this.elements.saveChangesBtn.classList.remove('d-none');
                this.elements.textDisplay.style.backgroundColor = '#fff3cd';
                this.elements.textDisplay.style.border = '2px solid #ffc107';
            }
        } else {
            if (this.textEditor.textChanged) {
                this.textEditor.textChanged = false;
                this.elements.saveChangesBtn.classList.add('d-none');
                this.elements.textDisplay.style.backgroundColor = '#f8f9fa';
                this.elements.textDisplay.style.border = '';
            }
        }
    }

    /**
     * Aktualizuje wyświetlany tekst
     */
    updateDisplayText(text) {
        this.elements.textDisplay.textContent = text;
        this.textEditor.originalText = text;
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
        if (this.textEditor.isEditMode) {
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                this.saveEdit();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                this.cancelEdit();
            }
        } else {
            if (e.key === 'e' && !e.ctrlKey && !e.altKey &&
                document.activeElement.tagName !== 'INPUT' &&
                document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                this.toggleEditMode();
            }
        }
    }

    /**
     * Obsługa resize okna
     */
    handleResize() {
        this.hideSelection();
    }

    // === PUBLIC API ===

    /**
     * Zapisuje zmiany
     */
    async saveCurrentText() {
        const currentText = this.elements.textDisplay.textContent;

        try {
            const result = await window.apiClient.updateOcrText(this.config.docId, currentText);

            if (result.success) {
                this.textEditor.originalText = currentText;
                this.textEditor.textChanged = false;
                this.elements.saveChangesBtn.classList.add('d-none');
                this.elements.textDisplay.style.backgroundColor = '#f8f9fa';
                this.elements.textDisplay.style.border = '';

                window.alertManager.showOcrSuccess(
                    'Zmiany zostały zapisane',
                    result.ocr_doc_id,
                    this.config.docId,
                    this.config.parentId
                );
            } else {
                throw new Error(result.error || 'Nieznany błąd');
            }

        } catch (error) {
            window.alertManager.error('Błąd podczas zapisywania: ' + error.message);
        }
    }

    /**
     * Anuluje edycję
     */
    cancelEdit() {
        this.elements.textEditArea.value = this.textEditor.originalTextBeforeEdit;
        this.exitEditMode(false);
    }

    /**
     * Zapisuje edycję
     */
    saveEdit() {
        const editedText = this.elements.textEditArea.value;

        if (editedText !== this.textEditor.originalTextBeforeEdit) {
            this.updateDisplayText(editedText);
            this.checkForTextChanges();
        }

        this.exitEditMode(true);
    }

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
