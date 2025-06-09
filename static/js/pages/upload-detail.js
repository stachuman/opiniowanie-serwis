// ZAMIEŃ CAŁY PLIK upload-detail.js NA:

export function startOcrPolling(opinionId) {
  const checkInterval = 2000; // co 2 sekundy - szybsze sprawdzanie
  const maxAttempts = 300; // max ~10 minut
  let attempts = 0;

  console.log(`🔄 Rozpoczęto polling OCR dla opinii ${opinionId}`);

  const interval = setInterval(async () => {
    attempts++;
    
    if (attempts > maxAttempts) {
      clearInterval(interval);
      console.warn('⏰ OCR polling timeout');
      if (window.alertManager) {
        window.alertManager.warning('OCR trwa zbyt długo. Sprawdź status ręcznie w opinii.');
      }
      
      // Przekieruj mimo timeout
      setTimeout(() => {
        window.location.href = `/opinion/${opinionId}`;
      }, 2000);
      return;
    }

    try {
      // ✅ NOWY ENDPOINT - dla opinii zamiast dokumentu
      const response = await fetch(`/api/opinion/${opinionId}/ocr-status`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      console.log(`📊 OCR Progress (${attempts}/${maxAttempts}):`, {
        done: data.ocr_done,
        completed: data.completed_docs,
        total: data.total_docs,
        pending: data.pending_docs,
        progress: `${(data.progress_overall * 100).toFixed(1)}%`
      });

      // ✅ Sprawdź czy OCR zakończony
      if (data.ocr_done) {
        clearInterval(interval);
        console.log('✅ OCR zakończony - przekierowuję do opinii');
        
        if (window.alertManager) {
          window.alertManager.success(`OCR zakończony! Przetworzono ${data.completed_docs}/${data.total_docs} dokumentów.`);
        }
        
        // Krótkie opóźnienie przed przekierowaniem
        setTimeout(() => {
          window.location.href = `/opinion/${opinionId}`;
        }, 1000);
      } else {
        // ✅ Opcjonalnie: aktualizuj progress bar jeśli istnieje
        updateProgressDisplay(data);
      }
      
    } catch (err) {
      console.error('❌ Błąd sprawdzania OCR statusu:', err);
      
      // Po kilku błędach - zatrzymaj polling
      if (attempts % 10 === 0) { // co 10 prób
        console.warn('🚨 Wiele błędów polling - może serwer niedostępny');
        if (window.alertManager) {
          window.alertManager.error('Problemy z połączeniem. Sprawdź status OCR ręcznie.');
        }
      }
    }
  }, checkInterval);
}

// ✅ NOWA: Funkcja do aktualizacji progress bar
function updateProgressDisplay(data) {
  // Znajdź element progress bar jeśli istnieje
  const progressBar = document.querySelector('.progress-bar');
  const progressText = document.querySelector('#processingMessage');
  
  if (progressBar) {
    const percentage = Math.round(data.progress_overall * 100);
    progressBar.style.width = `${percentage}%`;
    progressBar.setAttribute('aria-valuenow', percentage);
    progressBar.textContent = `${percentage}%`;
  }
  
  if (progressText) {
    const message = `Przetwarzanie ${data.pending_docs} z ${data.total_docs} dokumentów... 
                    (${data.completed_docs} zakończonych, ${Math.round(data.progress_overall * 100)}%)`;
    progressText.textContent = message;
  }
}

// ✅ NOWA: Export dodatkowych funkcji dla debugowania
export function checkOcrStatus(opinionId) {
  return fetch(`/api/opinion/${opinionId}/ocr-status`)
    .then(response => response.json())
    .then(data => {
      console.log('OCR Status:', data);
      return data;
    });
}