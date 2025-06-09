/**
 * Wspólna obsługa modali
 * Zunifikuje kod z różnych template'ów dla modali
 */

class ModalManager {
  constructor() {
    this.activeModals = new Map();
    this.setupGlobalListeners();
  }

  /**
   * Tworzy nowy modal programatycznie
   */
  create(id, options = {}) {
    const config = {
      title: options.title || 'Modal',
      body: options.body || '',
      size: options.size || '', // 'sm', 'lg', 'xl'
      backdrop: options.backdrop !== false ? 'static' : false,
      keyboard: options.keyboard !== false,
      centered: options.centered || false,
      scrollable: options.scrollable || false,
      buttons: options.buttons || [],
      ...options
    };

    const modal = this.createModalElement(id, config);
    document.body.appendChild(modal);

    const bsModal = new bootstrap.Modal(modal, {
      backdrop: config.backdrop,
      keyboard: config.keyboard
    });

    this.activeModals.set(id, {
      element: modal,
      instance: bsModal,
      config: config
    });

    return bsModal;
  }

  /**
   * Pokazuje istniejący lub tworzy nowy modal
   */
  show(id, options = {}) {
    let modalData = this.activeModals.get(id);
    
    if (!modalData) {
      // Sprawdź czy modal istnieje w DOM
      const existingModal = document.getElementById(id);
      if (existingModal) {
        const bsModal = bootstrap.Modal.getOrCreateInstance(existingModal);
        modalData = {
          element: existingModal,
          instance: bsModal,
          config: {}
        };
        this.activeModals.set(id, modalData);
      } else {
        // Utwórz nowy modal
        this.create(id, options);
        modalData = this.activeModals.get(id);
      }
    }

    // Aktualizuj zawartość jeśli podano
    if (options.title) {
      this.updateTitle(id, options.title);
    }
    if (options.body) {
      this.updateBody(id, options.body);
    }

    modalData.instance.show();
    return modalData.instance;
  }

  /**
   * Ukrywa modal
   */
  hide(id) {
    const modalData = this.activeModals.get(id);
    if (modalData) {
      modalData.instance.hide();
    }
  }

  /**
   * Usuwa modal z DOM
   */
  destroy(id) {
    const modalData = this.activeModals.get(id);
    if (modalData) {
      modalData.instance.dispose();
      modalData.element.remove();
      this.activeModals.delete(id);
    }
  }

  /**
   * Aktualizuje tytuł modala
   */
  updateTitle(id, title) {
    const modalData = this.activeModals.get(id);
    if (modalData) {
      const titleElement = modalData.element.querySelector('.modal-title');
      if (titleElement) {
        titleElement.innerHTML = title;
      }
    }
  }

  /**
   * Aktualizuje zawartość modala
   */
  updateBody(id, body) {
    const modalData = this.activeModals.get(id);
    if (modalData) {
      const bodyElement = modalData.element.querySelector('.modal-body');
      if (bodyElement) {
        bodyElement.innerHTML = body;
      }
    }
  }

  /**
   * Pokazuje loader w modalu
   */
  showLoader(id, message = 'Ładowanie...') {
    const loaderHtml = `
      <div class="d-flex justify-content-center align-items-center py-4">
        <div class="spinner-border text-primary me-3" role="status" style="width: 3rem; height: 3rem;">
          <span class="visually-hidden">Ładowanie...</span>
        </div>
        <span>${message}</span>
      </div>
    `;
    this.updateBody(id, loaderHtml);
  }

  /**
   * Tworzy element modala
   */
  createModalElement(id, config) {
    const modal = document.createElement('div');
    modal.id = id;
    modal.className = 'modal fade';
    modal.tabIndex = -1;
    modal.setAttribute('aria-hidden', 'true');

    const sizeClass = config.size ? `modal-${config.size}` : '';
    const centeredClass = config.centered ? 'modal-dialog-centered' : '';
    const scrollableClass = config.scrollable ? 'modal-dialog-scrollable' : '';

    const buttonsHtml = config.buttons.map(btn => 
      `<button type="button" class="btn ${btn.class || 'btn-secondary'}" 
              ${btn.dismiss ? 'data-bs-dismiss="modal"' : ''} 
              ${btn.onclick ? `onclick="${btn.onclick}"` : ''}>
        ${btn.icon ? `<i class="${btn.icon}"></i> ` : ''}${btn.text}
      </button>`
    ).join('');

    modal.innerHTML = `
      <div class="modal-dialog ${sizeClass} ${centeredClass} ${scrollableClass}">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${config.title}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            ${config.body}
          </div>
          ${buttonsHtml ? `<div class="modal-footer">${buttonsHtml}</div>` : ''}
        </div>
      </div>
    `;

    return modal;
  }

  /**
   * Konfiguruje globalne event listenery
   */
  setupGlobalListeners() {
    // Auto-cleanup po zamknięciu modala
    document.addEventListener('hidden.bs.modal', (e) => {
      const modalId = e.target.id;
      const modalData = this.activeModals.get(modalId);
      
      if (modalData && modalData.config.autoDestroy) {
        this.destroy(modalId);
      }
    });
  }

  // === PREDEFINIOWANE MODOLE ===

  /**
   * Modal potwierdzenia
   */
  showConfirm(title, message, onConfirm, onCancel = null) {
    const id = 'confirmModal_' + Date.now();
    
    const modal = this.create(id, {
      title: title,
      body: `<p>${message}</p>`,
      autoDestroy: true,
      buttons: [
        {
          text: 'Anuluj',
          class: 'btn-secondary',
          dismiss: true,
          onclick: onCancel ? `(${onCancel.toString()})(); bootstrap.Modal.getInstance(document.getElementById('${id}')).hide();` : ''
        },
        {
          text: 'Potwierdź',
          class: 'btn-primary',
          onclick: `(${onConfirm.toString()})(); bootstrap.Modal.getInstance(document.getElementById('${id}')).hide();`
        }
      ]
    });

    modal.show();
    return modal;
  }

  /**
   * Modal edycji notatki
   */
  showNoteEdit(docId, currentNote = '', isOpinion = false) {
    const id = 'noteEditModal';
    const endpoint = isOpinion ? `/opinion/${docId}/update-note` : `/document/${docId}/update-note`;
    
    const modal = this.show(id, {
      title: '<i class="bi bi-sticky-fill me-2"></i>Edycja notatki',
      body: `
        <form id="noteForm" method="post" action="${endpoint}">
          <input type="hidden" name="doc_id" value="${docId}">
          <div class="mb-3">
            <label for="noteContent" class="form-label">Notatka do ${isOpinion ? 'opinii' : 'dokumentu'}</label>
            <textarea class="form-control" id="noteContent" name="note" rows="5" 
                      placeholder="Wprowadź notatkę...">${currentNote}</textarea>
          </div>
          <div class="d-flex justify-content-end">
            <button type="button" class="btn btn-outline-secondary me-2" data-bs-dismiss="modal">Anuluj</button>
            <button type="submit" class="btn btn-primary">
              <i class="bi bi-save me-1"></i>Zapisz notatkę
            </button>
          </div>
        </form>
      `
    });

    return modal;
  }

  /**
   * Modal podglądu dokumentu
   */
  showDocumentPreview(docId, docName) {
    const id = 'quickPreviewModal';
    
    const modal = this.show(id, {
      title: `<i class="bi bi-eye me-2"></i>${docName}`,
      size: 'xl',
      centered: true,
      scrollable: true,
      body: `
        <div class="d-flex justify-content-center align-items-center" style="height: 500px;">
          <div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem;">
            <span class="visually-hidden">Ładowanie...</span>
          </div>
          <span class="ms-3">Wczytywanie podglądu...</span>
        </div>
      `,
      buttons: [
        {
          text: '<i class="bi bi-arrows-fullscreen me-1"></i>Otwórz pełny podgląd',
          class: 'btn-primary',
          onclick: `window.open('/document/${docId}', '_blank')`
        },
        {
          text: 'Zamknij',
          class: 'btn-outline-secondary',
          dismiss: true
        }
      ]
    });

    // Pobierz zawartość podglądu
    window.apiClient.getDocumentPreviewContent(docId)
      .then(html => {
        this.updateBody(id, html);
      })
      .catch(error => {
        this.updateBody(id, `
          <div class="alert alert-danger m-3">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <strong>Błąd!</strong> Nie udało się załadować podglądu: ${error.message}
          </div>
        `);
      });

    return modal;
  }

  /**
   * Modal rozpoznanego tekstu fragmentu (dla OCR)
   */
  showFragmentText(text, onAddToFullText = null) {
    const id = 'fragmentTextModal';
    
    const buttons = [
      {
        text: 'Zamknij',
        class: 'btn-secondary',
        dismiss: true
      }
    ];

    if (onAddToFullText) {
      buttons.unshift({
        text: '<i class="bi bi-plus-circle"></i> Dodaj do pełnego tekstu',
        class: 'btn-primary',
        onclick: `(${onAddToFullText.toString()})()`
      });
    }

    const modal = this.show(id, {
      title: '<i class="bi bi-eye-fill me-2"></i>Rozpoznany tekst',
      size: 'lg',
      body: `
        <div class="alert alert-info">
          <i class="bi bi-info-circle me-2"></i>
          <strong>Tekst rozpoznany z zaznaczonego fragmentu:</strong>
        </div>
        <div class="card bg-light">
          <div class="card-body">
            <pre id="fragmentTextContent" class="mb-0" style="white-space: pre-wrap; max-height: 400px; overflow-y: auto;">${text}</pre>
          </div>
        </div>
      `,
      buttons: buttons
    });

    return modal;
  }

  /**
   * Przywraca oryginalną zawartość modala (cleanup funkcja)
   */
  restoreModalContent(modalId, originalContent) {
    const modalData = this.activeModals.get(modalId);
    if (modalData) {
      const modalBody = modalData.element.querySelector('.modal-body');
      if (modalBody && originalContent) {
        modalBody.innerHTML = originalContent;
      }
    }
  }
}

// Globalna instancja
const modalManager = new ModalManager();

// Funkcje globalne dla kompatybilności
window.showModal = (id, options) => modalManager.show(id, options);
window.hideModal = (id) => modalManager.hide(id);
window.createModal = (id, options) => modalManager.create(id, options);
window.showConfirmModal = (title, message, onConfirm, onCancel) => 
  modalManager.showConfirm(title, message, onConfirm, onCancel);

// Funkcje helper dla konkretnych modali
window.showNoteEditModal = (docId, currentNote, isOpinion) => 
  modalManager.showNoteEdit(docId, currentNote, isOpinion);
window.showDocumentPreview = (docId, docName) => 
  modalManager.showDocumentPreview(docId, docName);
window.showFragmentTextModal = (text, onAddCallback) => 
  modalManager.showFragmentText(text, onAddCallback);

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ModalManager;
}

// Przypisz do globalnego scope
window.ModalManager = ModalManager;
window.modalManager = modalManager;
