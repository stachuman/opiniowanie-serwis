# app/navigation.py
"""
Moduł pomocniczy dla generowania elementów nawigacyjnych w aplikacji Court Workflow.
"""

from typing import List, Dict, Any, Optional
from fastapi import Request
from sqlmodel import Session
from app.models import Document


class NavigationItem:
    """Pojedynczy element nawigacji (breadcrumb lub akcja)."""

    def __init__(self, name: str, url: str = None, icon: str = None,
                 class_: str = None, **kwargs):
        self.name = name
        self.url = url
        self.icon = icon
        self.class_ = class_
        self.extra_attrs = kwargs

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'name': self.name,
            'url': self.url,
            'icon': self.icon,
            'class': self.class_
        }
        result.update(self.extra_attrs)
        return {k: v for k, v in result.items() if v is not None}


class BreadcrumbBuilder:
    """Builder dla tworzenia breadcrumbs."""

    def __init__(self, request: Request):
        self.request = request
        self.items: List[NavigationItem] = []

    def add_home(self) -> 'BreadcrumbBuilder':
        """Dodaj link do strony głównej (lista opinii)."""
        self.items.append(NavigationItem(
            name="Lista opinii",
            url=str(self.request.url_for('list_opinions')),
            icon="list"
        ))
        return self

    def add_documents(self) -> 'BreadcrumbBuilder':
        """Dodaj link do listy wszystkich dokumentów."""
        self.items.append(NavigationItem(
            name="Wszystkie dokumenty",
            url=str(self.request.url_for('list_documents')),
            icon="files"
        ))
        return self

    def add_opinion(self, opinion: Document) -> 'BreadcrumbBuilder':
        """Dodaj breadcrumb dla opinii."""
        name = opinion.sygnatura or opinion.original_filename or f"Opinia #{opinion.id}"
        self.items.append(NavigationItem(
            name=name,
            url=str(self.request.url_for('opinion_detail', doc_id=opinion.id)),
            icon="file-earmark-text"
        ))
        return self

    def add_document(self, document: Document) -> 'BreadcrumbBuilder':
        """Dodaj breadcrumb dla dokumentu."""
        name = document.original_filename or f"Dokument #{document.id}"
        self.items.append(NavigationItem(
            name=name,
            url=str(self.request.url_for('document_detail', doc_id=document.id)),
            icon="file-earmark"
        ))
        return self

    def add_current(self, name: str, icon: str = None) -> 'BreadcrumbBuilder':
        """Dodaj aktualną stronę (bez linku)."""
        self.items.append(NavigationItem(
            name=name,
            icon=icon
        ))
        return self

    def add_custom(self, name: str, url: str = None, icon: str = None) -> 'BreadcrumbBuilder':
        """Dodaj niestandardowy breadcrumb."""
        self.items.append(NavigationItem(
            name=name,
            url=url,
            icon=icon
        ))
        return self

    def build(self) -> List[Dict[str, Any]]:
        """Zwróć listę breadcrumbs jako słowniki."""
        return [item.to_dict() for item in self.items]


class PageActionsBuilder:
    """Builder dla tworzenia akcji na stronie."""

    def __init__(self, request: Request):
        self.request = request
        self.actions: List[NavigationItem] = []

    def add_primary(self, text: str, url: str, icon: str = None) -> 'PageActionsBuilder':
        """Dodaj główną akcję (niebieski przycisk)."""
        self.actions.append(NavigationItem(
            name=text,
            url=url,
            icon=icon,
            class_="btn-primary"
        ))
        return self

    def add_secondary(self, text: str, url: str, icon: str = None) -> 'PageActionsBuilder':
        """Dodaj drugorzędną akcję (szary przycisk)."""
        self.actions.append(NavigationItem(
            name=text,
            url=url,
            icon=icon,
            class_="btn-outline-secondary"
        ))
        return self

    def add_danger(self, text: str, url: str = "#", icon: str = None,
                   modal_target: str = None) -> 'PageActionsBuilder':
        """Dodaj niebezpieczną akcję (czerwony przycisk)."""
        action = NavigationItem(
            name=text,
            url=url,
            icon=icon,
            class_="btn-outline-danger"
        )
        if modal_target:
            action.extra_attrs.update({
                'data_bs_toggle': 'modal',
                'data_bs_target': modal_target
            })
        self.actions.append(action)
        return self

    def add_custom(self, text: str, url: str, icon: str = None,
                   class_: str = "btn-outline-primary", **kwargs) -> 'PageActionsBuilder':
        """Dodaj niestandardową akcję."""
        self.actions.append(NavigationItem(
            name=text,
            url=url,
            icon=icon,
            class_=class_,
            **kwargs
        ))
        return self

    def build(self) -> List[Dict[str, Any]]:
        """Zwróć listę akcji jako słowniki."""
        return [action.to_dict() for action in self.actions]


class ContextInfoBuilder:
    """Builder dla kontekstowych informacji na stronie."""

    def __init__(self):
        self.items: List[Dict[str, str]] = []

    def add_info(self, label: str, value: str, badge_class: str = None) -> 'ContextInfoBuilder':
        """Dodaj informację kontekstową."""
        self.items.append({
            'label': label,
            'value': value,
            'badge_class': badge_class
        })
        return self

    def build(self) -> List[Dict[str, str]]:
        """Zwróć listę informacji kontekstowych."""
        return self.items


def build_opinion_navigation(request: Request, opinion: Document,
                             session: Session) -> Dict[str, Any]:
    """
    Zbuduj kompletną nawigację dla widoku opinii.

    Args:
        request: Obiekt FastAPI Request
        opinion: Dokument opinii
        session: Sesja bazy danych

    Returns:
        Słownik z elementami nawigacji gotowy do przekazania do template
    """
    # Breadcrumbs
    breadcrumbs = (BreadcrumbBuilder(request)
                   .add_home()
                   .add_current(opinion.sygnatura or opinion.original_filename or f"Opinia #{opinion.id}",
                                "file-earmark-text")
                   .build())

    # Tytuł strony
    page_title = f"Opinia #{opinion.id}"

    # Akcje strony
    actions = (PageActionsBuilder(request)
               .add_primary("Dodaj dokumenty",
                            str(request.url_for('opinion_upload_form', doc_id=opinion.id)),
                            "plus-circle")
               .add_secondary("Historia wersji",
                              str(request.url_for('document_history', doc_id=opinion.id)),
                              "clock-history")
               .add_danger("Usuń opinię", modal_target="#deleteConfirmModal", icon="trash")
               .build())

    # Informacje kontekstowe
    from app.document_utils import STEP_ICON
    step_icon = STEP_ICON.get(opinion.step, "question-circle")
    step_class = {
        'k1': 'bg-danger',
        'k2': 'bg-warning',
        'k3': 'bg-success',
        'k4': 'bg-secondary'
    }.get(opinion.step, 'bg-secondary')

    context_info = (ContextInfoBuilder()
                    .add_info("Sygnatura", opinion.sygnatura or "Brak")
                    .add_info("Status", f"{opinion.step}", step_class)
                    .add_info("Typ dokumentu", opinion.doc_type or "Nie określono")
                    .add_info("Data utworzenia",
                              opinion.upload_time.strftime('%Y-%m-%d %H:%M') if opinion.upload_time else "Brak")
                    .build())

    return {
        'breadcrumbs': breadcrumbs,
        'page_title': page_title,
        'page_actions': actions,
        'context_info': context_info,
        'step_icon': step_icon
    }


def build_document_navigation(request: Request, document: Document,
                              session: Session, parent_opinion: Document = None) -> Dict[str, Any]:
    """
    Zbuduj kompletną nawigację dla widoku dokumentu.

    Args:
        request: Obiekt FastAPI Request
        document: Dokument
        session: Sesja bazy danych
        parent_opinion: Opinia nadrzędna (jeśli istnieje)

    Returns:
        Słownik z elementami nawigacji gotowy do przekazania do template
    """
    # Breadcrumbs
    breadcrumb_builder = BreadcrumbBuilder(request)

    if parent_opinion:
        # Dokument należy do opinii
        breadcrumb_builder.add_home().add_opinion(parent_opinion)
    else:
        # Dokument samodzielny
        breadcrumb_builder.add_documents()

    breadcrumbs = (breadcrumb_builder
                   .add_current(document.original_filename or f"Dokument #{document.id}",
                                "file-earmark")
                   .build())

    # Tytuł strony
    page_title = f"Dokument #{document.id}"

    # Akcje strony
    actions_builder = PageActionsBuilder(request)
    actions_builder.add_secondary("Pobierz",
                                  str(request.url_for('document_download', doc_id=document.id)),
                                  "download")

    # OCR actions
    if document.ocr_status != 'done':
        actions_builder.add_primary("Uruchom OCR",
                                    str(request.url_for('run_ocr', doc_id=document.id)),
                                    "gear")

    # Update actions
    if document.mime_type and 'word' in document.mime_type:
        actions_builder.add_secondary("Aktualizuj",
                                      str(request.url_for('document_update_form', doc_id=document.id)),
                                      "pencil")

    actions_builder.add_danger("Usuń", modal_target="#deleteConfirmModal", icon="trash")

    actions = actions_builder.build()

    # Informacje kontekstowe
    ocr_status_map = {
        'none': ('Brak', 'bg-secondary'),
        'pending': ('Oczekuje', 'bg-warning'),
        'running': ('W trakcie', 'bg-info'),
        'done': ('Zakończone', 'bg-success'),
        'fail': ('Błąd', 'bg-danger')
    }
    ocr_status, ocr_class = ocr_status_map.get(document.ocr_status, ('Nieznany', 'bg-secondary'))

    context_info = (ContextInfoBuilder()
                    .add_info("Nazwa pliku", document.original_filename or "Brak")
                    .add_info("Typ dokumentu", document.doc_type or "Nie określono")
                    .add_info("Status OCR", ocr_status, ocr_class)
                    .add_info("Rozmiar", "Nieznany")  # Można dodać funkcję obliczającą rozmiar
                    .build())

    return {
        'breadcrumbs': breadcrumbs,
        'page_title': page_title,
        'page_actions': actions,
        'context_info': context_info
    }


def build_simple_navigation(request: Request, title: str,
                            parent_link: tuple = None) -> Dict[str, Any]:
    """
    Zbuduj prostą nawigację dla formularzy i listów.

    Args:
        request: Obiekt FastAPI Request
        title: Tytuł strony
        parent_link: Tuple z (nazwa, url, icon) dla strony nadrzędnej

    Returns:
        Słownik z elementami nawigacji
    """
    breadcrumb_builder = BreadcrumbBuilder(request)

    if parent_link:
        name, url, icon = parent_link
        breadcrumb_builder.add_custom(name, url, icon)

    breadcrumbs = breadcrumb_builder.add_current(title).build()

    return {
        'breadcrumbs': breadcrumbs,
        'page_title': title,
        'page_actions': [],
        'context_info': []
    }