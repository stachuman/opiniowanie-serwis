# Instrukcja konfiguracji skrótu iPhone

Ten dokument wyjaśnia, jak skonfigurować skrót iPhone do przesyłania plików PDF **lub wielu zdjęć** bezpośrednio do systemu Court Workflow z automatycznym przetwarzaniem OCR.

## 🆕 NOWA FUNKCJONALNOŚĆ: Multi-Image Upload

**System teraz obsługuje trzy tryby:**
1. **Pojedynczy PDF** (jak dotychczas) - pełna kompatybilność wsteczna
2. **Wiele zdjęć poprzez multipart/form-data** - ograniczone wsparcie iPhone Shortcuts
3. **✅ Wiele zdjęć poprzez Base64 JSON** (ZALECANE dla iPhone!) - rozwiązanie problemu z limitacjami Shortcuts

## Wymagania

- iOS 13 lub nowszy z zainstalowaną aplikacją Skróty (Shortcuts)
- Dostęp sieciowy do serwera Court Workflow (LAN)
- Adres IP i port serwera (np. `http://192.168.1.100:80`)

## Endpoint API

**URL:** `http://ADRES_IP_SERWERA:80/api/upload/mobile`

**Metoda:** POST

**Content-Type:** multipart/form-data

### Tryb 1: Pojedynczy PDF (istniejący)
**Parametry:**
- `files[]`: Pojedynczy plik PDF

**Odpowiedź (JSON):**
```json
{
  "success": true,
  "opinion_id": 1045,
  "document_id": 1046,
  "ocr_queued": true,
  "message": "Upload successful. OCR processing started.",
  "preview_url": "/opinion/1045"
}
```

### Tryb 2: Wiele zdjęć → PDF (NOWY!)
**Parametry:**
- `files[]`: Tablica zdjęć (2-50 plików)
- **Formaty:** `.jpg`, `.jpeg`, `.png`, `.heic`

**Odpowiedź (JSON):**
```json
{
  "success": true,
  "opinion_id": 1045,
  "document_id": 1046,
  "ocr_queued": true,
  "image_count": 5,
  "message": "Upload successful. 5 images combined into PDF. OCR processing started.",
  "preview_url": "/opinion/1045"
}
```

### Tryb 3: Base64 Batch Upload (ZALECANY dla iPhone!) 🎯

**URL:** `http://ADRES_IP_SERWERA:80/api/upload/mobile/batch`

**Metoda:** POST

**Content-Type:** application/json

**Parametry:**
```json
{
  "images": ["base64_string_1", "base64_string_2", ...],
  "filenames": ["IMG_0001.jpg", "IMG_0002.jpg", ...]
}
```

**Dlaczego to rozwiązanie jest najlepsze:**
- ✅ **Działa z wieloma plikami** - brak limitacji multipart/form-data
- ✅ **Prostsza konfiguracja** - JSON zamiast formularzy
- ✅ **Stabilniejsze** - brak problemów z flatteningiem tablic
- ✅ **Natywne wsparcie** - iPhone Shortcuts w pełni obsługuje JSON
- ⚠️ Większy payload (~33% overhead Base64)

**Odpowiedź (JSON):**
```json
{
  "success": true,
  "opinion_id": 1047,
  "document_id": 1048,
  "ocr_queued": true,
  "image_count": 5,
  "message": "Upload successful. 5 images combined into PDF. OCR processing started.",
  "preview_url": "/opinion/1047"
}
```

### Automatyczne przetwarzanie zdjęć:
✅ **Rotacja EXIF** - zdjęcia automatycznie obracane na podstawie orientacji telefonu
✅ **Łączenie w PDF** - wszystkie zdjęcia w jednym wielostronicowym PDF
✅ **Usuwanie oryginałów** - przechowywany tylko PDF (oszczędność miejsca)
✅ **Bezpieczeństwo** - limit 50 zdjęć, max 22MB każde (po dekodowaniu)
✅ **Jakość** - automatyczne skalowanie dużych zdjęć (>4096px)
✅ **Format HEIC** - pełne wsparcie dla natywnego formatu zdjęć iPhone

## Konfiguracja skrótu krok po kroku

### ✅ ZALECANA KONFIGURACJA: Base64 Batch Upload

**Ten skrót rozwiązuje problem iPhone Shortcuts z wieloma plikami!**

#### Akcja 1: Wybierz zdjęcia
- Wyszukaj: **"Wybierz zdjęcia"** (lub **"Select Photos"**)
- Konfiguracja:
  - Wybierz wiele: **TAK** (włącz)
  - To pozwala wybrać 2-50 zdjęć naraz

#### Akcja 2: Base64 Encode (dla każdego zdjęcia)
- Wyszukaj: **"Base64 Encode"** (lub **"Koduj Base64"**)
- Wejście: **"Zdjęcia"** (wynik z poprzedniej akcji)
- Kodowanie: **Base64**
- Podział wierszy: **Brak** (WAŻNE!)

#### Akcja 3: Pobierz nazwę pliku (dla każdego zdjęcia)
- Wyszukaj: **"Get Name"** (lub **"Pobierz nazwę"**)
- Wejście: **"Zdjęcia"** (z Akcji 1)

#### Akcja 4: Pobierz zawartość adresu URL
- Wyszukaj: **"Pobierz zawartość adresu URL"** (lub **"Get Contents of URL"**)
- URL: `http://ADRES_IP_SERWERA/api/upload/mobile/batch`
- Metoda: **POST**
- Treść żądania: **JSON**
- Nagłówki:
  - `Content-Type`: `application/json`

**Treść JSON (Request Body):**
```json
{
  "images": [Encoded Text],
  "filenames": [Name]
}
```

**WAŻNE:** W Shortcuts:
- `[Encoded Text]` to wynik z Akcji 2 (Base64 Encode)
- `[Name]` to wynik z Akcji 3 (Get Name)
- Shortcuts automatycznie utworzy tablice JSON z tych wartości

#### Akcja 5: Pobierz słownik z danych wejściowych
- Wyszukaj: **"Get Dictionary from Input"**
- Wejście: Wynik z **"Zawartość adresu URL"**

#### Akcja 6: Pokaż powiadomienie
- Tytuł: `Zdjęcia wysłane!`
- Treść:
  ```
  Połączono [Dictionary Value "image_count"] zdjęć w PDF
  ID opinii: [Dictionary Value "opinion_id"]
  ```

---

## Stara konfiguracja (dla dokumentacji)

### 1. Utwórz nowy skrót i włącz Share Sheet

1. Otwórz aplikację **Skróty** na iPhonie
2. Kliknij **"+"** aby utworzyć nowy skrót
3. **KLUCZOWE:** Kliknij ikonę **ⓘ** (Details/Szczegóły) w prawym górnym rogu
4. Włącz przełącznik **"Udostępnij jako szybką akcję"** (lub po angielsku **"Show in Share Sheet"**)
5. W sekcji **"Typy arkusza udostępniania"** (Share Sheet Types):
   - Kliknij **"Dowolne"** (Any)
   - Odznacz wszystko oprócz **"Pliki"** (Files) lub **"PDFs"**
6. Wróć do edycji skrótu (strzałka wstecz)
7. Nadaj nazwę: **"Wyślij do systemu akt"**

**WAŻNE:** Po włączeniu "Show in Share Sheet", na górze skrótu pojawi się automatyczny pasek informujący "Otrzymuje pliki z arkusza udostępniania" - to oznacza że konfiguracja jest poprawna!

### 2. Dodaj akcje

Dodaj następujące akcje w podanej kolejności:

#### Akcja 1: Powtórz z każdym
- Wyszukaj: **"Powtórz z każdym"** (lub **"Repeat with Each"**)
- Wejście: **"Dane wejściowe skrótu"** (lub **"Shortcut Input"**)
  - To będzie zawierało pliki udostępnione z innych aplikacji
- To przechodzi przez wszystkie udostępnione pliki

#### Akcja 2: Pobierz zawartość adresu URL
Wewnątrz pętli powtarzania dodaj:
- Wyszukaj: **"Pobierz zawartość adresu URL"** (lub **"Get Contents of URL"**)
- Skonfiguruj następująco:

**URL:**
```
http://ADRES_IP_SERWERA/api/upload/mobile
```
(Zamień `ADRES_IP_SERWERA` na rzeczywisty adres IP serwera, np. `192.168.1.100`)

**Metoda:** `POST`

**Treść żądania:** `Formularz` (lub `Form`)

**Dodaj pole:**
- Nazwa pola: `file`
- Typ pola: `Plik` (lub `File`)
- Wartość pola: **"Element powtórzenia"** (lub **"Repeat Item"**) z poprzedniej akcji

**Nagłówki:** Nie wymagane (dostęp LAN, brak uwierzytelniania)

#### Akcja 3: Pobierz słownik z danych wejściowych
- Wyszukaj: **"Pobierz słownik z danych wejściowych"** (lub **"Get Dictionary from Input"**)
- Wejście: Wynik z **"Zawartość adresu URL"**
- To parsuje odpowiedź JSON

#### Akcja 4: Pokaż powiadomienie
- Wyszukaj: **"Pokaż powiadomienie"** (lub **"Show Notification"**)
- Tytuł: `Wysłano pomyślnie`
- Treść:
  ```
  ID opinii: [Wartość słownika "opinion_id"]
  Status OCR: [Wartość słownika "message"]
  ```

#### Akcja 5: Zakończ powtarzanie
- Dodawana automatycznie gdy utworzysz "Powtórz z każdym"

### 3. Opcjonalnie: Dodaj obsługę błędów

Po "Pobierz zawartość adresu URL", dodaj:

- Wyszukaj: **"Jeżeli"** (lub **"If"**)
- Warunek: **"Wartość słownika 'success' jest prawdą"**
- Jeśli Prawda: Pokaż powiadomienie o sukcesie (powyżej)
- W przeciwnym razie:
  - Pokaż alert z komunikatem błędu
  - Treść: `[Wartość słownika "detail"]` lub `Wysyłanie nie powiodło się`

### 4. Opcjonalnie: Otwórz podgląd w przeglądarce

Po powiadomieniu o sukcesie, dodaj:

- Wyszukaj: **"URL"**
- Wartość: `http://ADRES_IP_SERWERA[Wartość słownika "preview_url"]`
- Następnie dodaj: **"Otwórz adresy URL"** (lub **"Open URLs"**)

To otworzy stronę szczegółów opinii w Safari.

## 🆕 Konfiguracja skrótu dla wielu zdjęć (NOWY!)

### Prosty skrót: Wybierz zdjęcia → Wyślij

Ta konfiguracja pozwala na wysłanie 2-50 zdjęć jednocześnie, które zostaną automatycznie połączone w jeden PDF.

#### Akcja 1: Wybierz zdjęcia
- Wyszukaj: **"Wybierz zdjęcia"** (lub **"Select Photos"**)
- Konfiguracja:
  - Wybierz wiele: **TAK** (włącz)
  - To pozwala wybrać wiele zdjęć naraz

#### Akcja 2: Pobierz zawartość adresu URL
- Wyszukaj: **"Pobierz zawartość adresu URL"** (lub **"Get Contents of URL"**)
- Skonfiguruj:

**URL:**
```
http://ADRES_IP_SERWERA/api/upload/mobile
```

**Metoda:** `POST`

**Treść żądania:** `Formularz` (lub `Form`)

**Dodaj pole (wielokrotne):**
- Nazwa pola: `files`
- Typ pola: `Plik` (lub `File`)
- Wartość pola: **"Zdjęcia"** (wynik z poprzedniej akcji)
- **WAŻNE:** Upewnij się że pole nazywa się `files` (liczba mnoga) nie `file`

#### Akcja 3: Pobierz słownik z danych wejściowych
- Wejście: Wynik z **"Zawartość adresu URL"**

#### Akcja 4: Pokaż powiadomienie
- Tytuł: `Zdjęcia wysłane!`
- Treść:
  ```
  Połączono [Wartość słownika "image_count"] zdjęć w PDF
  ID opinii: [Wartość słownika "opinion_id"]
  ```

### Zaawansowany skrót: Share Sheet dla zdjęć

Identyczna konfiguracja jak dla PDF (sekcja wyżej), ale:

1. W **Szczegółach** skrótu (⚙️), w sekcji **"Typy arkusza udostępniania"**:
   - Odznacz **"Pliki"**
   - Zaznacz **"Zdjęcia"** (lub **"Images"**)

2. Zmień **Akcję 2** aby parametr był wielokrotny:
   - Nazwa pola: `files` (nie `file`)
   - Wartość: **"Dane wejściowe skrótu"** (wszystkie udostępnione zdjęcia)

### Użycie skrótu dla zdjęć:

**Z aplikacji Zdjęcia:**
1. Wybierz 2-50 zdjęć (przytrzymaj, wybierz wiele)
2. Kliknij **Udostępnij**
3. Wybierz Twój skrót
4. System automatycznie:
   - Wykrywa orientację zdjęć (EXIF)
   - Obraca je poprawnie
   - Łączy w jeden wielostronicowy PDF
   - Uruchamia OCR

**Z aparatu (zdjęcia na żywo):**
1. Zrób kilka zdjęć dokumentu
2. Otwórz Zdjęcia → wybierz je
3. Udostępnij → Twój skrót

## Przykładowa konfiguracja skrótu

```
┌─────────────────────────────────┐
│ Wybierz plik (PDF)              │
└─────────────────────────────────┘
          ↓
┌─────────────────────────────────┐
│ Powtórz z każdym (Plik)         │
└─────────────────────────────────┘
          ↓
┌─────────────────────────────────┐
│ Pobierz zawartość adresu URL    │
│ URL: http://192.168.1.100:80/   │
│      api/upload/mobile          │
│ Metoda: POST                    │
│ Treść: Formularz                │
│   file: [Element powtórzenia]   │
└─────────────────────────────────┘
          ↓
┌─────────────────────────────────┐
│ Pobierz słownik z danych wej.   │
└─────────────────────────────────┘
          ↓
┌─────────────────────────────────┐
│ Pokaż powiadomienie             │
│ Tytuł: Wysłano pomyślnie        │
│ Treść: ID opinii: [opinion_id]  │
└─────────────────────────────────┘
          ↓
┌─────────────────────────────────┐
│ Zakończ powtarzanie             │
└─────────────────────────────────┘
```

## Użytkowanie

### Z aplikacji Zdjęcia:
1. Otwórz aplikację Zdjęcia
2. Wybierz pliki PDF utworzone ze skanowanych dokumentów
3. Kliknij przycisk **Udostępnij**
4. Wybierz skrót **"Wyślij do systemu akt"**
5. Poczekaj na powiadomienie o sukcesie

### Z aplikacji Pliki:
1. Otwórz aplikację Pliki
2. Przejdź do plików PDF
3. Kliknij przycisk **Udostępnij** przy pliku
4. Wybierz skrót **"Wyślij do systemu akt"**
5. Poczekaj na powiadomienie o sukcesie

### Z aplikacji Skróty:
1. Otwórz aplikację Skróty
2. Kliknij **"Wyślij do systemu akt"**
3. Wybierz pliki PDF gdy zostaniesz o to poproszony
4. Poczekaj na powiadomienie o sukcesie

## Co dzieje się po wysłaniu

1. **Utworzenie opinii:** Automatycznie tworzona jest nowa opinia z nazwą zawierającą timestamp:
   - Przykład: `Mobile Upload 2025-11-27 22:49:35`

2. **Załączenie PDF:** Twój PDF jest przesyłany jako dokument podrzędny z typem `protokol`

3. **Kolejkowanie OCR:** Przetwarzanie OCR rozpoczyna się automatycznie w tle

4. **Wynik OCR:** Po zakończeniu tworzony jest plik tekstowy (`ocr_txt`) z wyodrębnionym tekstem

## Rozwiązywanie problemów

### "Nie można połączyć się z serwerem"
- Sprawdź czy adres IP serwera jest poprawny
- Upewnij się że iPhone jest w tej samej sieci (LAN)
- Sprawdź czy serwer działa: `ps aux | grep uvicorn`

### "Nieprawidłowy typ pliku"
- Skrót PDF akceptuje tylko pliki `.pdf`
- Skrót zdjęć akceptuje: `.jpg`, `.jpeg`, `.png`, `.heic`
- Sprawdź rozszerzenie pliku
- Nie można mieszać PDFów i zdjęć w jednym wysłaniu

### "Zbyt wiele plików"
- Maksymalnie 50 zdjęć w jednym wysłaniu
- Jeśli masz więcej, podziel na mniejsze grupy

### "Zdjęcie uszkodzone lub nieprawidłowe"
- Zdjęcie może być uszkodzone
- Usuń to zdjęcie i spróbuj ponownie
- Sprawdź czy zdjęcie otwiera się w aplikacji Zdjęcia

### "Zdjęcie przekracza limit 20MB"
- Pojedyncze zdjęcie jest za duże
- System automatycznie pomniejsza podczas konwersji, ale walidacja odbywa się przed
- Skompresuj zdjęcie lub zrób nowe w niższej jakości

### "Wysyłanie nie powiodło się" z błędem 500
- Sprawdź logi serwera: `tail -f /tmp/uvicorn.log`
- Zweryfikuj wolne miejsce na dysku: `df -h`

### OCR się nie uruchamia
- Sprawdź status kolejki OCR przez interfejs webowy
- Zweryfikuj czy background workers działają

## Testowanie endpointu

Możesz przetestować API używając curl z dowolnego komputera w sieci LAN:

### Test 1: Pojedynczy PDF (backward compatibility)
```bash
# Utwórz testowy PDF
cd /tmp
gs -sDEVICE=pdfwrite -dNOPAUSE -dBATCH -dSAFER -sOutputFile=test.pdf << 'EOF'
%!PS-Adobe-3.0
/Times-Roman findfont 12 scalefont setfont
50 750 moveto (Testowy dokument) show
showpage
EOF

# Wyślij przez API
curl -X POST http://ADRES_IP_SERWERA/api/upload/mobile \
  -F "files=@test.pdf" \
  -H "Accept: application/json"

# Oczekiwana odpowiedź:
# {
#   "success": true,
#   "opinion_id": 1045,
#   "document_id": 1046,
#   "ocr_queued": true,
#   "message": "Upload successful. OCR processing started.",
#   "preview_url": "/opinion/1045"
# }
```

### Test 2: Wiele zdjęć → PDF (NOWA FUNKCJONALNOŚĆ)
```bash
# Utwórz testowe zdjęcia (wymaga ImageMagick)
cd /tmp
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 1'" test1.jpg
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 2'" test2.jpg
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 3'" test3.jpg

# Wyślij wiele zdjęć przez API
curl -X POST http://ADRES_IP_SERWERA/api/upload/mobile \
  -F "files=@test1.jpg" \
  -F "files=@test2.jpg" \
  -F "files=@test3.jpg" \
  -H "Accept: application/json"

# Oczekiwana odpowiedź:
# {
#   "success": true,
#   "opinion_id": 1047,
#   "document_id": 1048,
#   "ocr_queued": true,
#   "image_count": 3,
#   "message": "Upload successful. 3 images combined into PDF. OCR processing started.",
#   "preview_url": "/opinion/1047"
# }
```

### Test 3: Walidacja - mieszanie typów (powinno się nie udać)
```bash
# To powinno zwrócić HTTP 400
curl -X POST http://ADRES_IP_SERWERA/api/upload/mobile \
  -F "files=@test.pdf" \
  -F "files=@test1.jpg" \
  -H "Accept: application/json"

# Oczekiwana odpowiedź:
# {
#   "detail": "Mixed file types not supported. Upload either: (1) single PDF, or (2) multiple images."
# }
```

### Test 4: Base64 Batch Upload (NOWY ENDPOINT - ZALECANY!)
```bash
# Utwórz testowe zdjęcia
cd /tmp
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 1'" test1.jpg
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 2'" test2.jpg
convert -size 800x600 xc:white -pointsize 48 -draw "text 100,300 'Strona 3'" test3.jpg

# Zakoduj do Base64
BASE64_1=$(base64 -w 0 test1.jpg)
BASE64_2=$(base64 -w 0 test2.jpg)
BASE64_3=$(base64 -w 0 test3.jpg)

# Wyślij przez nowy endpoint Base64 batch
curl -X POST http://ADRES_IP_SERWERA/api/upload/mobile/batch \
  -H "Content-Type: application/json" \
  -d "{
    \"images\": [\"$BASE64_1\", \"$BASE64_2\", \"$BASE64_3\"],
    \"filenames\": [\"test1.jpg\", \"test2.jpg\", \"test3.jpg\"]
  }"

# Oczekiwana odpowiedź:
# {
#   "success": true,
#   "opinion_id": 1049,
#   "document_id": 1050,
#   "ocr_queued": true,
#   "image_count": 3,
#   "message": "Upload successful. 3 images combined into PDF. OCR processing started.",
#   "preview_url": "/opinion/1049"
# }
```

### Test 5: Base64 Batch - Walidacja (błędne dane)
```bash
# Test z nierówną liczbą elementów (powinno się nie udać)
curl -X POST http://ADRES_IP_SERWERA/api/upload/mobile/batch \
  -H "Content-Type: application/json" \
  -d '{
    "images": ["base64string1", "base64string2"],
    "filenames": ["file1.jpg"]
  }'

# Oczekiwana odpowiedź:
# {
#   "detail": "Array length mismatch: 2 images but 1 filenames"
# }
```

## Uwagi dotyczące bezpieczeństwa

- **Brak uwierzytelniania** - System zaprojektowany tylko do dostępu w sieci LAN
- **Tylko HTTP** - Brak szyfrowania HTTPS/TLS (środowisko LAN)
- **Brak kluczy API** - Bezpośredni dostęp z zaufanej sieci

Jeśli wdrażasz poza siecią LAN, zaimplementuj uwierzytelnianie przed wystawieniem do internetu.

## Zaawansowana konfiguracja

### Wsparcie dla wielu serwerów

Utwórz oddzielne skróty dla różnych serwerów:
- "Wyślij do systemu (Biuro)"
- "Wyślij do systemu (Dom)"

Każdy z innym adresem IP.

### Grupowe wysyłanie z powiadomieniami

Zmodyfikuj powiadomienie aby pokazywać postęp:
```
Wysłano [Indeks powtórzenia] z [Liczba plików]
Bieżący: [Wartość słownika "opinion_id"]
```

### Auto-otwieranie interfejsu webowego

Dodaj na końcu:
```
Otwórz URL: http://ADRES_IP_SERWERA/
```

To automatycznie otwiera listę opinii po wysłaniu.

## Wsparcie

W przypadku problemów lub pytań:
1. Sprawdź logi serwera: `tail -f /tmp/uvicorn.log`
2. Zweryfikuj endpoint API: `curl http://ADRES_IP_SERWERA/debug/routes | jq`
3. Przejrzyj issues na GitHubie: https://github.com/anthropics/claude-code/issues

## Szybki start - Minimalna konfiguracja

Jeśli chcesz najszybszą konfigurację:

1. **Skróty** → **+** → Nazwa: "Wyślij PDF"
2. Dodaj akcje:
   - **Wybierz plik** (PDF)
   - **Pobierz zawartość URL**
     - URL: `http://TWOJ_IP/api/upload/mobile`
     - Metoda: POST
     - Treść: Formularz
     - Pole: `file` = [Wybierz plik]
   - **Pokaż powiadomienie**: "Wysłano!"

3. Gotowe! Użyj z **Udostępnij** → **Skróty** → **Wyślij PDF**
