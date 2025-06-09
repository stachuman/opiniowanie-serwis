/**
 * JavaScript specyficzny dla strony documents.html (lista dokumentów)
 * Obsługuje funkcjonalności związane z filtrowaniem, wyszukiwaniem i zarządzaniem listą
 */

class DocumentListManager {
  constructor() {
    this.state = {
      autoRefreshEnabled: false,
      autoRefreshInterval: null,
      lastRefreshTime: null
    };

    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.setupEventListeners();
    this.setupAutoRefresh();
    this.setupQuickActions();
    console.log('DocumentListManager zainicjalizowany');
  }

  /**
   * Konfiguracja event listenerów
   */
  setupEventListeners() {
    document.addEventListener('click', (e) => this.handleGlobalClick(e));
    document.addEventListener('change', (e) => this.handleFormChange(e));
  }

  /**
   * Obsługa globalnych kliknięć
   */
  handleGlobalClick(e) {
    // Szybki podgląd dokumentu
    const previewBtn = e.target.closest('.quick-preview-btn');
    if (previewBtn) {
      this.handleQuickPreview(e, previewBtn);
      return;
    }

    // Zapobiegaj nawigacji po kliknięciu w dropdown toggle
    const dropdownToggle = e.target.closest('.dropdown-toggle');
    if (dropdownToggle) {
      e.stopPropagation();
      return;
    }

    // Zapobiegaj nawigacji po kliknięciu w menu dropdown
    const dropdownMenu = e.target.closest('.dropdown-menu');
    if (dropdownMenu) {
      e.stopPropagation();
      return;
    }
  }

  /**
   * Obsługa zmian w formularzu filtrów
   */
  handleFormChange(e) {
    const form = e.target.closest('#documentsFilterForm');
    if (!form) return;

    // Auto-submit formularza po zmianie filtrów
    const isCheckbox = e.target.type === 'checkbox';
    const isSelect = e.target.tagName === 'SELECT';

    if (isCheckbox || isSelect) {
      // Krótkie opóźnienie aby użytkownik mógł zmienić więcej opcji
      clearTimeout(this.formSubmitTimeout);
      this.formSubmitTimeout = setTimeout(() => {
        form.submit();
      }, 500);
    }
  }

  /**
   * Obsługa szybkiego podglądu
   */
  handleQuickPreview(e, previewBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = previewBtn.getAttribute('data-doc-id');
    const docName = previewBtn.getAttribute('data-doc-name');

    if (window.modalManager) {
      window.modalManager.showDocumentPreview(docId, docName);
    } else {
      // Fallback - otwórz w nowej karcie
      window.open(`/document/${docId}`, '_blank');
    }
  }

  /**
   * Konfiguracja auto-odświeżania
   */
  setupAutoRefresh() {
    // Sprawdź czy są aktywne procesy OCR
    const runningOcrElements = document.querySelectorAll('.badge:has(.spinner-border)');

    if (runningOcrElements.length > 0) {
      this.enableAutoRefresh();
    }
  }

  /**
   * Włącza auto-odświeżanie
   */
  enableAutoRefresh(interval = 10000) {
    if (this.state.autoRefreshEnabled) return;

    this.state.autoRefreshEnabled = true;
    this.state.autoRefreshInterval = setInterval(() => {
      this.refreshPage();
    }, interval);

    // Dodaj wskaźnik auto-odświeżania
    this.showAutoRefreshIndicator();
  }

  /**
   * Wyłącza auto-odświeżanie
   */
  disableAutoRefresh() {
    if (!this.state.autoRefreshEnabled) return;

    this.state.autoRefreshEnabled = false;

    if (this.state.autoRefreshInterval) {
      clearInterval(this.state.autoRefreshInterval);
      this.state.autoRefreshInterval = null;
    }

    this.hideAutoRefreshIndicator();
  }

  /**
   * Odświeża stronę
   */
  refreshPage() {
    this.state.lastRefreshTime = new Date();
    location.reload();
  }

  /**
   * Pokazuje wskaźnik auto-odświeżania
   */
  showAutoRefreshIndicator() {
    // Sprawdź czy wskaźnik już istnieje
    if (document.getElementById('autoRefreshIndicator')) return;

    const indicator = document.createElement('div');
    indicator.id = 'autoRefreshIndicator';
    indicator.className = 'alert alert-info alert-dismissible fade show position-fixed';
    indicator.style.cssText = `
      top: 20px;
      right: 20px;
      z-index: 1050;
      max-width: 300px;
    `;

    indicator.innerHTML = `
      <div class="d-flex align-items-center">
        <div class="spinner-border spinner-border-sm text-info me-2" role="status">
          <span class="visually-hidden">Ładowanie...</span>
        </div>
        <div>
          <strong>Auto-odświeżanie</strong><br>
          <small>Monitorowanie procesów OCR...</small>
        </div>
        <button type="button" class="btn-close ms-auto" onclick="documentsListManager.disableAutoRefresh()"></button>
      </div>
    `;

    document.body.appendChild(indicator);
  }

  /**
   * Ukrywa wskaźnik auto-odświeżania
   */
  hideAutoRefreshIndicator() {
    const indicator = document.getElementById('autoRefreshIndicator');
    if (indicator) {
      indicator.remove();
    }
  }

  /**
   * Konfiguracja szybkich akcji
   */
  setupQuickActions() {
    // Możliwość dodania szybkich akcji na dokumentach
    this.setupBulkActions();
    this.setupKeyboardShortcuts();
  }

  /**
   * Konfiguracja akcji zbiorczych
   */
  setupBulkActions() {
    // Dodaj checkboxy do selekcji wielu dokumentów
    const table = document.getElementById('documentsTable');
    if (!table) return;

    // Dodaj główny checkbox w nagłówku
    const headerRow = table.querySelector('thead tr');
    if (headerRow) {
      const checkboxCell = document.createElement('th');
      checkboxCell.style.width = '40px';
      checkboxCell.innerHTML = `
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="selectAllDocs">
        </div>
      `;
      headerRow.insertBefore(checkboxCell, headerRow.firstChild);
    }

    // Dodaj checkboxy do każdego wiersza
    const bodyRows = table.querySelectorAll('tbody tr');
    bodyRows.forEach((row, index) => {
      const checkboxCell = document.createElement('td');
      checkboxCell.innerHTML = `
        <div class="form-check">
          <input class="form-check-input" type="checkbox" name="selectedDocs" value="${index}">
        </div>
      `;
      row.insertBefore(checkboxCell, row.firstChild);
    });

    // Obsługa "wybierz wszystkie"
    const selectAllCheckbox = document.getElementById('selectAllDocs');
    if (selectAllCheckbox) {
      selectAllCheckbox.addEventListener('change', (e) => {
        const checkboxes = document.querySelectorAll('input[name="selectedDocs"]');
        checkboxes.forEach(checkbox => {
          checkbox.checked = e.target.checked;
        });
        this.updateBulkActionsVisibility();
      });
    }

    // Obsługa pojedynczych checkboxów
    const docCheckboxes = document.querySelectorAll('input[name="selectedDocs"]');
    docCheckboxes.forEach(checkbox => {
      checkbox.addEventListener('change', () => {
        this.updateBulkActionsVisibility();
      });
    });
  }

  /**
   * Aktualizuje widoczność akcji zbiorczych
   */
  updateBulkActionsVisibility() {
    const selectedCheckboxes = document.querySelectorAll('input[name="selectedDocs"]:checked');
    const bulkActions = document.getElementById('bulkActions');

    if (selectedCheckboxes.length > 0) {
      if (!bulkActions) {
        this.createBulkActionsBar();
      }
    } else {
      if (bulkActions) {
        bulkActions.remove();
      }
    }
  }

  /**
   * Tworzy pasek akcji zbiorczych
   */
  createBulkActionsBar() {
    const bulkActions = document.createElement('div');
    bulkActions.id = 'bulkActions';
    bulkActions.className = 'alert alert-primary d-flex justify-content-between align-items-center';
    bulkActions.innerHTML = `
      <div>
        <i class="bi bi-check-square me-2"></i>
        <span id="selectedCount">0</span> dokumentów zaznaczonych
      </div>
      <div class="btn-group">
        <button class="btn btn-sm btn-outline-primary" onclick="documentsListManager.bulkDownload()">
          <i class="bi bi-download"></i> Pobierz
        </button>
        <button class="btn btn-sm btn-outline-warning" onclick="documentsListManager.bulkRunOcr()">
          <i class="bi bi-play"></i> Uruchom OCR
        </button>
        <button class="btn btn-sm btn-outline-danger" onclick="documentsListManager.bulkDelete()">
          <i class="bi bi-trash"></i> Usuń
        </button>
      </div>
    `;

    const mainContent = document.querySelector('main .container');
    if (mainContent) {
      mainContent.insertBefore(bulkActions, mainContent.firstChild);
    }

    this.updateSelectedCount();
  }

  /**
   * Aktualizuje licznik zaznaczonych dokumentów
   */
  updateSelectedCount() {
    const selectedCheckboxes = document.querySelectorAll('input[name="selectedDocs"]:checked');
    const countElement = document.getElementById('selectedCount');

    if (countElement) {
      countElement.textContent = selectedCheckboxes.length;
    }
  }

  /**
   * Konfiguracja skrótów klawiszowych
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+A - zaznacz wszystkie
      if (e.ctrlKey && e.key === 'a' && !e.target.matches('input, textarea')) {
        e.preventDefault();
        const selectAllCheckbox = document.getElementById('selectAllDocs');
        if (selectAllCheckbox) {
          selectAllCheckbox.checked = true;
          selectAllCheckbox.dispatchEvent(new Event('change'));
        }
      }

      // Escape - odznacz wszystkie
      if (e.key === 'Escape') {
        const selectAllCheckbox = document.getElementById('selectAllDocs');
        if (selectAllCheckbox && selectAllCheckbox.checked) {
          selectAllCheckbox.checked = false;
          selectAllCheckbox.dispatchEvent(new Event('change'));
        }
      }

      // F5 - odśwież (z zapobieganiem domyślnej akcji)
      if (e.key === 'F5') {
        e.preventDefault();
        this.refreshPage();
      }
    });
  }

  // === AKCJE ZBIORCZE ===

  /**
   * Pobieranie wielu dokumentów
   */
  async bulkDownload() {
    const selectedCheckboxes = document.querySelectorAll('input[name="selectedDocs"]:checked');

    if (selectedCheckboxes.length === 0) {
      window.alertManager.warning('Nie zaznaczono żadnych dokumentów');
      return;
    }

    // Dla każdego zaznaczonego dokumentu otwórz download w nowej karcie
    selectedCheckboxes.forEach(checkbox => {
      const row = checkbox.closest('tr');
      const downloadLink = row.querySelector('a[href*="/download"]');

      if (downloadLink) {
        window.open(downloadLink.href, '_blank');
      }
    });

    window.alertManager.success(`Rozpoczęto pobieranie ${selectedCheckboxes.length} dokumentów`);
  }

  /**
   * Uruchamianie OCR dla wielu dokumentów
   */
  async bulkRunOcr() {
    const selectedCheckboxes = document.querySelectorAll('input[name="selectedDocs"]:checked');

    if (selectedCheckboxes.length === 0) {
      window.alertManager.warning('Nie zaznaczono żadnych dokumentów');
      return;
    }

    const confirmation = confirm(
      `Czy na pewno chcesz uruchomić OCR dla ${selectedCheckboxes.length} dokumentów? ` +
      'To może potrwać długo i obciążyć serwer.'
    );

    if (!confirmation) return;

    // Tutaj należałoby zaimplementować endpoint do zbiorczego OCR
    window.alertManager.info('Funkcja zbiorczego OCR będzie dostępna wkrótce');
  }

  /**
   * Usuwanie wielu dokumentów
   */
  async bulkDelete() {
    const selectedCheckboxes = document.querySelectorAll('input[name="selectedDocs"]:checked');

    if (selectedCheckboxes.length === 0) {
      window.alertManager.warning('Nie zaznaczono żadnych dokumentów');
      return;
    }

    const confirmation = confirm(
      `Czy na pewno chcesz usunąć ${selectedCheckboxes.length} dokumentów? ` +
      'Ta operacja jest nieodwracalna!'
    );

    if (!confirmation) return;

    // Tutaj należałoby zaimplementować endpoint do zbiorczego usuwania
    window.alertManager.info('Funkcja zbiorczego usuwania będzie dostępna wkrótce');
  }

  // === UTILITY METHODS ===

  /**
   * Sprawdza czy są aktywne procesy OCR
   */
  hasActiveOcrProcesses() {
    return document.querySelectorAll('.spinner-border').length > 0;
  }

  /**
   * Pobiera liczbę dokumentów
   */
  getDocumentCount() {
    const badge = document.querySelector('.badge.bg-secondary');
    return badge ? parseInt(badge.textContent) || 0 : 0;
  }

  /**
   * Eksportuje listę dokumentów do CSV
   */
  exportToCSV() {
    const table = document.getElementById('documentsTable');
    if (!table) return;

    let csv = '';

    // Nagłówki
    const headers = [];
    table.querySelectorAll('thead th').forEach(th => {
      headers.push(th.textContent.trim());
    });
    csv += headers.join(',') + '\n';

    // Dane
    table.querySelectorAll('tbody tr').forEach(row => {
      const rowData = [];
      row.querySelectorAll('td').forEach(td => {
        // Wyczyść tekst z HTML i dodaj do CSV
        const text = td.textContent.trim().replace(/[\r\n]+/g, ' ').replace(/,/g, ';');
        rowData.push(text);
      });
      csv += rowData.join(',') + '\n';
    });

    // Pobierz plik
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dokumenty_${new Date().toISOString().split('T')[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    window.alertManager.success('Lista dokumentów została wyeksportowana do CSV');
  }

  /**
   * Niszczy manager
   */
  destroy() {
    this.disableAutoRefresh();

    // Usuń event listenery
    document.removeEventListener('click', this.handleGlobalClick);
    document.removeEventListener('change', this.handleFormChange);
    document.removeEventListener('keydown', this.setupKeyboardShortcuts);

    // Wyczyść timeouty
    if (this.formSubmitTimeout) {
      clearTimeout(this.formSubmitTimeout);
    }

    // Wyczyść stan
    this.state = {};
  }

  // === PUBLIC API ===

  /**
   * Odświeża listę dokumentów
   */
  refresh() {
    this.refreshPage();
  }

  /**
   * Włącza/wyłącza auto-odświeżanie
   */
  toggleAutoRefresh() {
    if (this.state.autoRefreshEnabled) {
      this.disableAutoRefresh();
    } else {
      this.enableAutoRefresh();
    }
  }

  /**
   * Pobiera informacje o stanie listy
   */
  getListInfo() {
    return {
      documentCount: this.getDocumentCount(),
      hasActiveOcr: this.hasActiveOcrProcesses(),
      autoRefreshEnabled: this.state.autoRefreshEnabled,
      lastRefreshTime: this.state.lastRefreshTime
    };
  }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
  window.documentsListManager = new DocumentListManager();
});

// Export globalny
window.DocumentListManager = DocumentListManager;