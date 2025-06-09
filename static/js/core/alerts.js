/**
 * Zunifikowany system alertów i powiadomień
 * Konsoliduje różne implementacje z template'ów
 */

class AlertManager {
  constructor() {
    this.defaultDuration = 5000;
    this.position = 'top-right';
  }

  /**
   * Główna funkcja wyświetlania alertów
   */
  show(message, type = 'info', options = {}) {
    const config = {
      duration: options.duration || this.defaultDuration,
      dismissible: options.dismissible !== false,
      icon: options.icon || this.getDefaultIcon(type),
      title: options.title,
      actions: options.actions || [],
      ...options
    };

    const alert = this.createAlert(message, type, config);
    document.body.appendChild(alert);

    // Auto-remove po określonym czasie
    if (config.duration > 0) {
      setTimeout(() => {
        if (alert.parentNode) {
          this.removeAlert(alert);
        }
      }, config.duration);
    }

    return alert;
  }

  /**
   * Skróty dla różnych typów alertów
   */
  success(message, options = {}) {
    return this.show(message, 'success', options);
  }

  error(message, options = {}) {
    return this.show(message, 'danger', options);
  }

  warning(message, options = {}) {
    return this.show(message, 'warning', options);
  }

  info(message, options = {}) {
    return this.show(message, 'info', options);
  }

  /**
   * Alert dla powodzenia OCR z linkami powrotu
   */
  showOcrSuccess(message, ocrDocId = null, docId = null, parentId = null) {
    let returnLinks = '';
    
    if (parentId) {
      // Dokument należy do opinii
      returnLinks = `
        <div class="mt-2">
          <a href="/opinion/${parentId}?ocr_updated=true&ocr_doc_id=${ocrDocId || ''}"
             class="btn btn-sm btn-outline-dark me-2">
            <i class="bi bi-arrow-left"></i> Powrót do opinii
          </a>
          <a href="/document/${docId}?ocr_updated=true&ocr_doc_id=${ocrDocId || ''}"
             class="btn btn-sm btn-outline-dark">
            <i class="bi bi-file-earmark"></i> Widok dokumentu
          </a>
        </div>
      `;
    } else if (docId) {
      // Dokument samodzielny
      returnLinks = `
        <div class="mt-2">
          <a href="/document/${docId}?ocr_updated=true&ocr_doc_id=${ocrDocId || ''}"
             class="btn btn-sm btn-outline-dark me-2">
            <i class="bi bi-arrow-left"></i> Widok dokumentu
          </a>
          <a href="/documents"
             class="btn btn-sm btn-outline-dark">
            <i class="bi bi-files"></i> Lista dokumentów
          </a>
        </div>
      `;
    }

    const fullMessage = `
      <div class="fw-bold">${message}</div>
      <small class="text-muted">Tekst został zapisany na serwerze i będzie dostępny po powrocie do widoku dokumentu.</small>
      ${returnLinks}
    `;

    return this.success(fullMessage, {
      duration: 10000,
      dismissible: true
    });
  }

  /**
   * Alert synchronizacji z serwerem
   */
  showSyncInfo() {
    const message = `
      <strong>Synchronizacja z serwerem</strong><br>
      <small>Załadowano najnowszy tekst OCR z serwera.</small>
    `;

    return this.info(message, {
      duration: 4000,
      icon: 'bi-cloud-check'
    });
  }

  /**
   * Alert kopiowania do schowka
   */
  showCopySuccess(message = 'Skopiowano do schowka!') {
    return this.success(message, {
      duration: 3000,
      icon: 'bi-check-circle'
    });
  }

  /**
   * Tworzy element alertu
   */
  createAlert(message, type, config) {
    const alertClass = `alert-${type}`;
    const alert = document.createElement('div');
    
    alert.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
    alert.style.cssText = this.getPositionStyles();
    alert.style.zIndex = '9999';
    alert.style.minWidth = '300px';
    alert.style.maxWidth = config.maxWidth || '450px';

    const iconHtml = config.icon ? `<i class="${config.icon} me-2"></i>` : '';
    const titleHtml = config.title ? `<div class="fw-bold">${config.title}</div>` : '';
    
    let actionsHtml = '';
    if (config.actions && config.actions.length > 0) {
      actionsHtml = '<div class="mt-2">' + 
        config.actions.map(action => 
          `<a href="${action.url}" class="btn btn-sm ${action.class || 'btn-outline-primary'} me-2">
            ${action.icon ? `<i class="${action.icon}"></i> ` : ''}${action.text}
          </a>`
        ).join('') + 
        '</div>';
    }

    const dismissButton = config.dismissible ? 
      '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>' : '';

    alert.innerHTML = `
      <div class="d-flex align-items-start">
        ${iconHtml}
        <div class="flex-grow-1">
          ${titleHtml}
          <div>${message}</div>
          ${actionsHtml}
        </div>
        ${dismissButton}
      </div>
    `;

    // Obsługa Bootstrap dismiss
    if (config.dismissible) {
      alert.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-close')) {
          this.removeAlert(alert);
        }
      });
    }

    return alert;
  }

  /**
   * Usuwa alert z animacją
   */
  removeAlert(alert) {
    alert.classList.remove('show');
    alert.classList.add('fade');
    
    setTimeout(() => {
      if (alert.parentNode) {
        alert.remove();
      }
    }, 150);
  }

  /**
   * Pobiera domyślną ikonę dla typu alertu
   */
  getDefaultIcon(type) {
    const icons = {
      'success': 'bi-check-circle',
      'danger': 'bi-exclamation-triangle',
      'warning': 'bi-exclamation-triangle',
      'info': 'bi-info-circle'
    };
    return icons[type] || 'bi-info-circle';
  }

  /**
   * Style pozycjonowania alertów
   */
  getPositionStyles() {
    const positions = {
      'top-right': 'top: 20px; right: 20px;',
      'top-left': 'top: 20px; left: 20px;',
      'bottom-right': 'bottom: 20px; right: 20px;',
      'bottom-left': 'bottom: 20px; left: 20px;',
      'top-center': 'top: 20px; left: 50%; transform: translateX(-50%);'
    };
    
    return positions[this.position] || positions['top-right'];
  }

  /**
   * Ustawia pozycję alertów
   */
  setPosition(position) {
    this.position = position;
  }

  /**
   * Usuwa wszystkie alerty
   */
  clearAll() {
    const alerts = document.querySelectorAll('.alert.position-fixed');
    alerts.forEach(alert => this.removeAlert(alert));
  }
}

// Globalna instancja
const alertManager = new AlertManager();

// Eksport funkcji globalnych dla kompatybilności
window.showAlert = (message, type, options) => alertManager.show(message, type, options);
window.showSuccessAlert = (message, type, ocrDocId) => alertManager.showOcrSuccess(message, ocrDocId);
window.showErrorAlert = (message) => alertManager.error(message);
window.showSyncInfo = () => alertManager.showSyncInfo();

// Aliasy dla łatwiejszego użycia
window.alert.success = (message, options) => alertManager.success(message, options);
window.alert.error = (message, options) => alertManager.error(message, options);
window.alert.warning = (message, options) => alertManager.warning(message, options);
window.alert.info = (message, options) => alertManager.info(message, options);

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AlertManager;
}

// Przypisz do globalnego scope
window.AlertManager = AlertManager;
window.alertManager = alertManager;
