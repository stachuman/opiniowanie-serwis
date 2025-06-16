"""
Przetwarzanie wstępne dokumentów przed OCR.
"""
import os
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ExifTags

from .config import logger, DPI, MAX_IMAGE_DIMENSION, MIN_IMAGE_DIMENSION

def preprocess_image(image_path, skip_exif_rotation=False):
    """
    Przetwarza obraz, aby poprawić wyniki OCR.
    
    Args:
        image_path: Ścieżka do pliku obrazu
        
    Returns:
        str: Ścieżka do przetworzonego obrazu
    """
    try:
        # Wczytaj obraz
        image = Image.open(image_path)
        original_size = image.size
        logger.info(f"Preprocessing obrazu: {image_path}, rozmiar oryginalny: {original_size[0]}x{original_size[1]}")
        print(f"🖼️ [PREPROCESS] Oryginalny rozmiar: {original_size[0]}x{original_size[1]}")
        
        # Obsługa EXIF Orientation - obrócenie obrazu przed dalszym przetwarzaniem
        # Można wyłączyć jeśli użytkownik ma kontrole obrotu w interfejsie
        if not skip_exif_rotation:
            try:
                exif = image.getexif()
                if exif:
                    orientation = exif.get(0x0112)  # Orientation tag
                    if orientation:
                        print(f"🖼️ [PREPROCESS] Znaleziono EXIF orientation: {orientation}")
                        
                        # Rotation mapping based on EXIF orientation
                        rotation_map = {
                            3: 180,  # Rotate 180 degrees
                            6: 270,  # Rotate 90 degrees clockwise (270 counterclockwise)
                            8: 90,   # Rotate 90 degrees counterclockwise
                        }
                        
                        if orientation in rotation_map:
                            degrees = rotation_map[orientation]
                            image = image.rotate(degrees, expand=True)
                            print(f"🖼️ [PREPROCESS] Obrócono obraz o {degrees} stopni (EXIF orientation {orientation})")
                            logger.info(f"Obrócono obraz o {degrees} stopni zgodnie z EXIF orientation {orientation}")
                        
                        # Usuń dane EXIF po rotacji - zmniejsza overhead
                        image_no_exif = Image.new(image.mode, image.size)
                        image_no_exif.putdata(list(image.getdata()))
                        image = image_no_exif
                        print(f"🖼️ [PREPROCESS] Usunięto dane EXIF")
            except Exception as e:
                print(f"⚠️ [PREPROCESS] Błąd obsługi EXIF: {e}")
                logger.warning(f"Błąd obsługi EXIF: {e}")
        else:
            print(f"🖼️ [PREPROCESS] Pominięto obrót EXIF (kontrola użytkownika)")
        
        # Konwersja do RGB jeśli obraz ma kanał alpha
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
            print(f"🖼️ [PREPROCESS] Konwersja z RGBA do RGB")
        elif image.mode != 'RGB':
            image = image.convert('RGB')
            print(f"🖼️ [PREPROCESS] Konwersja z {image.mode} do RGB")
        
        # Skalowanie obrazu - zarówno w górę (małe) jak i w dół (duże)
        width, height = image.size
        min_dimension = MIN_IMAGE_DIMENSION  # Minimalna szerokość lub wysokość
        max_dimension = MAX_IMAGE_DIMENSION  # Maksymalna szerokość lub wysokość dla oszczędności pamięci GPU
        
        # Sprawdź czy obraz jest zbyt mały i wymaga przeskalowania w górę
        if width < min_dimension or height < min_dimension:
            scale_factor = min_dimension / min(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Przeskalowano mały obraz z {width}x{height} do {new_width}x{new_height}")
        
        # Sprawdź czy obraz jest zbyt duży i wymaga przeskalowania w dół
        elif width > max_dimension or height > max_dimension:
            scale_factor = max_dimension / max(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Przeskalowano duży obraz z {width}x{height} do {new_width}x{new_height} (oszczędność pamięci GPU)")
        
        # Zapisz przetworzony obraz
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
            tmp_path = tmp_img.name
        
        final_size = image.size
        image.save(tmp_path, "PNG")
        
        print(f"🖼️ [PREPROCESS] Finalny rozmiar: {final_size[0]}x{final_size[1]}")
        print(f"🖼️ [PREPROCESS] Zapisano do: {tmp_path}")
        logger.info(f"Preprocessing zakończony: {final_size[0]}x{final_size[1]} -> {tmp_path}")
        
        return tmp_path
        
    except Exception as e:
        logger.error(f"Błąd podczas przetwarzania obrazu: {str(e)}")
        return str(image_path)  # Zwróć oryginalną ścieżkę w przypadku błędu

def extract_pages_from_pdf(pdf_path, max_batch_size=5):
    """
    Konwertuje PDF na listy obrazów stron podzielone na partie.
    
    Args:
        pdf_path: Ścieżka do pliku PDF
        max_batch_size: Maksymalna liczba stron w partii
        
    Returns:
        list: Lista list ścieżek do obrazów stron (pogrupowane w partie)
    """
    try:
        from pdf2image import convert_from_path
        
        # Konwertuj PDF na obrazy
        pages = convert_from_path(pdf_path, dpi=DPI)
        total_pages = len(pages)
        logger.info(f"Wyodrębniono {total_pages} stron z PDF")
        
        # Podziel strony na partie
        batches = []
        for i in range(0, total_pages, max_batch_size):
            batch_pages = pages[i:i+max_batch_size]
            
            # Zapisz strony z tej partii jako obrazy
            batch_paths = []
            for j, img in enumerate(batch_pages):
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
                    tmp_path = tmp_img.name
                
                img.save(tmp_path, "PNG")
                batch_paths.append(tmp_path)
            
            batches.append(batch_paths)
            
        return batches
        
    except Exception as e:
        logger.error(f"Błąd podczas konwersji PDF na obrazy: {str(e)}")
        return []

def preprocess_image_fragment(image, min_dimension=300):
    """
    Przetwarza fragment obrazu dla OCR (optymalizacja pamięci).
    
    Args:
        image: PIL Image object
        min_dimension: Minimalna szerokość lub wysokość fragmentu
        
    Returns:
        PIL Image: Przetworzony obraz
    """
    try:
        # Konwersja do RGB jeśli obraz ma kanał alpha
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3])
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Skalowanie fragmentu obrazu
        width, height = image.size
        max_fragment_dimension = MAX_IMAGE_DIMENSION // 2  # Dla fragmentów używamy mniejszy limit
        
        # Sprawdź czy fragment jest zbyt mały
        if width < min_dimension or height < min_dimension:
            scale_factor = min_dimension / min(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Przeskalowano mały fragment z {width}x{height} do {new_width}x{new_height}")
        
        # Sprawdź czy fragment jest zbyt duży
        elif width > max_fragment_dimension or height > max_fragment_dimension:
            scale_factor = max_fragment_dimension / max(width, height)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.info(f"Przeskalowano duży fragment z {width}x{height} do {new_width}x{new_height}")
        
        return image
        
    except Exception as e:
        logger.error(f"Błąd podczas przetwarzania fragmentu obrazu: {str(e)}")
        return image  # Zwróć oryginalny obraz w przypadku błędu
