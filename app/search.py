# app/search.py
"""
Moduł obsługi wyszukiwania i funkcji fuzzy search dla języka polskiego.
"""

import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

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

@dataclass
class SearchMatch:
    """Represents a search match with context."""
    text: str
    start_pos: int
    end_pos: int
    match_type: str  # 'exact', 'fuzzy'
    confidence: float  # 0.0 - 1.0
    original_text: str


@dataclass
class ContextSnippet:
    """Represents a context snippet with highlighted matches."""
    text: str
    highlighted_text: str
    match_positions: List[Tuple[int, int]]
    confidence: float
    match_type: str  # 'metadata', 'content', 'attachment'
    source_info: str  # Additional info about the source


def find_search_matches(text: str, search_term: str, is_fuzzy: bool = False, threshold: float = 0.7) -> List[SearchMatch]:
    """
    Znajduje wszystkie dopasowania search_term w tekście.
    
    Args:
        text: tekst do przeszukania
        search_term: szukany termin
        is_fuzzy: czy używać fuzzy search
        threshold: próg podobieństwa dla fuzzy search
    
    Returns:
        Lista SearchMatch obiektów
    """
    matches = []
    
    if not search_term or not text:
        return matches
    
    # Najpierw spróbuj dokładne dopasowanie (case-insensitive)
    search_lower = search_term.lower()
    text_lower = text.lower()
    
    start = 0
    while True:
        pos = text_lower.find(search_lower, start)
        if pos == -1:
            break
        
        matches.append(SearchMatch(
            text=text[pos:pos + len(search_term)],
            start_pos=pos,
            end_pos=pos + len(search_term),
            match_type='exact',
            confidence=1.0,
            original_text=text
        ))
        
        start = pos + 1
    
    # Jeśli nie ma dokładnych dopasowań, spróbuj z normalizacją
    if not matches:
        norm_search = normalize_text_for_search(search_term)
        norm_text = normalize_text_for_search(text)
        
        start = 0
        while True:
            pos = norm_text.find(norm_search, start)
            if pos == -1:
                break
            
            # Użyj ulepszonej funkcji mapowania pozycji
            original_start = _find_original_position_improved(text, search_term, pos)
            original_end = original_start + len(search_term)
            
            # Waliduj, czy znalezione dopasowanie jest prawidłowe
            if (original_start >= 0 and 
                original_end <= len(text) and 
                original_start < original_end):
                
                found_text = text[original_start:original_end]
                if normalize_text_for_search(found_text) == norm_search:
                    matches.append(SearchMatch(
                        text=found_text,
                        start_pos=original_start,
                        end_pos=original_end,
                        match_type='normalized',
                        confidence=0.9,
                        original_text=text
                    ))
            
            start = pos + 1
    
    # Fuzzy dopasowania (jeśli włączone i nie ma innych)
    if is_fuzzy and not matches:
        matches.extend(_find_fuzzy_matches(text, search_term, threshold))
    
    return matches


def _find_original_position_improved(original_text: str, search_term: str, norm_pos: int) -> int:
    """
    Ulepszona funkcja znajdowania pozycji - szuka bezpośrednio w oryginalnym tekście.
    """
    # Walidacja podstawowa
    if not original_text or not search_term:
        return 0
    
    if len(search_term) > len(original_text):
        return 0
    
    norm_search = normalize_text_for_search(search_term)
    
    # Szukaj wszystkich możliwych dopasowań w oryginalnym tekście
    max_iterations = min(len(original_text) - len(search_term) + 1, 10000)  # Limit iteracji
    
    for i in range(max_iterations):
        candidate = original_text[i:i + len(search_term)]
        if normalize_text_for_search(candidate) == norm_search:
            return i
    
    # Fallback - bezpieczna pozycja
    fallback_pos = max(0, min(norm_pos, len(original_text) - len(search_term)))
    return max(0, fallback_pos)  # Zapewnij, że pozycja nie jest ujemna


def _find_original_position(original_text: str, normalized_text: str, norm_pos: int) -> int:
    """
    Znajdź pozycję w oryginalnym tekście na podstawie pozycji w znormalizowanym.
    Tworzy precyzyjne mapowanie pozycji między tekstami.
    """
    if norm_pos >= len(normalized_text):
        return len(original_text)
    
    if norm_pos <= 0:
        return 0
    
    # Tworzymy mapowanie pozycji przez symulację normalizacji
    position_map = []
    normalized_chars = []
    
    for i, char in enumerate(original_text):
        # Symulujemy normalizację jak w normalize_text_for_search
        norm_char = char.lower()
        
        # Usuwanie polskich znaków diakrytycznych
        for polish_char, basic_char in POLISH_DIACRITICS_MAP.items():
            norm_char = norm_char.replace(polish_char, basic_char)
        
        # Sprawdzamy czy znak zostanie zachowany po normalizacji
        if re.match(r'[\w\s]', norm_char):
            normalized_chars.append(norm_char)
            position_map.append(i)
        elif char.isspace():
            # Białe znaki zawsze mapujemy
            normalized_chars.append(' ')
            position_map.append(i)
    
    # Normalizujemy białe znaki (jak w normalize_text_for_search)
    norm_result = ''.join(normalized_chars)
    norm_result = re.sub(r'\s+', ' ', norm_result).strip()
    
    # Znajdź odpowiadającą pozycję
    if norm_pos >= len(position_map):
        return len(original_text)
    
    # Dodatkowa walidacja - porównaj z oczekiwanym znormalizowanym tekstem
    if norm_result != normalized_text:
        # Fallback do proporcji jeśli mapowanie nie jest dokładne
        ratio = norm_pos / len(normalized_text) if len(normalized_text) > 0 else 0
        return min(int(ratio * len(original_text)), len(original_text))
    
    return position_map[min(norm_pos, len(position_map) - 1)]


def _find_fuzzy_matches(text: str, search_term: str, threshold: float) -> List[SearchMatch]:
    """
    Znajduje fuzzy dopasowania w tekście.
    """
    matches = []
    norm_search = normalize_text_for_search(search_term)
    words = text.split()
    
    for i, word in enumerate(words):
        norm_word = normalize_text_for_search(word)
        if len(norm_word) >= len(norm_search) * 0.7:
            similarity = polish_similarity(norm_search, norm_word)
            if similarity >= threshold:
                # Znajdź pozycję słowa w oryginalnym tekście
                word_start = text.find(word)
                if word_start != -1:
                    matches.append(SearchMatch(
                        text=word,
                        start_pos=word_start,
                        end_pos=word_start + len(word),
                        match_type='fuzzy',
                        confidence=similarity,
                        original_text=text
                    ))
    
    return matches


def extract_context_snippets(text: str, search_term: str, context_length: int = 200, 
                           max_snippets: int = 3, is_fuzzy: bool = False) -> List[ContextSnippet]:
    """
    Wyodrębnia fragmenty kontekstu z podświetlonymi dopasowaniami.
    
    Args:
        text: tekst źródłowy
        search_term: szukany termin
        context_length: długość fragmentu kontekstu
        max_snippets: maksymalna liczba fragmentów
        is_fuzzy: czy używać fuzzy search
    
    Returns:
        Lista ContextSnippet obiektów
    """
    snippets = []
    
    if not search_term or not text:
        return snippets
    
    matches = find_search_matches(text, search_term, is_fuzzy)
    
    if not matches:
        return snippets
    
    # Grupuj blisko siebie znajdujące się dopasowania
    grouped_matches = _group_nearby_matches(matches, context_length)
    
    for group in grouped_matches[:max_snippets]:
        snippet = _create_context_snippet(text, group, search_term, context_length)
        if snippet:
            snippets.append(snippet)
    
    return snippets


def _group_nearby_matches(matches: List[SearchMatch], context_length: int) -> List[List[SearchMatch]]:
    """
    Grupuje dopasowania, które są blisko siebie.
    """
    if not matches:
        return []
    
    # Sortuj dopasowania według pozycji
    sorted_matches = sorted(matches, key=lambda m: m.start_pos)
    
    groups = []
    current_group = [sorted_matches[0]]
    
    for match in sorted_matches[1:]:
        # Jeśli dopasowanie jest blisko poprzedniej grupy, dodaj do niej
        last_match = current_group[-1]
        if match.start_pos - last_match.end_pos <= context_length:
            current_group.append(match)
        else:
            # Nowa grupa
            groups.append(current_group)
            current_group = [match]
    
    groups.append(current_group)
    return groups


def _create_context_snippet(text: str, matches: List[SearchMatch], search_term: str, 
                          context_length: int) -> Optional[ContextSnippet]:
    """
    Tworzy fragment kontekstu z podświetlonymi dopasowaniami.
    """
    if not matches:
        return None
    
    # Znajdź zakres dla fragmentu kontekstu
    first_match = min(matches, key=lambda m: m.start_pos)
    last_match = max(matches, key=lambda m: m.end_pos)
    
    # Oblicz pozycje początku i końca kontekstu
    context_start = max(0, first_match.start_pos - context_length // 2)
    context_end = min(len(text), last_match.end_pos + context_length // 2)
    
    # Dostosuj granice do granic słów
    context_start = _adjust_to_word_boundary(text, context_start, direction='start')
    context_end = _adjust_to_word_boundary(text, context_end, direction='end')
    
    # Wyciągnij fragment
    snippet_text = text[context_start:context_end]
    
    # Utwórz podświetlony tekst
    highlighted_text = _highlight_matches_in_snippet(snippet_text, matches, context_start)
    
    # Dodaj elipsy jeśli potrzeba
    if context_start > 0:
        snippet_text = "..." + snippet_text
        highlighted_text = "..." + highlighted_text
    if context_end < len(text):
        snippet_text = snippet_text + "..."
        highlighted_text = highlighted_text + "..."
    
    # Oblicz średnią pewność
    avg_confidence = sum(m.confidence for m in matches) / len(matches)
    
    return ContextSnippet(
        text=snippet_text,
        highlighted_text=highlighted_text,
        match_positions=[(m.start_pos - context_start, m.end_pos - context_start) for m in matches],
        confidence=avg_confidence,
        match_type='content',
        source_info=''
    )


def _adjust_to_word_boundary(text: str, pos: int, direction: str) -> int:
    """
    Dostosowuje pozycję do granicy słowa.
    """
    if pos <= 0:
        return 0
    if pos >= len(text):
        return len(text)
    
    if direction == 'start':
        # Idź w lewo do spacji lub początku
        while pos > 0 and not text[pos - 1].isspace():
            pos -= 1
    else:  # direction == 'end'
        # Idź w prawo do spacji lub końca
        while pos < len(text) and not text[pos].isspace():
            pos += 1
    
    return pos


def _highlight_matches_in_snippet(snippet: str, matches: List[SearchMatch], context_start: int) -> str:
    """
    Podświetla dopasowania w fragmencie tekstu.
    """
    if not snippet or not matches:
        return snippet
    
    highlighted = snippet
    offset = 0
    
    # Sortuj dopasowania według pozycji
    sorted_matches = sorted(matches, key=lambda m: m.start_pos)
    
    for match in sorted_matches:
        # Oblicz pozycję w fragmencie
        match_start = match.start_pos - context_start + offset
        match_end = match.end_pos - context_start + offset
        
        # Walidacja pozycji
        if (0 <= match_start < len(highlighted) and 
            match_start < match_end and
            match_end <= len(highlighted)):
            
            # Podświetl dopasowanie
            before = highlighted[:match_start]
            matched = highlighted[match_start:match_end]
            after = highlighted[match_end:]
            
            # Zabezpieczenie przed pustym dopasowaniem
            if matched:
                # Dodaj tagi podświetlenia
                highlighted_match = f'<mark class="search-highlight">{matched}</mark>'
                highlighted = before + highlighted_match + after
                
                # Aktualizuj offset dla kolejnych dopasowań
                offset += len(highlighted_match) - len(matched)
    
    return highlighted


def highlight_search_results(text, search_term, max_length=200):
    """
    Stara funkcja zachowana dla kompatybilności wstecznej.
    Znajduje i podkreśla znalezione fragmenty w tekście.
    Zwraca skrócony tekst z podkreślonymi dopasowaniami.
    """
    snippets = extract_context_snippets(text, search_term, max_length, max_snippets=1)
    if snippets:
        return snippets[0].highlighted_text
    
    # Fallback do starego zachowania
    return text[:max_length] + "..." if len(text) > max_length else text
