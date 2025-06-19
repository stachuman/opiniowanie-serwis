# app/config/document_types.py
"""
Konfiguracja typów dokumentów
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class DocumentType:
    """Pojedynczy typ dokumentu"""
    code: str
    name: str
    description: str
    color: str  # Bootstrap color class: primary, success, danger, warning, info, secondary, etc.
    icon: str   # Bootstrap icon class
    default_visible: bool = True  # Czy pokazywać domyślnie w filtrach
    sort_order: int = 0  # Kolejność sortowania


class DocumentTypeConfig:
    """Konfiguracja typów dokumentów"""
    
    # Definicje typów dokumentów
    TYPES = [
        DocumentType(
            code="opinia",
            name="Opinia",
            description="Opinia sądowa/biegłego",
            color="primary",
            icon="file-earmark-text",
            default_visible=True,
            sort_order=1
        ),
        DocumentType(
            code="akta",
            name="Akta",
            description="Akta sądowe",
            color="secondary",
            icon="folder2-open",
            default_visible=True,
            sort_order=4
        ),
        DocumentType(
            code="dokumentacja_medyczna",
            name="Dokumentacja medyczna",
            description="Dokumentacja medyczna i badania",
            color="danger",
            icon="heart-pulse",
            default_visible=True,
            sort_order=5
        ),
        DocumentType(
            code="wniosek",
            name="Wniosek",
            description="Wniosek procesowy",
            color="info",
            icon="file-earmark-plus",
            default_visible=True,
            sort_order=6
        ),
        DocumentType(
            code="zaswiadczenie",
            name="Zaświadczenie",
            description="Zaświadczenie urzędowe",
            color="success",
            icon="award",
            default_visible=True,
            sort_order=7
        ),
        DocumentType(
            code="inne",
            name="Inne",
            description="Inne dokumenty",
            color="warning",
            icon="file-earmark",
            default_visible=True,
            sort_order=8
        ),
        DocumentType(
            code="ocr_txt",
            name="OCR TXT",
            description="Wynik rozpoznawania tekstu OCR",
            color="secondary",
            icon="file-earmark-text",
            default_visible=False,  # Ukryte domyślnie
            sort_order=10
        ),
        DocumentType(
            code="archiwalna_wersja",
            name="Archiwalna wersja",
            description="Archiwalna wersja dokumentu",
            color="secondary",
            icon="archive",
            default_visible=False,  # Ukryte domyślnie
            sort_order=11
        ),
        DocumentType(
            code="postanowienie",
            name="Postanowienie",
            description="Postanowienie o badaniu",
            color="primary",
            icon="file-earmark",
            default_visible=True,  # Ukryte domyślnie
            sort_order=2
        ),
        DocumentType(
            code="protokol",
            name="Protokoły przesłuchań i zarzuty",
            description="Protokoły przesłuchań i zarzuty",
            color="primary",
            icon="file-earmark",
            default_visible=True,
            sort_order=3
        )
    ]
    
    @classmethod
    def get_type_by_code(cls, code: str) -> Optional[DocumentType]:
        """Pobiera typ dokumentu po kodzie"""
        for doc_type in cls.TYPES:
            if doc_type.code == code:
                return doc_type
        return None
    
    @classmethod
    def get_all_types(cls) -> List[DocumentType]:
        """Pobiera wszystkie typy dokumentów"""
        return sorted(cls.TYPES, key=lambda x: x.sort_order)
    
    @classmethod
    def get_default_visible_codes(cls) -> List[str]:
        """Pobiera kody typów domyślnie widocznych"""
        return [doc_type.code for doc_type in cls.TYPES if doc_type.default_visible]
    
    @classmethod
    def get_type_dict(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> nazwa dla kompatybilności"""
        return {doc_type.code: doc_type.name for doc_type in cls.TYPES}
    
    @classmethod
    def get_type_colors(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> kolor"""
        return {doc_type.code: doc_type.color for doc_type in cls.TYPES}
    
    @classmethod
    def get_type_icons(cls) -> Dict[str, str]:
        """Pobiera mapowanie kod -> ikona"""
        return {doc_type.code: doc_type.icon for doc_type in cls.TYPES}

    @classmethod
    def get_legacy_name_to_code_mapping(cls) -> Dict[str, str]:
        """Mapowanie starych nazw na nowe kody dla kompatybilności wstecznej"""
        return {
            "Opinia": "opinia",
            "Akta": "akta", 
            "Dokumentacja medyczna": "dokumentacja_medyczna",
            "Wniosek": "wniosek",
            "Zaświadczenie": "zaswiadczenie",
            "Inne": "inne",
            "OCR TXT": "ocr_txt",
            "Archiwalna wersja": "archiwalna_wersja"
        }

    @classmethod
    def get_code_to_legacy_name_mapping(cls) -> Dict[str, str]:
        """Mapowanie kodów na stare nazwy dla kompatybilności wstecznej"""
        legacy_mapping = cls.get_legacy_name_to_code_mapping()
        return {code: name for name, code in legacy_mapping.items()}


# Eksportuj dla łatwego importu
document_type_config = DocumentTypeConfig()
