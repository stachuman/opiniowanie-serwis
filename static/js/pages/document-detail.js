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
  }

  /**
   * Obsługa globalnych kliknięć
   */
  handleGlobalClick(e) {
    // Przyciski uruchamiania OCR
    const runOcrBtn = e.target.closest('.run-ocr-btn');
    if (runOcrBtn) {
      this.handleRunOcr(e, runOcrBtn);
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

// Export globalny
window.DocumentDetailManager = DocumentDetailManager;