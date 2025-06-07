# app/search.py
"""
Moduł obsługi wyszukiwania i funkcji fuzzy search dla języka polskiego.
"""

import re
from difflib import SequenceMatcher

# Mapa polskich znaków diakrytycznych na podstawowe
POLISH_DIACRITICS_MAP = {
    'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
    'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N', 'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z'
}

def remove_polish_diacritics(text):
    """Usuwa polskie znaki diakrytyczne z tekstu."""
    for polish_char, basic_char in POLISH_DIACRITICS_MAP.items():
        text = text.replace(polish_char, basic_char)
    return text

def normalize_text_for_search(text):
    """
    Normalizuje tekst do wyszukiwania:
    - konwertuje na małe litery
    - usuwa znaki diakrytyczne
    - usuwa znaki interpunkcyjne
    - normalizuje białe znaki
    """
    if not text:
        return ""
    
    # Konwersja na małe litery
    text = text.lower()
    
    # Usunięcie znaków diakrytycznych
    text = remove_polish_diacritics(text)
    
    # Usunięcie znaków interpunkcyjnych i pozostawienie tylko liter, cyfr i spacji
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # Normalizacja białych znaków
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def polish_similarity(s1, s2):
    """
    Oblicza podobieństwo między dwoma stringami z uwzględnieniem specyfiki polskiego.
    Zwraca wartość od 0.0 do 1.0.
    """
    # Normalizuj oba teksty
    norm_s1 = normalize_text_for_search(s1)
    norm_s2 = normalize_text_for_search(s2)
    
    # Użyj SequenceMatcher do obliczenia podobieństwa
    return SequenceMatcher(None, norm_s1, norm_s2).ratio()

def is_fuzzy_match(search_term, text, threshold=0.7):
    """
    Sprawdza czy search_term występuje w text z uwzględnieniem fuzzy matching.
    
    Args:
        search_term: szukany termin
        text: tekst do przeszukania  
        threshold: próg podobieństwa (0.0-1.0)
    
    Returns:
        bool: True jeśli znaleziono dopasowanie
    """
    if not search_term or not text:
        return False
    
    # Normalizuj search term
    norm_search = normalize_text_for_search(search_term)
    
    # Jeśli search term jest krótki (1-2 znaki), użyj dokładnego wyszukiwania
    if len(norm_search) <= 2:
        return norm_search in normalize_text_for_search(text)
    
    # Podziel tekst na słowa
    words = normalize_text_for_search(text).split()
    
    # Sprawdź podobieństwo z każdym słowem
    for word in words:
        if len(word) >= len(norm_search) * 0.7:  # Słowo nie może być za krótkie
            similarity = polish_similarity(norm_search, word)
            if similarity >= threshold:
                return True
    
    # Sprawdź też czy search term występuje jako substring (po normalizacji)
    if len(norm_search) >= 3 and norm_search in normalize_text_for_search(text):
        return True
    
    # Sprawdź podobieństwo z fragmentami tekstu (dla fraz)
    if ' ' in norm_search:
        text_fragments = []
        words = normalize_text_for_search(text).split()
        search_words = norm_search.split()
        
        # Utwórz fragmenty tekstu o długości podobnej do search term
        for i in range(len(words) - len(search_words) + 1):
            fragment = ' '.join(words[i:i + len(search_words)])
            text_fragments.append(fragment)
        
        # Sprawdź podobieństwo z fragmentami
        for fragment in text_fragments:
            similarity = polish_similarity(norm_search, fragment)
            if similarity >= threshold:
                return True
    
    return False

def highlight_search_results(text, search_term, max_length=200):
    """
    Znajduje i podkreśla znalezione fragmenty w tekście.
    Zwraca skrócony tekst z podkreślonymi dopasowaniami.
    """
    if not search_term or not text:
        return text[:max_length] + "..." if len(text) > max_length else text
    
    # Znajdź pozycję najbardziej pasującego fragmentu
    norm_search = normalize_text_for_search(search_term)
    norm_text = normalize_text_for_search(text)
    
    # Proste podkreślenie dla dokładnych dopasowań
    if norm_search in norm_text:
        # Znajdź pozycję w oryginalnym tekście
        start_pos = norm_text.find(norm_search)
        if start_pos != -1:
            # Oblicz pozycję w oryginalnym tekście (przybliżenie)
            original_pos = int(start_pos * len(text) / len(norm_text))
            
            # Wybierz fragment wokół znalezionego tekstu
            context_start = max(0, original_pos - max_length // 2)
            context_end = min(len(text), original_pos + max_length // 2)
            
            result = text[context_start:context_end]
            if context_start > 0:
                result = "..." + result
            if context_end < len(text):
                result = result + "..."
            
            return result
    
    # Jeśli nie ma dokładnego dopasowania, zwróć początek tekstu
    return text[:max_length] + "..." if len(text) > max_length else text
