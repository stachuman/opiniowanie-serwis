# app/llm_service.py - POPRAWIONE FUNKCJE
"""
Moduł do komunikacji z lokalnym LLM serverem (llama-server).
"""

import httpx
import asyncio
import logging
import json
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Konfiguracja LLM
LLM_SERVER_URL = "http://192.168.1.101:80"
LLM_TIMEOUT = 300  # 5 minut timeout (zwiększone)
LLM_MAX_TOKENS = 2000

# Domyślna instrukcja dla podsumowań
DEFAULT_SUMMARY_INSTRUCTION = """Przeanalizuj poniższy dokument i przygotuj zwięzłe podsumowanie w języku polskim. 

Podsumowanie powinno zawierać:
1. **Główną tematykę** - o czym jest dokument
2. **Kluczowe informacje** - najważniejsze fakty, daty, osoby
3. **Wnioski lub zalecenia** - jeśli są zawarte w dokumencie

Zachowaj profesjonalny ton i skup się na merytorycznych aspektach. Maksymalnie 300 słów.

Dokument do analizy:"""

class LLMService:
    """Serwis do komunikacji z LLM serverem."""
    
    def __init__(self, server_url: str = LLM_SERVER_URL, timeout: int = LLM_TIMEOUT):
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout
        
    async def generate_summary(self, document_text: str, custom_instruction: Optional[str] = None) -> dict:
        """
        Generuje podsumowanie dokumentu używając LLM.
        
        Args:
            document_text: Tekst dokumentu do podsumowania
            custom_instruction: Opcjonalna instrukcja (użyje domyślnej jeśli None)
            
        Returns:
            dict: {'success': bool, 'summary': str, 'error': str}
        """
        try:
            # Użyj custom instruction lub domyślnej
            instruction = custom_instruction or DEFAULT_SUMMARY_INSTRUCTION
            
            # Przygotuj prompt - ograniczaj długość tekstu jeśli za długi
            if len(document_text) > 8000:  # Ograniczenie długości
                document_text = document_text[:8000] + "\n\n[TEKST SKRÓCONY...]"
            
            full_prompt = f"{instruction}\n\n{document_text}"
            
            # Przygotuj payload dla llama-server
            payload = {
                "prompt": full_prompt,
                "n_predict": LLM_MAX_TOKENS,  # Używaj n_predict dla llama-server
                "temperature": 0.7,
                "top_p": 0.9,
                "stop": ["</s>", "<|end|>", "\n\n---\n\n", "Dokument do analizy:"],
                "stream": False  # Non-streaming dla tej funkcji
            }
            
            # Wyślij żądanie do LLM
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"Wysyłanie żądania do LLM: {self.server_url}/completion")
                logger.info(f"Payload: prompt length={len(full_prompt)}, n_predict={payload['n_predict']}")
                
                response = await client.post(
                    f"{self.server_url}/completion",
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )
                
                logger.info(f"Otrzymano odpowiedź: status={response.status_code}")
                response.raise_for_status()
                result = response.json()
                
                logger.info(f"JSON result keys: {result.keys()}")
                
                # Wyciągnij wygenerowany tekst - spróbuj różne klucze
                summary = None
                for key in ['content', 'response', 'text', 'completion']:
                    if key in result:
                        summary = result[key]
                        logger.info(f"Znaleziono tekst w kluczu: {key}")
                        break
                
                if summary is None:
                    logger.error(f"Nie znaleziono tekstu w odpowiedzi: {result}")
                    return {
                        "success": False,
                        "summary": "",
                        "error": f"LLM zwrócił odpowiedź bez tekstu. Dostępne klucze: {list(result.keys())}"
                    }
                
                summary = summary.strip() if summary else ""
                
                if not summary:
                    return {
                        "success": False,
                        "summary": "",
                        "error": "LLM zwrócił pusty wynik"
                    }
                
                logger.info(f"LLM wygenerował podsumowanie o długości: {len(summary)} znaków")
                
                return {
                    "success": True,
                    "summary": summary,
                    "error": None
                }
                
        except httpx.TimeoutException:
            error_msg = f"Timeout - LLM nie odpowiedział w ciągu {self.timeout} sekund"
            logger.error(error_msg)
            return {"success": False, "summary": "", "error": error_msg}
            
        except httpx.HTTPStatusError as e:
            error_msg = f"LLM server zwrócił błąd HTTP {e.response.status_code}: {e.response.text}"
            logger.error(error_msg)
            return {"success": False, "summary": "", "error": error_msg}
            
        except httpx.ConnectError:
            error_msg = f"Nie można połączyć się z LLM serverem ({self.server_url})"
            logger.error(error_msg)
            return {"success": False, "summary": "", "error": error_msg}
            
        except Exception as e:
            error_msg = f"Nieoczekiwany błąd podczas komunikacji z LLM: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {"success": False, "summary": "", "error": error_msg}

    async def stream_summary(
        self,
        document_text: str,
        custom_instruction: str | None = None,
        n_predict: int = LLM_MAX_TOKENS,
    ):
        """
        Generator zwracający kolejne fragmenty odpowiedzi LLM (stream=True).
        POPRAWIONA wersja - obsługuje różne formaty odpowiedzi z llama-server.
        """
        try:
            instruction = custom_instruction or DEFAULT_SUMMARY_INSTRUCTION
            
            # Ograniczaj długość tekstu
            if len(document_text) > 8000:
                document_text = document_text[:8000] + "\n\n[TEKST SKRÓCONY...]"
            
            full_prompt = f"{instruction}\n\n{document_text}"

            payload = {
                "prompt": full_prompt,
                "n_predict": n_predict,
                "temperature": 0.7,
                "top_p": 0.9,
                "stop": ["</s>", "<|end|>", "\n\n---\n\n", "Dokument do analizy:"],
                "stream": True,
            }

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.server_url}/completion",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    # Sprawdź status odpowiedzi
                    if resp.status_code != 200:
                        yield f"Błąd HTTP {resp.status_code}: {resp.text}"
                        return
                    
                    # Odczytaj strumień - różne strategie w zależności od formatu
                    content_type = resp.headers.get('content-type', '').lower()
                    
                    if 'text/event-stream' in content_type or 'text/plain' in content_type:
                        # Format SSE lub plain text
                        async for raw_line in resp.aiter_lines():
                            if not raw_line:
                                continue
                                
                            line = raw_line.strip()
                            
                            # Obsługa SSE format
                            if line.startswith("data:"):
                                chunk = line.removeprefix("data:").strip()
                                if chunk == "[DONE]":
                                    break
                                if chunk:
                                    try:
                                        # Spróbuj sparsować jako JSON
                                        data = json.loads(chunk)
                                        if 'content' in data:
                                            yield data['content']
                                        elif 'token' in data:
                                            yield data['token']
                                        else:
                                            yield chunk
                                    except json.JSONDecodeError:
                                        # Jeśli to nie JSON, wyślij jako tekst
                                        yield chunk
                            else:
                                # Zwykły tekst
                                if line and line != "[DONE]":
                                    yield line
                    else:
                        # Fallback - czytaj surowe bajty
                        async for chunk in resp.aiter_bytes():
                            if chunk:
                                text = chunk.decode('utf-8', errors='ignore')
                                if text.strip():
                                    yield text
                                    
        except Exception as e:
            logger.error(f"Błąd podczas streaming: {str(e)}", exc_info=True)
            yield f"BŁĄD STREAMING: {str(e)}"
 
    async def test_connection(self) -> dict:
        """
        Testuje połączenie z LLM serverem.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Spróbuj podstawowego testu z bardzo krótkim promptem
                test_payload = {
                    "prompt": "Test. Odpowiedz: OK",
                    "n_predict": 5,
                    "temperature": 0.1,
                    "stream": False
                }
                
                response = await client.post(
                    f"{self.server_url}/completion",
                    json=test_payload,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "success": True,
                        "error": None,
                        "server_info": {
                            "status": "OK",
                            "response_keys": list(result.keys()),
                            "sample_response": str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
                        }
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Server zwrócił kod {response.status_code}: {response.text}",
                        "server_info": None
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "server_info": None
            }

# Funkcje pomocnicze do zarządzania notatkami
def combine_note_with_summary(existing_note: str, summary: str, mode: str = "append") -> str:
    """
    Łączy istniejącą notatkę z podsumowaniem AI.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    ai_summary = f"[PODSUMOWANIE AI - {timestamp}]\n{summary}"
    
    if not existing_note or not existing_note.strip():
        return ai_summary
    
    if mode == "replace":
        return ai_summary
    elif mode == "prepend":
        return f"{ai_summary}\n\n---\n\n{existing_note}"
    else:  # append (domyślnie)
        return f"{existing_note}\n\n---\n\n{ai_summary}"

# Globalna instancja serwisu
llm_service = LLMService()

def get_default_instruction() -> str:
    """Zwraca domyślną instrukcję dla podsumowań."""
    return DEFAULT_SUMMARY_INSTRUCTION

def set_default_instruction(instruction: str):
    """Ustawia nową domyślną instrukcję."""
    global DEFAULT_SUMMARY_INSTRUCTION
    DEFAULT_SUMMARY_INSTRUCTION = instruction
