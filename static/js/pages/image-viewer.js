/**
 * JavaScript specyficzny dla strony image_view_with_selection.html
 * Obsługuje zaawansowane funkcje Image viewer z OCR
 */

class ImageViewerManager {
  constructor(docId, options = {}) {
    this.docId = docId;
    this.config = {
      hasOcr: options.hasOcr || false,
      parentId: options.parentId || null,
      ...options
    };

    this.state = {
      isFullscreen: false,
      currentZoom: 1.0,
      isDragging: false,
      lastX: 0,
      lastY: 0,
      rotation: 0
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
    this.setupImageSpecificFeatures();
    console.log('ImageViewerManager zainicjalizowany dla dokumentu', this.docId);
  }

  /**
   * Znajdź kluczowe elementy
   */
  findElements() {
    this.elements = {
      imageContainer: document.getElementById('imageContainer'),
      mainImage: document.getElementById('mainImage'),
      imageWrapper: document.getElementById('imageWrapper'),
      toggleEditBtn: document.getElementById('toggleEditMode'),
      saveChangesBtn: document.getElementById('saveChangesBtn'),
      copyFullBtn: document.getElementById('copyFullBtn')
    };
  }

  /**
   * Konfiguracja event listenerów
   */
  setupEventListeners() {
    // Image zoom and pan
    if (this.elements.mainImage) {
      this.elements.mainImage.addEventListener('wheel', (e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          this.handleWheelZoom(e);
        }
      });

      this.elements.mainImage.addEventListener('load', () => {
        this.onImageLoad();
      });
    }

    // Dragging for panned images
    this.setupDragAndPan();

    // Double-click to fit/zoom
    if (this.elements.mainImage) {
      this.elements.mainImage.addEventListener('dblclick', (e) => {
        if (!e.ctrlKey) { // Nie konfliktuj z zaznaczaniem OCR
          this.toggleFitToScreen();
        }
      });
    }

    // Full screen toggle
    document.addEventListener('fullscreenchange', () => {
      this.handleFullscreenChange();
    });
  }

  /**
   * Konfiguracja drag and pan
   */
  setupDragAndPan() {
    if (!this.elements.imageContainer) return;

    this.elements.imageContainer.addEventListener('mousedown', (e) => {
      // Tylko dla środkowego przycisku myszy lub gdy zoom > 1
      if (e.button === 1 || (this.state.currentZoom > 1.0 && e.button === 0 && e.altKey)) {
        e.preventDefault();
        this.startDragging(e);
      }
    });

    document.addEventListener('mousemove', (e) => {
      if (this.state.isDragging) {
        this.handleDragging(e);
      }
    });

    document.addEventListener('mouseup', () => {
      this.stopDragging();
    });
  }

  /**
   * Konfiguracja skrótów klawiszowych specyficznych dla obrazów
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Tylko gdy focus jest w obszarze image viewer
      if (!this.elements.imageContainer?.contains(document.activeElement) &&
          document.activeElement !== document.body) {
        return;
      }

      switch (e.key) {
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

        case 'f':
          if (!e.ctrlKey && !e.altKey) {
            e.preventDefault();
            this.fitToScreen();
          }
          break;

        case 'r':
          if (e.ctrlKey) {
            e.preventDefault();
            this.rotateImage();
          }
          break;

        case 's':
          if (e.ctrlKey) {
            e.preventDefault();
            this.saveCurrentText();
          }
          break;

        case 'ArrowUp':
          if (this.state.currentZoom > 1.0) {
            e.preventDefault();
            this.panImage(0, -50);
          }
          break;

        case 'ArrowDown':
          if (this.state.currentZoom > 1.0) {
            e.preventDefault();
            this.panImage(0, 50);
          }
          break;

        case 'ArrowLeft':
          if (this.state.currentZoom > 1.0) {
            e.preventDefault();
            this.panImage(-50, 0);
          }
          break;

        case 'ArrowRight':
          if (this.state.currentZoom > 1.0) {
            e.preventDefault();
            this.panImage(50, 0);
          }
          break;
      }
    });
  }

  /**
   * Konfiguracja funkcji specyficznych dla obrazów
   */
  setupImageSpecificFeatures() {
    // Add image controls toolbar
    this.addImageControls();

    // Setup image analysis tools
    this.setupImageAnalysis();

    // Setup brightness/contrast controls
    this.setupImageAdjustments();
  }

  /**
   * Dodaje kontrolki obrazu do toolbara
   */
  addImageControls() {
    const textEditorContainer = document.getElementById('textEditorContainer');
    if (!textEditorContainer) return;

    // Sprawdź czy kontrolki już istnieją
    if (document.getElementById('imageControls')) return;

    const imageControls = document.createElement('div');
    imageControls.id = 'imageControls';
    imageControls.className = 'card mb-3';
    imageControls.innerHTML = `
      <div class="card-header py-2">
        <div class="d-flex justify-content-between align-items-center">
          <span><i class="bi bi-image me-2"></i>Kontrolki obrazu</span>
          <div class="btn-group btn-group-sm">
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.zoomOut()" title="Pomniejsz (Ctrl+-)">
              <i class="bi bi-zoom-out"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.resetZoom()" title="Resetuj zoom (Ctrl+0)">
              <span id="imageZoomLevel">100%</span>
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.zoomIn()" title="Powiększ (Ctrl++)">
              <i class="bi bi-zoom-in"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.fitToScreen()" title="Dopasuj do ekranu (F)">
              <i class="bi bi-arrows-fullscreen"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.rotateImage()" title="Obróć (Ctrl+R)">
              <i class="bi bi-arrow-clockwise"></i>
            </button>
            <button type="button" class="btn btn-outline-secondary" onclick="imageViewerManager.toggleFullscreen()" title="Pełny ekran (F11)">
              <i class="bi bi-fullscreen"></i>
            </button>
          </div>
        </div>
      </div>
    `;

    textEditorContainer.insertBefore(imageControls, textEditorContainer.firstChild);
  }

  /**
   * Konfiguruje narzędzia analizy obrazu
   */
  setupImageAnalysis() {
    // Dodaj informacje o obrazie
    this.showImageInfo();
  }

  /**
   * Konfiguruje regulację jasności/kontrastu
   */
  setupImageAdjustments() {
    const imageControls = document.getElementById('imageControls');
    if (!imageControls) return;

    // Dodaj kontrolki regulacji
    const adjustmentControls = document.createElement('div');
    adjustmentControls.className = 'card-body py-2 border-top';
    adjustmentControls.innerHTML = `
      <div class="row g-2">
        <div class="col-md-4">
          <label for="brightnessSlider" class="form-label small">Jasność</label>
          <input type="range" class="form-range" id="brightnessSlider" min="-100" max="100" value="0">
        </div>
        <div class="col-md-4">
          <label for="contrastSlider" class="form-label small">Kontrast</label>
          <input type="range" class="form-range" id="contrastSlider" min="-100" max="100" value="0">
        </div>
        <div class="col-md-4">
          <div class="d-flex justify-content-end align-items-end h-100">
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="imageViewerManager.resetImageAdjustments()">
              Reset
            </button>
          </div>
        </div>
      </div>
    `;

    imageControls.appendChild(adjustmentControls);

    // Dodaj event listenery
    document.getElementById('brightnessSlider').addEventListener('input', (e) => {
      this.adjustImageBrightness(e.target.value);
    });

    document.getElementById('contrastSlider').addEventListener('input', (e) => {
      this.adjustImageContrast(e.target.value);
    });
  }

  // === ZOOM FUNCTIONS ===

  /**
   * Powiększa obraz
   */
  zoomIn() {
    this.state.currentZoom *= 1.2;
    this.applyZoom();
  }

  /**
   * Pomniejsza obraz
   */
  zoomOut() {
    this.state.currentZoom /= 1.2;
    if (this.state.currentZoom < 0.1) {
      this.state.currentZoom = 0.1;
    }
    this.applyZoom();
  }

  /**
   * Resetuje zoom
   */
  resetZoom() {
    this.state.currentZoom = 1.0;
    this.applyZoom();
  }

  /**
   * Dopasowuje obraz do ekranu
   */
  fitToScreen() {
    if (!this.elements.mainImage || !this.elements.imageContainer) return;

    const img = this.elements.mainImage;
    const container = this.elements.imageContainer;

    const containerWidth = container.clientWidth - 40;
    const containerHeight = container.clientHeight - 40;

    const scaleX = containerWidth / img.naturalWidth;
    const scaleY = containerHeight / img.naturalHeight;

    this.state.currentZoom = Math.min(scaleX, scaleY, 1.0);
    this.applyZoom();
  }

  /**
   * Przełącza między fit to screen a 100%
   */
  toggleFitToScreen() {
    if (this.state.currentZoom !== 1.0) {
      this.resetZoom();
    } else {
      this.fitToScreen();
    }
  }

  /**
   * Obsługa zoom scrollem myszy
   */
  handleWheelZoom(e) {
    const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
    this.state.currentZoom *= zoomFactor;

    if (this.state.currentZoom < 0.1) this.state.currentZoom = 0.1;
    if (this.state.currentZoom > 5.0) this.state.currentZoom = 5.0;

    this.applyZoom();
  }

  /**
   * Aplikuje zoom do obrazu
   */
  applyZoom() {
    if (!this.elements.mainImage) return;

    this.elements.mainImage.style.transform = `scale(${this.state.currentZoom}) rotate(${this.state.rotation}deg)`;
    this.elements.mainImage.style.cursor = this.state.currentZoom > 1.0 ? 'grab' : 'crosshair';

    // Aktualizuj wskaźnik zoom
    const zoomLevel = document.getElementById('imageZoomLevel');
    if (zoomLevel) {
      zoomLevel.textContent = Math.round(this.state.currentZoom * 100) + '%';
    }
  }

  // === DRAGGING AND PANNING ===

  /**
   * Rozpoczyna przeciąganie
   */
  startDragging(e) {
    this.state.isDragging = true;
    this.state.lastX = e.clientX;
    this.state.lastY = e.clientY;

    if (this.elements.mainImage) {
      this.elements.mainImage.style.cursor = 'grabbing';
    }
  }

  /**
   * Obsługa przeciągania
   */
  handleDragging(e) {
    if (!this.state.isDragging) return;

    const deltaX = e.clientX - this.state.lastX;
    const deltaY = e.clientY - this.state.lastY;

    this.panImage(deltaX, deltaY);

    this.state.lastX = e.clientX;
    this.state.lastY = e.clientY;
  }

  /**
   * Zatrzymuje przeciąganie
   */
  stopDragging() {
    if (!this.state.isDragging) return;

    this.state.isDragging = false;

    if (this.elements.mainImage) {
      this.elements.mainImage.style.cursor = this.state.currentZoom > 1.0 ? 'grab' : 'crosshair';
    }
  }

  /**
   * Przesuwa obraz
   */
  panImage(deltaX, deltaY) {
    if (!this.elements.imageContainer) return;

    this.elements.imageContainer.scrollLeft -= deltaX;
    this.elements.imageContainer.scrollTop -= deltaY;
  }

  // === ROTATION ===

  /**
   * Obraca obraz o 90 stopni
   */
  rotateImage() {
    this.state.rotation = (this.state.rotation + 90) % 360;
    this.applyZoom(); // applyZoom również aplikuje rotację
  }

  // === FULLSCREEN ===

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
    const element = this.elements.imageContainer || document.documentElement;

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
      document.body.classList.add('image-fullscreen');
    } else {
      document.body.classList.remove('image-fullscreen');
    }
  }

  // === IMAGE ADJUSTMENTS ===

  /**
   * Reguluje jasność obrazu
   */
  adjustImageBrightness(value) {
    this.applyImageFilters();
  }

  /**
   * Reguluje kontrast obrazu
   */
  adjustImageContrast(value) {
    this.applyImageFilters();
  }

  /**
   * Aplikuje filtry obrazu
   */
  applyImageFilters() {
    if (!this.elements.mainImage) return;

    const brightnessSlider = document.getElementById('brightnessSlider');
    const contrastSlider = document.getElementById('contrastSlider');

    if (!brightnessSlider || !contrastSlider) return;

    const brightness = parseInt(brightnessSlider.value);
    const contrast = parseInt(contrastSlider.value);

    const brightnessValue = 100 + brightness; // 0-200%
    const contrastValue = 100 + contrast; // 0-200%

    this.elements.mainImage.style.filter = `brightness(${brightnessValue}%) contrast(${contrastValue}%)`;
  }

  /**
   * Resetuje regulacje obrazu
   */
  resetImageAdjustments() {
    const brightnessSlider = document.getElementById('brightnessSlider');
    const contrastSlider = document.getElementById('contrastSlider');

    if (brightnessSlider) brightnessSlider.value = 0;
    if (contrastSlider) contrastSlider.value = 0;

    if (this.elements.mainImage) {
      this.elements.mainImage.style.filter = '';
    }
  }

  // === IMAGE INFO ===

  /**
   * Obsługa załadowania obrazu
   */
  onImageLoad() {
    this.showImageInfo();
    this.fitToScreen(); // Auto-fit przy pierwszym ładowaniu
  }

  /**
   * Pokazuje informacje o obrazie
   */
  showImageInfo() {
    if (!this.elements.mainImage) return;

    const img = this.elements.mainImage;
    const fileSize = this.getImageFileSize();

    // Dodaj info panel
    let infoPanel = document.getElementById('imageInfoPanel');
    if (!infoPanel) {
      infoPanel = document.createElement('div');
      infoPanel.id = 'imageInfoPanel';
      infoPanel.className = 'alert alert-light mb-3';

      const textEditorContainer = document.getElementById('textEditorContainer');
      if (textEditorContainer) {
        textEditorContainer.appendChild(infoPanel);
      }
    }

    infoPanel.innerHTML = `
      <div class="row small text-muted">
        <div class="col-md-6">
          <strong>Wymiary:</strong> ${img.naturalWidth} × ${img.naturalHeight} px
        </div>
        <div class="col-md-6">
          <strong>Zoom:</strong> <span id="currentZoomInfo">${Math.round(this.state.currentZoom * 100)}%</span>
          ${fileSize ? ` | <strong>Rozmiar:</strong> ${fileSize}` : ''}
        </div>
      </div>
    `;
  }

  /**
   * Pobiera rozmiar pliku obrazu (jeśli dostępny)
   */
  getImageFileSize() {
    // Ta informacja może być przekazana z serwera
    // Na razie zwracamy null
    return null;
  }

  // === UTILITY FUNCTIONS ===

  /**
   * Zapisuje aktualny tekst OCR
   */
  async saveCurrentText() {
    if (window.textEditor) {
      return await window.textEditor.saveChanges();
    }
    return false;
  }

  /**
   * Eksportuje obraz z zastosowanymi filtrami
   */
  async exportProcessedImage() {
    if (!this.elements.mainImage) return;

    try {
      // Utwórz canvas z przetworzonym obrazem
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');

      canvas.width = this.elements.mainImage.naturalWidth;
      canvas.height = this.elements.mainImage.naturalHeight;

      // Aplikuj filtry
      const filters = this.elements.mainImage.style.filter;
      if (filters) {
        ctx.filter = filters;
      }

      ctx.drawImage(this.elements.mainImage, 0, 0);

      // Eksportuj
      canvas.toBlob((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `processed_image_${this.docId}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        window.alertManager.success('Przetworzony obraz został wyeksportowany');
      }, 'image/png');
    } catch (error) {
      window.alertManager.error('Nie udało się wyeksportować obrazu');
    }
  }

  /**
   * Pobiera informacje o stanie obrazu
   */
  getImageInfo() {
    return {
      zoom: this.state.currentZoom,
      rotation: this.state.rotation,
      isFullscreen: this.state.isFullscreen,
      naturalWidth: this.elements.mainImage?.naturalWidth || 0,
      naturalHeight: this.elements.mainImage?.naturalHeight || 0
    };
  }

  /**
   * Niszczy manager
   */
  destroy() {
    // Usuń event listenery
    document.removeEventListener('fullscreenchange', this.handleFullscreenChange);
    document.removeEventListener('keydown', this.setupKeyboardShortcuts);
    document.removeEventListener('mousemove', this.handleDragging);
    document.removeEventListener('mouseup', this.stopDragging);

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
   * Ustawia zoom
   */
  setZoom(zoom) {
    this.state.currentZoom = zoom;
    this.applyZoom();
  }

  /**
   * Pobiera aktualny zoom
   */
  getZoom() {
    return this.state.currentZoom;
  }

  /**
   * Ustawia rotację
   */
  setRotation(degrees) {
    this.state.rotation = degrees % 360;
    this.applyZoom();
  }

  /**
   * Pobiera aktualną rotację
   */
  getRotation() {
    return this.state.rotation;
  }

  /**
   * Centruje obraz
   */
  centerImage() {
    if (!this.elements.imageContainer) return;

    const container = this.elements.imageContainer;
    container.scrollLeft = (container.scrollWidth - container.clientWidth) / 2;
    container.scrollTop = (container.scrollHeight - container.clientHeight) / 2;
  }
}

// Export globalny
window.ImageViewerManager = ImageViewerManager;