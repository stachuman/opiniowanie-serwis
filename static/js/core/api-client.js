/**
 * Wspólny klient API - zunifikowane wywołania AJAX
 * Konsoliduje duplikowane wywołania API z różnych template'ów
 */

class ApiClient {
  constructor() {
    this.baseUrl = '';
    this.defaultHeaders = {
      'Content-Type': 'application/json'
    };
  }

  /**
   * Główna metoda HTTP request
   */
  async request(url, options = {}) {
    const config = {
      method: 'GET',
      headers: { ...this.defaultHeaders, ...options.headers },
      ...options
    };

    try {
      const response = await fetch(this.baseUrl + url, config);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Sprawdź typ odpowiedzi
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        return await response.json();
      } else {
        return await response.text();
      }

    } catch (error) {
      console.error('API Request failed:', error);
      throw error;
    }
  }

  /**
   * GET request
   */
  async get(url, params = {}) {
    const searchParams = new URLSearchParams(params);
    const fullUrl = searchParams.toString() ? `${url}?${searchParams}` : url;
    return this.request(fullUrl);
  }

/**
 * POST request
 */
async post(url, data = {}, options = {}) {
  const config = {
    method: 'POST',
    body: data instanceof FormData ? data : JSON.stringify(data),
    ...options
  };

  // POPRAWKA: Dla FormData nie ustawiaj Content-Type, ale zawsze dodaj Accept dla AJAX
  if (data instanceof FormData) {
    config.headers = {
      'Accept': 'application/json', // WAŻNE: Zawsze dodaj Accept dla AJAX requestów
      ...options.headers
    }; // Zachowaj tylko headers z options, pomijając defaultHeaders Content-Type
  } else {
    // Dla JSON zachowaj pełne defaultHeaders
    config.headers = { ...this.defaultHeaders, ...options.headers };
  }

  return this.request(url, config);
}

  /**
   * PUT request
   */
  async put(url, data = {}) {
    return this.request(url, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }

  /**
   * DELETE request
   */
  async delete(url) {
    return this.request(url, { method: 'DELETE' });
  }

  // === OCR API CALLS ===

  /**
   * Pobierz postęp OCR dla dokumentu
   */
  async getOcrProgress(docId) {
    return this.get(`/api/document/${docId}/ocr-progress`);
  }

  /**
   * Pobierz tekst OCR dla dokumentu
   */
  async getOcrText(docId) {
    return this.get(`/api/document/${docId}/ocr-text`);
  }

  /**
   * Wykonaj OCR na fragmencie dokumentu
   */
  async ocrSelection(docId, selectionData) {
    return this.post(`/api/document/${docId}/ocr-selection`, selectionData);
  }

  /**
   * Zaktualizuj tekst OCR
   */
  async updateOcrText(docId, textContent) {
    const formData = new FormData();
    formData.append('text_content', textContent);
    return this.post(`/api/document/${docId}/update-ocr-text`, formData);
  }

  /**
   * Uruchom OCR dla dokumentu
   */
  async runOcr(docId) {
    return this.post(`/document/${docId}/run-ocr`);
  }

  // === DOCUMENT API CALLS ===

  /**
   * Pobierz szczegóły dokumentu
   */
  async getDocument(docId) {
    return this.get(`/api/document/${docId}`);
  }

  /**
   * Aktualizuj notatkę dokumentu
   */
  async updateDocumentNote(docId, note) {
    const formData = new FormData();
    formData.append('note', note);
    return this.post(`/document/${docId}/update-note`, formData);
  }

  /**
   * Pobierz zawartość podglądu dokumentu
   */
  async getDocumentPreviewContent(docId) {
    return this.get(`/document/${docId}/preview-content`);
  }

  // === LLM API CALLS ===

  /**
   * Test połączenia z LLM
   */
  async testLlmConnection() {
    return this.get('/api/llm/test-connection');
  }

  /**
   * Generuj podsumowanie dokumentu
   */
  async generateDocumentSummary(docId, options = {}) {
    const formData = new FormData();
    
    if (options.customInstruction) {
      formData.append('custom_instruction', options.customInstruction);
    }
    formData.append('save_to_note', options.saveToNote || false);
    formData.append('note_mode', options.noteMode || 'append');

    return this.post(`/document/${docId}/summarize`, formData);
  }

  /**
   * Generuj szybkie podsumowanie
   */
  async generateQuickSummary(docId, options = {}) {
    const formData = new FormData();
    
    if (options.instruction) {
      formData.append('custom_instruction', options.instruction);
    }
    formData.append('save_to_note', options.saveToNote || false);
    formData.append('note_mode', options.noteMode || 'append');

    return this.post(`/document/${docId}/quick-summarize`, formData);
  }

  /**
   * Generuj podsumowanie ze streamingiem
   */
  async generateSummaryStream(docId, options = {}) {
    const formData = new FormData();
    
    if (options.instruction) {
      formData.append('custom_instruction', options.instruction);
    }
    formData.append('save_to_note', options.saveToNote || false);
    formData.append('note_mode', options.noteMode || 'append');

    const response = await fetch(`/document/${docId}/quick-summarize/stream`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return response; // Zwróć response dla streamingu
  }

  // === OPINION API CALLS ===

  /**
   * Aktualizuj opinię
   */
  async updateOpinion(docId, data) {
    const formData = new FormData();
    Object.keys(data).forEach(key => {
      formData.append(key, data[key]);
    });
    return this.post(`/opinion/${docId}/update`, formData);
  }

  /**
   * Aktualizuj notatkę opinii
   */
  async updateOpinionNote(docId, note) {
    const formData = new FormData();
    formData.append('note', note);
    return this.post(`/opinion/${docId}/update-note`, formData);
  }

  // === MONITORING AND POLLING ===

  /**
   * Monitoruj postęp OCR z automatycznym polling
   */
  startOcrProgressMonitoring(docId, callback, interval = 2000) {
    const monitor = async () => {
      try {
        const data = await this.getOcrProgress(docId);
        callback(data);

        if (data.status === 'running' || data.status === 'pending') {
          setTimeout(monitor, interval);
        }
      } catch (error) {
        console.error('Błąd monitorowania OCR:', error);
        setTimeout(monitor, interval * 2); // Zwiększ interwał przy błędzie
      }
    };

    monitor();
  }

  /**
   * Batch request - wykonaj wiele requestów równolegle
   */
  async batch(requests) {
    const promises = requests.map(req => 
      this.request(req.url, req.options).catch(error => ({ error, request: req }))
    );
    
    return Promise.all(promises);
  }

  // === UTILITY METHODS ===

  /**
   * Pobierz dane z formularza i przekonwertuj na FormData lub JSON
   */
  getFormData(formElement, asJson = false) {
    const formData = new FormData(formElement);
    
    if (asJson) {
      const data = {};
      for (let [key, value] of formData.entries()) {
        data[key] = value;
      }
      return data;
    }
    
    return formData;
  }

  /**
   * Sprawdź czy request jest bezpieczny (CSRF protection)
   */
  addCsrfToken(headers = {}) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrfToken) {
      headers['X-CSRF-Token'] = csrfToken;
    }
    return headers;
  }

  /**
   * Retry mechanizm dla nieudanych requestów
   */
  async requestWithRetry(url, options = {}, maxRetries = 3) {
    let lastError;
    
    for (let i = 0; i <= maxRetries; i++) {
      try {
        return await this.request(url, options);
      } catch (error) {
        lastError = error;
        
        if (i < maxRetries) {
          // Exponential backoff
          const delay = Math.pow(2, i) * 1000;
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }
    
    throw lastError;
  }
}

// Globalna instancja
const apiClient = new ApiClient();

// Eksport funkcji globalnych dla kompatybilności wstecznej
window.apiCall = (url, options) => apiClient.request(url, options);
window.getOcrProgress = (docId) => apiClient.getOcrProgress(docId);
window.getOcrText = (docId) => apiClient.getOcrText(docId);
window.updateOcrText = (docId, text) => apiClient.updateOcrText(docId, text);

// Export dla modułów
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ApiClient;
}

// Przypisz do globalnego scope
window.ApiClient = ApiClient;
window.apiClient = apiClient;
