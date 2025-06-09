/**
 * Wspólne funkcje kopiowania do schowka
 * Zunifikowane z base.html z dodatkowymi ulepszonymi metodami
 */

class ClipboardManager {
  constructor() {
    this.setupGlobalListeners();
  }

  /**
   * Główna funkcja kopiowania tekstu do schowka
   */
  async copyTextToClipboard(text, callback) {
    if (!text || !text.trim()) {
      throw new Error('Brak tekstu do skopiowania');
    }
    
    console.log('copyTextToClipboard - rozpoczęcie kopiowania, długość tekstu:', text.length);

    try {
      // Nowoczesny Clipboard API
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        console.log('Próba kopiowania przez Clipboard API...');
        await navigator.clipboard.writeText(text);
        console.log('Clipboard API - sukces');

        // Weryfikacja
        try {
          const clipboardContent = await navigator.clipboard.readText();
          if (clipboardContent === text) {
            console.log('Weryfikacja: tekst rzeczywiście w schowku');
          }
        } catch (readError) {
          console.warn('Nie można odczytać schowka dla weryfikacji:', readError.message);
        }
      } else {
        // Fallback dla starszych przeglądarek
        console.log('Clipboard API niedostępne, używam fallback...');
        const success = await this.fallbackCopyToClipboard(text);
        if (!success) {
          throw new Error('Fallback method failed');
        }
        console.log('Fallback method - sukces');
      }

      if (typeof callback === 'function') {
        callback();
      }

    } catch (err) {
      console.error('Wszystkie metody kopiowania zawiodły:', err);
      throw new Error('Nie udało się skopiować tekstu do schowka: ' + err.message);
    }
  }

  /**
   * Agresywna metoda kopiowania dla modali i trudnych kontekstów
   */
  async copyTextToClipboardAggressive(text, callback) {
    if (!text || !text.trim()) {
      throw new Error('Brak tekstu do skopiowania');
    }

    console.log('Agresywna metoda kopiowania...');

    try {
      // Standardowa metoda najpierw
      await this.copyTextToClipboard(text);
      console.log('Standardowa metoda zadziałała');
      if (typeof callback === 'function') {
        callback();
      }
      return;
    } catch (standardError) {
      console.log('Standardowa metoda nie powiodła się, próbuję agresywnej...', standardError.message);
    }

    // Metoda agresywna dla modali
    try {
      const success = await this.aggressiveCopyToClipboard(text);
      if (success) {
        console.log('Agresywna metoda zadziałała');
        if (typeof callback === 'function') {
          callback();
        }
        return;
      }
    } catch (aggressiveError) {
      console.log('Agresywna metoda nie powiodła się:', aggressiveError.message);
    }

    throw new Error('Wszystkie metody kopiowania zawiodły');
  }

  /**
   * Fallback metoda dla starszych przeglądarek
   */
  async fallbackCopyToClipboard(text) {
    console.log('Rozpoczęcie fallback copy method...');

    return new Promise((resolve) => {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      ta.style.top = '0';
      ta.style.opacity = '0';
      ta.style.pointerEvents = 'none';
      ta.style.zIndex = '-1';

      document.body.appendChild(ta);

      try {
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, text.length);

        const successful = document.execCommand('copy');
        console.log('execCommand result:', successful);

        document.body.removeChild(ta);
        resolve(successful);

      } catch (error) {
        console.error('Błąd w fallback method:', error);
        document.body.removeChild(ta);
        resolve(false);
      }
    });
  }

  /**
   * Agresywna metoda kopiowania specjalnie dla modali
   */
  async aggressiveCopyToClipboard(text) {
    console.log('Agresywna metoda kopiowania...');

    // Metoda 1: Focus na body
    try {
      document.body.focus();
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        console.log('Agresywna metoda 1 (Clipboard API) - sukces');
        return true;
      }
    } catch (e) {
      console.log('Agresywna metoda 1 nie powiodła się:', e.message);
    }

    // Metoda 2: Textarea z focusem
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'absolute';
      ta.style.left = '0';
      ta.style.top = '0';
      ta.style.width = '1px';
      ta.style.height = '1px';
      ta.style.padding = '0';
      ta.style.border = 'none';
      ta.style.outline = 'none';
      ta.style.boxShadow = 'none';
      ta.style.background = 'transparent';
      ta.style.zIndex = '9999';

      document.body.appendChild(ta);
      ta.focus({ preventScroll: true });
      ta.select();

      if (ta.setSelectionRange) {
        ta.setSelectionRange(0, text.length);
      }

      await new Promise(resolve => setTimeout(resolve, 50));

      const successful = document.execCommand('copy');
      console.log('Agresywna metoda 2 (execCommand) - wynik:', successful);

      document.body.removeChild(ta);
      if (successful) return true;

    } catch (e) {
      console.log('Agresywna metoda 2 nie powiodła się:', e.message);
    }

    // Metoda 3: Selection API
    try {
      const range = document.createRange();
      const selection = window.getSelection();

      const span = document.createElement('span');
      span.textContent = text;
      span.style.position = 'absolute';
      span.style.left = '-9999px';
      document.body.appendChild(span);

      range.selectNode(span);
      selection.removeAllRanges();
      selection.addRange(range);

      const successful = document.execCommand('copy');
      console.log('Agresywna metoda 3 (Selection API) - wynik:', successful);

      selection.removeAllRanges();
      document.body.removeChild(span);

      if (successful) return true;

    } catch (e) {
      console.log('Agresywna metoda 3 nie powiodła się:', e.message);
    }

    return false;
  }

  /**
   * Wizualne potwierdzenie kopiowania
   */
  flashCopied(btn) {
    const prev = btn.innerHTML;
    const prevClasses = Array.from(btn.classList);

    btn.innerHTML = '<i class="bi bi-check2"></i> Skopiowano!';
    btn.classList.remove('btn-outline-secondary', 'btn-outline-primary');
    btn.classList.add('btn-success');

    setTimeout(() => {
      btn.innerHTML = prev;
      btn.className = '';
      prevClasses.forEach(cls => btn.classList.add(cls));
    }, 2000);
  }

  /**
   * Globalna obsługa przycisków z data-copy-target
   */
  setupGlobalListeners() {
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-copy-target]');
      if (!btn) return;

      console.log('Globalny handler kopiowania - kliknięcie na przycisk z data-copy-target');

      const targetSel = btn.getAttribute('data-copy-target');
      console.log('Cel do skopiowania:', targetSel);

      const targetEl = document.querySelector(targetSel);
      if (!targetEl) {
        console.warn('Nie znaleziono elementu do skopiowania:', targetSel);
        alert('Błąd: nie można znaleźć elementu do skopiowania');
        return;
      }

      try {
        const textToCopy = targetEl.innerText || targetEl.textContent || '';
        console.log('Tekst do skopiowania (pierwsze 50 znaków):', textToCopy.substring(0, 50));

        if (!textToCopy.trim()) {
          console.warn('Brak tekstu do skopiowania');
          alert('Brak tekstu do skopiowania');
          return;
        }

        await this.copyTextToClipboard(textToCopy);
        this.flashCopied(btn);
        console.log('Globalne kopiowanie zakończone pomyślnie');

      } catch (error) {
        console.error('Błąd globalnego kopiowania:', error);
        alert('Nie udało się skopiować tekstu do schowka: ' + error.message);
      }
    });
  }

  /**
   * Funkcje kompatybilności wstecznej
   */
  setupLegacyFunctions() {
    // Eksport do globalnego scope dla kompatybilności
    window.copyTextToClipboard = this.copyTextToClipboard.bind(this);
    window.copyTextToClipboardAggressive = this.copyTextToClipboardAggressive.bind(this);
    window.flashCopied = this.flashCopied.bind(this);
    
    // Stara funkcja z callback'ami
    window.copyToClipboard = async (text, successCallback, errorCallback) => {
      try {
        await this.copyTextToClipboard(text);
        if (typeof successCallback === 'function') {
          successCallback();
        }
      } catch (error) {
        if (typeof errorCallback === 'function') {
          errorCallback(error);
        } else {
          console.error('Błąd kopiowania:', error);
        }
      }
    };
  }
}

// Globalna instancja
const clipboardManager = new ClipboardManager();

// Inicjalizacja przy ładowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
  clipboardManager.setupLegacyFunctions();
});

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ClipboardManager;
}

// Przypisz do globalnego scope
window.ClipboardManager = ClipboardManager;
window.clipboardManager = clipboardManager;