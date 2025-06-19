# app/config/case_statuses.py
"""
Konfiguracja statusów spraw sądowych
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class CaseStatus:
    """Pojedynczy status sprawy"""
    code: str
    name: str
    description: str
    color: str  # Bootstrap color class: danger, warning, success, secondary, etc.
    icon: str   # Bootstrap icon class
    default_visible: bool = True  # Czy pokazywać domyślnie w filtrach
    sort_order: int = 0  # Kolejność sortowania


class CaseStatusConfig:
    """Konfiguracja statusów spraw"""
    
    # Definicje statusów
    STATUSES = [
        CaseStatus(
            code="k1",
            name="k1 – Dokumenty są papierowo, do przygotowania",
            description="Niekompletne, konieczne skanowanie",
            color="danger",
            icon="pencil-fill",
            default_visible=True,
            sort_order=1
        ),
        CaseStatus(
            code="k1.5",
            name="k1.5 – Brak dokumentów sąd/prokuratra",
            description="Niekompletne, oczekiwanie na sąd/prokuraturę",
            color="danger",
            icon="pencil-fill",
            default_visible=True,
            sort_order=2
        ),
        CaseStatus(
            code="k2", 
            name="k2 – Komplet dokumentów",
            description="Wszystkie dokumenty są kompletne",
            color="warning",
            icon="journals",
            default_visible=True,
            sort_order=3
        ),
        CaseStatus(
            code="k2.5", 
            name="k2.5 – Word gotowy, niewysłany",
            description="Dokument worda jest gotowy, do weryfikacji",
            color="warning",
            icon="journals",
            default_visible=True,
            sort_order=4
        ),
        CaseStatus(
            code="k3",
            name="k3 – Word z wyciągiem wysłany", 
            description="Dokument Word z wyciągiem został wysłany",
            color="success",
            icon="check-circle-fill",
            default_visible=False,
            sort_order=5
        ),
        CaseStatus(
            code="k4",
            name="k4 – Archiwum",
            description="Sprawa została zarchiwizowana",
            color="secondary", 
            icon="archive-fill",
            default_visible=False,  # Domyślnie ukryte
            sort_order=6
        )
    ]
    
    @classmethod
    def get_status_by_code(cls, code: str) -> Optional[CaseStatus]:
        """Pobiera status po kodzie"""
        for status in cls.STATUSES:
            if status.code == code:
                return status
        return None
    
    @classmethod
    def get_all_statuses(cls) -> List[CaseStatus]:
        """Pobiera wszystkie statusy"""
        return sorted(cls.STATUSES, key=lambda x: x.sort_order)
    
    @classmethod
    def get_default_visible_codes(cls) -> List[str]:
        """Pobiera kody statusów domyślnie widocznych"""
        return [status.code for status in cls.STATUSES if status.default_visible]
    
    @classmethod
    def get_status_dict(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> nazwa dla kompatybilności"""
        return {status.code: status.name for status in cls.STATUSES}
    
    @classmethod
    def get_status_colors(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> kolor"""
        return {status.code: status.color for status in cls.STATUSES}
    
    @classmethod
    def get_status_icons(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> ikona"""
        return {status.code: status.icon for status in cls.STATUSES}


# Eksportuj dla łatwego importu
case_status_config = CaseStatusConfig()
