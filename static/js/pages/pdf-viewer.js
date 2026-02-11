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
  }

  highlightPageMarker(textElement, marker) {
     const textContent = textElement.textContent;
    const markerIndex = textContent.indexOf(marker);

    if (markerIndex === -1) return;

  // Stwórz tymczasowe podświetlenie poprzez zmianę koloru tła
    const originalStyle = textElement.style.backgroundColor;

  // Krótkie miganie
  setTimeout(() => {
    textElement.style.backgroundColor = '#ffffcc';
    setTimeout(() => {
      textElement.style.backgroundColor = originalStyle;
    }, 300);
  }, 100);
}
/**
 * Synchronizuje przewijanie tekstu z aktualną stroną PDF
 */
scrollToPageInText(pageNumber) {
  const textDisplay = document.getElementById('textDisplay');
  if (!textDisplay) return;

  const pageMarker = `=== Strona ${pageNumber} ===`;
  const textContent = textDisplay.textContent || textDisplay.innerText;

  // Znajdź pozycję znacznika strony
  const markerIndex = textContent.indexOf(pageMarker);

  if (markerIndex === -1) {
    // Jeśli nie znaleziono znacznika, spróbuj alternatywnych formatów
    const altMarkers = [
      `===Strona ${pageNumber}===`,
      `=== Strona${pageNumber} ===`,
      `== Strona ${pageNumber} ==`
    ];

    let foundIndex = -1;
    for (const altMarker of altMarkers) {
      foundIndex = textContent.indexOf(altMarker);
      if (foundIndex !== -1) break;
    }

    if (foundIndex === -1) {
      return;
    }

    markerIndex = foundIndex;
  }

  // Oblicz przybliżoną pozycję scrolla
  const totalTextLength = textContent.length;
  const markerPosition = markerIndex / totalTextLength;

  // Przewiń do odpowiedniej pozycji
  const scrollHeight = textDisplay.scrollHeight;
  const containerHeight = textDisplay.clientHeight;
  const maxScrollTop = scrollHeight - containerHeight;

  // Oblicz docelową pozycję (z małym offsetem do góry dla lepszej widoczności)
  const targetScrollTop = Math.max(0, (markerPosition * scrollHeight) - 50);
  const finalScrollTop = Math.min(targetScrollTop, maxScrollTop);

  // Płynne przewijanie
  textDisplay.scrollTo({
    top: finalScrollTop,
    behavior: 'smooth'
  });

  // Opcjonalne: Podświetl znacznik na krótko
  this.highlightPageMarker(textDisplay, pageMarker);
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
        case 'PageUp':
          if (window.ocrViewer) {
            e.preventDefault();
            window.ocrViewer.prevPage();
          }
          break;

        case 'PageDown':
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
  }

  /**
   * Dodaje kontrolki zoom do toolbara - WYŁĄCZONE
   */
  addZoomControls() {
    // Funkcja zoom wyłączona - przyciski nie działają prawidłowo
    return;
  }

  /**
   * Konfiguruje funkcję skoku do strony
   */
  setupPageJump() {
    const pageJumpBtn = document.getElementById('pageJumpBtn');
    const pageJumpInput = document.getElementById('pageJumpInput');
    
    if (!pageJumpBtn || !pageJumpInput) return;

    // Event listener dla przycisku "Idź"
    pageJumpBtn.addEventListener('click', () => {
      this.handlePageJump();
    });

    // Event listener dla Enter w polu tekstowym
    pageJumpInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        this.handlePageJump();
      }
    });

    // Aktualizuj maksymalną wartość pola gdy się zmieni liczba stron
    this.updatePageJumpMaxValue();
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

  // NOWE: Synchronizuj tekst po przeskalowaniu
  this.scrollToPageInText(window.ocrViewer?.state.currentPage || 1);
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
   * Obsługuje skok do strony z pola tekstowego
   */
  handlePageJump() {
    if (!window.ocrViewer) return;

    const pageJumpInput = document.getElementById('pageJumpInput');
    if (!pageJumpInput) return;

    const pageNumber = pageJumpInput.value.trim();
    if (!pageNumber) return;

    const targetPage = parseInt(pageNumber);
    const totalPages = window.ocrViewer.state.totalPages;

    if (isNaN(targetPage) || targetPage < 1 || targetPage > totalPages) {
      window.alertManager.error(`Numer strony musi być między 1 a ${totalPages}`);
      pageJumpInput.focus();
      return;
    }

    window.ocrViewer.renderPage(targetPage);
    pageJumpInput.value = ''; // Wyczyść pole po udanym skoku
  }

  /**
   * Aktualizuje maksymalną wartość dla pola skoku do strony
   */
  updatePageJumpMaxValue() {
    const pageJumpInput = document.getElementById('pageJumpInput');
    if (!pageJumpInput || !window.ocrViewer) return;

    const totalPages = window.ocrViewer.state.totalPages;
    if (totalPages) {
      pageJumpInput.setAttribute('max', totalPages.toString());
      pageJumpInput.setAttribute('placeholder', `Nr strony (1-${totalPages})`);
    }
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

        // Aktualizuj pole skoku do strony
        this.updatePageJumpMaxValue();

        // NOWE: Synchronizuj tekst po zmianie strony
        setTimeout(() => {
            this.scrollToPageInText(pageNumber);
        }, 200); // Krótkie opóźnienie żeby OCR zdążył załadować tekst
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