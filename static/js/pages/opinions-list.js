/**
 * JavaScript specyficzny dla strony opinions.html (lista opinii)
 * Obsługuje funkcjonalności związane z filtrowaniem, wyszukiwaniem i zarządzaniem opinii
 */

class OpinionsListManager {
  constructor() {
    this.formSubmitTimeout = null;
    this.currentViewMode = 'context'; // domyślny tryb wyświetlania
    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.setupEventListeners();
    this.setupFormHandlers();
    this.setupFilterButtons();
    this.setupSearchContextHandlers(); // NOWE: obsługa kontekstu wyszukiwania
    this.setupViewModeToggle(); // NOWE: obsługa przełącznika trybu
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
    console.log('Global click handler called, target:', e.target); // DEBUG
    
    // Edycja notatek opinii
    const editBtn = e.target.closest('.edit-note-btn');
    if (editBtn) {
      console.log('Found edit-note-btn'); // DEBUG
      this.handleNoteEdit(e, editBtn);
      return;
    }

    // Szybki podgląd opinii
    const previewBtn = e.target.closest('.quick-preview-btn');
    if (previewBtn) {
      console.log('Found quick-preview-btn'); // DEBUG
      this.handleQuickPreview(e, previewBtn);
      return;
    }

    // Przycisk "Pokaż więcej kontekstu"
    const showMoreBtn = e.target.closest('.show-more-context');
    if (showMoreBtn) {
      console.log('Found show-more-context button!'); // DEBUG
      this.handleShowMoreContext(e, showMoreBtn);
      return;
    }

    // Zapobiegaj nawigacji w akcjach
    const actionArea = e.target.closest('td[onclick*="stopPropagation"]');
    if (actionArea) {
      console.log('Found action area'); // DEBUG
      e.stopPropagation();
      return;
    }
    
    console.log('No matching handler found for click'); // DEBUG
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

    // Dodaj obsługę submit formularza z loaderem
    form.addEventListener('submit', (e) => {
      this.showSearchLoader();
    });

    // Obsługa checkboxów filtrów statusów - znajdź wszystkie checkboxy statusów dynamicznie
    const statusCheckboxes = form.querySelectorAll('input[type="checkbox"][id^="check_"]');
    statusCheckboxes.forEach(checkbox => {
      // Sprawdź czy to checkbox statusu (nie search_content ani fuzzy_search)
      if (!['search_content', 'fuzzy_search'].includes(checkbox.name)) {
        checkbox.addEventListener('change', () => {
          clearTimeout(this.formSubmitTimeout);
          this.formSubmitTimeout = setTimeout(() => {
            this.showSearchLoader();
            form.submit();
          }, 500);
        });
      }
    });

    // Obsługa checkbox wyszukiwania w treści
    const searchContentCheckbox = form.querySelector('input[name="search_content"]');
    if (searchContentCheckbox) {
      searchContentCheckbox.addEventListener('change', function() {
        const searchInput = form.querySelector('input[name="search"]');
        if (this.checked && searchInput.value.trim()) {
          if (confirm('Wyszukiwanie w treści dokumentów może być wolne. Kontynuować?')) {
            window.opinionsListManager.showSearchLoader();
            form.submit();
          } else {
            this.checked = false;
          }
        } else if (!this.checked) {
          window.opinionsListManager.showSearchLoader();
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
          window.opinionsListManager.showSearchLoader();
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
        const checkboxes = document.querySelectorAll('input[type="checkbox"][id^="check_"]:not([name="search_content"]):not([name="fuzzy_search"])');
        checkboxes.forEach(checkbox => checkbox.checked = true);
        
        // Jeśli jest aktywne wyszukiwanie, pokaż loader
        const searchInput = document.querySelector('input[name="search"]');
        if (searchInput && searchInput.value.trim()) {
          this.showSearchLoader();
        }
      });
    }

    // Przycisk odznacz wszystkie
    const deselectAllBtn = document.getElementById('deselectAllBtn');
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', () => {
        const checkboxes = document.querySelectorAll('input[type="checkbox"][id^="check_"]:not([name="search_content"]):not([name="fuzzy_search"])');
        checkboxes.forEach(checkbox => checkbox.checked = false);
        
        // Jeśli jest aktywne wyszukiwanie, pokaż loader
        const searchInput = document.querySelector('input[name="search"]');
        if (searchInput && searchInput.value.trim()) {
          this.showSearchLoader();
        }
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
   * NOWE: Pokazuje loader wyszukiwania
   */
  showSearchLoader() {
    // Sprawdź czy wyszukiwanie w treści jest włączone
    const searchContentCheckbox = document.querySelector('input[name="search_content"]');
    const searchInput = document.querySelector('input[name="search"]');
    const isContentSearch = searchContentCheckbox && searchContentCheckbox.checked;
    const hasSearchTerm = searchInput && searchInput.value.trim();

    if (isContentSearch && hasSearchTerm) {
      // Pokaż loader tylko gdy wyszukujemy w treści (może być wolne)
      this.createSearchLoader();
    }
  }

  /**
   * NOWE: Tworzy i wyświetla loader wyszukiwania
   */
  createSearchLoader() {
    // Usuń poprzedni loader jeśli istnieje
    const existingLoader = document.getElementById('searchLoader');
    if (existingLoader) {
      existingLoader.remove();
    }

    // Utwórz overlay z loaderem
    const loaderOverlay = document.createElement('div');
    loaderOverlay.id = 'searchLoader';
    loaderOverlay.className = 'position-fixed top-0 start-0 w-100 h-100 d-flex align-items-center justify-content-center';
    loaderOverlay.style.cssText = `
      background-color: rgba(255, 255, 255, 0.9);
      z-index: 9999;
      backdrop-filter: blur(2px);
    `;

    loaderOverlay.innerHTML = `
      <div class="text-center">
        <div class="spinner-border text-primary mb-3" role="status" style="width: 3rem; height: 3rem;">
          <span class="visually-hidden">Wyszukiwanie...</span>
        </div>
        <h4 class="text-primary">Wyszukiwanie w dokumentach...</h4>
        <p class="text-muted">
          <i class="bi bi-search me-2"></i>
          Przeszukiwanie treści dokumentów PDF, Word i wyników OCR może chwilę potrwać.
        </p>
        <div class="progress" style="width: 300px; margin: 0 auto;">
          <div class="progress-bar progress-bar-striped progress-bar-animated" 
               role="progressbar" style="width: 100%"></div>
        </div>
        <small class="text-muted mt-2 d-block">Proszę czekać...</small>
      </div>
    `;

    document.body.appendChild(loaderOverlay);

    // Auto-usuń loader po 30 sekundach (fallback)
    setTimeout(() => {
      if (document.getElementById('searchLoader')) {
        this.hideSearchLoader();
      }
    }, 30000);
  }

  /**
   * NOWE: Ukrywa loader wyszukiwania
   */
  hideSearchLoader() {
    const loader = document.getElementById('searchLoader');
    if (loader) {
      loader.remove();
    }
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

    // Usuń loader
    this.hideSearchLoader();
  }

  /**
   * NOWE: Obsługa przełącznika trybu wyświetlania
   */
  setupViewModeToggle() {
    const normalRadio = document.getElementById('viewNormal');
    const contextRadio = document.getElementById('viewContext');
    
    if (normalRadio && contextRadio) {
      // Ustaw domyślny tryb
      if (this.currentViewMode === 'context') {
        contextRadio.checked = true;
      } else {
        normalRadio.checked = true;
      }
      
      // Obsługa zmiany trybu
      [normalRadio, contextRadio].forEach(radio => {
        radio.addEventListener('change', (e) => {
          if (e.target.checked) {
            this.switchViewMode(e.target.value);
          }
        });
      });
    }
  }
  
  /**
   * NOWE: Przełącza tryb wyświetlania wyników
   */
  switchViewMode(mode) {
    this.currentViewMode = mode;
    const searchContexts = document.querySelectorAll('.search-context');
    
    if (mode === 'normal') {
      // Ukryj konteksty wyszukiwania
      searchContexts.forEach(context => {
        context.style.display = 'none';
      });
    } else if (mode === 'context') {
      // Pokaż konteksty wyszukiwania
      searchContexts.forEach(context => {
        context.style.display = 'block';
      });
    }
    
    // Zapisz preferencję użytkownika
    localStorage.setItem('opinionsViewMode', mode);
    console.log(`Przełączono tryb wyświetlania na: ${mode}`);
  }
  
  /**
   * NOWE: Obsługa kontekstu wyszukiwania
   */
  setupSearchContextHandlers() {
    // Ładuj zapisaną preferencję użytkownika
    const savedMode = localStorage.getItem('opinionsViewMode');
    if (savedMode) {
      this.currentViewMode = savedMode;
    }
    
    // Zastosuj tryb przy ładowaniu strony
    setTimeout(() => {
      this.switchViewMode(this.currentViewMode);
      
      // DEBUG: Sprawdź czy przyciski "Pokaż więcej" istnieją
      const showMoreButtons = document.querySelectorAll('.show-more-context');
      console.log('Znaleziono przycisków "Pokaż więcej":', showMoreButtons.length);
      showMoreButtons.forEach((btn, index) => {
        console.log(`Przycisk ${index}:`, btn, 'data-doc-id:', btn.getAttribute('data-doc-id'));
      });
    }, 100);
  }
  
  /**
   * NOWE: Obsługa przycisku "Pokaż więcej kontekstu"
   */
  async handleShowMoreContext(e, showMoreBtn) {
    console.log('handleShowMoreContext called'); // DEBUG
    e.preventDefault();
    e.stopPropagation();
    
    const docId = showMoreBtn.getAttribute('data-doc-id');
    const totalCount = parseInt(showMoreBtn.getAttribute('data-total'));
    console.log('docId:', docId, 'totalCount:', totalCount); // DEBUG
    console.log('Current URL:', window.location.href); // DEBUG
    console.log('URL search params:', window.location.search); // DEBUG
    
    // Znajdź kontener kontekstu dla tego dokumentu
    const contextContainer = showMoreBtn.closest('.search-context');
    if (!contextContainer) {
      console.error('Nie znaleziono kontener kontekstu'); // DEBUG
      return;
    }
    
    console.log('Znaleziono kontener kontekstu:', contextContainer); // DEBUG
    
    // Ukryj przycisk i pokaż spinner
    const originalContent = showMoreBtn.innerHTML;
    showMoreBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Ładowanie...';
    showMoreBtn.disabled = true;
    
    try {
      console.log('Wysyłanie zapytania do API...'); // DEBUG
      // Pobierz dodatkowe konteksty z serwera
      const response = await this.fetchAdditionalContexts(docId);
      console.log('Odpowiedź z API:', response); // DEBUG
      
      if (response.success && response.contexts) {
        this.renderAdditionalContexts(contextContainer, response.contexts);
        showMoreBtn.style.display = 'none';
      } else {
        throw new Error(response.error || 'Nie udało się pobrać dodatkowych kontekstów');
      }
    } catch (error) {
      console.error('Błąd ładowania kontekstów:', error);
      if (window.alertManager) {
        window.alertManager.error('Błąd podczas ładowania dodatkowych kontekstów: ' + error.message);
      } else {
        alert('Błąd podczas ładowania dodatkowych kontekstów: ' + error.message);
      }
      
      // Przywróć przycisk
      showMoreBtn.innerHTML = originalContent;
      showMoreBtn.disabled = false;
    }
  }
  
  /**
   * NOWE: Pobiera dodatkowe konteksty z serwera
   */
  async fetchAdditionalContexts(docId) {
    const currentSearch = new URLSearchParams(window.location.search).get('search') || '';
    const searchContent = new URLSearchParams(window.location.search).get('search_content') === 'on' || new URLSearchParams(window.location.search).get('search_content') === 'true';
    const fuzzySearch = new URLSearchParams(window.location.search).get('fuzzy_search') === 'on' || new URLSearchParams(window.location.search).get('fuzzy_search') === 'true';
    
    const requestPayload = {
      doc_id: parseInt(docId), // Upewnij się, że to jest liczba
      search_term: currentSearch,
      search_content: searchContent,
      fuzzy_search: fuzzySearch
    };
    
    console.log('Wysyłając żądanie do API:', requestPayload); // DEBUG
    
    const response = await fetch('/api/search/additional-contexts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify(requestPayload)
    });
    
    console.log('Odpowiedź HTTP status:', response.status); // DEBUG
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const jsonResponse = await response.json();
    console.log('Pełna odpowiedź z API:', jsonResponse); // DEBUG
    
    return jsonResponse;
  }
  
  /**
   * NOWE: Renderuje dodatkowe konteksty
   */
  renderAdditionalContexts(contextContainer, contexts) {
    console.log('renderAdditionalContexts called with:', contexts.length, 'contexts'); // DEBUG
    console.log('contextContainer:', contextContainer); // DEBUG
    
    // Znajdź przycisk "Pokaż więcej" i usuń go
    const showMoreBtn = contextContainer.querySelector('.show-more-context');
    if (showMoreBtn) {
      console.log('Removing show-more button:', showMoreBtn); // DEBUG
      showMoreBtn.remove();
    } else {
      console.log('No show-more button found in container'); // DEBUG
    }
    
    // Dodaj nowe konteksty
    contexts.forEach((snippet, index) => {
      console.log(`Adding context snippet ${index}:`, snippet); // DEBUG
      
      const snippetDiv = document.createElement('div');
      snippetDiv.className = 'context-snippet mb-2 p-2 bg-light rounded new-context-snippet';
      snippetDiv.style.border = '2px solid red'; // DEBUG: Temporary red border to see if it's added
      
      snippetDiv.innerHTML = `
        <div class="d-flex justify-content-between align-items-start mb-1">
          <small class="text-muted fw-bold">
            ${this.getMatchTypeIcon(snippet.match_type)} ${snippet.source_info}
          </small>
          ${snippet.confidence < 1.0 ? `<small class="badge bg-secondary">${Math.round(snippet.confidence * 100)}%</small>` : ''}
        </div>
        <div class="context-text small">
          ${snippet.highlighted_text}
        </div>
      `;
      
      console.log('Adding snippetDiv to container:', snippetDiv); // DEBUG
      contextContainer.appendChild(snippetDiv);
      console.log('Container children count after adding:', contextContainer.children.length); // DEBUG
    });
    
    // Dodaj informację o pełnym kontekście
    const infoDiv = document.createElement('div');
    infoDiv.className = 'alert alert-success mt-2 small';
    infoDiv.innerHTML = `<i class="bi bi-check-circle me-1"></i>Dodano ${contexts.length} dodatkowych fragmentów kontekstu. Pokazano wszystkie znalezione wyniki.`;
    infoDiv.style.border = '2px solid blue'; // DEBUG: Blue border for info div
    contextContainer.appendChild(infoDiv);
    
    console.log(`Dodano ${contexts.length} dodatkowych kontekstów do kontenera`);
    console.log('Final container content:', contextContainer.innerHTML); // DEBUG
  }
  
  /**
   * NOWE: Zwraca ikonę dla typu dopasowania
   */
  getMatchTypeIcon(matchType) {
    switch (matchType) {
      case 'metadata':
        return '<i class="bi bi-tag text-info me-1"></i>';
      case 'content':
        return '<i class="bi bi-file-text text-success me-1"></i>';
      case 'attachment':
        return '<i class="bi bi-paperclip text-warning me-1"></i>';
      default:
        return '<i class="bi bi-search text-primary me-1"></i>';
    }
  }
  
  /**
   * NOWE: Podświetla termin wyszukiwania w kontekście
   */
  highlightSearchTerm(text, searchTerm) {
    if (!searchTerm || !text) return text;
    
    const regex = new RegExp(`(${this.escapeRegex(searchTerm)})`, 'gi');
    return text.replace(regex, '<mark class="search-highlight">$1</mark>');
  }
  
  /**
   * NOWE: Escape regex characters
   */
  escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
  
  /**
   * NOWE: Pobiera informacje o kontekście wyszukiwania
   */
  getSearchContextInfo() {
    const searchContexts = document.querySelectorAll('.search-context');
    const totalSnippets = document.querySelectorAll('.context-snippet').length;
    
    return {
      documentsWithContext: searchContexts.length,
      totalSnippets: totalSnippets,
      currentViewMode: this.currentViewMode
    };
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