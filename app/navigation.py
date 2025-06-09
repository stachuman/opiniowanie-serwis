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


def add_common_context(context: dict) -> dict:
    """
    Dodaje wspólne zmienne do kontekstu, które są potrzebne we wszystkich templates.

    Args:
        context: Istniejący kontekst template

    Returns:
        Zaktualizowany kontekst z dodatkowymi zmiennymi
    """
    from datetime import datetime

    return {
        **context,
        "current_year": datetime.now().year,
        # Dodaj inne wspólne zmienne tutaj w przyszłości
    }


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
                            str(request.url_for('upload_to_opinion_form', doc_id=opinion.id)),  # POPRAWIONE
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
                                    str(request.url_for('document_run_ocr', doc_id=document.id)),
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
                    .add_info("Data dodania",
                              document.upload_time.strftime('%Y-%m-%d %H:%M') if document.upload_time else "Brak")
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


def truncate_name(name: str, max_length: int = 30) -> str:
    """Skróć długie nazwy w nawigacji."""
    return name[:max_length] + "..." if len(name) > max_length else name


def add_navigation_to_context(request: Request, base_context: dict,
                              nav_type: str, **nav_kwargs) -> dict:
    """
    Helper do dodawania nawigacji do istniejącego kontekstu.

    Args:
        request: FastAPI Request
        base_context: Istniejący kontekst szablonu
        nav_type: Typ nawigacji ('opinion', 'document', 'simple')
        **nav_kwargs: Dodatkowe argumenty dla buildera nawigacji

    Returns:
        Zaktualizowany kontekst z elementami nawigacji
    """
    if nav_type == 'opinion':
        navigation = build_opinion_navigation(request, **nav_kwargs)
    elif nav_type == 'document':
        navigation = build_document_navigation(request, **nav_kwargs)
    elif nav_type == 'simple':
        navigation = build_simple_navigation(request, **nav_kwargs)
    else:
        raise ValueError(f"Nieznany typ nawigacji: {nav_type}")

    return {**base_context, **navigation}


def build_preview_navigation(request: Request, document: Document,
                             session: Session, preview_type: str) -> Dict[str, Any]:
    """
    Zbuduj nawigację dla wszystkich typów podglądu (PDF, Word, Image).

    Args:
        request: FastAPI Request
        document: Dokument do podglądu
        session: Sesja bazy danych
        preview_type: Typ podglądu ('pdf', 'word', 'image')

    Returns:
        Słownik z kompletną nawigacją
    """
    # Pobierz opinię nadrzędną jeśli istnieje
    parent_opinion = None
    if document.parent_id:
        parent_opinion = session.get(Document, document.parent_id)

    # Breadcrumbs
    breadcrumbs = BreadcrumbBuilder(request)

    if parent_opinion:
        breadcrumbs.add_home().add_opinion(parent_opinion).add_document(document)
    else:
        breadcrumbs.add_documents().add_document(document)

    # Dodaj odpowiedni breadcrumb dla typu podglądu
    preview_configs = {
        'pdf': ('Podgląd PDF', 'file-earmark-pdf'),
        'word': ('Podgląd Word', 'file-earmark-word'),
        'image': ('Podgląd obrazu', 'image'),
        'text': ('Podgląd tekstowy', 'file-text')
    }

    title, icon = preview_configs.get(preview_type, ('Podgląd', 'eye'))
    breadcrumbs.add_current(title, icon)

    # Page Actions - spójne dla wszystkich typów podglądu
    actions = (PageActionsBuilder(request)
               .add_secondary("Szczegóły dokumentu",
                              str(request.url_for('document_detail', doc_id=document.id)),
                              "arrow-left")
               .add_secondary("Pobierz",
                              str(request.url_for('document_download', doc_id=document.id)),
                              "download"))

    # Dodaj specjalne akcje w zależności od typu
    if preview_type == 'pdf':
        actions.add_primary("Zaawansowany OCR",
                            str(request.url_for('document_pdf_viewer', doc_id=document.id)),
                            "search")
    elif preview_type == 'image':
        actions.add_primary("Zaawansowany OCR",
                            str(request.url_for('document_image_viewer', doc_id=document.id)),
                            "search")
    elif preview_type == 'word' and document.mime_type and 'word' in document.mime_type:
        actions.add_secondary("Aktualizuj",
                              str(request.url_for('document_update_form', doc_id=document.id)),
                              "pencil")

    # Context Info - ujednolicone dla wszystkich typów
    context_info = build_document_context_info(document)

    return {
        'breadcrumbs': breadcrumbs.build(),
        'page_title': f"{title} - {document.original_filename}",
        'page_actions': actions.build(),
        'context_info': context_info
    }


def build_document_context_info(document: Document) -> List[Dict[str, str]]:
    """
    Zbuduj standardowe context_info dla dokumentu.

    Args:
        document: Dokument

    Returns:
        Lista z informacjami kontekstowymi
    """
    context_info = []

    # Status OCR - zawsze na pierwszym miejscu
    ocr_status_map = {
        'none': ('Niewykonany', 'bg-secondary'),
        'pending': ('Oczekuje', 'bg-warning'),
        'running': ('W trakcie', 'bg-info'),
        'done': ('Zakończony', 'bg-success'),
        'fail': ('Błąd', 'bg-danger')
    }

    ocr_status, ocr_class = ocr_status_map.get(document.ocr_status, ('Nieznany', 'bg-secondary'))
    context_info.append({
        'label': 'Status OCR',
        'value': ocr_status,
        'badge_class': ocr_class
    })

    # Pewność OCR - jeśli dostępna
    if document.ocr_status == 'done' and document.ocr_confidence:
        context_info.append({
            'label': 'Pewność OCR',
            'value': f'{(document.ocr_confidence * 100):.0f}%',
            'badge_class': 'bg-info'
        })

    # Typ dokumentu
    context_info.append({
        'label': 'Typ dokumentu',
        'value': document.doc_type or 'Nieznany'
    })

    # Data dodania
    context_info.append({
        'label': 'Data dodania',
        'value': document.upload_time.strftime('%Y-%m-%d %H:%M') if document.upload_time else 'Brak'
    })

    return context_info


def build_form_navigation(request: Request, form_title: str,
                          form_type: str = 'general') -> Dict[str, Any]:
    """
    Zbuduj nawigację dla formularzy (upload, create, update).

    Args:
        request: FastAPI Request
        form_title: Tytuł formularza
        form_type: Typ formularza ('upload', 'create', 'update', 'general')

    Returns:
        Słownik z nawigacją
    """
    breadcrumbs = BreadcrumbBuilder(request)

    # Różne breadcrumbs w zależności od typu formularza
    if form_type == 'upload':
        breadcrumbs.add_home()
    elif form_type == 'create':
        breadcrumbs.add_home()
    elif form_type == 'ocr':
        breadcrumbs.add_documents()
    else:
        breadcrumbs.add_home()

    breadcrumbs.add_current(form_title, "plus-circle")

    # Page Actions - dla formularzy zwykle są proste
    actions = []

    if form_type == 'upload':
        actions = (PageActionsBuilder(request)
                   .add_secondary("Pusta opinia",
                                  str(request.url_for('create_empty_opinion_form')),
                                  "file-earmark")
                   .add_secondary("Szybki OCR",
                                  str(request.url_for('quick_ocr_form')),
                                  "lightning")
                   .build())
    elif form_type == 'create':
        actions = (PageActionsBuilder(request)
                   .add_secondary("Powrót",
                                  str(request.url_for('list_opinions')),
                                  "arrow-left")
                   .build())
    elif form_type == 'ocr':
        actions = (PageActionsBuilder(request)
                   .add_primary("Nowa opinia z Word",
                                str(request.url_for('upload_form')),
                                "file-earmark-word")
                   .add_secondary("Pusta opinia",
                                  str(request.url_for('create_empty_opinion_form')),
                                  "file-earmark")
                   .build())

    return {
        'breadcrumbs': breadcrumbs.build(),
        'page_title': form_title,
        'page_actions': actions,
        'context_info': []
    }


def build_advanced_viewer_navigation(request: Request, document: Document,
                                     session: Session, viewer_type: str) -> Dict[str, Any]:
    """
    Zbuduj nawigację dla zaawansowanych viewerów (PDF z OCR, Image z OCR).

    Args:
        request: FastAPI Request
        document: Dokument
        session: Sesja bazy danych
        viewer_type: Typ viewera ('pdf_viewer', 'image_viewer')

    Returns:
        Słownik z nawigacją
    """
    # Pobierz opinię nadrzędną jeśli istnieje
    parent_opinion = None
    if document.parent_id:
        parent_opinion = session.get(Document, document.parent_id)

    # Breadcrumbs
    breadcrumbs = BreadcrumbBuilder(request)

    if parent_opinion:
        breadcrumbs.add_home().add_opinion(parent_opinion).add_document(document)
    else:
        breadcrumbs.add_documents().add_document(document)

    # Tytuły dla różnych typów viewerów
    viewer_configs = {
        'pdf_viewer': ('Zaawansowany podgląd PDF', 'search'),
        'image_viewer': ('Zaawansowany podgląd obrazu', 'search')
    }

    title, icon = viewer_configs.get(viewer_type, ('Zaawansowany podgląd', 'search'))
    breadcrumbs.add_current(title, icon)

    # Page Actions - powrót do szczegółów
    actions = (PageActionsBuilder(request)
               .add_secondary("Powrót do dokumentu",
                              str(request.url_for('document_detail', doc_id=document.id)),
                              "arrow-left")
               .add_secondary("Pobierz",
                              str(request.url_for('document_download', doc_id=document.id)),
                              "download")
               .build())

    return {
        'breadcrumbs': breadcrumbs.build(),
        'page_title': f"{title} - {document.original_filename}",
        'page_actions': actions,
        'context_info': []
    }


def get_step_badge_class(step: str) -> str:
    """
    Zwróć klasę CSS dla badge'a statusu.

    Args:
        step: Status dokumentu (k1, k2, k3, k4)

    Returns:
        Klasa CSS Bootstrap
    """
    step_classes = {
        'k1': 'bg-danger',
        'k2': 'bg-warning',
        'k3': 'bg-success',
        'k4': 'bg-secondary'
    }
    return step_classes.get(step, 'bg-secondary')


def get_step_icon(step: str) -> str:
    """
    Zwróć ikonę Bootstrap Icons dla statusu.

    Args:
        step: Status dokumentu (k1, k2, k3, k4)

    Returns:
        Nazwa ikony Bootstrap Icons
    """
    step_icons = {
        'k1': 'pencil-fill',
        'k2': 'journals',
        'k3': 'check-circle-fill',
        'k4': 'archive-fill'
    }
    return step_icons.get(step, 'question-circle')


# ==================== AKTUALIZOWANE ISTNIEJĄCE FUNKCJE ====================

def build_opinion_navigation(request: Request, opinion: Document,
                             session: Session) -> Dict[str, Any]:
    """
    Zbuduj kompletną nawigację dla widoku opinii.
    ZAKTUALIZOWANA WERSJA z lepszymi page_actions.
    """
    # Breadcrumbs
    breadcrumbs = (BreadcrumbBuilder(request)
                   .add_home()
                   .add_current(opinion.sygnatura or opinion.original_filename or f"Opinia #{opinion.id}",
                                "file-earmark-text")
                   .build())

    # Tytuł strony
    page_title = f"Opinia #{opinion.id}"

    # POPRAWKA: Lepsze page_actions
    actions = (PageActionsBuilder(request)
               .add_primary("Dodaj dokumenty",
                            str(request.url_for('upload_to_opinion_form', doc_id=opinion.id)),
                            "plus-circle")
               .add_secondary("Edytuj opinię",
                              str(request.url_for('document_detail', doc_id=opinion.id)),
                              "pencil")
               .build())

    # Informacje kontekstowe
    step_class = get_step_badge_class(opinion.step)
    step_icon = get_step_icon(opinion.step)

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
    ZAKTUALIZOWANA WERSJA z lepszymi page_actions.
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

    # POPRAWKA: Lepsze page_actions
    actions_builder = PageActionsBuilder(request)

    # Zawsze dodaj pobieranie
    actions_builder.add_secondary("Pobierz",
                                  str(request.url_for('document_download', doc_id=document.id)),
                                  "download")

    # Akcje OCR w zależności od statusu
    if document.ocr_status == 'none' and document.mime_type != 'text/plain':
        actions_builder.add_primary("Uruchom OCR",
                                    str(request.url_for('document_run_ocr', doc_id=document.id)),
                                    "play")
    elif document.ocr_status == 'done':
        # Dodaj link do podsumowania AI jeśli OCR jest gotowy
        actions_builder.add_secondary("Podsumowanie AI",
                                      str(request.url_for('document_summarize_form', doc_id=document.id)),
                                      "robot")

    # Akcje aktualizacji dla dokumentów Word
    if document.mime_type and 'word' in document.mime_type:
        actions_builder.add_secondary("Aktualizuj",
                                      str(request.url_for('document_update_form', doc_id=document.id)),
                                      "pencil")

    actions = actions_builder.build()

    # Informacje kontekstowe
    context_info = build_document_context_info(document)

    return {
        'breadcrumbs': breadcrumbs,
        'page_title': page_title,
        'page_actions': actions,
        'context_info': context_info
    }