/**
 * JavaScript specyficzny dla strony opinions.html (lista opinii)
 * Obsługuje funkcjonalności związane z filtrowaniem, wyszukiwaniem i zarządzaniem opinii
 */

class OpinionsListManager {
  constructor() {
    this.formSubmitTimeout = null;
    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.setupEventListeners();
    this.setupFormHandlers();
    this.setupFilterButtons();
    console.log('OpinionsListManager zainicjalizowany');
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
    // Edycja notatek opinii
    const editBtn = e.target.closest('.edit-note-btn');
    if (editBtn) {
      this.handleNoteEdit(e, editBtn);
      return;
    }

    // Szybki podgląd opinii
    const previewBtn = e.target.closest('.quick-preview-btn');
    if (previewBtn) {
      this.handleQuickPreview(e, previewBtn);
      return;
    }

    // Zapobiegaj nawigacji w akcjach
    const actionArea = e.target.closest('td[onclick*="stopPropagation"]');
    if (actionArea) {
      e.stopPropagation();
      return;
    }
  }

  /**
   * Obsługa edycji notatek
   */
  handleNoteEdit(e, editBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = editBtn.getAttribute('data-doc-id');
    const currentNote = editBtn.getAttribute('data-current-note') || '';

    // Sprawdź czy modalManager jest dostępny
    if (window.modalManager && typeof window.modalManager.showNoteEdit === 'function') {
      // Użyj modalManager z obsługą submit
      this.showNoteEditModal(docId, currentNote);
    } else {
      // Fallback - użyj prompt
      console.warn('modalManager niedostępny, używam fallback');
      this.showNoteEditFallback(docId, currentNote);
    }
  }

  /**
   * Pokazuje modal edycji notatki z prawidłową obsługą
   */
  showNoteEditModal(docId, currentNote) {
    const modal = window.modalManager.showNoteEdit(docId, currentNote, true); // true = isOpinion

    // Dodaj obsługę submit formularza
    const modalElement = document.getElementById('noteEditModal');
    if (modalElement) {
      const form = modalElement.querySelector('#noteForm');
      if (form) {
        // Usuń poprzednie listenery
        const newForm = form.cloneNode(true);
        form.parentNode.replaceChild(newForm, form);

        // Dodaj nowy listener
        newForm.addEventListener('submit', (e) => this.handleNoteFormSubmit(e, docId));
      }
    }
  }

  /**
   * Fallback dla edycji notatki
   */
  showNoteEditFallback(docId, currentNote) {
    const newNote = prompt('Edytuj notatkę opinii:', currentNote || '');

    if (newNote !== null) { // Użytkownik nie anulował
      this.updateOpinionNote(docId, newNote);
    }
  }

  /**
   * Obsługa submit formularza notatki
   */
  async handleNoteFormSubmit(e, docId) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const note = formData.get('note') || '';

    // Wyłącz przycisk submit
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Zapisywanie...';
    }

    try {
      await this.updateOpinionNote(docId, note);

      // Ukryj modal
      window.modalManager.hide('noteEditModal');

      // Pokaż sukces
      window.alertManager.success('Notatka została zaktualizowana');

      // Odśwież stronę
      setTimeout(() => location.reload(), 1000);

    } catch (error) {
      console.error('Błąd aktualizacji notatki:', error);
      window.alertManager.error('Błąd podczas zapisywania: ' + error.message);

      // Przywróć przycisk
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="bi bi-save me-1"></i>Zapisz notatkę';
      }
    }
  }

  /**
   * Aktualizuje notatkę opinii
   */
  async updateOpinionNote(docId, note) {
    const response = await fetch(`/opinion/${docId}/update-note`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
      },
      body: `note=${encodeURIComponent(note)}`
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const result = await response.json();

    if (!result.success) {
      throw new Error(result.error || 'Nieznany błąd');
    }

    return result;
  }

  /**
   * Obsługa szybkiego podglądu
   */
  handleQuickPreview(e, previewBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = previewBtn.getAttribute('data-doc-id');
    const docName = previewBtn.getAttribute('data-doc-name');

    if (window.modalManager && typeof window.modalManager.showDocumentPreview === 'function') {
      window.modalManager.showDocumentPreview(docId, docName);
    } else {
      // Fallback - otwórz w nowej karcie
      window.open(`/document/${docId}`, '_blank');
    }
  }

  /**
   * Konfiguracja obsługi formularzy
   */
  setupFormHandlers() {
    const form = document.getElementById('opinionsFilterForm');
    if (!form) return;

    // Obsługa checkboxów filtrów
    const checkboxes = form.querySelectorAll('input[type="checkbox"][name^="k"]');
    checkboxes.forEach(checkbox => {
      checkbox.addEventListener('change', () => {
        clearTimeout(this.formSubmitTimeout);
        this.formSubmitTimeout = setTimeout(() => form.submit(), 500);
      });
    });

    // Obsługa checkbox wyszukiwania w treści
    const searchContentCheckbox = form.querySelector('input[name="search_content"]');
    if (searchContentCheckbox) {
      searchContentCheckbox.addEventListener('change', function() {
        const searchInput = form.querySelector('input[name="search"]');
        if (this.checked && searchInput.value.trim()) {
          if (confirm('Wyszukiwanie w treści dokumentów może być wolne. Kontynuować?')) {
            form.submit();
          } else {
            this.checked = false;
          }
        } else if (!this.checked) {
          form.submit();
        }
      });
    }

    // Obsługa checkbox wyszukiwania rozmytego
    const fuzzySearchCheckbox = form.querySelector('input[name="fuzzy_search"]');
    if (fuzzySearchCheckbox) {
      fuzzySearchCheckbox.addEventListener('change', function() {
        const searchInput = form.querySelector('input[name="search"]');
        if (searchInput.value.trim()) {
          form.submit();
        }
      });
    }

    // Enter w polu wyszukiwania
    const searchInput = form.querySelector('input[name="search"]');
    if (searchInput) {
      searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          form.submit();
        }
      });
    }
  }

  /**
   * Obsługa zmian w formularzu
   */
  handleFormChange(e) {
    const form = e.target.closest('#opinionsFilterForm');
    if (!form) return;

    // Auto-submit dla select i innych elementów
    if (e.target.tagName === 'SELECT') {
      clearTimeout(this.formSubmitTimeout);
      this.formSubmitTimeout = setTimeout(() => form.submit(), 500);
    }
  }

  /**
   * Konfiguracja przycisków filtrów
   */
  setupFilterButtons() {
    // Przycisk zaznacz wszystkie
    const selectAllBtn = document.getElementById('selectAllBtn');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        const checkboxes = document.querySelectorAll('input[type="checkbox"][name^="k"]');
        checkboxes.forEach(checkbox => checkbox.checked = true);
      });
    }

    // Przycisk odznacz wszystkie
    const deselectAllBtn = document.getElementById('deselectAllBtn');
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', () => {
        const checkboxes = document.querySelectorAll('input[type="checkbox"][name^="k"]');
        checkboxes.forEach(checkbox => checkbox.checked = false);
      });
    }
  }

  /**
   * Sprawdza ile opinii jest wyświetlanych
   */
  getOpinionsCount() {
    const badge = document.querySelector('.badge.bg-primary');
    if (badge) {
      const text = badge.textContent;
      const match = text.match(/(\d+)/);
      return match ? parseInt(match[1]) : 0;
    }
    return 0;
  }

  /**
   * Eksportuje listę opinii do CSV
   */
  exportToCSV() {
    const table = document.querySelector('.table');
    if (!table) {
      window.alertManager.warning('Nie znaleziono tabeli do eksportu');
      return;
    }

    let csv = '';

    // Nagłówki
    const headers = [];
    table.querySelectorAll('thead th').forEach(th => {
      headers.push('"' + th.textContent.trim().replace(/"/g, '""') + '"');
    });
    csv += headers.join(',') + '\n';

    // Dane
    table.querySelectorAll('tbody tr').forEach(row => {
      const rowData = [];
      row.querySelectorAll('td').forEach(td => {
        // Wyczyść tekst z HTML i escape quotes
        let text = td.textContent.trim()
          .replace(/[\r\n]+/g, ' ')
          .replace(/\s+/g, ' ')
          .replace(/"/g, '""');
        rowData.push('"' + text + '"');
      });
      csv += rowData.join(',') + '\n';
    });

    // Pobierz plik
    this.downloadFile(csv, `opinie_${new Date().toISOString().split('T')[0]}.csv`, 'text/csv');
    window.alertManager.success('Lista opinii została wyeksportowana do CSV');
  }

  /**
   * Pobiera plik
   */
  downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
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
    // Usuń event listenery
    document.removeEventListener('click', this.handleGlobalClick);
    document.removeEventListener('change', this.handleFormChange);

    // Wyczyść timeouty
    if (this.formSubmitTimeout) {
      clearTimeout(this.formSubmitTimeout);
    }
  }

  // === PUBLIC API ===

  /**
   * Odświeża listę opinii
   */
  refresh() {
    location.reload();
  }

  /**
   * Pobiera informacje o stanie listy
   */
  getListInfo() {
    return {
      opinionsCount: this.getOpinionsCount(),
      hasFilters: window.location.search.length > 0
    };
  }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
  window.opinionsListManager = new OpinionsListManager();
});

// Export globalny
window.OpinionsListManager = OpinionsListManager;