# System Planowania Tras

## Opis projektu

System do planowania i optymalizacji tras dla wielu lokalizacji. Projekt wykorzystuje algorytmy optymalizacji (TSP - Problem Komiwojażera) do znajdowania najkrótszych tras między punktami, z uwzględnieniem ograniczeń dziennych dystansów.

## Wymagania systemowe

- Python 3.x
- Zależności wymienione w pliku `requirements.txt`

## Instalacja

1. Sklonuj repozytorium
2. Zainstaluj wymagane pakiety:

```bash
pip install -r requirements.txt
```

## Główne funkcjonalności

- Geolokalizacja adresów
- Optymalizacja tras (TSP)
- Generowanie map wielowarstwowych
- Zaawansowane cache'owanie tras
- Podział tras na dni z ograniczeniami dystansu
- Obsługa wielowątkowości
- Konwersja danych Excel do JSON
- Automatyczne generowanie map HTML

## Struktura projektu i opis plików

### Katalogi główne

- `core/` - główne moduły systemu
- `cache/` - katalog na dane cache'owane
- `__out/` - katalog na wygenerowane pliki wyjściowe

### Pliki główne

- `run.py` - główny plik aplikacji zawierający logikę biznesową, obsługę danych wejściowych i generowanie map
- `config.py` - plik konfiguracyjny zawierający stałe i ustawienia systemu
- `create_JSON.py` - skrypt do konwersji danych z pliku Excel do formatu JSON

### Moduły w katalogu core/

- `trasa.py` - moduł definiujący klasę Trasa i jej metody do zarządzania pojedynczą trasą
- `cache_manager.py` - zarządzanie cache'owaniem tras i danych
- `distance_utils.py` - narzędzia do obliczania odległości między punktami
- `map_utils.py` - funkcje pomocnicze do generowania i stylizacji map
- `route_utils.py` - narzędzia do obsługi tras i ich optymalizacji
- `tsp_algorithms.py` - implementacje algorytmów TSP (Nearest Neighbor, 2-opt, MST)

### Pliki danych

- `Tabela.xlsx` - plik wejściowy z danymi adresowymi
- `Tabela.json` - przetworzone dane w formacie JSON
- `index.html` - wygenerowana mapa z optymalnymi trasami
- `mapa_wszystkich_tras.html` - mapa zawierająca wszystkie możliwe trasy

## Użycie

1. Przygotuj plik Excel (`Tabela.xlsx`) z adresami
2. Uruchom skrypt:

```bash
python run.py
```

3. Wygenerowane mapy będą dostępne w katalogu `__out/`

## Algorytmy

- Nearest Neighbor - algorytm najbliższego sąsiada
- 2-opt - algorytm optymalizacji lokalnej
- MST Approximation - aproksymacja oparta na minimalnym drzewie rozpinającym

## Cache

System wykorzystuje zaawansowany system cache'owania w katalogu `cache/` w celu:

- Przyspieszenia obliczeń
- Zmniejszenia liczby zapytań do API
- Zachowania historycznych danych o trasach
- Optymalizacji wykorzystania zasobów

## Obsługa błędów

- Automatyczne ponowne próby geolokalizacji
- Obsługa timeoutów
- Logowanie błędów
- Walidacja danych wejściowych

## Ograniczenia

- Maksymalny dzienny dystans (domyślnie 1000 km)
- Limit zapytań do API geolokalizacji
- Wymagane połączenie internetowe dla geolokalizacji
- Maksymalna liczba punktów w jednej trasie

## Rozwój

- Możliwość dodawania własnych ograniczeń
- Integracja z innymi API map
- Optymalizacja wydajności
- Rozszerzenie o dodatkowe algorytmy TSP
- Implementacja interfejsu użytkownika

## Zależności

- pandas==2.1.4 - do obsługi danych tabelarycznych
- openpyxl==3.1.2 - do obsługi plików Excel
- geopy==2.4.1 - do geolokalizacji adresów
- folium==0.14.0 - do generowania map interaktywnych
- requests==2.31.0 - do komunikacji z API
- pickle5==0.0.11 - do obsługi cache'owania
- polyline==2.0.0 - do kodowania tras
- networkx==3.2.1 - do implementacji algorytmów grafowych

## Wydajność

- Optymalizacja pamięci dla dużych zestawów danych
- Efektywne cache'owanie wyników
- Wielowątkowa obsługa zapytań
- Automatyczna walidacja i czyszczenie cache'u
