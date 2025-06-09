/**
 * JavaScript specyficzny dla strony pdf_view_with_selection.html
 * Obsługuje zaawansowane funkcje PDF viewer z OCR
 */

class PdfViewerManager {
  constructor(docId, options = {}) {
    this.docId = docId;
    this.config = {
      hasOcr: options.hasOcr || false,
      parentId: options.parentId || null,
      ...options
    };

    this.state = {
      isFullscreen: false,
      currentScale: 1.5,
      autoSave: false
    };

    this.elements = {};
    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.findElements();
    this.setupEventListeners();
    this.setupKeyboardShortcuts();
    this.setupPdfSpecificFeatures();
    console.log('PdfViewerManager zainicjalizowany dla dokumentu', this.docId);
  }

  /**
   * Znajdź kluczowe elementy
   */
  findElements() {
    this.elements = {
      prevPageBtn: document.getElementById('prevPage'),
      nextPageBtn: document.getElementById('nextPage'),
      pageInfo: document.getElementById('pageInfo'),
      pdfContainer: document.getElementById('pdfContainer'),
      toggleEditBtn: document.getElementById('toggleEditMode'),
      saveChangesBtn: document.getElementById('saveChangesBtn'),
      copyFullBtn: document.getElementById('copyFullBtn')
    };
  }

  /**
   * Konfiguracja event listenerów
   */
  setupEventListeners() {
    // Navigation buttons są już obsługiwane przez OcrViewer
    // Tutaj dodajemy specyficzne dla PDF funkcje

    // Full screen toggle
    document.addEventListener('fullscreenchange', () => {
      this.handleFullscreenChange();
    });

    // Wheel zoom
    if (this.elements.pdfContainer) {
      this.elements.pdfContainer.addEventListener('wheel', (e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          this.handleWheelZoom(e);
        }
      });
    }

    // Auto-save toggle
    if (this.elements.saveChangesBtn) {
      // Double-click on save button to toggle auto-save
      this.elements.saveChangesBtn.addEventListener('dblclick', () => {
        this.toggleAutoSave();
      });
    }
  }

  /**
   * Konfiguracja skrótów klawiszowych specyficznych dla PDF
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Tylko gdy focus jest w obszarze PDF viewer
      if (!this.elements.pdfContainer?.contains(document.activeElement) &&
          document.activeElement !== document.body) {
        return;
      }

      switch (e.key) {
        case 'ArrowLeft':
        case 'PageUp':
          if (window.ocrViewer) {
            e.preventDefault();
            window.ocrViewer.prevPage();
          }
          break;

        case 'ArrowRight':
        case 'PageDown':
        case ' ': // Space
          if (window.ocrViewer) {
            e.preventDefault();
            window.ocrViewer.nextPage();
          }
          break;

        case 'Home':
          if (window.ocrViewer) {
            e.preventDefault();
            window.ocrViewer.renderPage(1);
          }
          break;

        case 'End':
          if (window.ocrViewer && window.ocrViewer.state.totalPages) {
            e.preventDefault();
            window.ocrViewer.renderPage(window.ocrViewer.state.totalPages);
          }
          break;

        case 'F11':
          e.preventDefault();
          this.toggleFullscreen();
          break;

        case '+':
        case '=':
          if (e.ctrlKey) {
            e.preventDefault();
            this.zoomIn();
          }
          break;

        case '-':
          if (e.ctrlKey) {
            e.preventDefault();
            this.zoomOut();
          }
          break;

        case '0':
          if (e.ctrlKey) {
            e.preventDefault();
            this.resetZoom();
          }
          break;

        case 's':
          if (e.ctrlKey) {
            e.preventDefault();
            this.saveCurrentText();
          }
          break;
      }
    });
  }

  /**
   * Konfiguracja funkcji specyficznych dla PDF
   */
  setupPdfSpecificFeatures() {
    // Add zoom controls to toolbar if not present
    this.addZoomControls();

    // Setup page jump functionality
    this.setupPageJump();

    // Setup search in PDF functionality
    this.setupPdfSearch();
  }

  /**
   * Dodaje kontrolki zoom do toolbara
   */
  addZoomControls() {
    const pageInfo = this.elements.pageInfo;
    if (!pageInfo) return;

    // Sprawdź czy kontrolki już istnieją
    if (document.getElementById('pdfZoomControls')) return;

    const zoomControls = document.createElement('div');
    zoomControls.id = 'pdfZoomControls';
    zoomControls.className = 'btn-group ms-2';
    zoomControls.innerHTML = `
      <button type="button" class="btn btn-sm btn-outline-secondary" onclick="pdfViewerManager.zoomOut()" title="Pomniejsz (Ctrl+-)">
        <i class="bi bi-zoom-out"></i>
      </button>
      <button type="button" class="btn btn-sm btn-outline-secondary" onclick="pdfViewerManager.resetZoom()" title="Resetuj zoom (Ctrl+0)">
        <span id="zoomLevel">150%</span>
      </button>
      <button type="button" class="btn btn-sm btn-outline-secondary" onclick="pdfViewerManager.zoomIn()" title="Powiększ (Ctrl++)">
        <i class="bi bi-zoom-in"></i>
      </button>
    `;

    pageInfo.parentNode.appendChild(zoomControls);
  }

  /**
   * Konfiguruje funkcję skoku do strony
   */
  setupPageJump() {
    const pageInfo = this.elements.pageInfo;
    if (!pageInfo) return;

    // Dodaj event listener do kliknięcia na informację o stronie
    pageInfo.addEventListener('click', () => {
      this.showPageJumpDialog();
    });

    pageInfo.style.cursor = 'pointer';
    pageInfo.title = 'Kliknij aby przejść do konkretnej strony';
  }

  /**
   * Konfiguruje wyszukiwanie w PDF
   */
  setupPdfSearch() {
    // Dodaj pole wyszukiwania do interfejsu
    const textEditorContainer = document.getElementById('textEditorContainer');
    if (!textEditorContainer) return;

    // Sprawdź czy już istnieje
    if (document.getElementById('pdfSearchBox')) return;

    const searchBox = document.createElement('div');
    searchBox.id = 'pdfSearchBox';
    searchBox.className = 'card mb-3';
    searchBox.innerHTML = `
      <div class="card-header py-2">
        <div class="d-flex align-items-center">
          <i class="bi bi-search me-2"></i>
          <input type="text" class="form-control form-control-sm"
                 id="pdfSearchInput" placeholder="Wyszukaj w dokumencie PDF...">
          <button type="button" class="btn btn-sm btn-outline-secondary ms-2" onclick="pdfViewerManager.searchInPdf()">
            Szukaj
          </button>
        </div>
      </div>
    `;

    textEditorContainer.insertBefore(searchBox, textEditorContainer.firstChild);

    // Dodaj event listener dla Enter
    document.getElementById('pdfSearchInput').addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        this.searchInPdf();
      }
    });
  }

  // === ZOOM FUNCTIONS ===

  /**
   * Powiększa PDF
   */
  zoomIn() {
    this.state.currentScale *= 1.2;
    this.updatePdfScale();
  }

  /**
   * Pomniejsza PDF
   */
  zoomOut() {
    this.state.currentScale /= 1.2;
    if (this.state.currentScale < 0.5) {
      this.state.currentScale = 0.5;
    }
    this.updatePdfScale();
  }

  /**
   * Resetuje zoom
   */
  resetZoom() {
    this.state.currentScale = 1.5;
    this.updatePdfScale();
  }

  /**
   * Obsługa zoom scrollem myszy
   */
  handleWheelZoom(e) {
    if (e.deltaY < 0) {
      this.zoomIn();
    } else {
      this.zoomOut();
    }
  }

  /**
   * Aktualizuje skalę PDF
   */
  updatePdfScale() {
    if (window.ocrViewer) {
      window.ocrViewer.state.scale = this.state.currentScale;
      window.ocrViewer.renderPage(window.ocrViewer.state.currentPage);
    }

    // Aktualizuj wskaźnik zoom
    const zoomLevel = document.getElementById('zoomLevel');
    if (zoomLevel) {
      zoomLevel.textContent = Math.round(this.state.currentScale * 100) + '%';
    }
  }

  // === FULLSCREEN FUNCTIONS ===

  /**
   * Przełącza pełny ekran
   */
  toggleFullscreen() {
    if (!this.state.isFullscreen) {
      this.enterFullscreen();
    } else {
      this.exitFullscreen();
    }
  }

  /**
   * Wchodzi w pełny ekran
   */
  enterFullscreen() {
    const element = this.elements.pdfContainer || document.documentElement;

    if (element.requestFullscreen) {
      element.requestFullscreen();
    } else if (element.mozRequestFullScreen) {
      element.mozRequestFullScreen();
    } else if (element.webkitRequestFullscreen) {
      element.webkitRequestFullscreen();
    } else if (element.msRequestFullscreen) {
      element.msRequestFullscreen();
    }
  }

  /**
   * Wychodzi z pełnego ekranu
   */
  exitFullscreen() {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    } else if (document.mozCancelFullScreen) {
      document.mozCancelFullScreen();
    } else if (document.webkitExitFullscreen) {
      document.webkitExitFullscreen();
    } else if (document.msExitFullscreen) {
      document.msExitFullscreen();
    }
  }

  /**
   * Obsługa zmiany pełnego ekranu
   */
  handleFullscreenChange() {
    this.state.isFullscreen = !!document.fullscreenElement;

    // Aktualizuj UI dla pełnego ekranu
    if (this.state.isFullscreen) {
      document.body.classList.add('pdf-fullscreen');
    } else {
      document.body.classList.remove('pdf-fullscreen');
    }
  }

  // === NAVIGATION FUNCTIONS ===

  /**
   * Pokazuje dialog skoku do strony
   */
  showPageJumpDialog() {
    if (!window.ocrViewer) return;

    const currentPage = window.ocrViewer.state.currentPage;
    const totalPages = window.ocrViewer.state.totalPages;

    const pageNumber = prompt(
      `Przejdź do strony (1-${totalPages}):`,
      currentPage.toString()
    );

    if (pageNumber !== null) {
      const targetPage = parseInt(pageNumber);

      if (targetPage >= 1 && targetPage <= totalPages) {
        window.ocrViewer.renderPage(targetPage);
      } else {
        window.alertManager.error(`Numer strony musi być między 1 a ${totalPages}`);
      }
    }
  }

  /**
   * Wyszukiwanie w PDF
   */
  async searchInPdf() {
    const searchInput = document.getElementById('pdfSearchInput');
    if (!searchInput) return;

    const query = searchInput.value.trim();
    if (!query) {
      window.alertManager.warning('Wprowadź tekst do wyszukania');
      return;
    }

    // Tutaj można zaimplementować wyszukiwanie w treści PDF
    // Na razie pokazujemy placeholder
    window.alertManager.info(`Wyszukiwanie "${query}" będzie dostępne wkrótce`);
  }

  // === AUTO-SAVE FUNCTIONS ===

  /**
   * Przełącza auto-save
   */
  toggleAutoSave() {
    this.state.autoSave = !this.state.autoSave;

    if (this.state.autoSave) {
      this.startAutoSave();
      window.alertManager.success('Auto-zapis włączony (co 30 sekund)');
    } else {
      this.stopAutoSave();
      window.alertManager.info('Auto-zapis wyłączony');
    }

    this.updateAutoSaveIndicator();
  }

  /**
   * Rozpoczyna auto-save
   */
  startAutoSave() {
    this.stopAutoSave(); // Zatrzymaj poprzedni timer

    this.autoSaveTimer = setInterval(() => {
      if (window.textEditor && window.textEditor.hasChanges()) {
        window.textEditor.saveChanges(true); // silent save
      }
    }, 30000); // 30 sekund
  }

  /**
   * Zatrzymuje auto-save
   */
  stopAutoSave() {
    if (this.autoSaveTimer) {
      clearInterval(this.autoSaveTimer);
      this.autoSaveTimer = null;
    }
  }

  /**
   * Aktualizuje wskaźnik auto-save
   */
  updateAutoSaveIndicator() {
    const saveBtn = this.elements.saveChangesBtn;
    if (!saveBtn) return;

    if (this.state.autoSave) {
      saveBtn.title = 'Zapisz zmiany (Auto-zapis: WŁĄCZONY - kliknij dwukrotnie aby wyłączyć)';
      saveBtn.classList.add('btn-success');
      saveBtn.classList.remove('btn-outline-success');
    } else {
      saveBtn.title = 'Zapisz zmiany (Auto-zapis: WYŁĄCZONY - kliknij dwukrotnie aby włączyć)';
      saveBtn.classList.remove('btn-success');
      saveBtn.classList.add('btn-outline-success');
    }
  }

  // === UTILITY FUNCTIONS ===

  /**
   * Zapisuje aktualny tekst
   */
  async saveCurrentText() {
    if (window.textEditor) {
      return await window.textEditor.saveChanges();
    }
    return false;
  }

  /**
   * Eksportuje aktualną stronę jako obraz
   */
  async exportCurrentPageAsImage() {
    if (!window.ocrViewer) return;

    const canvas = document.getElementById('pdfCanvas');
    if (!canvas) return;

    try {
      // Konwertuj canvas na blob
      canvas.toBlob((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `strona_${window.ocrViewer.state.currentPage}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        window.alertManager.success('Strona została wyeksportowana jako obraz');
      }, 'image/png');
    } catch (error) {
      window.alertManager.error('Nie udało się wyeksportować strony');
    }
  }

  /**
   * Pobiera informacje o dokumencie PDF
   */
  getPdfInfo() {
    if (!window.ocrViewer) return null;

    return {
      currentPage: window.ocrViewer.state.currentPage,
      totalPages: window.ocrViewer.state.totalPages,
      scale: this.state.currentScale,
      isFullscreen: this.state.isFullscreen,
      autoSave: this.state.autoSave
    };
  }

  /**
   * Niszczy manager
   */
  destroy() {
    this.stopAutoSave();

    // Usuń event listenery
    document.removeEventListener('fullscreenchange', this.handleFullscreenChange);
    document.removeEventListener('keydown', this.setupKeyboardShortcuts);

    // Wyjdź z pełnego ekranu jeśli aktywny
    if (this.state.isFullscreen) {
      this.exitFullscreen();
    }

    // Wyczyść stan
    this.state = {};
    this.elements = {};
  }

  // === PUBLIC API ===

  /**
   * Przechodzi do określonej strony
   */
  goToPage(pageNumber) {
    if (window.ocrViewer) {
      window.ocrViewer.renderPage(pageNumber);
    }
  }

  /**
   * Pobiera aktualną stronę
   */
  getCurrentPage() {
    return window.ocrViewer ? window.ocrViewer.state.currentPage : 1;
  }

  /**
   * Pobiera całkowitą liczbę stron
   */
  getTotalPages() {
    return window.ocrViewer ? window.ocrViewer.state.totalPages : 1;
  }

  /**
   * Ustawia zoom
   */
  setZoom(scale) {
    this.state.currentScale = scale;
    this.updatePdfScale();
  }

  /**
   * Pobiera aktualny zoom
   */
  getZoom() {
    return this.state.currentScale;
  }
}

// Export globalny
window.PdfViewerManager = PdfViewerManager;