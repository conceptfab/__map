import argparse
import json
import os
import pickle
import threading
import time
import traceback

import folium
import networkx as nx
import pandas as pd
import polyline
import requests
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

from config import (
    ALGORITHM_COLORS,
    LINE_STYLES,
    OSRM_MAX_RETRIES,
    OSRM_RETRY_DELAY,
    OSRM_SERVERS,
    OSRM_TIMEOUT,
)


# Funkcje do obsługi cachowania tras
def load_cached_routes(cache_file="cache/cached_routes.pkl"):
    """
    Ładuje zapisane trasy z pliku cache

    Args:
        cache_file (str): Ścieżka do pliku cache

    Returns:
        dict: Słownik przechowujący zapisane trasy
    """
    cached_routes = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "rb") as f:
                cached_routes = pickle.load(f)
            print(f"Załadowano {len(cached_routes)} zapisanych tras z {cache_file}")
        except Exception as e:
            print(f"Błąd wczytywania zapisanych tras: {str(e)}")
    return cached_routes


def save_cached_routes(cached_routes, cache_file="cache/cached_routes.pkl"):
    """
    Zapisuje trasy do pliku cache

    Args:
        cached_routes (dict): Słownik przechowujący trasy
        cache_file (str): Ścieżka do pliku cache

    Returns:
        bool: True jeśli operacja się powiodła, False w przeciwnym przypadku
    """
    import threading

    # Mutex do synchronizacji zapisu do pliku
    if not hasattr(save_cached_routes, "lock"):
        save_cached_routes.lock = threading.Lock()

    try:
        # Upewnij się, że folder cache istnieje
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)

        with save_cached_routes.lock:
            with open(cache_file, "wb") as f:
                pickle.dump(cached_routes, f)
            print(f"Zapisano {len(cached_routes)} tras do {cache_file}")
            return True
    except Exception as e:
        print(f"Błąd zapisywania tras: {str(e)}")
        return False


def geolokalizuj_adres(adres, max_retries=3, delay=1):
    """
    Konwertuje adres na współrzędne geograficzne używając Nominatim
    (OpenStreetMap)

    Args:
        adres (str): Pełny adres do geolokalizacji
        max_retries (int): Maksymalna liczba prób w przypadku błędu
        delay (int): Opóźnienie między próbami w sekundach

    Returns:
        tuple: (latitude, longitude) lub (None, None) w przypadku błędu
    """
    geolocator = Nominatim(user_agent="my_geocoder_app")

    # Przygotowanie lepszych wariantów adresu
    adres_variants = [
        f"{adres}, Polska",  # Pełny adres z krajem
        # Bardziej precyzyjne warianty
        f"{adres.replace(',', ', ')}, Polska",  # Poprawienie spacji
        f"{adres.replace('Ul.', 'ulica')}, Polska",  # Zamiana skrótu
        f"{adres.replace('Ul.', 'ul.')}, Polska",  # Zamiana skrótu
        # Dokładniejszy format adresu
        adres.split(",")[0].strip() + ", Polska",  # Pierwszy element
        # Warianty z numerem budynku
        f"{adres.split(',')[0].strip().replace(' ', ', ')}, Polska",  # Zamiana spacji
    ]

    # Zwiększenie parametrów dla większej dokładności
    for attempt in range(max_retries):
        for variant in adres_variants:
            try:
                # Dodajemy opóźnienie przed każdym zapytaniem
                time.sleep(delay)
                print(f"Próba geolokalizacji: {variant}")
                # Zwiększamy parametry dokładności
                location = geolocator.geocode(
                    variant, timeout=20, exactly_one=True, addressdetails=True
                )

                if location:
                    print(f"Znaleziono lokalizację: {location.address}")
                    # Dodać sprawdzenie pewności wyniku
                    if hasattr(location, "raw") and "importance" in location.raw:
                        print(f"Pewność wyniku: {location.raw['importance']}")
                    return location.latitude, location.longitude
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"Błąd geolokalizacji dla adresu {variant}: {str(e)}")
                time.sleep(delay * 2)  # Zwiększamy opóźnienie po błędzie
            except Exception as e:
                print(f"Niespodziewany błąd: {str(e)}")
                time.sleep(delay)

    print(f"Nie udało się znaleźć lokalizacji dla adresu: {adres}")
    return None, None


def excel_to_json(excel_file, json_file=None):
    """
    Konwertuje plik Excel na format JSON z geolokalizacją adresów

    Args:
        excel_file (str): Ścieżka do pliku Excel
        json_file (str, optional): Ścieżka do pliku wyjściowego JSON.
                                 Jeśli nie podano, użyje nazwy pliku Excel z rozszerzeniem .json

    Returns:
        bool: True jeśli operacja się powiodła, False w przeciwnym przypadku
    """
    try:
        # Sprawdź czy plik Excel istnieje
        if not os.path.exists(excel_file):
            print(f"Błąd: Plik Excel {excel_file} nie istnieje!")
            return False

        # Wczytanie pliku Excel
        print(f"Wczytuję dane z pliku Excel: {excel_file}")
        df = pd.read_excel(excel_file)
        print(f"Wczytano {len(df)} rekordów z pliku Excel")

        # Jeśli nie podano nazwy pliku wyjściowego, użyj nazwy pliku Excel
        if json_file is None:
            json_file = os.path.splitext(excel_file)[0] + ".json"

        # Sprawdź, czy plik JSON już istnieje i wczytaj go
        existing_data = []
        if os.path.exists(json_file):
            print(f"Plik JSON {json_file} już istnieje, aktualizuję dane...")
            with open(json_file, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                # Konwertuj istniejące dane do DataFrame
                existing_df = pd.DataFrame(existing_data)

                # Aktualizuj tylko rekordy bez współrzędnych
                merged_df = df.copy()
                if (
                    "latitude" in existing_df.columns
                    and "longitude" in existing_df.columns
                ):
                    for index, row in existing_df.iterrows():
                        if pd.notna(row["latitude"]) and pd.notna(row["longitude"]):
                            # Znajdź odpowiadający rekord w df
                            matching_rows = merged_df[
                                merged_df["pełny_adres"] == row["pełny_adres"]
                            ]
                            if not matching_rows.empty:
                                merged_df.loc[matching_rows.index[0], "latitude"] = row[
                                    "latitude"
                                ]
                                merged_df.loc[matching_rows.index[0], "longitude"] = (
                                    row["longitude"]
                                )

                df = merged_df

        # Konwersja DataFrame do listy słowników
        data = df.to_dict(orient="records")

        # Jeśli nie ma kolumny "pełny_adres", spróbuj ją utworzyć
        for item in data:
            if "pełny_adres" not in item:
                miasto = item.get("Miasto", "").strip()
                adres = item.get("Adres", "").strip()
                kod = item.get("Kod pocztowy", "").strip()
                item["pełny_adres"] = f"{adres}, {kod} {miasto}"
                print(f"Utworzono pełny adres: {item['pełny_adres']}")

        # Zapis do pliku JSON
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"Pomyślnie zapisano dane do pliku JSON: {json_file}")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas konwersji Excel do JSON: {str(e)}")
        traceback.print_exc()
        return False


def uzupelnij_geolokalizacje(json_file):
    """
    Uzupełnia brakujące współrzędne geograficzne w pliku JSON

    Args:
        json_file (str): Ścieżka do pliku JSON

    Returns:
        bool: True jeśli operacja się powiodła, False w przeciwnym przypadku
    """
    try:
        # Sprawdzamy dostępność serwisu
        if not sprawdz_status_serwisu_geolokalizacji():
            print(
                "Serwis geolokalizacji jest niedostępny. Próbuję kontynuować z istniejącymi danymi."
            )

        # Wczytanie danych z JSON
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Licznik uzupełnionych adresów
        uzupelnione = 0
        total_to_process = len(
            [
                item
                for item in data
                if "pełny_adres" in item
                and (
                    item.get("latitude") is None
                    or item.get("longitude") is None
                    or pd.isna(item.get("latitude"))
                    or pd.isna(item.get("longitude"))
                    or str(item.get("latitude")).lower() == "nan"
                    or str(item.get("longitude")).lower() == "nan"
                )
            ]
        )

        print(f"Znaleziono {total_to_process} adresów do geolokalizacji.")

        if total_to_process == 0:
            print("Wszystkie adresy mają już współrzędne geograficzne.")
            return True

        # Iteracja przez wszystkie rekordy
        processed = 0
        for i, item in enumerate(data):
            # Sprawdzenie czy brakuje współrzędnych
            if "pełny_adres" in item and (
                item.get("latitude") is None
                or item.get("longitude") is None
                or pd.isna(item.get("latitude"))
                or pd.isna(item.get("longitude"))
                or str(item.get("latitude")).lower() == "nan"
                or str(item.get("longitude")).lower() == "nan"
            ):
                processed += 1
                print(
                    f"Przetwarzanie {processed}/{total_to_process}: {item['pełny_adres']}"
                )
                latitude, longitude = geolokalizuj_adres(
                    item["pełny_adres"], max_retries=5, delay=2
                )
                if latitude is not None and longitude is not None:
                    item["latitude"] = latitude
                    item["longitude"] = longitude
                    uzupelnione += 1
                    print(f"Uzupełniono współrzędne dla: {item['pełny_adres']}")
                else:
                    print(
                        f"Nie udało się znaleźć współrzędnych dla: {item['pełny_adres']}"
                    )

                # Zapisywanie częściowych wyników co 3 adresy
                if processed % 3 == 0 or processed == total_to_process:
                    with open(json_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    print(
                        f"Zapisano częściowe wyniki. Uzupełniono {uzupelnione}/{total_to_process} adresów."
                    )

                # Dodaj opóźnienie, aby nie przeciążyć API
                time.sleep(2)  # Zwiększono opóźnienie do 2 sekund

        # Zapis zaktualizowanych danych do pliku JSON
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(
            f"Zakończono uzupełnianie współrzędnych. Uzupełniono {uzupelnione} adresów."
        )
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas uzupełniania geolokalizacji: {str(e)}")
        return False


def przygotuj_etykiety_kolejnosci(path, daily_segments):
    """
    Przygotowuje etykiety z numerem dnia i kolejnością dla punktów trasy

    Args:
        path (list): Ścieżka z indeksami lokalizacji
        daily_segments (list): Lista segmentów podzielonych na dni

    Returns:
        tuple: (day_for_point, order_for_point) - słowniki z przypisaniem dnia i kolejności
    """
    day_for_point = {}
    order_for_point = {}

    order_idx = 0
    for day_idx, day in enumerate(daily_segments):
        for segment in day["segments"]:
            from_idx, to_idx = segment
            # Zapisz dzień i kolejność dla punktu początkowego
            if from_idx not in day_for_point:
                day_for_point[from_idx] = day_idx + 1
                order_for_point[from_idx] = order_idx
                order_idx += 1

            # Dla ostatniego segmentu zapisz także dla punktu końcowego
            if segment == day["segments"][-1]:
                day_for_point[to_idx] = day_idx + 1
                order_for_point[to_idx] = order_idx
                order_idx += 1

    return day_for_point, order_for_point


def generuj_mape_wielowarstwowa(
    json_file,
    html_file="index.html",
    show_route=True,
    offline_mode=False,
    force_recalculate=False,
):
    """
    Generuje mapę HTML z wieloma warstwami informacji: lokalizacje, numery, adresy,
    trasy z różnych algorytmów oraz numerami dni i kolejności odwiedzania

    Args:
        json_file (str): Ścieżka do pliku JSON
        html_file (str): Ścieżka do wyjściowego pliku HTML
        show_route (bool): Czy wyświetlać warstwy z trasami
        offline_mode (bool): Czy używać tylko danych lokalnych (bez pobierania tras)
        force_recalculate (bool): Czy wymusić ponowne obliczenia tras

    Returns:
        bool: True jeśli operacja się powiodła
    """
    try:
        # Upewnij się, że folder __out istnieje
        os.makedirs("__out", exist_ok=True)

        # Jeśli html_file już zawiera ścieżkę __out, nie dodawaj jej ponownie
        if not html_file.startswith("__out"):
            html_file = os.path.join("__out", html_file)

        # Wczytanie danych
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Filtrowanie lokalizacji z prawidłowymi współrzędnymi
        valid_locations = [
            item
            for item in data
            if "latitude" in item
            and "longitude" in item
            and item["latitude"] is not None
            and item["longitude"] is not None
            and not pd.isna(item["latitude"])
            and not pd.isna(item["longitude"])
        ]

        if not valid_locations:
            print("Brak lokalizacji z prawidłowymi współrzędnymi")
            return False

        # Obliczanie średnich współrzędnych dla centrowania mapy
        avg_lat = sum(item["latitude"] for item in valid_locations) / len(
            valid_locations
        )
        avg_lng = sum(item["longitude"] for item in valid_locations) / len(
            valid_locations
        )

        # Tworzenie mapy
        mapa = folium.Map(location=[avg_lat, avg_lng], zoom_start=7)

        # Definicja podstawowych warstw
        warstwy = {
            "Lokalizacje": folium.FeatureGroup(name="Lokalizacje", show=True),
            "Numery": folium.FeatureGroup(name="Numery", show=True),
            "Adresy": folium.FeatureGroup(name="Adresy", show=True),
        }

        # Jeśli potrzebna warstwa trasy, obliczamy różne trasy
        if show_route:
            # Znajdź pozycję startową (Nadarzyn)
            start_location = next(
                (item for item in valid_locations if item.get("Miasto") == "Nadarzyn"),
                valid_locations[
                    0
                ],  # Jeśli nie ma Nadarzyna, użyj pierwszej lokalizacji
            )

            # Wyznacz pozostałe lokalizacje
            other_locations = [
                item for item in valid_locations if item != start_location
            ]

            # Oblicz macierz odległości
            print("Obliczanie macierzy odległości między lokalizacjami...")
            matrix_data = oblicz_macierz_odleglosci(
                other_locations,
                start_location,
                offline_mode=offline_mode,
                force_recalculate=force_recalculate,
            )

            # Znajdź różne trasy z różnych algorytmów
            print("Wyznaczanie tras przy użyciu różnych algorytmów...")
            all_routes_data = znajdz_najkrotsza_trase_tsp(
                matrix_data, force_recalculate=force_recalculate
            )

            # Tworzymy warstwy dla każdego algorytmu
            warstwy = {}
            trasy_warstwy = {}
            order_warstwy = {}
            start_day_warstwy = (
                {}
            )  # Dodajemy definicję słownika dla warstw początku dnia

            # Dodajemy podstawowe warstwy
            warstwy["Lokalizacje"] = folium.FeatureGroup(name="Lokalizacje", show=True)
            warstwy["Numery"] = folium.FeatureGroup(name="Numery", show=True)
            warstwy["Adresy"] = folium.FeatureGroup(name="Adresy", show=True)

            # Tworzymy warstwy dla każdego algorytmu
            for algo_name in all_routes_data["algorithms"].keys():
                warstwy[f"Trasa - {algo_name}"] = folium.FeatureGroup(
                    name=f"Trasa - {algo_name}"
                )
                warstwy[f"Kolejność - {algo_name}"] = folium.FeatureGroup(
                    name=f"Kolejność - {algo_name}"
                )
                warstwy[f"Początek dnia - {algo_name}"] = folium.FeatureGroup(
                    name=f"Początek dnia - {algo_name}"
                )
                trasy_warstwy[algo_name] = warstwy[f"Trasa - {algo_name}"]
                order_warstwy[algo_name] = warstwy[f"Kolejność - {algo_name}"]
                start_day_warstwy[algo_name] = warstwy[f"Początek dnia - {algo_name}"]

        # Dodanie wszystkich warstw do mapy
        for nazwa, warstwa in warstwy.items():
            warstwa.add_to(mapa)

        # Dodanie obiektów do poszczególnych warstw
        for item in valid_locations:
            # Warstwa: Lokalizacje
            popup_text = f"""
            <b>{item.get('Miasto', '')}</b><br>
            Adres: {item.get('Adres', '')}<br>
            Kod pocztowy: {item.get('Kod pocztowy', '')}<br>
            Numer: {item.get('numer', '')}
            """

            folium.Marker(
                location=[item["latitude"], item["longitude"]],
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=item.get("Miasto", ""),
            ).add_to(warstwy["Lokalizacje"])

            # Warstwa: Numery
            folium.CircleMarker(
                location=[item["latitude"], item["longitude"]],
                radius=12,
                color="red",
                fill=True,
                fill_color="red",
                fill_opacity=0.7,
                popup=f"Numer: {item.get('numer', '')}",
            ).add_to(warstwy["Numery"])

            folium.map.Marker(
                [item["latitude"], item["longitude"]],
                icon=folium.DivIcon(
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                    html=f'<div style="font-size: 10pt; color: white; text-align: center; font-weight: bold;">{item.get("numer", "")}</div>',
                ),
            ).add_to(warstwy["Numery"])

            # Warstwa: Adresy
            pelny_adres = item.get("pełny_adres", "")
            folium.map.Marker(
                [item["latitude"], item["longitude"]],
                icon=folium.DivIcon(
                    icon_size=(200, 20),
                    icon_anchor=(100, -20),
                    html=f'<div style="font-size: 9pt; color: black; background-color: white; padding: 2px; border-radius: 3px; text-align: center;">{pelny_adres}</div>',
                ),
            ).add_to(warstwy["Adresy"])

        # Jeśli potrzebne warstwy trasy, dodajemy trasy i numery kolejności z różnych algorytmów
        if show_route:
            # Tworzymy legendę z informacjami o trasach
            legend_html = f"""
            <div style="position: fixed; 
                        bottom: 50px; right: 50px; width: 320px; height: auto;
                        border:2px solid grey; z-index:9999; 
                        background-color:white;
                        padding: 10px;
                        font-size: 13px;
                        font-family: Arial, sans-serif;">
            &nbsp; <b>Porównanie algorytmów:</b> <br>
            <table style="width: 100%; margin-top: 8px; border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #ccc; font-weight: bold;">
                <td style="padding: 4px;">Algorytm</td>
                <td style="padding: 4px; text-align: right;">Dystans</td>
                <td style="padding: 4px; text-align: right;">Dni</td>
            </tr>
            """

            # Dodajemy informacje o wszystkich algorytmach do legendy
            # Słownik do przechowywania palet kolorów dla każdego algorytmu
            algorithm_palettes = {}

            # Mapowanie nazw algorytmów na klucze z ALGORITHM_COLORS
            algo_name_mapping = {
                "Najbliższy sąsiad": "nearest_neighbor",
                "Najbliższy sąsiad + 2-opt": "two_opt",
                "MST": "mst_approx",
            }

            # Sortujemy algorytmy według odległości (od najlepszego)
            sorted_algos = sorted(
                all_routes_data["algorithms"].items(), key=lambda x: x[1]["distance"]
            )

            for i, (algo_name, algo_data) in enumerate(sorted_algos):
                is_best = algo_name == all_routes_data["best_algorithm_name"]
                total_distance = algo_data["distance"]
                num_days = len(algo_data["daily_segments"])

                # Użyj pierwszego koloru z palety dla danego algorytmu
                algo_key = algo_name_mapping.get(algo_name, "default")
                color = ALGORITHM_COLORS[algo_key][0]  # Pierwszy kolor z palety

                # Generujemy paletę kolorów dla dni tego algorytmu
                algorithm_palettes[algo_name] = generuj_kolory_dla_dni(
                    num_days, algo_key
                )

                # Wyróżnij najlepszy algorytm
                style = (
                    "font-weight: bold; background-color: #f0f0f0;" if is_best else ""
                )

                legend_html += f"""
                <tr style="{style}">
                    <td style="padding: 4px;">
                        <svg height="3" width="30">
                            <line x1="0" y1="0" x2="30" y2="0" 
                                  style="stroke:{color};
                                         stroke-width:{LINE_STYLES.get(algo_name, {}).get('weight', 3)}px;
                                         stroke-dasharray:{LINE_STYLES.get(algo_name, {}).get('dash_array', 'none')};" />
                        </svg>
                        {algo_name}
                    </td>
                    <td style="padding: 4px; text-align: right;">{total_distance:.1f} km</td>
                    <td style="padding: 4px; text-align: center;">{num_days}</td>
                </tr>
                """

            legend_html += "</table>"

            # Dodajemy sekcję z podziałem na dni dla wszystkich algorytmów
            legend_html += '<div style="margin-top: 10px; border-top: 1px solid #ccc; padding-top: 8px;">'

            for algo_name, algo_data in sorted_algos:
                is_best = algo_name == all_routes_data["best_algorithm_name"]
                daily_segments = algo_data["daily_segments"]
                palette = algorithm_palettes[algo_name]

                # Dodaj naglówek sekcji dla algorytmu tylko gdy mamy więcej niż 1 dzień
                if len(daily_segments) > 1:
                    legend_html += f"""
                    <div style="margin-top: 6px; margin-bottom: 4px;">
                        <b>{algo_name}</b> - podział na dni:
                    </div>
                    <div style="display: flex; flex-wrap: wrap; margin-bottom: 8px;">
                    """

                    # Dodaj kolorowe kwadraty dla dni
                    for i, color in enumerate(palette):
                        legend_html += f"""
                        <div style="margin: 2px; display: flex; align-items: center;">
                            <div style="width: 12px; height: 12px; background-color: {color}; margin-right: 4px;"></div>
                            <span style="font-size: 11px;">Dzień {i+1}</span>
                        </div>
                        """

                    legend_html += "</div>"

            legend_html += """
            </div>
            
            <div style="font-size: 11px; margin-top: 8px; color: #666; text-align: center;">
                Warstwy można włączać/wyłączać w panelu kontrolnym
            </div>
            
            </div>
            """

            mapa.get_root().html.add_child(folium.Element(legend_html))

            # Dodajemy trasy i numery kolejności dla każdego algorytmu na osobne warstwy
            for algo_name, algo_data in all_routes_data["algorithms"].items():
                # Rysowanie segmentów dziennych tras
                daily_segments = algo_data["daily_segments"]
                path = algo_data["path"]

                # Użyj palety kolorów specyficznej dla tego algorytmu
                colors = algorithm_palettes[algo_name]

                # Nazwa warstwy dla tego algorytmu
                layer_name = f"Trasa - {algo_name}"
                order_layer_name = f"Kolejność - {algo_name}"

                # Przygotuj informacje o kolejności punktów i przynależności do dni
                day_for_point, order_for_point = przygotuj_etykiety_kolejnosci(
                    path, daily_segments
                )

                # Dodaj markery z informacją o kolejności i dniu
                for i, idx in enumerate(path):
                    if (
                        idx == 0 and i == len(path) - 1
                    ):  # Pomijamy ostatni punkt (ten sam co początkowy)
                        continue

                    loc = matrix_data["locations"][idx]
                    day_num = day_for_point.get(idx, "?")
                    order_num = order_for_point.get(idx, i)

                    # Tworzymy etykietę z dniem i kolejnością
                    order_label = f"D{day_num}-{order_num:02d}"

                    # Użyj koloru odpowiadającego danemu dniowi
                    algo_key = algo_name_mapping.get(algo_name, "default")
                    colors = ALGORITHM_COLORS[algo_key]
                    # Dzień jest 1-based, więc odejmujemy 1 aby dostać indeks
                    day_idx = day_num - 1
                    # Jeśli mamy więcej dni niż kolorów, używamy modulo
                    color = colors[day_idx % len(colors)]

                    # Utwórz marker z numerem dnia i kolejnością
                    folium.map.Marker(
                        [loc["latitude"], loc["longitude"]],
                        icon=folium.DivIcon(
                            icon_size=(60, 30),
                            icon_anchor=(30, 15),
                            html=f"""
                            <div style="
                                background-color: {color}; 
                                color: white; 
                                border-radius: 5px; 
                                text-align: center; 
                                font-weight: bold; 
                                padding: 2px 5px;
                                font-size: 10px;
                                opacity: 0.8;
                            ">
                                {order_label}
                            </div>
                            """,
                        ),
                        tooltip=f"{algo_name}: Dzień {day_num}, Punkt {order_num}",
                    ).add_to(warstwy[order_layer_name])

                # Dodaj trasy na podstawie segmentów dziennych
                for day_idx, day in enumerate(daily_segments):
                    color = colors[day_idx]

                    # Dodaj marker początku dnia
                    if day["segments"]:
                        first_segment = day["segments"][0]
                        start_loc = matrix_data["locations"][first_segment[0]]
                        folium.CircleMarker(
                            location=[start_loc["latitude"], start_loc["longitude"]],
                            radius=20,  # Zwiększony o 30% z 15
                            color=color,
                            fill=False,  # Pusty środek
                            weight=3,  # Grubsza linia obrysu
                            popup=f"Początek dnia {day_idx+1}",
                            tooltip=f"Początek dnia {day_idx+1}",
                        ).add_to(
                            start_day_warstwy[algo_name]
                        )  # Używamy właściwej warstwy dla algorytmu

                    for segment in day["segments"]:
                        from_idx, to_idx = segment
                        from_loc = matrix_data["locations"][from_idx]
                        to_loc = matrix_data["locations"][to_idx]

                        # Pobierz szczegóły trasy
                        route_key = (from_idx, to_idx)
                        polyline_coords = matrix_data["routes"].get(route_key)
                        segment_distance = matrix_data["distances"].get(route_key, 0)

                        # Jeśli mamy szczegóły trasy, rysujemy po drogach
                        if polyline_coords:
                            # Zamień kolejność współrzędnych dla folium (lat, lng)
                            folium_coords = [(lat, lng) for lat, lng in polyline_coords]

                            # Dodaj linię trasy
                            tooltip = f"{algo_name} - Dzień {day_idx+1}: {int(segment_distance)} km"

                            folium.PolyLine(
                                folium_coords,
                                color=color,
                                weight=4,
                                opacity=0.8,
                                tooltip=tooltip,
                            ).add_to(warstwy[layer_name])
                        else:
                            # Jeśli brak szczegółów, rysujemy linię prostą
                            tooltip = f"{algo_name} - Dzień {day_idx+1}: {int(segment_distance)} km (linia prosta)"

                            folium.PolyLine(
                                [
                                    (from_loc["latitude"], from_loc["longitude"]),
                                    (to_loc["latitude"], to_loc["longitude"]),
                                ],
                                color=color,
                                weight=4,
                                opacity=0.8,
                                tooltip=tooltip,
                                dash_array="10, 10",
                            ).add_to(warstwy[layer_name])

        # Dodanie kontrolki warstw
        folium.LayerControl().add_to(mapa)

        # Zapisanie mapy do pliku HTML
        mapa.save(html_file)

        # Tworzymy drugi plik tylko dla tras
        if show_route:
            mapa_trasy = folium.Map(location=[avg_lat, avg_lng], zoom_start=7)

            # Dodajemy tylko warstwę lokalizacji i warstwy tras
            lokalizacje_warstwa = folium.FeatureGroup(name="Lokalizacje")

            # Warstwy dla algorytmów
            trasy_warstwy = {}
            order_warstwy = {}
            start_day_warstwy = {}
            for algo_name in all_routes_data["algorithms"]:
                is_best = algo_name == all_routes_data["best_algorithm_name"]
                trasy_warstwy[algo_name] = folium.FeatureGroup(
                    name=f"Trasa - {algo_name}", show=is_best
                )
                order_warstwy[algo_name] = folium.FeatureGroup(
                    name=f"Kolejność - {algo_name}", show=is_best
                )
                start_day_warstwy[algo_name] = folium.FeatureGroup(
                    name=f"Początek dnia - {algo_name}", show=is_best
                )
                # Dodaj warstwy do mapy od razu po utworzeniu
                mapa_trasy.add_child(trasy_warstwy[algo_name])
                mapa_trasy.add_child(order_warstwy[algo_name])
                mapa_trasy.add_child(start_day_warstwy[algo_name])

            # Dodaj markery lokalizacji
            for item in valid_locations:
                folium.Marker(
                    location=[item["latitude"], item["longitude"]],
                    popup=f"<b>{item.get('Miasto', '')}</b><br>#{item.get('numer', '')}",
                    tooltip=item.get("Miasto", ""),
                ).add_to(lokalizacje_warstwa)

            # Dodaj trasy i numery kolejności dla każdego algorytmu
            for algo_name, algo_data in all_routes_data["algorithms"].items():
                daily_segments = algo_data["daily_segments"]
                path = algo_data["path"]
                colors = generuj_kolory_dla_dni(len(daily_segments), algo_name)

                # Przygotuj informacje o kolejności punktów i przynależności do dni
                day_for_point, order_for_point = przygotuj_etykiety_kolejnosci(
                    path, daily_segments
                )

                # Dodaj markery z informacją o kolejności i dniu
                for i, idx in enumerate(path):
                    if (
                        idx == 0 and i == len(path) - 1
                    ):  # Pomijamy ostatni punkt (ten sam co początkowy)
                        continue

                    loc = matrix_data["locations"][idx]
                    day_num = day_for_point.get(idx, "?")
                    order_num = order_for_point.get(idx, i)

                    # Tworzymy etykietę z dniem i kolejnością
                    order_label = f"D{day_num}-{order_num:02d}"

                    # Użyj koloru odpowiadającego danemu dniowi
                    algo_key = algo_name_mapping.get(algo_name, "default")
                    colors = ALGORITHM_COLORS[algo_key]
                    # Dzień jest 1-based, więc odejmujemy 1 aby dostać indeks
                    day_idx = day_num - 1
                    # Jeśli mamy więcej dni niż kolorów, używamy modulo
                    color = colors[day_idx % len(colors)]

                    # Utwórz marker z numerem dnia i kolejnością
                    folium.map.Marker(
                        [loc["latitude"], loc["longitude"]],
                        icon=folium.DivIcon(
                            icon_size=(60, 30),
                            icon_anchor=(30, 15),
                            html=f"""
                            <div style="
                                background-color: {color}; 
                                color: white; 
                                border-radius: 5px; 
                                text-align: center; 
                                font-weight: bold; 
                                padding: 2px 5px;
                                font-size: 10px;
                                opacity: 0.8;
                            ">
                                {order_label}
                            </div>
                            """,
                        ),
                        tooltip=f"{algo_name}: Dzień {day_num}, Punkt {order_num}",
                    ).add_to(order_warstwy[algo_name])

                # Dodaj trasy
                for day_idx, day in enumerate(daily_segments):
                    color = colors[day_idx]

                    for segment in day["segments"]:
                        from_idx, to_idx = segment
                        from_loc = matrix_data["locations"][from_idx]
                        to_loc = matrix_data["locations"][to_idx]

                        route_key = (from_idx, to_idx)
                        polyline_coords = matrix_data["routes"].get(route_key)
                        segment_distance = matrix_data["distances"].get(route_key, 0)

                        if polyline_coords:
                            folium_coords = [(lat, lng) for lat, lng in polyline_coords]
                            tooltip = f"{algo_name} - Dzień {day_idx+1}: {int(segment_distance)} km"

                            folium.PolyLine(
                                folium_coords,
                                color=color,
                                weight=4,
                                opacity=0.8,
                                tooltip=tooltip,
                            ).add_to(trasy_warstwy[algo_name])
                        else:
                            tooltip = f"{algo_name} - Dzień {day_idx+1}: {int(segment_distance)} km (linia prosta)"

                            folium.PolyLine(
                                [
                                    (from_loc["latitude"], from_loc["longitude"]),
                                    (to_loc["latitude"], to_loc["longitude"]),
                                ],
                                color=color,
                                weight=4,
                                opacity=0.8,
                                tooltip=tooltip,
                                dash_array="10, 10",
                            ).add_to(trasy_warstwy[algo_name])

                    # Dodaj marker początku dnia
                    if day["segments"]:
                        first_segment = day["segments"][0]
                        start_loc = matrix_data["locations"][first_segment[0]]
                        folium.CircleMarker(
                            location=[start_loc["latitude"], start_loc["longitude"]],
                            radius=20,  # Zwiększony o 30% z 15
                            color=color,
                            fill=False,  # Pusty środek
                            weight=3,  # Grubsza linia obrysu
                            popup=f"Początek dnia {day_idx+1}",
                            tooltip=f"Początek dnia {day_idx+1}",
                        ).add_to(
                            start_day_warstwy[algo_name]
                        )  # Używamy właściwej warstwy dla algorytmu

            # Dodaj warstwy do mapy
            lokalizacje_warstwa.add_to(mapa_trasy)
            for algo_name, warstwa in trasy_warstwy.items():
                warstwa.add_to(mapa_trasy)
            for algo_name, warstwa in order_warstwy.items():
                warstwa.add_to(mapa_trasy)
            for algo_name, warstwa in start_day_warstwy.items():
                warstwa.add_to(mapa_trasy)

            # Dodaj kontrolkę warstw
            folium.LayerControl().add_to(mapa_trasy)

            # Dodaj tę samą legendę
            mapa_trasy.get_root().html.add_child(folium.Element(legend_html))

            # Zapisz drugą mapę
            mapa_trasy.save(os.path.join("__out", "mapa_wszystkich_tras.html"))
            print(
                "Wygenerowano mapę ze wszystkimi trasami: __out/mapa_wszystkich_tras.html"
            )

        print(f"Mapa główna została wygenerowana i zapisana jako {html_file}")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas generowania mapy: {str(e)}")
        traceback.print_exc()
        return False


def inicjalizuj_nan_wartosci(json_file):
    """
    Inicjalizuje wartości NaN w pliku JSON na None, aby poprawnie je rozpoznawać

    Args:
        json_file (str): Ścieżka do pliku JSON

    Returns:
        bool: True jeśli operacja się powiodła, False w przeciwnym przypadku
    """
    try:
        # Wczytanie danych
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Zamiana NaN na None
        for item in data:
            if "latitude" in item and (
                pd.isna(item["latitude"]) or str(item["latitude"]).lower() == "nan"
            ):
                item["latitude"] = None
            if "longitude" in item and (
                pd.isna(item["longitude"]) or str(item["longitude"]).lower() == "nan"
            ):
                item["longitude"] = None

        # Zapis danych
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"Zainicjalizowano wartości NaN w pliku {json_file}")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas inicjalizacji wartości NaN: {str(e)}")
        return False


def sprawdz_status_serwisu_geolokalizacji():
    """
    Sprawdza dostępność serwisu geolokalizacji przez testowe zapytanie

    Returns:
        bool: True jeśli serwis jest dostępny, False w przeciwnym przypadku
    """
    try:
        geolocator = Nominatim(user_agent="test_service")
        location = geolocator.geocode("Warszawa, Polska", timeout=10)
        if location:
            print("Serwis geolokalizacji jest dostępny.")
            return True
        else:
            print("Serwis geolokalizacji zwrócił pusty wynik dla testu.")
            return False
    except Exception as e:
        print(f"Serwis geolokalizacji jest niedostępny: {str(e)}")
        return False


def update_json_with_numbers(json_file_path):
    """
    Aktualizuje plik JSON dodając numerację do każdego wpisu.
    Jeśli plik nie istnieje, tworzy nowy z danymi z Excela.

    Args:
        json_file_path (str): Ścieżka do pliku JSON
    """
    try:
        # Sprawdź czy plik istnieje, jeśli nie - utwórz nowy z Excela
        if not os.path.exists(json_file_path):
            print(f"Plik {json_file_path} nie istnieje! Tworzę nowy z Excela...")
            excel_file = "Tabela.xlsx"

            if not os.path.exists(excel_file):
                print(f"Błąd: Plik Excel {excel_file} nie istnieje!")
                return False

            # Wczytaj dane z Excela
            df = pd.read_excel(excel_file)
            data = df.to_dict(orient="records")

            # Zapisz dane do JSON
            with open(json_file_path, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
            print(f"Utworzono nowy plik {json_file_path} z danymi z Excela")

        # Wczytaj dane z pliku JSON
        with open(json_file_path, "r", encoding="utf-8") as file:
            data = json.load(file)

        # Dodaj numerację do każdego wpisu
        for i, entry in enumerate(data, 1):
            entry["numer"] = i

        # Zapisz zaktualizowane dane z powrotem do pliku
        with open(json_file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)

        print(f"Pomyślnie zaktualizowano plik {json_file_path} z numeracją")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas aktualizacji pliku: {str(e)}")
        return False


def popraw_wspolrzedne_dla_lokalizacji(json_file):
    """
    Sprawdza i poprawia przypadki, gdy wiele lokalizacji ma identyczne współrzędne

    Args:
        json_file (str): Ścieżka do pliku JSON

    Returns:
        bool: True jeśli operacja się powiodła, False w przeciwnym przypadku
    """
    try:
        # Wczytanie danych z JSON
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Sprawdź, czy występują duplikaty współrzędnych
        coords_count = {}
        for item in data:
            if (
                "latitude" in item
                and "longitude" in item
                and item["latitude"] is not None
                and item["longitude"] is not None
            ):
                coord_key = f"{item['latitude']},{item['longitude']}"
                if coord_key in coords_count:
                    coords_count[coord_key].append(item["pełny_adres"])
                else:
                    coords_count[coord_key] = [item["pełny_adres"]]

        # Znajdź duplikaty
        duplicates = {k: v for k, v in coords_count.items() if len(v) > 1}

        if not duplicates:
            print("Nie znaleziono zduplikowanych współrzędnych.")
            return True

        print(f"Znaleziono {len(duplicates)} zestawów zduplikowanych współrzędnych.")
        for coords, addresses in duplicates.items():
            print(
                f"Współrzędne {coords} są używane przez {len(addresses)} lokalizacji:"
            )
            for addr in addresses:
                print(f"  - {addr}")

        # Próba poprawy duplikatów - wymuś ponowną geolokalizację
        poprawione = 0
        for i, item in enumerate(data):
            if "pełny_adres" in item and "latitude" in item and "longitude" in item:
                coord_key = f"{item['latitude']},{item['longitude']}"
                if (
                    coord_key in duplicates
                    and duplicates[coord_key].index(item["pełny_adres"]) > 0
                ):
                    print(f"Próba poprawy współrzędnych dla: {item['pełny_adres']}")
                    # Wymuszamy bardzo dokładny adres
                    miasto = item.get("Miasto", "").strip()
                    ulica = item.get("Adres", "").strip()
                    kod = item.get("Kod pocztowy", "").strip()

                    dokladny_adres = f"{ulica}, {kod} {miasto}, Polska"
                    latitude, longitude = geolokalizuj_adres(
                        dokladny_adres, max_retries=5, delay=2
                    )

                    if (
                        latitude is not None
                        and longitude is not None
                        and f"{latitude},{longitude}" != coord_key
                    ):
                        item["latitude"] = latitude
                        item["longitude"] = longitude
                        poprawione += 1
                        print(f"Poprawiono współrzędne dla: {item['pełny_adres']}")
                    else:
                        # Jeśli nie udało się znaleźć nowych współrzędnych, dodaj małe przesunięcie
                        # aby były widoczne na mapie (tylko do celów wizualizacji)
                        item["latitude"] = float(item["latitude"]) + (
                            0.002 * (duplicates[coord_key].index(item["pełny_adres"]))
                        )
                        item["longitude"] = float(item["longitude"]) + (
                            0.002 * (duplicates[coord_key].index(item["pełny_adres"]))
                        )
                        poprawione += 1
                        print(f"Dodano przesunięcie dla: {item['pełny_adres']}")

                    # Zapisuj częściowe wyniki co 3 poprawki
                    if poprawione % 3 == 0:
                        with open(json_file, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                        print(
                            f"Zapisano częściowe wyniki. Poprawiono {poprawione} adresów."
                        )

                    # Opóźnienie dla API
                    time.sleep(2)

        # Zapis zaktualizowanych danych do pliku JSON
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(
            f"Zakończono poprawianie zduplikowanych współrzędnych. Poprawiono {poprawione} adresów."
        )
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas poprawiania współrzędnych: {str(e)}")
        return False


def popraw_format_adresow(json_file):
    """
    Poprawia format adresów w pliku JSON i przygotowuje je do geolokalizacji

    Args:
        json_file (str): Ścieżka do pliku JSON

    Returns:
        bool: True jeśli operacja się powiodła
    """
    try:
        # Wczytanie danych
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Poprawianie każdego rekordu
        for item in data:
            miasto = item.get("Miasto", "").strip()
            adres = item.get("Adres", "").strip()
            kod = item.get("Kod pocztowy", "").strip()

            # Dokładniejsze przetwarzanie adresu
            # Usunięcie zbędnych spacji
            adres = " ".join(adres.split())

            # Poprawna standardyzacja ulicy
            if adres.startswith("Ul."):
                adres = adres.replace("Ul.", "ul.")
            elif adres.startswith("UL."):
                adres = adres.replace("UL.", "ul.")
            elif adres.startswith("Ulica"):
                adres = adres.replace("Ulica", "ul.")
            elif adres.startswith("ULICA"):
                adres = adres.replace("ULICA", "ul.")

            # Wyciągnięcie numeru domu i ulicy
            ulica_parts = adres.split(" ")
            numer_domu = ulica_parts[-1] if len(ulica_parts) > 1 else ""
            nazwa_ulicy = " ".join(ulica_parts[:-1]) if len(ulica_parts) > 1 else adres

            # Formatowanie z prefiksem ul. tylko jeśli nie ma go jeszcze
            if not (
                nazwa_ulicy.startswith("ul.")
                or nazwa_ulicy.startswith("al.")
                or nazwa_ulicy.startswith("pl.")
            ):
                nazwa_ulicy = "ul. " + nazwa_ulicy

            # Dodanie separatora między ulicą a numerem
            poprawny_adres = f"{nazwa_ulicy} {numer_domu}, {kod} {miasto}, Polska"

            # Usunięcie podwójnych spacji
            poprawny_adres = " ".join(poprawny_adres.split())

            item["adres_do_geolokalizacji"] = poprawny_adres

            print(f"Przygotowano adres: {poprawny_adres}")

        # Zapisanie zaktualizowanych danych
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"Poprawiono format adresów w pliku {json_file}")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas poprawiania adresów: {str(e)}")
        return False


def geolokalizuj_pojedynczy_adres(adres):
    """
    Wykonuje jednorazową geolokalizację adresu z większą dokładnością

    Args:
        adres (str): Adres do geolokalizacji

    Returns:
        tuple: (latitude, longitude) lub (None, None)
    """
    try:
        geolocator = Nominatim(user_agent="jednorazowa_dokladna_geolokalizacja")
        print(f"Geolokalizacja adresu: {adres}")

        # Wydłużony timeout dla pojedynczego zapytania
        time.sleep(1)  # Małe opóźnienie przed zapytaniem

        # Zwiększenie parametrów dokładności
        location = geolocator.geocode(
            adres,
            timeout=20,
            exactly_one=True,
            addressdetails=True,
            language="pl",  # Używamy polskiego języka
        )

        if location:
            print(f"Znaleziono lokalizację: {location.address}")
            print(f"Współrzędne: {location.latitude}, {location.longitude}")

            # Sprawdzenie czy adres zawiera numer budynku
            if any(char.isdigit() for char in adres):
                # Mamy numer budynku, więc powinniśmy otrzymać dokładny wynik
                return location.latitude, location.longitude
            else:
                # Dodatkowe sprawdzenie przy adresach bez numeru
                print(
                    "Uwaga: Adres nie zawiera numeru budynku, "
                    "dokładność może być mniejsza."
                )
                return location.latitude, location.longitude
        else:
            print(f"Nie znaleziono lokalizacji dla adresu: {adres}")

            # Spróbuj alternatywny format adresu
            alt_adres = adres.replace("ul.", "").replace(",", "")
            print(f"Próba z alternatywnym formatem adresu: {alt_adres}")
            time.sleep(1.5)
            alt_location = geolocator.geocode(alt_adres, timeout=20, language="pl")

            if alt_location:
                print(
                    f"Znaleziono lokalizację z alternatywnym formatem: "
                    f"{alt_location.address}"
                )
                return alt_location.latitude, alt_location.longitude

            return None, None

    except Exception as e:
        print(f"Błąd podczas geolokalizacji: {str(e)}")
        return None, None


def uzupelnij_wspolrzedne_jednorazowo(json_file):
    """
    Uzupełnia współrzędne dla wszystkich adresów w pliku JSON
    z większą dokładnością

    Args:
        json_file (str): Ścieżka do pliku JSON

    Returns:
        bool: True jeśli operacja się powiodła
    """
    try:
        # Wczytanie danych
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Licznik przetworzonych adresów
        processed = 0

        # Najpierw sortujemy lokalizacje, aby zacząć od adresów
        # z pełnymi danymi
        for item in sorted(
            data, key=lambda x: len(x.get("adres_do_geolokalizacji", "")), reverse=True
        ):
            if "adres_do_geolokalizacji" in item:
                # Sprawdzenie czy już mamy współrzędne
                if (
                    "latitude" not in item
                    or item["latitude"] is None
                    or pd.isna(item["latitude"])
                    or "longitude" not in item
                    or item["longitude"] is None
                    or pd.isna(item["longitude"])
                ):

                    # Wykonanie geolokalizacji
                    lat, lng = geolokalizuj_pojedynczy_adres(
                        item["adres_do_geolokalizacji"]
                    )

                    if lat is not None and lng is not None:
                        item["latitude"] = lat
                        item["longitude"] = lng
                        processed += 1
                        print(f"Uzupełniono współrzędne dla: {item['Miasto']}")
                    else:
                        # Jeśli nie udało się znaleźć współrzędnych,
                        # spróbuj sformułować adres inaczej
                        miasto = item.get("Miasto", "").strip()
                        ulica = item.get("Adres", "").strip()
                        kod = item.get("Kod pocztowy", "").strip()

                        alternatywny_adres = f"{ulica}, {miasto}, {kod}, Polska"
                        print(
                            f"Próba z alternatywnym formatem adresu: "
                            f"{alternatywny_adres}"
                        )

                        lat, lng = geolokalizuj_pojedynczy_adres(alternatywny_adres)

                        if lat is not None and lng is not None:
                            item["latitude"] = lat
                            item["longitude"] = lng
                            processed += 1
                            print(
                                f"Uzupełniono współrzędne dla "
                                f"alternatywnego adresu: {item['Miasto']}"
                            )
                        else:
                            # Jeśli nadal nie działa, spróbuj samo miasto
                            miasto_adres = f"{miasto}, Polska"
                            lat, lng = geolokalizuj_pojedynczy_adres(miasto_adres)

                            if lat is not None and lng is not None:
                                item["latitude"] = lat
                                item["longitude"] = lng
                                processed += 1
                                print(
                                    f"Uzupełniono współrzędne dla " f"miasta: {miasto}"
                                )

                    # Zapisywanie po każdym przetworzonym adresie
                    with open(json_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)

                    # Dłuższe opóźnienie dla API
                    time.sleep(2.5)
                else:
                    print(f"Adres już ma współrzędne: {item['Miasto']}")

        print(f"Uzupełniono współrzędne dla {processed} adresów")
        return True

    except Exception as e:
        print(f"Wystąpił błąd podczas uzupełniania współrzędnych: {str(e)}")
        return False


def pobierz_trase(start_lat, start_lng, end_lat, end_lng, cached_routes=None):
    """
    Pobiera trasę między dwoma punktami używając API OSRM z ulepszonym cachowaniem

    Args:
        start_lat (float): Szerokość geograficzna punktu początkowego
        start_lng (float): Długość geograficzna punktu początkowego
        end_lat (float): Szerokość geograficzna punktu końcowego
        end_lng (float): Długość geograficzna punktu końcowego
        cached_routes (dict, optional): Słownik przechowujący zapisane trasy

    Returns:
        tuple: (polyline_coords, distance_km) lub (None, None) w przypadku błędu
    """
    import threading

    # Mutex do synchronizacji dostępu do cache'u
    if not hasattr(pobierz_trase, "lock"):
        pobierz_trase.lock = threading.Lock()

    if cached_routes is None:
        cached_routes = {}

    cache_key = f"{start_lat},{start_lng}|{end_lat},{end_lng}"
    reverse_key = f"{end_lat},{end_lng}|{start_lat},{start_lng}"

    # Sprawdź, czy trasa jest w cache (w dowolnym kierunku)
    with pobierz_trase.lock:
        if cache_key in cached_routes:
            return cached_routes[cache_key]
        elif reverse_key in cached_routes:
            # Dla wielu dróg trasa w obie strony jest taka sama
            polyline_coords, distance_km = cached_routes[reverse_key]
            if polyline_coords:
                # Odwracamy kolejność punktów dla przeciwnego kierunku
                reversed_coords = polyline_coords[::-1]
                cached_routes[cache_key] = (reversed_coords, distance_km)
                return reversed_coords, distance_km

    try:
        # Używamy API OSRM do wyznaczania trasy z retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"http://router.project-osrm.org/route/v1/driving/{start_lng},{start_lat};{end_lng},{end_lat}?overview=full&geometries=polyline"
                response = requests.get(url, timeout=30)
                data = response.json()

                if (
                    response.status_code == 200
                    and "routes" in data
                    and len(data["routes"]) > 0
                ):
                    break

                print(f"Powtarzam zapytanie ({attempt+1}/{max_retries})...")
                time.sleep(2)  # Opóźnienie przed ponowną próbą
            except Exception as e:
                print(f"Błąd zapytania ({attempt+1}/{max_retries}): {str(e)}")
                time.sleep(2)
                if attempt == max_retries - 1:
                    raise

        if (
            response.status_code != 200
            or "routes" not in data
            or len(data["routes"]) == 0
        ):
            print(f"Błąd API: {data.get('message', 'Nieznany błąd')}")
            return None, None

        # Pobranie współrzędnych trasy i dystansu
        encoded_polyline = data["routes"][0]["geometry"]
        distance_km = (
            data["routes"][0]["distance"] / 1000
        )  # konwersja z metrów na kilometry

        # Dekodowanie polyline do listy współrzędnych
        polyline_coords = polyline.decode(encoded_polyline)

        # Zapisz trasę w cache (w obu kierunkach)
        with pobierz_trase.lock:
            cached_routes[cache_key] = (polyline_coords, distance_km)
            cached_routes[reverse_key] = (polyline_coords[::-1], distance_km)

        print(f"Pobrano trasę: {distance_km:.1f} km")
        return polyline_coords, distance_km

    except Exception as e:
        print(f"Błąd pobierania trasy: {str(e)}")
        return None, None


def oblicz_macierz_odleglosci(
    locations,
    start_location,
    cache_file="cache/cached_routes.pkl",
    num_threads=8,
    offline_mode=False,
    force_recalculate=False,
):
    """
    Wykorzystuje istniejący cache tras do natychmiastowego stworzenia matrycy odległości
    """
    import hashlib
    import json

    from core.cache_manager import CacheManager

    # Inicjalizacja cache managera
    cache_manager = CacheManager(
        cache_dir="cache",
        routes_file="cached_routes.pkl",
        matrix_file="distance_matrix.pkl",
    )

    # Przygotowanie lokalizacji
    all_locations = [start_location] + locations
    n = len(all_locations)

    # Generowanie klucza cache na podstawie lokalizacji
    def generate_matrix_key(locations_list):
        loc_coords = sorted(
            [
                (loc.get("latitude", 0), loc.get("longitude", 0))
                for loc in locations_list
            ]
        )
        loc_str = json.dumps(loc_coords)
        matrix_key = hashlib.sha256(loc_str.encode()).hexdigest()
        return matrix_key

    # Wygeneruj klucz dla matrycy
    matrix_key = generate_matrix_key(all_locations)

    # Sprawdź czy matryca istnieje w cache
    cached_matrix = cache_manager.get_matrix_entry(matrix_key)
    if cached_matrix and not force_recalculate:
        print(
            f"Znaleziono gotową matrycę odległości w cache (klucz: {matrix_key[:8]}...)"
        )
        return cached_matrix["data"]

    # W trybie offline, jeśli nie ma matrycy w cache, zwracamy błąd
    if offline_mode:
        if cached_matrix:
            print("Używam matrycy z cache w trybie offline.")
            return cached_matrix["data"]
        else:
            raise Exception(
                "Błąd: Brak matrycy odległości w cache, a aplikacja jest w trybie offline. Uruchom w trybie online aby pobrać dane."
            )

    print(
        f"Tworzę matrycę odległości z istniejącego cache tras (klucz: {matrix_key[:8]}...)..."
    )

    # Inicjalizuj struktury danych
    distance_matrix = {}
    routes_data = {}
    brakujace_trasy = 0

    # Stwórz macierz bezpośrednio z istniejącego cache
    for i in range(n):
        for j in range(n):
            if i != j:
                loc_i = all_locations[i]
                loc_j = all_locations[j]

                # Pobierz trasę bezpośrednio z cache
                polyline_coords, distance_km = cache_manager.get_route(
                    loc_i["latitude"],
                    loc_i["longitude"],
                    loc_j["latitude"],
                    loc_j["longitude"],
                )

                if polyline_coords is not None or distance_km is not None:
                    # Trasa znaleziona w cache
                    key = (i, j)
                    distance_matrix[key] = distance_km
                    routes_data[key] = polyline_coords
                else:
                    # Trasa nie znaleziona - tylko obliczam tę jedną brakującą
                    brakujace_trasy += 1
                    print(
                        f"Brak trasy w cache: {loc_i.get('Miasto', 'Start')} → {loc_j.get('Miasto', 'Start')}"
                    )

                    polyline_coords, distance_km = pobierz_trase(
                        loc_i["latitude"],
                        loc_i["longitude"],
                        loc_j["latitude"],
                        loc_j["longitude"],
                    )

                    if polyline_coords is not None and distance_km is not None:
                        # Dodaj do cache i do matrycy
                        cache_manager.add_route(
                            loc_i["latitude"],
                            loc_i["longitude"],
                            loc_j["latitude"],
                            loc_j["longitude"],
                            polyline_coords,
                            distance_km,
                        )

                        key = (i, j)
                        distance_matrix[key] = distance_km
                        routes_data[key] = polyline_coords
                    else:
                        # Nie udało się pobrać trasy
                        print(
                            f"BŁĄD: Nie udało się pobrać trasy {loc_i.get('Miasto', 'Start')} → {loc_j.get('Miasto', 'Start')}"
                        )

    # Przygotuj dane matrycy
    matrix_data = {
        "distances": distance_matrix,
        "routes": routes_data,
        "locations": all_locations,
    }

    # Zapisz matrycę do cache
    print(
        f"Zapisuję nową matrycę do cache (obliczono tylko {brakujace_trasy} brakujących tras)"
    )
    cache_manager.add_matrix_entry(matrix_key, matrix_data)

    return matrix_data


def znajdz_najkrotsza_trase_tsp(
    matrix_data, max_daily_distance=1000, num_threads=8, force_recalculate=False
):
    """
    Znajduje najkrótszą trasę TSP z wykorzystaniem wielowątkowości i cache'owania.
    Umożliwia zapisywanie i odtwarzanie stanu obliczeń.

    Args:
        matrix_data (dict): Macierz odległości między lokalizacjami
        max_daily_distance (float): Maksymalna dzienna odległość
        num_threads (int): Liczba wątków do przetwarzania równoległego (domyślnie 8)
        force_recalculate (bool): Czy wymusić ponowne obliczenie tras

    Returns:
        dict: Wyniki dla wszystkich algorytmów oraz informacja o najlepszym
    """
    import hashlib
    import json
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime

    from core.cache_manager import CacheManager

    # Inicjalizacja menedżera cache
    cache_manager = CacheManager(
        cache_dir="cache",
        routes_file="cached_routes.pkl",
        matrix_file="distance_matrix.pkl",
    )

    distances = matrix_data["distances"]
    locations = matrix_data["locations"]
    n = len(locations)

    # Generowanie klucza cache dla wyników TSP
    def generate_tsp_key():
        # Bierzemy pod uwagę macierz odległości i max_daily_distance
        matrix_str = json.dumps(
            sorted([(f"{k[0]},{k[1]}", v) for k, v in distances.items()])
        )
        tsp_data = f"{matrix_str}|{max_daily_distance}|{n}"
        tsp_key = hashlib.sha256(tsp_data.encode()).hexdigest()
        return tsp_key

    # Sprawdź czy mamy już obliczenia w cache, chyba że wymuszono przeliczenie
    tsp_key = generate_tsp_key()
    tsp_cache_file = f"cache/tsp_results_{tsp_key[:8]}.json"

    if not force_recalculate and os.path.exists(tsp_cache_file):
        try:
            print(f"Znaleziono zapisane wyniki TSP w cache (klucz: {tsp_key[:8]})")
            with open(tsp_cache_file, "r", encoding="utf-8") as f:
                cached_results = json.load(f)
            return cached_results
        except Exception as e:
            print(f"Błąd podczas ładowania cache TSP: {str(e)}")

    print(f"Brak wyników TSP w cache lub wymuszono przeliczenie (klucz: {tsp_key[:8]})")

    # 1. Algorytm zachłanny (Nearest Neighbor)
    def nearest_neighbor():
        print("Uruchamiam algorytm najbliższego sąsiada...")
        path = [0]  # Startujemy z lokalizacji 0 (Nadarzyn)
        unvisited = set(range(1, n))
        total_distance = 0

        while unvisited:
            current = path[-1]
            nearest = min(
                unvisited, key=lambda x: distances.get((current, x), float("inf"))
            )

            distance = distances.get((current, nearest), float("inf"))
            total_distance += distance

            path.append(nearest)
            unvisited.remove(nearest)

        # Dodaj powrót do punktu początkowego
        return_distance = distances.get((path[-1], 0), float("inf"))
        total_distance += return_distance
        path.append(0)

        return path, total_distance

    # 2. Algorytm 2-opt (poprawa rozwiązania zachłannego) - wersja wielowątkowa
    def two_opt(path, total_distance):
        print("Uruchamiam algorytm 2-opt dla poprawy rozwiązania...")
        improved = True
        best_distance = total_distance
        best_path = path.copy()
        path_lock = threading.Lock()

        # Mierzenie czasu wykonania
        start_time = time.time()
        iteration_count = 0

        # Równoległy 2-opt na segmentach trasy
        def process_segment(start_i, end_i, current_path, current_best_distance):
            local_best_distance = current_best_distance
            local_best_path = current_path.copy()
            local_improved = False
            local_iterations = 0

            for i in range(start_i, min(end_i, len(current_path) - 2)):
                for j in range(i + 1, len(current_path) - 1):
                    local_iterations += 1
                    # Oblicz zmianę odległości przy zamianie krawędzi
                    a, b = current_path[i - 1], current_path[i]
                    c, d = current_path[j], current_path[j + 1]

                    current_distance = distances.get((a, b), 0) + distances.get(
                        (c, d), 0
                    )
                    new_distance = distances.get((a, c), 0) + distances.get((b, d), 0)

                    if new_distance < current_distance:
                        # Tworzymy nową ścieżkę z zamianą
                        new_path = current_path.copy()
                        new_path[i : j + 1] = reversed(new_path[i : j + 1])

                        # Oblicz nowy całkowity dystans
                        new_total = 0
                        for k in range(len(new_path) - 1):
                            new_total += distances.get(
                                (new_path[k], new_path[k + 1]), 0
                            )

                        if new_total < local_best_distance:
                            local_best_distance = new_total
                            local_best_path = new_path.copy()
                            local_improved = True

            return (
                local_improved,
                local_best_path,
                local_best_distance,
                local_iterations,
            )

        # Iteracyjne ulepszanie z wielowątkowością
        while improved:
            improved = False
            iteration_count += 1

            # Wyświetl postęp co 5 iteracji
            if iteration_count % 5 == 0:
                elapsed = time.time() - start_time
                print(
                    f"2-opt: iteracja {iteration_count}, czas: {elapsed:.2f}s, dystans: {best_distance:.2f} km"
                )

            # Podziel zakres iteracji na segmenty dla wątków
            segment_size = max(1, (len(path) - 3) // num_threads)
            segments = [
                (i, min(i + segment_size, len(path) - 2))
                for i in range(1, len(path) - 2, segment_size)
            ]

            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [
                    executor.submit(process_segment, start, end, path, best_distance)
                    for start, end in segments
                ]

                total_local_iterations = 0
                for future in futures:
                    local_improved, local_path, local_distance, local_iterations = (
                        future.result()
                    )
                    total_local_iterations += local_iterations

                    if local_improved and local_distance < best_distance:
                        with path_lock:
                            best_distance = local_distance
                            best_path = local_path.copy()
                            path = local_path.copy()
                            improved = True
                            print(
                                f"Znaleziono lepsze rozwiązanie: {best_distance:.2f} km"
                            )

            # Jeśli długo nie ma poprawy (ponad 20 iteracji), kończymy
            if iteration_count > 20 and not improved:
                print(
                    f"Przerwano optymalizację po {iteration_count} iteracjach bez poprawy"
                )
                break

        total_time = time.time() - start_time
        print(
            f"Zakończono 2-opt po {iteration_count} iteracjach, czas: {total_time:.2f}s"
        )
        return best_path, best_distance

    # 3. Algorytm przybliżony oparty na MST (Minimum Spanning Tree)
    def mst_approx():
        print("Uruchamiam algorytm oparty na MST...")
        start_time = time.time()

        # Tworzenie grafu
        G = nx.Graph()
        for i in range(n):
            for j in range(i + 1, n):
                dist = distances.get((i, j), float("inf"))
                G.add_edge(i, j, weight=dist)

        # Znajdź MST
        mst = nx.minimum_spanning_tree(G)

        # Wykonaj przejście DFS po MST
        path = list(nx.dfs_preorder_nodes(mst, source=0))
        path.append(0)  # Powrót do początku

        # Oblicz całkowity dystans
        total_distance = 0
        for i in range(len(path) - 1):
            total_distance += distances.get((path[i], path[i + 1]), float("inf"))

        total_time = time.time() - start_time
        print(f"Zakończono MST w {total_time:.2f}s")
        return path, total_distance

    # Uruchom algorytmy równolegle z pomiarem czasu
    start_total_time = time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        print("Uruchamiam algorytmy równolegle...")
        nn_future = executor.submit(nearest_neighbor)
        # MST można uruchomić od razu
        mst_future = executor.submit(mst_approx)

        # Czekaj na nearest_neighbor i potem uruchom 2-opt
        nn_path, nn_distance = nn_future.result()
        nn_time = time.time() - start_total_time
        print(
            f"Algorytm najbliższego sąsiada zakończony: {nn_distance:.2f} km, czas: {nn_time:.2f}s"
        )

        opt_start_time = time.time()
        opt_future = executor.submit(two_opt, nn_path.copy(), nn_distance)

        # Pobierz pozostałe wyniki
        opt_path, opt_distance = opt_future.result()
        opt_time = time.time() - opt_start_time
        print(
            f"Algorytm 2-opt zakończony: {opt_distance:.2f} km, czas: {opt_time:.2f}s"
        )

        mst_path, mst_distance = mst_future.result()
        mst_time = time.time() - start_total_time
        print(f"Algorytm MST zakończony: {mst_distance:.2f} km, czas: {mst_time:.2f}s")

    # Dodaj podział tras na dni
    print("Dzielę trasy na dni...")

    # Wyniki dla wszystkich algorytmów
    algorithms = {
        "Najbliższy sąsiad": {
            "path": nn_path.copy(),
            "distance": nn_distance,
            "time": nn_time,
            "daily_segments": podziel_trase_na_dni(
                nn_path, distances, max_daily_distance
            ),
        },
        "Najbliższy sąsiad + 2-opt": {
            "path": opt_path.copy(),
            "distance": opt_distance,
            "time": opt_time + nn_time,  # Całkowity czas to NN + 2-opt
            "daily_segments": podziel_trase_na_dni(
                opt_path, distances, max_daily_distance
            ),
        },
        "MST": {
            "path": mst_path.copy(),
            "distance": mst_distance,
            "time": mst_time,
            "daily_segments": podziel_trase_na_dni(
                mst_path, distances, max_daily_distance
            ),
        },
    }

    # Znajdź najlepszy algorytm
    best_algorithm_name = min(
        algorithms.keys(), key=lambda x: algorithms[x]["distance"]
    )
    best_algorithm = algorithms[best_algorithm_name]

    print(
        f"Najlepszy algorytm: {best_algorithm_name}, dystans: {best_algorithm['distance']:.2f} km"
    )

    # Przygotuj wyniki do zapisania
    results = {
        "algorithms": algorithms,
        "best_algorithm_name": best_algorithm_name,
        "best_algorithm": best_algorithm,
        "metadata": {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "max_daily_distance": max_daily_distance,
            "num_threads": num_threads,
            "locations_count": n,
            "matrix_key": tsp_key,
            "total_execution_time": time.time() - start_total_time,
        },
    }

    # Zapisz wyniki do cache
    try:
        os.makedirs("cache", exist_ok=True)
        with open(tsp_cache_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Zapisano wyniki TSP do cache: {tsp_cache_file}")
    except Exception as e:
        print(f"Błąd podczas zapisywania cache TSP: {str(e)}")

    # Zwróć wszystkie algorytmy oraz informację o najlepszym
    return results


def generuj_kolory_dla_dni(num_days, algorithm_name="default"):
    """
    Generuje listę kolorów dla dni trasy, używając predefiniowanych palet z config.py

    Args:
        num_days (int): Liczba dni
        algorithm_name (str): Nazwa algorytmu, dla którego generujemy kolory

    Returns:
        list: Lista kolorów w formacie hex
    """
    # Pobierz paletę kolorów dla danego algorytmu lub użyj domyślnej
    colors = ALGORITHM_COLORS.get(algorithm_name, ALGORITHM_COLORS["default"])

    # Jeśli potrzebujemy więcej kolorów niż jest w palecie, powtarzamy kolory
    if num_days > len(colors):
        colors = colors * (num_days // len(colors) + 1)

    # Zwróć tylko tyle kolorów, ile jest dni
    return colors[:num_days]


def podziel_trase_na_dni(path, distances, max_daily_distance):
    """
    Dzieli trasę na segmenty dzienne według maksymalnej odległości dziennej

    Args:
        path (list): Ścieżka z punktami trasy
        distances (dict): Słownik z odległościami między punktami
        max_daily_distance (float): Maksymalna dzienna odległość

    Returns:
        list: Lista słowników z segmentami dziennymi
    """
    daily_segments = []
    current_day = []
    current_distance = 0

    for i in range(len(path) - 1):
        from_idx = path[i]
        to_idx = path[i + 1]

        segment_distance = distances.get((from_idx, to_idx), 0)

        # Sprawdź, czy dodanie tego segmentu nie przekroczy dziennego limitu
        if current_distance + segment_distance <= max_daily_distance:
            current_day.append((from_idx, to_idx))
            current_distance += segment_distance
        else:
            # Zapisz obecny dzień i rozpocznij nowy
            daily_segments.append(
                {"segments": current_day, "distance": current_distance}
            )

            current_day = [(from_idx, to_idx)]
            current_distance = segment_distance

    # Dodaj ostatni dzień
    if current_day:
        daily_segments.append({"segments": current_day, "distance": current_distance})

    return daily_segments


def sprawdz_dostepnosc_serwerow_osrm():
    """
    Sprawdza dostępność różnych serwerów OSRM równolegle z poprawionymi adresami URL

    Returns:
        list: Lista działających serwerów OSRM
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Poprawiona lista serwerów z protokołem HTTPS
    osrm_servers = [
        "https://routing.openstreetmap.de",  # używamy tylko HTTPS
        "https://router.project-osrm.org",  # zmieniono na HTTPS
    ]

    dzialajace_serwery = []
    czas_odpowiedzi = {}

    print("Sprawdzanie dostępności serwerów OSRM (równolegle)...")

    def check_server(server):
        try:
            start_time = time.time()
            # Poprawione zapytanie zgodne z API OSRM
            response = requests.get(
                f"{server}/route/v1/driving/21.017532,52.237049;21.017532,52.237049?overview=full",
                timeout=20,  # zwiększony timeout
            )
            end_time = time.time()

            if response.status_code == 200:
                try:
                    data = response.json()
                    if "routes" in data:
                        czas_odpowiedzi[server] = end_time - start_time
                        print(f"Serwer {server} działa poprawnie.")
                        return server
                except Exception as e:
                    print(f"Błąd parsowania odpowiedzi z serwera {server}: {str(e)}")
            else:
                print(f"Serwer {server} zwrócił kod błędu: {response.status_code}")
            return None
        except Exception as e:
            print(f"Błąd sprawdzania serwera {server}: {str(e)}")
            return None

    with ThreadPoolExecutor(max_workers=len(osrm_servers)) as executor:
        futures = {
            executor.submit(check_server, server): server for server in osrm_servers
        }

        for future in as_completed(futures):
            server = future.result()
            if server:
                dzialajace_serwery.append(server)

    # Sortuj serwery według czasu odpowiedzi
    dzialajace_serwery.sort(key=lambda x: czas_odpowiedzi.get(x, float("inf")))

    print(f"Znaleziono {len(dzialajace_serwery)} działających serwerów OSRM")
    for server in dzialajace_serwery:
        print(f"Serwer {server}: {czas_odpowiedzi[server]:.2f}s")

    # Jeśli nie znaleziono działających serwerów, dodaj domyślny niezawodny
    if not dzialajace_serwery:
        print("Nie znaleziono działających serwerów. Używam awaryjnego serwera.")
        dzialajace_serwery = ["https://routing.openstreetmap.de"]

    return dzialajace_serwery


def ustaw_serwery_osrm(serwery):
    """
    Aktualizuje listę serwerów OSRM w pliku konfiguracyjnym.

    Args:
        serwery (list): Lista działających serwerów OSRM

    Returns:
        bool: True jeśli operacja się powiodła
    """
    try:
        # Importujemy moduł config
        import config

        # Ustawiamy nową listę serwerów
        config.OSRM_SERVERS = serwery

        print(f"Zaktualizowano listę serwerów OSRM: {serwery}")
        return True
    except Exception as e:
        print(f"Wystąpił błąd podczas aktualizacji listy serwerów: {str(e)}")
        return False


def odświeżaj_serwery_osrm(interval=300):
    """
    Uruchamia wątek okresowo sprawdzający dostępność serwerów OSRM.

    Args:
        interval (int): Interwał czasu między sprawdzeniami w sekundach
    """
    import threading
    import time

    def sprawdzaj_okresowo():
        while True:
            try:
                print("\nPeriodyczne sprawdzanie dostępności serwerów OSRM...")
                dzialajace_serwery = sprawdz_dostepnosc_serwerow_osrm()

                if dzialajace_serwery:
                    ustaw_serwery_osrm(dzialajace_serwery)

                # Czekaj określony czas przed kolejnym sprawdzeniem
                time.sleep(interval)
            except Exception as e:
                print(f"Błąd w wątku odświeżania serwerów: {str(e)}")
                time.sleep(interval)

    # Uruchom wątek w tle
    refresh_thread = threading.Thread(target=sprawdzaj_okresowo, daemon=True)
    refresh_thread.start()

    return refresh_thread


def sprawdz_i_utworz_json(json_file_path, excel_file_path="Tabela.xlsx"):
    """
    Sprawdza czy plik JSON istnieje, a jeśli nie - tworzy go z pliku Excel.

    Args:
        json_file_path (str): Ścieżka do pliku JSON
        excel_file_path (str): Ścieżka do pliku Excel

    Returns:
        bool: True jeśli plik istnieje lub został pomyślnie utworzony
    """
    if os.path.exists(json_file_path):
        print(f"Plik JSON {json_file_path} już istnieje.")
        return True

    if not os.path.exists(excel_file_path):
        print(f"Błąd: Plik Excel {excel_file_path} nie istnieje!")
        return False

    print(f"Plik JSON {json_file_path} nie istnieje. Tworzę go z pliku Excel...")
    if excel_to_json(excel_file_path, json_file_path):
        print(f"Pomyślnie utworzono plik JSON: {json_file_path}")

        # Dodaj numerację
        update_json_with_numbers(json_file_path)

        # Uzupełnij dane geolokalizacyjne
        inicjalizuj_nan_wartosci(json_file_path)
        popraw_format_adresow(json_file_path)
        uzupelnij_geolokalizacje(json_file_path)

        return True
    else:
        print(f"Nie udało się utworzyć pliku JSON.")
        return False


def verify_and_cleanup_cache(json_file_path="Tabela.json", offline_mode=False):
    """
    Weryfikuje poprawność plików cache i czyści niepotrzebne pliki.
    W trybie offline sprawdza dodatkowo, czy cache jest wystarczający do działania.

    Args:
        json_file_path (str): Ścieżka do pliku JSON z lokalizacjami
        offline_mode (bool): Czy aplikacja działa w trybie offline

    Returns:
        tuple: (is_valid, cleanup_count) - czy cache jest poprawny i ilość usuniętych plików
    """
    from core.cache_manager import CacheManager

    print("Weryfikacja i porządkowanie plików cache...")

    # Inicjalizacja menedżera cache
    cache_manager = CacheManager(
        cache_dir="cache",
        routes_file="cached_routes.pkl",
        matrix_file="distance_matrix.pkl",
    )

    # Weryfikacja integralności cache
    is_valid = cache_manager.verify_cache_integrity(json_file_path)

    # W trybie offline, jeśli cache nie jest poprawny, aplikacja nie może działać
    if offline_mode and not is_valid:
        raise Exception(
            "Błąd: Cache jest niepoprawny lub niekompletny, a aplikacja jest w trybie offline. "
            "Uruchom w trybie online aby pobrać dane."
        )

    # Czyszczenie katalogu cache
    cleanup_count = cache_manager.cleanup_cache_directory()

    if is_valid:
        print(
            f"Cache zweryfikowany poprawnie. Usunięto {cleanup_count} niepotrzebnych plików."
        )
    else:
        print("Cache wymaga ponownego obliczenia. Niekompletny lub niezgodny z danymi.")

    return is_valid, cleanup_count


if __name__ == "__main__":
    # Parsowanie argumentów wiersza poleceń
    parser = argparse.ArgumentParser(description="Generator map tras z optymalizacją.")
    parser.add_argument(
        "--json_file", default="Tabela.json", help="Ścieżka do pliku JSON z danymi"
    )
    parser.add_argument(
        "--excel_file",
        default="Tabela.xlsx",
        help="Ścieżka do pliku Excel z danymi źródłowymi",
    )
    parser.add_argument(
        "--html_file",
        default=os.path.join("__out", "index.html"),
        help="Ścieżka do pliku HTML wyjściowego",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Liczba wątków do przetwarzania równoległego",
    )
    parser.add_argument(
        "--no-route", action="store_true", help="Nie pokazuj tras na mapie"
    )
    parser.add_argument(
        "--force-recalculate", action="store_true", help="Wymuś ponowne obliczenia tras"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Uruchom w trybie offline (tylko z cache)",
    )

    args = parser.parse_args()

    # Ścieżki do plików
    json_file = args.json_file
    excel_file = args.excel_file
    html_file = args.html_file
    threads = args.threads
    show_route = not args.no_route
    force_recalculate = args.force_recalculate
    offline_mode = args.offline

    try:
        # 1. Sprawdź czy plik JSON istnieje, jeśli nie - utwórz go z Excela
        if not sprawdz_i_utworz_json(json_file, excel_file):
            print(
                "Nie udało się utworzyć lub zweryfikować pliku JSON. Kończę działanie."
            )
            exit(1)

        # 2. Weryfikacja i czyszczenie cache
        try:
            cache_valid, cleaned_files = verify_and_cleanup_cache(
                json_file, offline_mode
            )

            # Jeśli wymuszono przeliczenie lub cache jest niepoprawny (ale nie w trybie offline)
            if force_recalculate or (not cache_valid and not offline_mode):
                print("Wymuszono ponowne obliczenie tras lub cache jest niepoprawny.")
                # Flaga wskazująca, że trzeba przeliczać trasy
                need_recalculation = True
            else:
                need_recalculation = False
                print("Cache jest poprawny. Można użyć zapisanych tras.")
        except Exception as e:
            # W trybie offline, jeśli cache jest niepoprawny, kończymy
            if offline_mode:
                print(f"BŁĄD KRYTYCZNY: {str(e)}")
                print(
                    "Aplikacja wymaga poprawnego cache w trybie offline. Kończę działanie."
                )
                exit(1)
            else:
                print(f"Ostrzeżenie: {str(e)}")
                print("Kontynuuję z pobraniem danych online.")
                need_recalculation = True

        # Jeśli jesteśmy w trybie offline, nie sprawdzaj serwerów OSRM
        if offline_mode:
            print("Uruchomiono w trybie offline. Używam tylko danych z cache.")
        else:
            # Sprawdź dostępność serwerów OSRM (równolegle)
            dzialajace_serwery = sprawdz_dostepnosc_serwerow_osrm()

            # Jeśli znaleziono działające serwery, ustaw je w kolejności od najszybszego
            if dzialajace_serwery:
                print(f"Ustawiam serwery OSRM w kolejności: {dzialajace_serwery}")
                ustaw_serwery_osrm(dzialajace_serwery)
            else:
                # Jeśli nie znaleziono działających serwerów, a cache jest poprawny, przejdź w tryb offline
                if cache_valid:
                    print(
                        "Nie znaleziono działających serwerów OSRM. Przełączam w tryb offline z użyciem cache."
                    )
                    offline_mode = True
                else:
                    print(
                        "BŁĄD KRYTYCZNY: Nie znaleziono działających serwerów OSRM, a cache jest niepoprawny."
                    )
                    print(
                        "Aplikacja nie może działać bez jednego z tych źródeł danych. Kończę działanie."
                    )
                    exit(1)

            # Jeśli jesteśmy w trybie online, uruchom wątek odświeżający listę serwerów
            if not offline_mode:
                odświeżaj_serwery_osrm(interval=300)

        # Generuj mapę
        print("\n--- Generowanie mapy ---")
        generuj_mape_wielowarstwowa(
            json_file,
            html_file,
            show_route,
            offline_mode=offline_mode,
            force_recalculate=need_recalculation,
        )

        # Wykonaj końcowe czyszczenie katalogu cache
        from core.cache_manager import CacheManager

        cache_manager = CacheManager()
        cleaned = cache_manager.cleanup_cache_directory()
        print(f"Zakończono porządkowanie katalogu cache. Usunięto {cleaned} plików.")

        print("\nZakończono generowanie mapy. Pliki HTML zapisano w folderze __out/")

    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {str(e)}")
        traceback.print_exc()
        exit(1)
