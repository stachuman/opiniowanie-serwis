/**
 * Wspólny edytor tekstu OCR
 * Zunifikuje logikę edycji tekstu z różnych template'ów
 */

class TextEditor {
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.container = document.getElementById(containerId);
    
    if (!this.container) {
      throw new Error(`Container ${containerId} not found`);
    }

    // Konfiguracja
    this.config = {
      docId: options.docId,
      autoSave: options.autoSave || false,
      saveInterval: options.saveInterval || 30000, // 30 sekund
      placeholder: options.placeholder || 'Wprowadź tekst...',
      readOnly: options.readOnly || false,
      ...options
    };

    // Stan edytora
    this.state = {
      isEditMode: false,
      originalText: '',
      originalTextBeforeEdit: '',
      textChanged: false,
      lastSaveTime: null,
      autoSaveTimer: null
    };

    // Elementy DOM
    this.elements = {};

    this.init();
  }

  /**
   * Inicjalizacja edytora
   */
  init() {
    this.setupDOM();
    this.bindEvents();
    this.setupAutoSave();
    this.setupKeyboardShortcuts();
  }

  /**
   * Tworzy tylko textarea (helper method)
  */
  createTextarea() {
    const textarea = document.createElement('textarea');
    textarea.className = 'form-control';
    textarea.rows = 15;
    textarea.style.cssText = `
      font-family: 'Courier New', monospace;
      resize: vertical;
      min-height: 300px;
  ` ;
    textarea.placeholder = this.config.placeholder;
    return textarea;
  }

  /**
   * Konfiguracja struktury DOM
   */
setupDOM() {
  // NAJPIERW utwórz podstawowe elementy
  this.elements = {
    displayArea: this.container.querySelector('.text-display') || this.createDisplayArea(),
    editArea: this.container.querySelector('.text-editor') || this.createEditArea(),
    textarea: null, // Będzie ustawiony poniżej
  };

  // WAŻNE: Sprawdź czy textarea istnieje w znalezionym editArea
  if (this.elements.editArea) {
    this.elements.textarea = this.elements.editArea.querySelector('textarea');
  }

  // Jeśli nadal nie ma textarea, stwórz go
  if (!this.elements.textarea) {
    console.warn('Textarea not found in existing editArea, creating new one');
    this.elements.textarea = this.createTextarea();
    this.elements.editArea.appendChild(this.elements.textarea);
  }

  // POTEM utwórz przyciski
  this.elements.toggleBtn = this.container.querySelector('.toggle-edit-btn') || this.createToggleButton();
  this.elements.saveBtn = this.container.querySelector('.save-changes-btn') || this.createSaveButton();
  this.elements.copyBtn = this.container.querySelector('.copy-text-btn') || this.createCopyButton();

  // NA KOŃCU utwórz toolbar (który używa przycisków)
  this.elements.toolbar = this.container.querySelector('.text-editor-toolbar') || this.createToolbar();

  // Reszta kodu...
  this.elements.editArea.style.display = 'none';
  this.updatePlaceholder();
}
  /**
   * Tworzy obszar wyświetlania tekstu
   */
  createDisplayArea() {
    const display = document.createElement('div');
    display.className = 'text-display border rounded p-3 bg-light';
    display.style.cssText = `
      min-height: 100px;
      max-height: 500px;
      overflow-y: auto;
      white-space: pre-wrap;
      cursor: text;
      font-family: inherit;
    `;
    
    this.container.appendChild(display);
    return display;
  }

  /**
   * Tworzy obszar edycji tekstu
   */
  createEditArea() {
    const editContainer = document.createElement('div');
    editContainer.className = 'text-editor';

    const textarea = this.createTextarea();
    editContainer.appendChild(textarea);
    this.container.appendChild(editContainer);

    // Ustaw referencję do textarea
    this.elements.textarea = textarea;
    return editContainer;
  }

  enterEditMode() {
    if (this.config.readOnly) return;

    // ZABEZPIECZENIE: Sprawdź czy textarea istnieje
    if (!this.elements.textarea) {
      console.error('Textarea not found! Cannot enter edit mode.');
      return;
    }

    const currentText = this.getCurrentText();
    this.state.originalTextBeforeEdit = currentText;

    // Ustaw tekst w textarea
    this.elements.textarea.value = currentText;

    // Przełącz widoczność
    this.elements.displayArea.style.display = 'none';
    this.elements.editArea.style.display = 'block';

    // Aktualizuj przycisk
    this.elements.toggleBtn.innerHTML = '<i class="bi bi-eye"></i> Podgląd';
    this.elements.toggleBtn.classList.remove('btn-outline-info');
    this.elements.toggleBtn.classList.add('btn-outline-warning');

    this.state.isEditMode = true;

    // Focus na textarea
    this.elements.textarea.focus();

    // Trigger event
    this.trigger('editModeEntered');
  }

  /**
   * Bindowanie event handlerów - Z ZABEZPIECZENIAMI
   */
  bindEvents() {
    // Toggle edit mode
    this.elements.toggleBtn.addEventListener('click', () => this.toggleEditMode());

    // Save changes
    this.elements.saveBtn.addEventListener('click', () => this.saveChanges());

    // Copy text
    this.elements.copyBtn.addEventListener('click', () => this.copyToClipboard());

    // Text changes monitoring - TYLKO JEŚLI TEXTAREA ISTNIEJE
    if (this.elements.textarea) {
      this.elements.textarea.addEventListener('input', () => this.onTextChange());
      this.elements.textarea.addEventListener('paste', () => {
        setTimeout(() => this.onTextChange(), 10);
      });
    } else {
      console.warn('Textarea not found - text change monitoring disabled');
    }

    // Display area click to enter edit mode
    this.elements.displayArea.addEventListener('click', () => {
      if (!this.state.isEditMode && !this.config.readOnly) {
        this.enterEditMode();
      }
    });

    // Monitor display area changes (external updates)
    this.setupDisplayMonitoring();
  }
  
  /**
   * Tworzy przycisk przełączania trybu
   */
  createToggleButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-outline-info toggle-edit-btn';
    btn.innerHTML = '<i class="bi bi-pencil"></i> Edytuj';
    btn.title = 'Przełącz tryb edycji (E)';
    
    return btn;
  }

  /**
   * Tworzy przycisk zapisywania
   */
  createSaveButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-outline-success save-changes-btn d-none';
    btn.innerHTML = '<i class="bi bi-save"></i> Zapisz zmiany';
    btn.title = 'Zapisz zmiany (Ctrl+S)';
    
    return btn;
  }

  /**
   * Tworzy przycisk kopiowania
   */
  createCopyButton() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm btn-outline-secondary copy-text-btn';
    btn.innerHTML = '<i class="bi bi-clipboard"></i> Kopiuj';
    btn.title = 'Kopiuj tekst do schowka';
    
    return btn;
  }

  /**
   * Tworzy pasek narzędzi
   */
  createToolbar() {
    const toolbar = document.createElement('div');
    toolbar.className = 'text-editor-toolbar d-flex justify-content-between align-items-center mb-2';
    
    const leftGroup = document.createElement('div');
    leftGroup.className = 'd-flex gap-2';
    
    const rightGroup = document.createElement('div');
    rightGroup.className = 'd-flex gap-2';
    
    leftGroup.appendChild(this.elements.toggleBtn);
    rightGroup.appendChild(this.elements.saveBtn);
    rightGroup.appendChild(this.elements.copyBtn);
    
    toolbar.appendChild(leftGroup);
    toolbar.appendChild(rightGroup);
    
    this.container.insertBefore(toolbar, this.container.firstChild);
    return toolbar;
  }

  /**
   * Bindowanie event handlerów
   */
  bindEvents() {
    // Toggle edit mode
    this.elements.toggleBtn.addEventListener('click', () => this.toggleEditMode());
    
    // Save changes
    this.elements.saveBtn.addEventListener('click', () => this.saveChanges());
    
    // Copy text
    this.elements.copyBtn.addEventListener('click', () => this.copyToClipboard());
    
    // Text changes monitoring
    if (this.elements.textarea) {
      this.elements.textarea.addEventListener('input', () => this.onTextChange());
      this.elements.textarea.addEventListener('paste', () => {
        setTimeout(() => this.onTextChange(), 10);
      });
    }

    // Display area click to enter edit mode
    this.elements.displayArea.addEventListener('click', () => {
      if (!this.state.isEditMode && !this.config.readOnly) {
        this.enterEditMode();
      }
    });

    // Monitor display area changes (external updates)
    this.setupDisplayMonitoring();
  }

  /**
   * Monitoring zmian w obszarze wyświetlania
   */
  setupDisplayMonitoring() {
    const observer = new MutationObserver(() => {
      this.checkForDisplayChanges();
    });

    observer.observe(this.elements.displayArea, {
      childList: true,
      subtree: true,
      characterData: true
    });
  }

  /**
   * Konfiguracja skrótów klawiszowych
   */
  setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Tylko gdy edytor ma focus lub jest w trybie edycji
      if (!this.container.contains(document.activeElement) && !this.state.isEditMode) {
        return;
      }

      if (this.state.isEditMode) {
        // Ctrl+Enter = zapisz i wyjdź z edycji
        if (e.ctrlKey && e.key === 'Enter') {
          e.preventDefault();
          this.saveAndExit();
        }
        // Escape = anuluj edycję
        else if (e.key === 'Escape') {
          e.preventDefault();
          this.cancelEdit();
        }
        // Ctrl+S = zapisz zmiany
        else if (e.ctrlKey && e.key === 's') {
          e.preventDefault();
          this.saveChanges();
        }
      } else {
        // E = wejdź w tryb edycji (tylko gdy nie w input/textarea)
        if (e.key === 'e' && !e.ctrlKey && !e.altKey &&
            document.activeElement.tagName !== 'INPUT' &&
            document.activeElement.tagName !== 'TEXTAREA') {
          e.preventDefault();
          this.enterEditMode();
        }
      }
    });
  }

  /**
   * Konfiguracja auto-save
   */
  setupAutoSave() {
    if (this.config.autoSave && this.config.docId) {
      this.state.autoSaveTimer = setInterval(() => {
        if (this.state.textChanged && !this.state.isEditMode) {
          this.saveChanges(true); // silent save
        }
      }, this.config.saveInterval);
    }
  }

  /**
   * Przełącza tryb edycji
   */
  toggleEditMode() {
    if (this.config.readOnly) return;
    
    if (this.state.isEditMode) {
      this.exitEditMode();
    } else {
      this.enterEditMode();
    }
  }

  /**
   * Wchodzi w tryb edycji
   */
  enterEditMode() {
    if (this.config.readOnly) return;

    const currentText = this.getCurrentText();
    this.state.originalTextBeforeEdit = currentText;

    // Ustaw tekst w textarea
    this.elements.textarea.value = currentText;

    // Przełącz widoczność
    this.elements.displayArea.style.display = 'none';
    this.elements.editArea.style.display = 'block';

    // Aktualizuj przycisk
    this.elements.toggleBtn.innerHTML = '<i class="bi bi-eye"></i> Podgląd';
    this.elements.toggleBtn.classList.remove('btn-outline-info');
    this.elements.toggleBtn.classList.add('btn-outline-warning');

    this.state.isEditMode = true;

    // Focus na textarea
    this.elements.textarea.focus();

    // Trigger event
    this.trigger('editModeEntered');
  }

  /**
   * Wychodzi z trybu edycji
   */
  exitEditMode(saveChanges = false) {
    if (saveChanges) {
      const editedText = this.elements.textarea.value;
      this.updateDisplayText(editedText);
    }

    // Przełącz widoczność
    this.elements.displayArea.style.display = 'block';
    this.elements.editArea.style.display = 'none';

    // Aktualizuj przycisk
    this.elements.toggleBtn.innerHTML = '<i class="bi bi-pencil"></i> Edytuj';
    this.elements.toggleBtn.classList.remove('btn-outline-warning');
    this.elements.toggleBtn.classList.add('btn-outline-info');

    this.state.isEditMode = false;

    // Trigger event
    this.trigger('editModeExited');
  }

  /**
   * Zapisuje i wychodzi z edycji
   */
  saveAndExit() {
    this.exitEditMode(true);
    this.checkForDisplayChanges();
  }

  /**
   * Anuluje edycję
   */
  cancelEdit() {
    // Przywróć oryginalny tekst
    this.elements.textarea.value = this.state.originalTextBeforeEdit;
    this.exitEditMode(false);
  }

  /**
   * Obsługa zmian tekstu
   */
  onTextChange() {
    if (this.state.isEditMode) {
      const currentText = this.elements.textarea.value;
      const hasChanges = currentText !== this.state.originalTextBeforeEdit;
      
      this.updateChangeIndicator(hasChanges);
    }
  }

  /**
   * Sprawdza zmiany w obszarze wyświetlania
   */
  checkForDisplayChanges() {
    const currentText = this.getCurrentText();
    const hasChanges = currentText !== this.state.originalText;
    
    this.updateChangeIndicator(hasChanges);
    
    if (hasChanges) {
      this.state.textChanged = true;
    }
  }

  /**
   * Aktualizuje wskaźnik zmian
   */
  updateChangeIndicator(hasChanges) {
    if (hasChanges) {
      if (!this.state.textChanged) {
        this.state.textChanged = true;
        this.elements.saveBtn.classList.remove('d-none');
        this.elements.displayArea.style.backgroundColor = '#fff3cd';
        this.elements.displayArea.style.border = '2px solid #ffc107';
      }
    } else {
      if (this.state.textChanged) {
        this.state.textChanged = false;
        this.elements.saveBtn.classList.add('d-none');
        this.elements.displayArea.style.backgroundColor = '';
        this.elements.displayArea.style.border = '';
      }
    }
  }

  /**
   * Zapisuje zmiany
   */
  async saveChanges(silent = false) {
    if (!this.config.docId) {
      if (!silent) {
        window.alertManager.warning('Brak ID dokumentu - nie można zapisać zmian');
      }
      return false;
    }

    const currentText = this.getCurrentText();
    
    if (!this.state.textChanged && !silent) {
      window.alertManager.info('Brak zmian do zapisania');
      return false;
    }

    try {
      this.showSaveIndicator();
      
      const result = await window.apiClient.updateOcrText(this.config.docId, currentText);

      if (result.success) {
        this.state.originalText = currentText;
        this.state.textChanged = false;
        this.state.lastSaveTime = new Date();
        
        this.updateChangeIndicator(false);
        this.hideSaveIndicator();

        if (!silent) {
          window.alertManager.success('Zmiany zostały zapisane');
        }

        this.trigger('textSaved', { text: currentText, result });
        return true;

      } else {
        throw new Error(result.error || 'Nieznany błąd');
      }

    } catch (error) {
      this.hideSaveIndicator();
      if (!silent) {
        window.alertManager.error('Błąd podczas zapisywania: ' + error.message);
      }
      this.trigger('saveError', { error });
      return false;
    }
  }

  /**
   * Kopiuje tekst do schowka
   */
  async copyToClipboard() {
    const text = this.getCurrentText();
    
    if (!text.trim()) {
      window.alertManager.warning('Brak tekstu do skopiowania');
      return;
    }

    try {
      await window.clipboardManager.copyTextToClipboard(text);
      window.clipboardManager.flashCopied(this.elements.copyBtn);
    } catch (error) {
      window.alertManager.error('Nie udało się skopiować tekstu: ' + error.message);
    }
  }

  /**
   * Pobiera aktualny tekst
   */
  getCurrentText() {
    if (this.state.isEditMode && this.elements.textarea) {
      return this.elements.textarea.value;
    } else {
      return this.elements.displayArea.textContent || '';
    }
  }


  /**
   * Aktualizuje wyświetlany tekst
   */
  updateDisplayText(text) {
    this.elements.displayArea.textContent = text;
    this.state.originalText = text;
    this.updatePlaceholder();
    this.trigger('textUpdated', { text });
  }

  /**
   * Aktualizuje placeholder
   */
  updatePlaceholder() {
    const text = this.elements.displayArea.textContent || '';
    
    if (!text.trim()) {
      this.elements.displayArea.innerHTML = `
        <div class="text-muted font-italic">
          <i class="bi bi-pencil me-2"></i>${this.config.placeholder}
        </div>
      `;
    }
  }

  /**
   * Pokazuje wskaźnik zapisywania
   */
  showSaveIndicator() {
    const originalHtml = this.elements.saveBtn.innerHTML;
    this.elements.saveBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Zapisywanie...';
    this.elements.saveBtn.disabled = true;
    
    this.elements.saveBtn._originalHtml = originalHtml;
  }

  /**
   * Ukrywa wskaźnik zapisywania
   */
  hideSaveIndicator() {
    if (this.elements.saveBtn._originalHtml) {
      this.elements.saveBtn.innerHTML = this.elements.saveBtn._originalHtml;
      delete this.elements.saveBtn._originalHtml;
    }
    this.elements.saveBtn.disabled = false;
  }

  /**
   * System eventów
   */
  trigger(eventName, data = {}) {
    const event = new CustomEvent(`textEditor:${eventName}`, {
      detail: data
    });
    this.container.dispatchEvent(event);
  }

  /**
   * Dodaje listener na event
   */
  on(eventName, callback) {
    this.container.addEventListener(`textEditor:${eventName}`, callback);
  }

  // === PUBLIC API ===

  /**
   * Ustawia tekst
   */
  setText(text) {
    console.log('TextEditor.setText called with:', text ? text.length + ' chars' : 'empty');
    console.log('Elements state:', {
      displayArea: !!this.elements.displayArea,
      editArea: !!this.elements.editArea,
      textarea: !!this.elements.textarea,
      isEditMode: this.state.isEditMode
    });

    this.updateDisplayText(text);

    if (this.state.isEditMode && this.elements.textarea) {
      this.elements.textarea.value = text;
    } else if (this.state.isEditMode && !this.elements.textarea) {
      console.warn('In edit mode but textarea not found!');
    }
  }

  /**
   * Pobiera tekst
   */
  getText() {
    return this.getCurrentText();
  }

  /**
   * Sprawdza czy są zmiany
   */
  hasChanges() {
    return this.state.textChanged;
  }

  /**
   * Wyłącza/włącza tryb tylko do odczytu
   */
  setReadOnly(readOnly) {
    this.config.readOnly = readOnly;
    
    if (readOnly && this.state.isEditMode) {
      this.exitEditMode(false);
    }
    
    this.elements.toggleBtn.style.display = readOnly ? 'none' : 'inline-block';
  }

  /**
   * Czyści tekst
   */
  clear() {
    this.updateDisplayText('');
    if (this.state.isEditMode) {
      this.elements.textarea.value = '';
    }
  }

  /**
   * Odświeża edytor
   */
  refresh() {
    this.checkForDisplayChanges();
    this.updatePlaceholder();
  }

  /**
   * Niszczy edytor
   */
  destroy() {
    if (this.state.autoSaveTimer) {
      clearInterval(this.state.autoSaveTimer);
    }
    
    // Usuń event listenery
    this.container.removeEventListener('keydown', this.handleKeyboard);
    
    // Wyczyść stan
    this.state = {};
    this.elements = {};
  }

}

// Export globalny
window.TextEditor = TextEditor;

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = TextEditor;
}
