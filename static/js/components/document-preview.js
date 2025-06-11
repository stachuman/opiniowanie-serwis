/**
 * Uproszczony komponent podglądu dokumentów z obsługą embedded view
 * Rozwiązuje problem zagnieżdżania widoków przez dodanie parametru ?embedded=true
 */

class DocumentPreview {
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);

    if (!this.container) {
      throw new Error(`Container ${containerId} not found`);
    }

    // Konfiguracja
    this.config = {
      docId: options.docId,
      docType: options.docType,
      filename: options.filename || '',
      previewUrl: options.previewUrl || `/document/${options.docId}/preview`,
      downloadUrl: options.downloadUrl || `/document/${options.docId}/download`,
      height: options.height || '600px',
      embedded: options.embedded !== false, // Domyślnie true dla embedded view
      ...options
    };

    // Stan komponentu
    this.state = {
      isLoading: true
    };

    // Elementy DOM
    this.elements = {};

    console.log('DocumentPreview config:', this.config);
    this.init();
  }

  /**
   * Inicjalizacja komponentu
   */
  init() {
    this.detectDocumentType();
    this.setupDOM();
    this.loadPreview();
  }

  /**
   * Wykrywa typ dokumentu na podstawie MIME type lub rozszerzenia
   */
  detectDocumentType() {
    if (this.config.docType && this.config.docType !== 'unknown') return;

    const filename = this.config.filename.toLowerCase();

    if (filename.endsWith('.pdf')) {
      this.config.docType = 'pdf';
    } else if (filename.match(/\.(jpg|jpeg|png|gif|bmp|tiff|webp)$/)) {
      this.config.docType = 'image';
    } else if (filename.match(/\.(doc|docx)$/)) {
      this.config.docType = 'word';
    } else if (filename.match(/\.(txt|log)$/)) {
      this.config.docType = 'text';
    } else {
      this.config.docType = 'unknown';
    }

    console.log('Detected document type:', this.config.docType, 'for file:', filename);
  }

  /**
   * Konfiguracja struktury DOM
   */
  setupDOM() {
    this.elements = {};
    this.container.className += ' document-preview-container';
    this.container.style.position = 'relative';

    // Dla embedded view nie pokazujemy toolbar (treść ma swój własny)
    if (!this.config.embedded || this.config.docType === 'pdf' || this.config.docType === 'image') {
      // Toolbar z przyciskiem pobierania
      this.elements.toolbar = this.createToolbar();
      this.container.appendChild(this.elements.toolbar);
    }

    // Preview area
    this.elements.previewArea = this.createPreviewArea();
    this.container.appendChild(this.elements.previewArea);

    // Status bar - tylko dla non-embedded view
    if (!this.config.embedded || this.config.docType === 'pdf' || this.config.docType === 'image') {
      this.elements.statusBar = this.createStatusBar();
      this.container.appendChild(this.elements.statusBar);
    }
  }

  /**
   * Tworzy prosty toolbar
   */
  createToolbar() {
    const toolbar = document.createElement('div');
    toolbar.className = 'preview-toolbar d-flex justify-content-between align-items-center p-2 bg-light border-bottom';

    // Nazwa pliku
    const fileInfo = document.createElement('span');
    fileInfo.className = 'text-muted small';
    fileInfo.innerHTML = `<i class="bi bi-file-earmark me-1"></i>${this.config.filename}`;

    // Przycisk pobierania
    const downloadBtn = document.createElement('a');
    downloadBtn.href = this.config.downloadUrl;
    downloadBtn.className = 'btn btn-sm btn-outline-primary';
    downloadBtn.innerHTML = '<i class="bi bi-download"></i> Pobierz';
    downloadBtn.title = 'Pobierz dokument';

    toolbar.appendChild(fileInfo);
    toolbar.appendChild(downloadBtn);

    return toolbar;
  }

  /**
   * Tworzy obszar podglądu
   */
  createPreviewArea() {
    const previewArea = document.createElement('div');
    previewArea.className = 'preview-area position-relative overflow-auto';
    previewArea.style.height = this.config.height;
    previewArea.style.backgroundColor = '#f8f9fa';

    // Kontener na treść
    const contentContainer = document.createElement('div');

    // Dla embedded view usuń centrowanie i wypełnienie
    if (this.config.embedded && (this.config.docType === 'word' || this.config.docType === 'text')) {
      contentContainer.className = 'preview-content h-100';
      contentContainer.style.padding = '0';
    } else {
      contentContainer.className = 'preview-content d-flex justify-content-center align-items-center h-100';
    }

    previewArea.appendChild(contentContainer);

    this.elements.contentContainer = contentContainer;
    return previewArea;
  }

  /**
   * Tworzy pasek statusu
   */
  createStatusBar() {
    const statusBar = document.createElement('div');
    statusBar.className = 'preview-status-bar d-flex justify-content-between align-items-center p-2 bg-light border-top small text-muted';

    const statusText = document.createElement('span');
    statusText.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Ładowanie...';

    statusBar.appendChild(statusText);
    this.elements.statusText = statusText;

    return statusBar;
  }

  /**
   * Oznacza zakończenie ładowania
   */
  finishLoading() {
    this.state.isLoading = false;
  }

  /**
   * Buduje URL dla podglądu z odpowiednimi parametrami
   */
  buildPreviewUrl() {
    let url = this.config.previewUrl;

    // JEDYNA ZMIANA: Dla Word i text dokumentów w embedded view dodaj parametr
    if (this.config.embedded && (this.config.docType === 'word' || this.config.docType === 'text')) {
      const separator = url.includes('?') ? '&' : '?';
      url += `${separator}embedded=true`;
    }

    return url;
  }
  /**
   * Ładuje podgląd dokumentu
   */
  async loadPreview() {
    this.updateStatus('<i class="bi bi-hourglass-split me-1"></i>Ładowanie...');

    try {
      console.log('Loading preview for type:', this.config.docType);

      switch (this.config.docType) {
        case 'pdf':
          await this.loadPdfPreview();
          break;
        case 'image':
          await this.loadImagePreview();
          break;
        case 'word':
          await this.loadWordPreview();
          break;
        case 'text':
          await this.loadTextPreview();
          break;
        default:
          this.showUnsupportedType();
      }
    } catch (error) {
      console.error('Error loading preview:', error);
      this.showError('Nie udało się załadować podglądu: ' + error.message);
    }
  }

  /**
   * Ładuje podgląd PDF
   */
  async loadPdfPreview() {
    const previewUrl = this.buildPreviewUrl();
    console.log('Loading PDF preview from:', previewUrl);

    const iframe = document.createElement('iframe');
    iframe.src = previewUrl;
    iframe.style.cssText = `
      width: 100%;
      height: 100%;
      border: none;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    `;

    // Najpierw dodaj iframe do kontenera
    this.elements.contentContainer.innerHTML = '';
    this.elements.contentContainer.appendChild(iframe);
    this.elements.previewElement = iframe;

    // Ustaw timeout jako backup dla ukrycia loadera
    const hideLoaderTimeout = setTimeout(() => {
      console.log('PDF load timeout - finishing load as backup');
      this.finishLoading();
      this.updateStatus('<i class="bi bi-check-circle me-1"></i>PDF załadowany');
    }, 3000);

    iframe.onload = () => {
      clearTimeout(hideLoaderTimeout);
      console.log('PDF iframe loaded successfully');
      this.finishLoading();
      this.updateStatus('<i class="bi bi-check-circle me-1"></i>PDF załadowany');
    };

    iframe.onerror = () => {
      clearTimeout(hideLoaderTimeout);
      console.error('Error loading PDF iframe');
      this.finishLoading();
      this.showError('Nie udało się załadować PDF');
    };
  }

  /**
   * Ładuje podgląd obrazu
   */
  async loadImagePreview() {
    const previewUrl = this.buildPreviewUrl();
    console.log('Loading image preview from:', previewUrl);

    const img = document.createElement('img');
    img.src = previewUrl;
    img.style.cssText = `
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
    `;
    img.draggable = false;

    // Najpierw dodaj obraz do kontenera
    this.elements.contentContainer.innerHTML = '';
    this.elements.contentContainer.appendChild(img);
    this.elements.previewElement = img;

    // Ustaw timeout jako backup
    const hideLoaderTimeout = setTimeout(() => {
      console.log('Image load timeout - finishing load as backup');
      this.finishLoading();
      this.updateStatus('<i class="bi bi-check-circle me-1"></i>Obraz załadowany');
    }, 5000);

    img.onload = () => {
      clearTimeout(hideLoaderTimeout);
      console.log('Image loaded successfully');
      this.finishLoading();
      this.updateStatus(`<i class="bi bi-check-circle me-1"></i>${img.naturalWidth} × ${img.naturalHeight} px`);
    };

    img.onerror = () => {
      clearTimeout(hideLoaderTimeout);
      console.error('Error loading image');
      this.finishLoading();
      this.showError('Nie udało się załadować obrazu');
    };
  }

  /**
   * Ładuje podgląd dokumentu Word
   */
  async loadWordPreview() {
    const previewUrl = this.buildPreviewUrl();
    console.log('Loading Word preview from:', previewUrl);

    if (this.config.embedded) {
      // Dla embedded view ładuj bezpośrednio HTML
      try {
        const response = await fetch(previewUrl);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const htmlContent = await response.text();

        this.elements.contentContainer.innerHTML = htmlContent;
        this.elements.previewElement = this.elements.contentContainer.firstElementChild;

        this.finishLoading();
        this.updateStatus('<i class="bi bi-check-circle me-1"></i>Dokument Word załadowany');

      } catch (error) {
        console.error('Error loading embedded Word preview:', error);
        this.showError('Nie udało się załadować dokumentu Word: ' + error.message);
      }
    } else {
      // Dla non-embedded view użyj iframe
      const iframe = document.createElement('iframe');
      iframe.src = previewUrl;
      iframe.style.cssText = `
        width: 100%;
        height: 100%;
        border: none;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
      `;

      this.elements.contentContainer.innerHTML = '';
      this.elements.contentContainer.appendChild(iframe);
      this.elements.previewElement = iframe;

      // Oznacz jako załadowane natychmiast dla Word docs
      this.finishLoading();

      const hideLoaderTimeout = setTimeout(() => {
        this.updateStatus('<i class="bi bi-check-circle me-1"></i>Dokument Word załadowany');
      }, 1000);

      iframe.onload = () => {
        clearTimeout(hideLoaderTimeout);
        this.updateStatus('<i class="bi bi-check-circle me-1"></i>Dokument Word załadowany');
      };

      iframe.onerror = () => {
        clearTimeout(hideLoaderTimeout);
        console.error('Error loading Word document');
        this.showError('Nie udało się załadować dokumentu Word');
      };
    }
  }

  /**
   * Ładuje podgląd tekstu
   */
  async loadTextPreview() {
    const previewUrl = this.buildPreviewUrl();
    console.log('Loading text preview from:', previewUrl);

    // Oznacz jako załadowane natychmiast
    this.finishLoading();

    if (this.config.embedded) {
      // Dla embedded view ładuj bezpośrednio HTML
      try {
        const response = await fetch(previewUrl);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const htmlContent = await response.text();

        this.elements.contentContainer.innerHTML = htmlContent;
        this.elements.previewElement = this.elements.contentContainer.firstElementChild;

        this.updateStatus('<i class="bi bi-check-circle me-1"></i>Tekst załadowany');

      } catch (error) {
        console.error('Error loading embedded text preview:', error);
        this.showError('Nie udało się załadować tekstu: ' + error.message);
      }
    } else {
      // Dla non-embedded view pobierz jako tekst i wyświetl
      try {
        const response = await fetch(previewUrl);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const text = await response.text();

        const preElement = document.createElement('pre');
        preElement.style.cssText = `
          white-space: pre-wrap;
          font-family: 'Courier New', monospace;
          font-size: 0.9rem;
          line-height: 1.5;
          padding: 1rem;
          background-color: white;
          border-radius: 0.375rem;
          max-width: 100%;
          overflow-x: auto;
          margin: 1rem;
          max-height: calc(${this.config.height} - 2rem);
          overflow-y: auto;
        `;
        preElement.textContent = text;

        this.elements.contentContainer.innerHTML = '';
        this.elements.contentContainer.appendChild(preElement);
        this.elements.previewElement = preElement;

        this.updateStatus(`<i class="bi bi-check-circle me-1"></i>${text.length} znaków`);

      } catch (error) {
        console.error('Error loading text preview:', error);
        this.showError('Nie udało się załadować tekstu: ' + error.message);
      }
    }
  }

  /**
   * Aktualizuje status
   */
  updateStatus(htmlText) {
    if (this.elements.statusText) {
      this.elements.statusText.innerHTML = htmlText;
    }
  }

  /**
   * Pokazuje błąd
   */
  showError(message) {
    console.error('DocumentPreview error:', message);

    this.finishLoading();

    this.elements.contentContainer.innerHTML = `
      <div class="text-center text-muted py-5">
        <i class="bi bi-exclamation-triangle text-warning" style="font-size: 3rem;"></i>
        <h5 class="mt-3 text-danger">Błąd podglądu</h5>
        <p class="mt-2">${message}</p>
        <div class="mt-3">
          <a class="btn btn-outline-secondary me-2" href="${this.config.downloadUrl}">
            <i class="bi bi-download"></i> Pobierz plik
          </a>
          <button class="btn btn-outline-primary" onclick="location.reload()">
            <i class="bi bi-arrow-clockwise"></i> Spróbuj ponownie
          </button>
        </div>
      </div>
    `;
    this.updateStatus('<i class="bi bi-x-circle text-danger me-1"></i>Błąd');
  }

  /**
   * Pokazuje nieobsługiwany typ
   */
  showUnsupportedType() {
    console.warn('Unsupported document type:', this.config.docType);

    this.finishLoading();

    this.elements.contentContainer.innerHTML = `
      <div class="text-center text-muted py-5">
        <i class="bi bi-file-earmark text-secondary" style="font-size: 3rem;"></i>
        <h5 class="mt-3">Podgląd niedostępny</h5>
        <p class="mt-2">Podgląd nie jest dostępny dla tego typu pliku (${this.config.docType}).</p>
        <div class="mt-3">
          <a class="btn btn-outline-secondary" href="${this.config.downloadUrl}">
            <i class="bi bi-download"></i> Pobierz plik
          </a>
        </div>
      </div>
    `;
    this.updateStatus('<i class="bi bi-info-circle text-muted me-1"></i>Nieobsługiwany typ');
  }

  // === PUBLIC API ===

  /**
   * Odświeża podgląd
   */
  refresh() {
    this.loadPreview();
  }

  /**
   * Sprawdza czy jest w trakcie ładowania
   */
  isLoading() {
    return this.state.isLoading;
  }

  /**
   * Niszczy komponent
   */
  destroy() {
    // Wyczyść kontener
    this.container.innerHTML = '';

    // Wyczyść stan
    this.state = {};
    this.elements = {};
  }
}

// Funkcje helper do szybkiego tworzenia podglądów
window.createDocumentPreview = (containerId, docId, options = {}) => {
  return new DocumentPreview(containerId, { docId, ...options });
};

window.createImagePreview = (containerId, imageUrl, options = {}) => {
  return new DocumentPreview(containerId, {
    docType: 'image',
    previewUrl: imageUrl,
    embedded: false,
    ...options
  });
};

window.createPdfPreview = (containerId, pdfUrl, options = {}) => {
  return new DocumentPreview(containerId, {
    docType: 'pdf',
    previewUrl: pdfUrl,
    embedded: false,
    ...options
  });
};

// Export globalny
window.DocumentPreview = DocumentPreview;

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = DocumentPreview;
}