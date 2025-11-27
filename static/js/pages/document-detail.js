/**
 * JavaScript specyficzny dla strony document.html (szczegóły dokumentu)
 * Obsługuje funkcjonalności związane z zarządzaniem dokumentem i OCR
 */

class DocumentDetailManager {
  constructor(docId, options = {}) {
    this.docId = docId;
    this.config = {
      hasOcr: options.hasOcr || false,
      ocrDocId: options.ocrDocId || null,
      ocrStatus: options.ocrStatus || 'none',
      ...options
    };

    this.state = {
      ocrProgressMonitoring: false,
      lastOcrCheck: null
    };

    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.setupEventListeners();
    this.setupOcrMonitoring();
    this.setupFormHandlers();
    console.log('DocumentDetailManager zainicjalizowany dla dokumentu', this.docId);
  }

  /**
   * Konfiguracja event listenerów
   */
  setupEventListeners() {
    document.addEventListener('click', (e) => this.handleGlobalClick(e));
    document.addEventListener('submit', (e) => this.handleFormSubmit(e));

    // Enter key support for merge page input
    const mergeInput = document.getElementById('mergePageSelection');
    if (mergeInput) {
      mergeInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          const mergeBtn = document.querySelector('.merge-ocr-btn');
          if (mergeBtn) {
            mergeBtn.click();
          }
        }
      });
      console.log('DocumentDetailManager: Merge input Enter key handler registered');
    }
  }

  /**
   * Obsługa globalnych kliknięć
   */
  handleGlobalClick(e) {
    // Debug: log all clicks on buttons
    if (e.target.closest('button')) {
      console.log('DocumentDetailManager: button clicked', e.target, e.target.closest('button'));
    }

    // Przyciski uruchamiania OCR
    const runOcrBtn = e.target.closest('.run-ocr-btn');
    if (runOcrBtn) {
      console.log('DocumentDetailManager: run-ocr-btn clicked', runOcrBtn);
      e.preventDefault();
      e.stopPropagation();
      this.handleRunOcr(e, runOcrBtn);
      return;
    }

    // Przycisk merge OCR
    const mergeOcrBtn = e.target.closest('.merge-ocr-btn');
    if (mergeOcrBtn) {
      console.log('DocumentDetailManager: merge-ocr-btn clicked', mergeOcrBtn);
      e.preventDefault();
      e.stopPropagation();
      this.handleMergeOcr(e, mergeOcrBtn);
      return;
    }

    // Przycisk odświeżania tekstu OCR
    const refreshOcrBtn = e.target.closest('.refresh-ocr-btn');
    if (refreshOcrBtn) {
      this.handleRefreshOcr(e, refreshOcrBtn);
      return;
    }
  }

/**
   * Obsługa uruchamiania OCR
   */
  async handleRunOcr(e, button) {
    e.preventDefault();
    console.log('DocumentDetailManager: handleRunOcr called');

    const docId = button.getAttribute('data-doc-id') || this.docId;

    try {
      // Wyłącz przycisk i pokaż loading
      button.disabled = true;
      const originalHtml = button.innerHTML;
      button.innerHTML = '<i class="bi bi-hourglass-split"></i> Uruchamianie...';

      // POPRAWKA: Bezpośredni fetch request zamiast przez apiClient
      const response = await fetch(`/document/${docId}/run_ocr`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        }
      });

      // Endpoint zwraca redirect, fetch automatycznie go obsłuży
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Pokaż komunikat sukcesu
      if (window.alertManager) {
        window.alertManager.success('Proces OCR został uruchomiony', {
          duration: 5000
        });
      }

      // Rozpocznij monitorowanie
      this.startOcrProgressMonitoring();

      // Odśwież stronę po krótkim opóźnieniu
      setTimeout(() => location.reload(), 2000);

    } catch (error) {
      console.error('Błąd uruchamiania OCR:', error);

      if (window.alertManager) {
        window.alertManager.error('Nie udało się uruchomić OCR: ' + error.message);
      } else {
        alert('Błąd uruchamiania OCR: ' + error.message);
      }

      // Przywróć przycisk
      button.disabled = false;
      button.innerHTML = originalHtml;
    }
  }

  /**
   * Obsługa merge OCR (OCR wybranych stron)
   */
  async handleMergeOcr(e, button) {
    e.preventDefault();
    console.log('DocumentDetailManager: handleMergeOcr called');

    const docId = button.getAttribute('data-doc-id') || this.docId;
    const pageInput = document.getElementById('mergePageSelection');

    if (!pageInput) {
      if (window.alertManager) {
        window.alertManager.error('Nie znaleziono pola wyboru stron');
      }
      return;
    }

    const pages = pageInput.value.trim();

    if (!pages) {
      if (window.alertManager) {
        window.alertManager.warning('Podaj numery stron do przetworzenia (np. 1,3,5-7)');
      }
      pageInput.focus();
      return;
    }

    // Walidacja formatu po stronie klienta
    const validPattern = /^[\d,\s\-]+$/;
    if (!validPattern.test(pages)) {
      if (window.alertManager) {
        window.alertManager.error('Nieprawidłowy format. Użyj cyfr, przecinków i myślników (np. 1,3,5-7)');
      }
      return;
    }

    try {
      // Wyłącz przycisk i pokaż loading
      button.disabled = true;
      const originalHtml = button.innerHTML;
      button.innerHTML = '<i class="bi bi-hourglass-split"></i> ...';

      // Wyślij request
      const formData = new FormData();
      formData.append('pages', pages);

      const response = await fetch(`/document/${docId}/run_ocr_merge`, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || `HTTP ${response.status}`);
      }

      // Pokaż komunikat sukcesu
      if (window.alertManager) {
        window.alertManager.success(`Merge OCR uruchomiony dla stron: ${pages}`, {
          duration: 5000
        });
      }

      // Rozpocznij monitorowanie
      this.startOcrProgressMonitoring();

      // Odśwież stronę po krótkim opóźnieniu
      setTimeout(() => location.reload(), 2000);

    } catch (error) {
      console.error('Błąd merge OCR:', error);

      if (window.alertManager) {
        window.alertManager.error('Nie udało się uruchomić merge OCR: ' + error.message);
      } else {
        alert('Błąd merge OCR: ' + error.message);
      }

      // Przywróć przycisk
      button.disabled = false;
      button.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Merge';
    }
  }

  /**
   * Obsługa odświeżania tekstu OCR
   */
  async handleRefreshOcr(e, button) {
    e.preventDefault();

    const ocrDocId = button.getAttribute('data-ocr-doc-id') || this.config.ocrDocId;

    if (!ocrDocId) {
      window.alertManager.warning('Brak ID dokumentu OCR');
      return;
    }

    try {
      this.showOcrRefreshLoader(true);

      // Pobierz aktualny tekst OCR
      const result = await window.apiClient.getOcrText(this.docId);

      if (result.success && result.has_ocr && result.text.trim()) {
        // Aktualizuj wyświetlany tekst
        this.updateOcrTextDisplay(result.text);
        window.alertManager.success('Tekst OCR został odświeżony', { duration: 3000 });
      } else {
        window.alertManager.warning('Brak tekstu OCR dla tego dokumentu');
      }

    } catch (error) {
      console.error('Błąd odświeżania OCR:', error);
      window.alertManager.error('Nie udało się odświeżyć tekstu OCR: ' + error.message);
    } finally {
      this.showOcrRefreshLoader(false);
    }
  }

  /**
   * Aktualizuje wyświetlanie tekstu OCR
   */
  updateOcrTextDisplay(text) {
    const ocrTextContent = document.getElementById('ocrTextContent');
    if (ocrTextContent) {
      const preElement = ocrTextContent.querySelector('pre');
      if (preElement) {
        preElement.textContent = text;
      }
    }
  }

  /**
   * Pokazuje/ukrywa loader odświeżania OCR
   */
  showOcrRefreshLoader(show) {
    const loader = document.getElementById('ocrRefreshLoader');
    const content = document.getElementById('ocrTextContent');

    if (loader && content) {
      if (show) {
        loader.classList.remove('d-none');
        content.style.opacity = '0.5';
      } else {
        loader.classList.add('d-none');
        content.style.opacity = '1';
      }
    }
  }

  /**
   * Konfiguracja monitorowania OCR
   */
  setupOcrMonitoring() {
    // Rozpocznij monitorowanie jeśli OCR jest aktywny
    if (this.config.ocrStatus === 'running' || this.config.ocrStatus === 'pending') {
      this.startOcrProgressMonitoring();
    }
  }

  /**
   * Rozpoczyna monitorowanie postępu OCR
   */
  startOcrProgressMonitoring() {
    if (this.state.ocrProgressMonitoring) return;

    this.state.ocrProgressMonitoring = true;

    window.apiClient.startOcrProgressMonitoring(this.docId, (data) => {
      this.handleOcrProgressUpdate(data);
    }, 2000);
  }

  /**
   * Obsługuje aktualizacje postępu OCR
   */
  handleOcrProgressUpdate(data) {
    const progressBar = document.getElementById('ocrProgressBar');
    const progressText = document.getElementById('ocrProgressText');
    const progressInfo = document.getElementById('ocrProgressInfo');

    if (data.status === 'running') {
      // Aktualizuj pasek postępu
      const progressPercent = (data.progress * 100).toFixed(0);

      if (progressBar) {
        progressBar.style.width = progressPercent + '%';
        progressBar.setAttribute('aria-valuenow', progressPercent);
      }

      if (progressText) {
        progressText.textContent = progressPercent + '%';
      }

      if (progressInfo) {
        let infoText = data.info || "Przetwarzanie...";
        if (data.current_page && data.total_pages) {
          infoText += ` (Strona ${data.current_page}/${data.total_pages})`;
        }
        progressInfo.textContent = infoText;
      }

    } else if (data.status === 'done' || data.status === 'fail') {
      // OCR zakończony
      this.state.ocrProgressMonitoring = false;

      if (data.status === 'done') {
        window.alertManager.success('OCR zakończony pomyślnie!', {
          duration: 5000
        });
      } else {
        window.alertManager.error('OCR zakończony błędem');
      }

      // Odśwież stronę po krótkim opóźnieniu
      setTimeout(() => location.reload(), 3000);
    }
  }

  /**
   * Konfiguracja obsługi formularzy
   */
  setupFormHandlers() {
    // Obsługa formularza edycji dokumentu
    const editForm = document.getElementById('documentEditForm');
    if (editForm) {
      editForm.addEventListener('submit', (e) => this.handleDocumentEditSubmit(e));
    }
  }

  /**
   * Obsługa formularza edycji dokumentu
   */
  async handleDocumentEditSubmit(e) {
    // Pozwól na normalne działanie formularza
    // Można tutaj dodać walidację lub async handling

    const formData = new FormData(e.target);
    const data = {};

    formData.forEach((value, key) => {
      data[key] = value;
    });

    // Log dla debugowania
    console.log('Aktualizacja dokumentu:', data);
  }

  /**
   * Obsługa submit formularzy globalnie
   */
  handleFormSubmit(e) {
    const form = e.target;

    // Obsługa różnych typów formularzy jeśli potrzeba
    // Na razie brak specjalnej obsługi
  }

  // === UTILITY METHODS ===

  /**
   * Sprawdza czy OCR jest aktywny
   */
  isOcrActive() {
    return this.config.ocrStatus === 'running' || this.config.ocrStatus === 'pending';
  }

  /**
   * Pobiera aktualny status OCR
   */
  async refreshOcrStatus() {
    try {
      const progress = await window.apiClient.getOcrProgress(this.docId);
      this.config.ocrStatus = progress.status;
      return progress;
    } catch (error) {
      console.warn('Nie udało się pobrać statusu OCR:', error);
      return null;
    }
  }

  /**
   * Aktualizuje przyciski OCR w zależności od statusu
   */
  updateOcrButtons(status) {
    const actionButtons = document.getElementById('ocrActionButtons');
    if (!actionButtons) return;

    // Tutaj można zaktualizować przyciski w zależności od statusu
    // Na razie pozostawiamy jak jest, ale można rozszerzyć
  }

  /**
   * Eksportuje tekst OCR do różnych formatów
   */
  async exportOcrText(format = 'txt') {
    if (!this.config.ocrDocId) {
      window.alertManager.warning('Brak tekstu OCR do eksportu');
      return;
    }

    try {
      const result = await window.apiClient.getOcrText(this.docId);

      if (result.success && result.text) {
        switch (format) {
          case 'txt':
            this.downloadTextFile(result.text, `ocr_${this.docId}.txt`);
            break;
          case 'clipboard':
            await window.clipboardManager.copyTextToClipboard(result.text);
            window.alertManager.success('Tekst OCR skopiowany do schowka');
            break;
          default:
            console.warn('Nieznany format eksportu:', format);
        }
      } else {
        window.alertManager.warning('Brak tekstu OCR do eksportu');
      }

    } catch (error) {
      window.alertManager.error('Nie udało się wyeksportować tekstu OCR: ' + error.message);
    }
  }

  /**
   * Pobiera plik tekstowy
   */
  downloadTextFile(content, filename) {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    URL.revokeObjectURL(url);
  }

  /**
   * Niszczy manager
   */
  destroy() {
    this.state.ocrProgressMonitoring = false;

    // Usuń event listenery
    document.removeEventListener('click', this.handleGlobalClick);
    document.removeEventListener('submit', this.handleFormSubmit);

    // Wyczyść stan
    this.state = {};
  }

  // === PUBLIC API ===

  /**
   * Odświeża widok dokumentu
   */
  refresh() {
    location.reload();
  }

  /**
   * Uruchamia OCR programmatycznie
   */
  async runOcr() {
    const button = document.querySelector('.run-ocr-btn');
    if (button) {
      button.click();
    } else {
      await this.handleRunOcr({ preventDefault: () => {} }, {
        getAttribute: () => this.docId,
        disabled: false,
        innerHTML: ''
      });
    }
  }

  /**
   * Pobiera informacje o dokumencie
   */
  getDocumentInfo() {
    return {
      docId: this.docId,
      ocrStatus: this.config.ocrStatus,
      hasOcr: this.config.hasOcr,
      ocrDocId: this.config.ocrDocId
    };
  }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
  console.log('DocumentDetailManager: DOM loaded, checking conditions...');
  console.log('Page type:', document.body.getAttribute('data-page-type'));
  console.log('URL pathname:', window.location.pathname);
  
  // Inicjalizuj tylko na stronach dokumentów
  if (document.querySelector('[data-page-type="document_detail"]') || 
      window.location.pathname.includes('/document/')) {
    
    console.log('DocumentDetailManager: Initializing...');
    
    // Pobierz docId z URL
    const pathParts = window.location.pathname.split('/');
    const docIdIndex = pathParts.indexOf('document') + 1;
    const docId = docIdIndex < pathParts.length ? parseInt(pathParts[docIdIndex]) : null;
    
    console.log('DocumentDetailManager: docId from URL:', docId);
    
    if (docId) {
      window.documentDetailManager = new DocumentDetailManager(docId);
      console.log('DocumentDetailManager: Initialized successfully');
    } else {
      console.warn('DocumentDetailManager: No docId found in URL');
    }
  } else {
    console.log('DocumentDetailManager: Not a document page, skipping initialization');
  }
});

// Export globalny
window.DocumentDetailManager = DocumentDetailManager;