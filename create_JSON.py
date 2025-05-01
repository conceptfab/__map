import json
import os
import time
import traceback

import folium
import pandas as pd
from geopy.distance import geodesic
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim


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
        # NOWE WARIANTY:
        f"{adres}, województwo {_wykryj_wojewodztwo(adres)}, Polska",  # Dodanie województwa
        f"{adres}, powiat {_wykryj_powiat(adres)}, Polska",  # Dodanie powiatu
        _formatuj_adres_openstreetmap(adres),  # Format OSM
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
                    variant,
                    timeout=30,  # Zwiększony timeout
                    exactly_one=True,
                    addressdetails=True,
                    language="pl",  # Dodanie języka polskiego
                    country_codes="pl",  # Ograniczenie do Polski
                )

                if location:
                    print(f"Znaleziono lokalizację: {location.address}")
                    # Sprawdzenie pewności wyniku
                    if hasattr(location, "raw") and "importance" in location.raw:
                        importance = location.raw["importance"]
                        print(f"Pewność wyniku: {importance}")
                        # Jeśli pewność jest zbyt niska, kontynuuj szukanie
                        if importance < 0.5:
                            print("Zbyt niska pewność wyniku, szukam dalej...")
                            continue
                    return location.latitude, location.longitude
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"Błąd geolokalizacji dla adresu {variant}: {str(e)}")
                time.sleep(delay * 2)  # Zwiększamy opóźnienie po błędzie
            except Exception as e:
                print(f"Niespodziewany błąd: {str(e)}")
                time.sleep(delay)

    print(f"Nie udało się znaleźć lokalizacji dla adresu: {adres}")
    return None, None


def _wykryj_wojewodztwo(adres):
    """Próba wykrycia województwa na podstawie adresu"""
    wojewodztwa = [
        "dolnośląskie",
        "kujawsko-pomorskie",
        "lubelskie",
        "lubuskie",
        "łódzkie",
        "małopolskie",
        "mazowieckie",
        "opolskie",
        "podkarpackie",
        "podlaskie",
        "pomorskie",
        "śląskie",
        "świętokrzyskie",
        "warmińsko-mazurskie",
        "wielkopolskie",
        "zachodniopomorskie",
    ]

    for woj in wojewodztwa:
        if woj.lower() in adres.lower():
            return woj
    return "mazowieckie"  # Domyślne województwo jeśli nie wykryto


def _wykryj_powiat(adres):
    """Próba wykrycia powiatu na podstawie większych miast"""
    miasta_powiaty = {
        "warszawa": "warszawski",
        "kraków": "krakowski",
        "łódź": "łódzki",
        "wrocław": "wrocławski",
        "poznań": "poznański",
        "gdańsk": "gdański",
        "szczecin": "szczeciński",
        "bydgoszcz": "bydgoski",
        "lublin": "lubelski",
        "białystok": "białostocki",
        "katowice": "katowicki",
    }

    for miasto, powiat in miasta_powiaty.items():
        if miasto.lower() in adres.lower():
            return powiat
    return ""  # Pusty string jeśli nie wykryto


def _formatuj_adres_openstreetmap(adres):
    """Formatuje adres w stylu preferowanym przez OpenStreetMap"""
    # Wyciągnięcie komponentów adresu
    komponenty = adres.split(",")
    if len(komponenty) >= 2:
        ulica_nr = komponenty[0].strip()
        miasto = komponenty[1].strip()

        # Sprawdzenie czy ulica zawiera numer
        if any(char.isdigit() for char in ulica_nr):
            # Spróbuj rozdzielić ulicę od numeru
            ostatnia_spacja = ulica_nr.rfind(" ")
            if ostatnia_spacja > 0:
                ulica = ulica_nr[:ostatnia_spacja].strip()
                numer = ulica_nr[ostatnia_spacja:].strip()
                return f"{numer}, {ulica}, {miasto}, Polska"

    # Jeśli nie udało się podzielić, zwróć oryginalny format
    return f"{adres}, Polska"


def excel_to_json(excel_file, json_file=None):
    """
    Konwertuje plik Excel na format JSON z geolokalizacją adresów

    Args:
        excel_file (str): Ścieżka do pliku Excel
        json_file (str, optional): Ścieżka do pliku wyjściowego JSON.
                                 Jeśli nie podano, użyje nazwy pliku Excel z rozszerzeniem .json
    """
    try:
        # Wczytanie pliku Excel
        df = pd.read_excel(excel_file)

        # Jeśli nie podano nazwy pliku wyjściowego, użyj nazwy pliku Excel
        if json_file is None:
            json_file = os.path.splitext(excel_file)[0] + ".json"

        # Sprawdź, czy plik JSON już istnieje i wczytaj go
        if os.path.exists(json_file):
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

        # Geolokalizacja adresów
        print("Rozpoczynam geolokalizację adresów...")
        geolokalizowane = 0

        for i, item in enumerate(data):
            if "pełny_adres" in item and (
                pd.isna(item.get("latitude")) or pd.isna(item.get("longitude"))
            ):
                latitude, longitude = geolokalizuj_adres(item["pełny_adres"])
                item["latitude"] = latitude
                item["longitude"] = longitude

                if latitude is not None and longitude is not None:
                    geolokalizowane += 1

                # Zapisuj co 10 rekordów lub na końcu
                if (i + 1) % 10 == 0 or i == len(data) - 1:
                    with open(json_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=4)
                    print(
                        f"Zapisano częściowe wyniki. Przetworzono {i+1}/{len(data)} adresów."
                    )

                # Dodaj opóźnienie, aby nie przeciążyć API
                time.sleep(1.5)  # Zwiększamy opóźnienie dla większej pewności

        # Zapis do pliku JSON (ostateczny)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(f"Pomyślnie przekonwertowano {excel_file} do {json_file}")
        print(f"Geolokalizowano {geolokalizowane} nowych adresów")

    except Exception as e:
        print(f"Wystąpił błąd: {str(e)}")
        return None


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


def generuj_mape_wielowarstwowa(json_file, html_file="index.html", show_route=False):
    """
    Generuje mapę HTML z wieloma warstwami informacji: lokalizacje, numery, adresy

    Args:
        json_file (str): Ścieżka do pliku JSON
        html_file (str): Ścieżka do wyjściowego pliku HTML
        show_route (bool): Czy wyświetlać warstwę z trasą (zawsze False)

    Returns:
        bool: True jeśli operacja się powiodła
    """
    try:
        # Wczytanie danych
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Filtrowanie lokalizacji z prawidłowymi współrzędnymi
        valid_locations = [
            item
            for item in data
            if all(
                key in item and item[key] is not None and not pd.isna(item[key])
                for key in ["latitude", "longitude"]
            )
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

        # Definicja warstw
        warstwy = {
            "Lokalizacje": folium.FeatureGroup(name="Lokalizacje", show=True),
            "Numery": folium.FeatureGroup(name="Numery", show=True),
            "Adresy": folium.FeatureGroup(name="Adresy", show=True),
        }

        # Dodanie wszystkich warstw do mapy
        for nazwa, warstwa in warstwy.items():
            warstwa.add_to(mapa)

        # Dodanie obiektów do poszczególnych warstw
        for item in valid_locations:
            # Warstwa: Lokalizacje
            popup_text = (
                f"<b>{item.get('Miasto', '')}</b><br>"
                f"Adres: {item.get('Adres', '')}<br>"
                f"Kod pocztowy: {item.get('Kod pocztowy', '')}<br>"
                f"Numer: {item.get('numer', '')}"
            )

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

            # Dodanie numeru jako tekstu
            numer_html = (
                '<div style="font-size: 10pt; color: white; '
                'text-align: center; font-weight: bold;">'
                f'{item.get("numer", "")}</div>'
            )

            folium.map.Marker(
                [item["latitude"], item["longitude"]],
                icon=folium.DivIcon(
                    icon_size=(20, 20), icon_anchor=(10, 10), html=numer_html
                ),
            ).add_to(warstwy["Numery"])

            # Warstwa: Adresy
            pelny_adres = item.get("pełny_adres", "")
            adres_html = (
                '<div style="font-size: 9pt; color: black; '
                "background-color: white; padding: 2px; "
                'border-radius: 3px; text-align: center;">'
                f"{pelny_adres}</div>"
            )

            folium.map.Marker(
                [item["latitude"], item["longitude"]],
                icon=folium.DivIcon(
                    icon_size=(200, 20), icon_anchor=(100, -20), html=adres_html
                ),
            ).add_to(warstwy["Adresy"])

        # Dodanie kontrolki warstw
        folium.LayerControl().add_to(mapa)

        # Zapisanie mapy do pliku HTML
        mapa.save(html_file)

        print(f"Mapa została wygenerowana i zapisana jako {html_file}")
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
        bool: True jeśli operacja się powiodła
    """
    try:
        # Wczytanie danych z JSON
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Sprawdź, czy występują duplikaty współrzędnych
        coords_count = {}
        for item in data:
            if all(
                key in item and item[key] is not None and not pd.isna(item[key])
                for key in ["latitude", "longitude"]
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

        # Próba poprawy duplikatów
        poprawione = 0
        for i, item in enumerate(data):
            if all(key in item for key in ["pełny_adres", "latitude", "longitude"]):
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
                        # Dodaj małe przesunięcie dla wizualizacji
                        index = duplicates[coord_key].index(item["pełny_adres"])
                        item["latitude"] = float(item["latitude"]) + (0.002 * index)
                        item["longitude"] = float(item["longitude"]) + (0.002 * index)
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

        # Zapis zaktualizowanych danych
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        print(
            f"Zakończono poprawianie zduplikowanych współrzędnych. "
            f"Poprawiono {poprawione} adresów."
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


if __name__ == "__main__":
    # Ścieżki do plików
    json_file = "Tabela.json"
    lokalizacje_html_file = "lokalizacje.html"  # Plik dla lokalizacji

    # Aktualizacja numeracji
    print("Aktualizacja numeracji w pliku JSON...")
    update_json_with_numbers(json_file)

    # Poprawienie formatu adresów (tylko jeśli potrzebne)
    if not all(
        "adres_do_geolokalizacji" in item
        for item in json.load(open(json_file, "r", encoding="utf-8"))
    ):
        print("Poprawianie formatu adresów...")
        popraw_format_adresow(json_file)

    # Uzupełnienie współrzędnych (tylko jeśli potrzebne)
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        brakujace_wspolrzedne = any(
            "latitude" not in item
            or item["latitude"] is None
            or pd.isna(item["latitude"])
            or "longitude" not in item
            or item["longitude"] is None
            or pd.isna(item["longitude"])
            for item in data
            if "adres_do_geolokalizacji" in item
        )

    if brakujace_wspolrzedne:
        print("Uzupełnianie współrzędnych geograficznych...")
        uzupelnij_wspolrzedne_jednorazowo(json_file)

    # Sprawdzenie, czy występują zduplikowane współrzędne
    print("Sprawdzanie zduplikowanych współrzędnych...")
    popraw_wspolrzedne_dla_lokalizacji(json_file)

    # Generowanie mapy lokalizacji
    print("Generowanie mapy lokalizacji...")
    generuj_mape_wielowarstwowa(json_file, lokalizacje_html_file, show_route=False)

    print("Zakończono przetwarzanie.")
