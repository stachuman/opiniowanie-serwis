/**
 * JavaScript specyficzny dla strony opinion_detail.html
 * Obsługuje funkcjonalności związane z zarządzaniem opinią i dokumentami
 */

class OpinionDetailManager {
  constructor() {
    this.currentSummaryDocId = null;
    this.currentSummaryDocName = null;
    this.quickInstructions = this.loadQuickInstructions();

    this.init();
  }

  /**
   * Inicjalizacja managera
   */
  init() {
    this.setupEventListeners();
    this.setupFormHandlers();
    this.setupModalHandlers();
    console.log('OpinionDetailManager zainicjalizowany');
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
    // Edycja notatek
    const editBtn = e.target.closest('.edit-note-btn');
    if (editBtn) {
      this.handleNoteEdit(e, editBtn);
      return;
    }

    // Podgląd dokumentów
    const previewBtn = e.target.closest('.quick-preview-btn');
    if (previewBtn) {
      this.handleQuickPreview(e, previewBtn);
      return;
    }

    // Szybkie podsumowania AI
    const summaryBtn = e.target.closest('.quick-summary-btn');
    if (summaryBtn) {
      this.handleQuickSummary(e, summaryBtn);
      return;
    }

    // NOWE: Uruchamianie OCR
    const runOcrBtn = e.target.closest('.run-ocr-btn');
    if (runOcrBtn) {
      this.handleRunOcr(e, runOcrBtn);
      return;
    }
  }

  /**
   * Obsługa uruchamiania OCR
   */
  async handleRunOcr(e, button) {
    e.preventDefault();

    const docId = button.getAttribute('data-doc-id');

    try {
      // Wyłącz przycisk i pokaż loading
      button.disabled = true;
      const originalHtml = button.innerHTML;
      button.innerHTML = '<i class="bi bi-hourglass-split"></i>';

      // Wywołaj API - POST request
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
      window.alertManager.success('Proces OCR został uruchomiony', {
        duration: 5000
      });

      // Odśwież stronę po krótkim opóźnieniu
      setTimeout(() => location.reload(), 2000);

    } catch (error) {
      console.error('Błąd uruchamiania OCR:', error);
      window.alertManager.error('Nie udało się uruchomić OCR: ' + error.message);

      // Przywróć przycisk
      button.disabled = false;
      button.innerHTML = '<i class="bi bi-play"></i>';
    }
  }
  /**
   * Obsługa edycji notatek
   */
  handleNoteEdit(e, editBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = editBtn.getAttribute('data-doc-id');
    const currentNote = editBtn.getAttribute('data-current-note');

    window.modalManager.showNoteEdit(docId, currentNote, false);
  }

  /**
   * Obsługa szybkiego podglądu
   */
  handleQuickPreview(e, previewBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = previewBtn.getAttribute('data-doc-id');
    const docName = previewBtn.getAttribute('data-doc-name');

    window.modalManager.showDocumentPreview(docId, docName);
  }

  /**
   * Obsługa szybkiego podsumowania
   */
  handleQuickSummary(e, summaryBtn) {
    e.preventDefault();
    e.stopPropagation();

    const docId = summaryBtn.getAttribute('data-doc-id');
    const docName = summaryBtn.getAttribute('data-doc-name');

    this.showQuickSummaryModal(docId, docName);
  }

  /**
   * Pokazuje modal szybkiego podsumowania AI
   */
  showQuickSummaryModal(docId, docName) {
    this.currentSummaryDocId = docId;
    this.currentSummaryDocName = docName;

    const modalHtml = this.createSummaryModalHtml();

    const modal = window.modalManager.create('quickSummaryModal', {
      title: `<i class="bi bi-robot me-2"></i>Podsumowanie AI: ${docName}`,
      body: modalHtml,
      size: 'xl',
      backdrop: 'static',
      keyboard: false,
      autoDestroy: false
    });

    modal.show();
    this.setupSummaryModalHandlers();
  }

  /**
   * Tworzy HTML dla modala podsumowania
   */
  createSummaryModalHtml() {
    return `
      <!-- Formularz szybkiej instrukcji -->
      <div id="summaryFormArea">
        <div class="mb-3">
          <label for="quickInstruction" class="form-label">
            Instrukcja dla AI <small class="text-muted">(opcjonalna)</small>
          </label>
          <textarea class="form-control" id="quickInstruction" rows="4"
                    placeholder="Pozostaw puste aby użyć domyślnej instrukcji lub wprowadź własną..."></textarea>
        </div>

        <!-- Opcje zapisu do notatki -->
        <div class="card bg-light mb-3">
          <div class="card-body py-2">
            <div class="form-check mb-2">
              <input class="form-check-input" type="checkbox" id="quickSaveToNote" checked>
              <label class="form-check-label" for="quickSaveToNote">
                <strong>Zapisz do notatki dokumentu</strong>
              </label>
            </div>

            <div id="quickNoteOptions" class="ms-3">
              <div class="form-check form-check-inline">
                <input class="form-check-input" type="radio" name="quickNoteMode" id="quickNoteAppend" value="append" checked>
                <label class="form-check-label" for="quickNoteAppend">Dodaj na końcu</label>
              </div>
              <div class="form-check form-check-inline">
                <input class="form-check-input" type="radio" name="quickNoteMode" id="quickNotePrepend" value="prepend">
                <label class="form-check-label" for="quickNotePrepend">Dodaj na początku</label>
              </div>
              <div class="form-check form-check-inline">
                <input class="form-check-input" type="radio" name="quickNoteMode" id="quickNoteReplace" value="replace">
                <label class="form-check-label" for="quickNoteReplace">Zastąp</label>
              </div>
            </div>
          </div>
        </div>

        <div class="d-flex justify-content-between">
          <div>
            <button type="button" class="btn btn-sm btn-outline-secondary" onclick="opinionDetailManager.loadQuickDefaultInstruction()">
              <i class="bi bi-arrow-clockwise"></i> Domyślna instrukcja
            </button>
            <button type="button" class="btn btn-sm btn-outline-info" onclick="opinionDetailManager.loadMedicalInstruction()">
              <i class="bi bi-heart-pulse"></i> Instrukcja medyczna
            </button>
            <button type="button" class="btn btn-sm btn-outline-warning" onclick="opinionDetailManager.loadLegalInstruction()">
              <i class="bi bi-scales"></i> Instrukcja prawna
            </button>
          </div>
          <button type="button" class="btn btn-primary" onclick="opinionDetailManager.generateQuickSummary()">
            <i class="bi bi-magic"></i> Generuj podsumowanie
          </button>
        </div>
      </div>

      <!-- Obszar ładowania -->
      <div id="summaryLoadingArea" style="display: none;">
        <div class="text-center py-4">
          <div class="spinner-border text-primary mb-3" role="status" style="width: 3rem; height: 3rem;">
            <span class="visually-hidden">Ładowanie...</span>
          </div>
          <h5>Generowanie podsumowania...</h5>
          <p class="text-muted">AI analizuje dokument. To może potrwać chwilę.</p>
          <div id="liveText" class="mt-3 p-3 bg-light border-start border-success d-none"
               style="white-space: pre-wrap; font-family: monospace; max-height: 300px; overflow-y: auto;">
          </div>
        </div>
      </div>

      <!-- Obszar wyniku -->
      <div id="summaryResultArea" style="display: none;">
        <div class="alert alert-success">
          <div id="summaryResultContent"></div>
        </div>
        <div class="d-flex justify-content-end gap-2">
          <button type="button" class="btn btn-outline-secondary" onclick="opinionDetailManager.copySummaryToClipboard()">
            <i class="bi bi-clipboard"></i> Kopiuj
          </button>
          <button type="button" class="btn btn-outline-primary" onclick="opinionDetailManager.generateAnotherQuick()">
            <i class="bi bi-arrow-repeat"></i> Generuj ponownie
          </button>
          <a href="/document/${this.currentSummaryDocId}/summarize" class="btn btn-outline-info" target="_blank">
            <i class="bi bi-arrows-fullscreen"></i> Pełny edytor
          </a>
        </div>
      </div>

      <!-- Obszar błędu -->
      <div id="summaryErrorArea" style="display: none;">
        <div class="alert alert-danger">
          <div id="summaryErrorContent"></div>
        </div>
        <button type="button" class="btn btn-outline-danger" onclick="opinionDetailManager.generateQuickSummary()">
          <i class="bi bi-arrow-repeat"></i> Spróbuj ponownie
        </button>
      </div>
    `;
  }

  /**
   * Konfiguruje handlery dla modala podsumowania
   */
  setupSummaryModalHandlers() {
    // Obsługa checkbox "Zapisz do notatki"
    const quickSaveToNote = document.getElementById('quickSaveToNote');
    const quickNoteOptions = document.getElementById('quickNoteOptions');

    if (quickSaveToNote && quickNoteOptions) {
      quickSaveToNote.addEventListener('change', function() {
        quickNoteOptions.style.display = this.checked ? 'block' : 'none';
      });
    }
  }

  /**
   * Ładuje instrukcje dla AI
   */
  loadQuickInstructions() {
    return {
      default: `Przeanalizuj poniższy dokument i przygotuj zwięzłe podsumowanie w języku polskim.

Podsumowanie powinno zawierać:
1. **Główną tematykę** - o czym jest dokument
2. **Kluczowe informacje** - najważniejsze fakty, daty, osoby
3. **Wnioski lub zalecenia** - jeśli są zawarte w dokumencie

Zachowaj profesjonalny ton i skup się na merytorycznych aspektach. Maksymalnie 300 słów.`,

      medical: `Przeanalizuj ten dokument medyczny i przygotuj strukturalne podsumowanie:

1. **Dane pacjenta** - podstawowe informacje
2. **Rozpoznanie** - główna diagnoza
3. **Objawy** - zgłaszane dolegliwości
4. **Badania** - wykonane badania i wyniki
5. **Leczenie** - zalecenia i leki
6. **Rokowania** - przewidywany przebieg

Zachowaj medyczną terminologię i podaj konkretne daty.`,

      legal: `Przeprowadź analizę prawną tego dokumentu:

1. **Charakter dokumentu** - rodzaj pisma prawnego
2. **Strony postępowania** - podmioty uczestniczące
3. **Przedmiot sprawy** - czego dotyczy
4. **Podstawy prawne** - przywołane przepisy
5. **Kluczowe ustalenia** - istotne fakty
6. **Wnioski** - podsumowanie stanowiska

Skup się na aspektach merytorycznych i prawnych.`
    };
  }

  // === INSTRUKCJE AI ===

  loadQuickDefaultInstruction() {
    document.getElementById('quickInstruction').value = this.quickInstructions.default;
  }

  loadMedicalInstruction() {
    document.getElementById('quickInstruction').value = this.quickInstructions.medical;
  }

  loadLegalInstruction() {
    document.getElementById('quickInstruction').value = this.quickInstructions.legal;
  }

  // === GENEROWANIE PODSUMOWAŃ ===

  /**
   * Generuje szybkie podsumowanie
   */
  async generateQuickSummary() {
    if (!this.currentSummaryDocId) return;

    const instruction = document.getElementById('quickInstruction').value.trim();
    const saveToNote = document.getElementById('quickSaveToNote').checked;
    const noteMode = document.querySelector('input[name="quickNoteMode"]:checked').value;

    // UI - przełącz na loading
    this.showSummaryUI('loading');

    try {
      // Spróbuj streaming jeśli dostępne
      try {
        await this.generateSummaryWithStreaming(instruction, saveToNote, noteMode);
      } catch (streamError) {
        console.warn('Streaming nie działa, próbuję tradycyjnie:', streamError);
        await this.generateSummaryTraditional(instruction, saveToNote, noteMode);
      }

    } catch (error) {
      console.error('Błąd generowania podsumowania:', error);
      this.showSummaryError(error.message);
    }
  }

  /**
   * Generowanie z streamingiem
   */
  async generateSummaryWithStreaming(instruction, saveToNote, noteMode) {
    const options = { instruction, saveToNote, noteMode };
    const response = await window.apiClient.generateSummaryStream(this.currentSummaryDocId, options);

    // Streaming
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let fullText = '';

    // Pokaż live text area
    const liveTextElement = document.getElementById('liveText');
    liveTextElement.classList.remove('d-none');

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });

      if (chunk.startsWith('BŁĄD:') || chunk.startsWith('ERROR:')) {
        throw new Error(chunk);
      }

      fullText += chunk;

      // Aktualizuj na żywo
      liveTextElement.textContent = fullText;
      liveTextElement.scrollTop = liveTextElement.scrollHeight;
    }

    // Gotowe
    this.showSummaryResult(fullText);
  }

  /**
   * Generowanie tradycyjne (bez streamingu)
   */
  async generateSummaryTraditional(instruction, saveToNote, noteMode) {
    const options = { instruction, saveToNote, noteMode };
    const result = await window.apiClient.generateQuickSummary(this.currentSummaryDocId, options);

    if (result.success) {
      this.showSummaryResult(result.summary);
    } else {
      throw new Error(result.error || 'Nieznany błąd');
    }
  }

  /**
   * Przełącza UI modala podsumowania
   */
  showSummaryUI(mode) {
    const formArea = document.getElementById('summaryFormArea');
    const loadingArea = document.getElementById('summaryLoadingArea');
    const resultArea = document.getElementById('summaryResultArea');
    const errorArea = document.getElementById('summaryErrorArea');

    // Ukryj wszystko
    [formArea, loadingArea, resultArea, errorArea].forEach(el => {
      if (el) el.style.display = 'none';
    });

    // Pokaż odpowiedni
    switch (mode) {
      case 'form':
        if (formArea) formArea.style.display = 'block';
        break;
      case 'loading':
        if (loadingArea) loadingArea.style.display = 'block';
        break;
      case 'result':
        if (resultArea) resultArea.style.display = 'block';
        break;
      case 'error':
        if (errorArea) errorArea.style.display = 'block';
        break;
    }
  }

  /**
   * Pokazuje wynik podsumowania
   */
  showSummaryResult(text) {
    const resultContent = document.getElementById('summaryResultContent');
    if (resultContent) {
      resultContent.innerHTML = text.replace(/\n/g, '<br>');
    }
    this.showSummaryUI('result');
  }

  /**
   * Pokazuje błąd podsumowania
   */
  showSummaryError(errorMessage) {
    const errorContent = document.getElementById('summaryErrorContent');
    if (errorContent) {
      errorContent.innerHTML = `<strong>Błąd:</strong> ${errorMessage}`;
    }
    this.showSummaryUI('error');
  }

  /**
   * Kopiuje podsumowanie do schowka
   */
  async copySummaryToClipboard() {
    const summaryContent = document.getElementById('summaryResultContent');
    if (!summaryContent) return;

    const text = summaryContent.innerText || summaryContent.textContent;

    try {
      await window.clipboardManager.copyTextToClipboard(text);
      window.alertManager.success('Podsumowanie skopiowane do schowka!', { duration: 3000 });
    } catch (error) {
      window.alertManager.error('Nie udało się skopiować do schowka');
    }
  }

  /**
   * Generuje ponownie
   */
  generateAnotherQuick() {
    this.showSummaryUI('form');
  }

  // === OBSŁUGA FORMULARZY ===

  setupFormHandlers() {
    // Będzie obsługiwane przez globalny handler
  }

  handleFormSubmit(e) {
    const form = e.target;

    // Obsługa formularza edycji notatki
    if (form.id === 'noteForm') {
      this.handleNoteFormSubmit(e, form);
      return;
    }
  }

  /**
   * Obsługa formularza edycji notatki
   */
  async handleNoteFormSubmit(e, form) {
    e.preventDefault();

    const formData = new FormData(form);
    const docId = formData.get('doc_id');
    const note = formData.get('note');

    try {
      const result = await window.apiClient.updateDocumentNote(docId, note);

      if (result.success) {
        window.alertManager.success('Notatka została zaktualizowana');
        window.modalManager.hide('noteEditModal');

        // Odśwież stronę po krótkim opóźnieniu
        setTimeout(() => location.reload(), 1000);
      } else {
        throw new Error(result.error || 'Nieznany błąd');
      }

    } catch (error) {
      window.alertManager.error('Błąd podczas aktualizacji notatki: ' + error.message);
    }
  }

  setupModalHandlers() {
    // Dodatkowe handlery dla modali jeśli potrzebne
  }
}

// Inicjalizacja po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
  window.opinionDetailManager = new OpinionDetailManager();
});

// Export globalny
window.OpinionDetailManager = OpinionDetailManager;