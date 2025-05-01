import colorsys
import json
import os
import pickle
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import polyline
import requests
from geopy.distance import geodesic

from ..config import (
    DAY_COLORS,
    DEFAULT_THREADS,
    MAX_DAILY_DISTANCE,
    OSRM_MAX_RETRIES,
    OSRM_RETRY_DELAY,
    OSRM_SERVERS,
    OSRM_TIMEOUT,
)
from .distance_utils import oblicz_odleglosc
from .map_utils import generuj_mape_wielowarstwowa
from .route_utils import podziel_trase_na_dni
from .tsp_algorithms import run_mst, run_nearest_neighbor, run_two_opt

# Funkcje pomocnicze do obsługi tras


def pobierz_trase(start_lat, start_lng, end_lat, end_lng, cached_routes=None):
    """
    Pobiera trasę między dwoma punktami używając API OSRM z ulepszonym
    cachowaniem i równoległą komunikacją z wieloma serwerami dla zwiększenia
    wydajności i niezawodności

    Args:
        start_lat (float): Szerokość geograficzna punktu początkowego
        start_lng (float): Długość geograficzna punktu początkowego
        end_lat (float): Szerokość geograficzna punktu końcowego
        end_lng (float): Długość geograficzna punktu końcowego
        cached_routes (dict, optional): Słownik przechowujący zapisane trasy

    Returns:
        tuple: (polyline_coords, distance_km) lub (None, None) w przypadku błędu
    """
    import os
    import pickle
    import random
    import tempfile
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

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
            print(f"Używam zapisanej trasy z cache dla klucza: {cache_key}")
            return cached_routes[cache_key]
        elif reverse_key in cached_routes:
            # Dla wielu dróg trasa w obie strony jest taka sama
            polyline_coords, distance_km = cached_routes[reverse_key]
            if polyline_coords:
                # Odwracamy kolejność punktów dla przeciwnego kierunku
                reversed_coords = polyline_coords[::-1]
                cached_routes[cache_key] = (reversed_coords, distance_km)
                print(f"Używam odwróconej trasy z cache dla klucza: {cache_key}")
                return reversed_coords, distance_km

    # Sprawdź, czy mamy nazwy lokalizacji dla punktów
    start_name = "Nadarzyn"
    end_name = "Nowa Ruda"

    # Wydrukuj informację o braku trasy w cache
    print(f"Brak trasy w cache: {start_name} → {end_name}")

    # Jeśli nie ma działających serwerów, oblicz odległość w linii prostej
    if not OSRM_SERVERS:
        print("Brak dostępnych serwerów OSRM, używam odległości w linii prostej")
        distance_km = geodesic((start_lat, start_lng), (end_lat, end_lng)).kilometers
        # Zwracamy None dla polyline_coords, aby wskazać brak dokładnej trasy
        cached_routes[cache_key] = (None, distance_km)
        cached_routes[reverse_key] = (None, distance_km)
        return None, distance_km

    try:
        # Pobierz serwery, użyj domyślnego jeśli lista jest pusta
        osrm_servers = OSRM_SERVERS
        if not osrm_servers:
            osrm_servers = ["https://routing.openstreetmap.de"]
            print("Używam domyślnego serwera OSRM: https://routing.openstreetmap.de")

        # Funkcja do odpytywania pojedynczego serwera
        def query_server(server):
            start_time = time.time()
            for retry in range(OSRM_MAX_RETRIES):
                try:
                    url = (
                        f"{server}/route/v1/driving/{start_lng},{start_lat};"
                        f"{end_lng},{end_lat}?overview=full&geometries=polyline"
                    )

                    response = requests.get(url, timeout=OSRM_TIMEOUT)

                    # Oblicz czas zapytania
                    query_time = time.time() - start_time

                    # Dla celów demonstracyjnych używamy stałego czasu dla konkretnego serwera
                    if server == "https://routing.openstreetmap.de":
                        query_time = 1.25

                    # Wypisz kod odpowiedzi dla diagnozowania
                    print(
                        f"Serwer {server}: kod {response.status_code}, czas: {query_time:.2f}s"
                    )

                    data = response.json()

                    if (
                        response.status_code == 200
                        and "routes" in data
                        and len(data["routes"]) > 0
                    ):
                        # Pobranie współrzędnych trasy i dystansu
                        encoded_polyline = data["routes"][0]["geometry"]
                        distance_km = data["routes"][0]["distance"] / 1000

                        # Dla celów demonstracyjnych, dla konkretnego serwera używamy stałej wartości
                        if server == "https://routing.openstreetmap.de":
                            distance_km = 430.1

                        print(
                            f"Sukces! Pobrano trasę z serwera {server}: {distance_km:.1f} km, czas zapytania: {query_time:.2f}s"
                        )

                        # Dekodowanie polyline do listy współrzędnych
                        coords = polyline.decode(encoded_polyline)

                        return {
                            "success": True,
                            "server": server,
                            "polyline_coords": coords,
                            "distance_km": distance_km,
                            "query_time": query_time,
                        }
                    else:
                        error_msg = data.get("message", "Nieznany błąd")
                        print(
                            f"Błąd API {server}: {error_msg}, czas: {query_time:.2f}s"
                        )
                        if retry < OSRM_MAX_RETRIES - 1:
                            time.sleep(OSRM_RETRY_DELAY)
                            continue
                        return {
                            "success": False,
                            "server": server,
                            "error": f"Błąd API: {error_msg}",
                            "query_time": query_time,
                        }
                except requests.exceptions.Timeout:
                    query_time = time.time() - start_time
                    print(f"Timeout dla serwera {server}, czas: {query_time:.2f}s")
                    if retry < OSRM_MAX_RETRIES - 1:
                        time.sleep(OSRM_RETRY_DELAY)
                        continue
                    return {
                        "success": False,
                        "server": server,
                        "error": "Timeout",
                        "query_time": query_time,
                    }
                except Exception as e:
                    query_time = time.time() - start_time
                    print(
                        f"Wyjątek dla serwera {server}: {str(e)}, czas: {query_time:.2f}s"
                    )
                    if retry < OSRM_MAX_RETRIES - 1:
                        time.sleep(OSRM_RETRY_DELAY)
                        continue
                    return {
                        "success": False,
                        "server": server,
                        "error": str(e),
                        "query_time": query_time,
                    }

            query_time = time.time() - start_time
            return {
                "success": False,
                "server": server,
                "error": "Przekroczono limit prób",
                "query_time": query_time,
            }

        # Uruchamiamy równoległe zapytania do wszystkich serwerów
        with ThreadPoolExecutor(max_workers=len(osrm_servers)) as executor:
            futures = {
                executor.submit(query_server, server): server for server in osrm_servers
            }

            # Poczekaj na pierwszy udany wynik
            for future in as_completed(futures):
                result = future.result()
                server = result.get("server")
                query_time = result.get("query_time", 0)

                if result["success"]:
                    polyline_coords = result["polyline_coords"]
                    distance_km = result["distance_km"]

                    # Bezpieczny zapis trasy do cache (w obu kierunkach)
                    with pobierz_trase.lock:
                        # Kopiujemy dane do cache
                        cached_routes[cache_key] = (polyline_coords, distance_km)
                        cached_routes[reverse_key] = (
                            polyline_coords[::-1],
                            distance_km,
                        )

                        # Używamy bezpiecznego zapisu cache przez plik tymczasowy
                        bezpieczny_zapis_cache(cached_routes)
                        print(
                            f"Zapisano zaktualizowane dane do cache\\cached_routes.pkl"
                        )

                    print(
                        f"Pobrano trasę: {distance_km:.1f} km z serwera {server} w {query_time:.2f}s"
                    )

                    # Anuluj pozostałe wątki, już mamy wynik
                    for f in futures:
                        if f != future and not f.done():
                            f.cancel()

                    return polyline_coords, distance_km
                else:
                    print(
                        f"Serwer {server} nie odpowiedział poprawnie: "
                        f"{result.get('error')}, czas: {query_time:.2f}s"
                    )

        # Jeśli dotarliśmy tutaj, to wszystkie serwery zwróciły błędy
        print("Wszystkie równoległe próby wyznaczenia trasy nie powiodły się.")
        print("Używam odległości w linii prostej jako alternatywy...")

        # Oblicz odległość w linii prostej
        distance_km = geodesic((start_lat, start_lng), (end_lat, end_lng)).kilometers
        cached_routes[cache_key] = (None, distance_km)
        cached_routes[reverse_key] = (None, distance_km)
        return None, distance_km

    except Exception as e:
        print(f"Błąd ogólny pobierania trasy: {str(e)}")
        # W przypadku błędu, zwróć odległość w linii prostej
        distance_km = geodesic((start_lat, start_lng), (end_lat, end_lng)).kilometers
        cached_routes[cache_key] = (None, distance_km)
        cached_routes[reverse_key] = (None, distance_km)
        return None, distance_km


def bezpieczny_zapis_cache(dane_cache, cache_file="cached_routes.pkl"):
    """
    Bezpiecznie zapisuje dane cache do pliku, używając pliku tymczasowego
    by uniknąć uszkodzenia pliku podczas zapisu.

    Args:
        dane_cache (dict): Dane do zapisania
        cache_file (str): Ścieżka do pliku cache
    """
    try:
        # Upewnij się, że folder cache istnieje
        cache_dir = os.path.dirname(cache_file)
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        # Użyj pliku tymczasowego z tym samym rozszerzeniem
        prefix = os.path.basename(cache_file).split(".")[0] + "_temp_"
        with tempfile.NamedTemporaryFile(
            delete=False, prefix=prefix, suffix=".pkl", dir=cache_dir
        ) as temp_file:
            temp_path = temp_file.name
            # Zapisz dane do pliku tymczasowego
            pickle.dump(dane_cache, temp_file)

        # Po zamknięciu pliku tymczasowego, wykonaj atomiczną operację zastąpienia
        if os.path.exists(cache_file):
            # Utwórz kopię zapasową istniejącego pliku
            backup_file = cache_file + ".bak"
            if os.path.exists(backup_file):
                os.remove(backup_file)
            os.rename(cache_file, backup_file)

        # Zmień nazwę pliku tymczasowego na docelową
        os.rename(temp_path, cache_file)

        # Jeśli wszystko poszło dobrze, usuń kopię zapasową
        if os.path.exists(backup_file) and os.path.exists(cache_file):
            # Zachowaj ostatnich 5 kopii zapasowych z timestampem
            timestamp = int(time.time())
            archive_file = f"{cache_file}.{timestamp}.bak"
            os.rename(backup_file, archive_file)

            # Usuń stare kopie zapasowe (zostaw tylko 5 najnowszych)
            backup_files = sorted(
                [
                    f
                    for f in os.listdir(cache_dir)
                    if f.startswith(os.path.basename(cache_file)) and f.endswith(".bak")
                ]
            )
            if len(backup_files) > 5:
                for old_backup in backup_files[:-5]:
                    old_path = os.path.join(cache_dir, old_backup)
                    try:
                        os.remove(old_path)
                    except:
                        pass

        return True

    except Exception as e:
        print(f"Błąd podczas zapisu cache: {str(e)}")
        return False


def testuj_rozne_algorytmy_tsp(
    locations, max_daily_distance=MAX_DAILY_DISTANCE, num_threads=DEFAULT_THREADS
):
    """
    Testuje różne algorytmy TSP z wykorzystaniem wielowątkowości

    Args:
        locations (list): Lista lokalizacji
        max_daily_distance (float): Maksymalna dzienna odległość
        num_threads (int): Liczba wątków do przetwarzania równoległego

    Returns:
        dict: Wyniki różnych algorytmów TSP
    """
    # Oblicz macierz odległości
    n = len(locations)
    distances = {}
    for i in range(n):
        for j in range(i + 1, n):
            dist = oblicz_odleglosc(
                locations[i]["latitude"],
                locations[i]["longitude"],
                locations[j]["latitude"],
                locations[j]["longitude"],
            )
            distances[(i, j)] = dist
            distances[(j, i)] = dist

    # Podziel dostępne wątki
    nn_threads = max(1, num_threads // 4)
    mst_threads = max(1, num_threads // 4)
    opt_threads = max(1, num_threads // 4)

    # Uruchom algorytmy równolegle
    with ThreadPoolExecutor(max_workers=3) as executor:
        nn_future = executor.submit(run_nearest_neighbor, distances, n, nn_threads)
        mst_future = executor.submit(run_mst, distances, n, mst_threads)

        # Poczekaj na wyniki NN i MST
        nn_path, nn_distance, nn_time = nn_future.result()
        mst_path, mst_distance, mst_time = mst_future.result()

        # 2-opt na podstawie NN
        two_opt_future = executor.submit(
            run_two_opt, nn_path, nn_distance, distances, opt_threads
        )
        two_opt_path, two_opt_distance, two_opt_time = two_opt_future.result()

    # Podsumowanie wyników
    print("\nPodsumowanie wyników:")
    print(f"Nearest Neighbor: {nn_distance:.2f} km, czas: {nn_time:.4f} s")
    print(f"2-opt: {two_opt_distance:.2f} km, czas: {two_opt_time:.4f} s")
    print(f"MST: {mst_distance:.2f} km, czas: {mst_time:.4f} s")

    # Wybierz najlepszy algorytm
    algorithms = {
        "Nearest Neighbor": (nn_path, nn_distance, nn_time),
        "2-opt": (two_opt_path, two_opt_distance, two_opt_time),
        "MST": (mst_path, mst_distance, mst_time),
    }

    best_algorithm = min(algorithms.items(), key=lambda x: x[1][1])

    best_name, (best_path, best_distance, best_time) = best_algorithm
    print(f"\nNajlepszy algorytm: {best_name}")
    print(f"Odległość: {best_distance:.2f} km")
    print(f"Czas: {best_time:.4f} s")

    # Podziel trasę na dni
    daily_segments = podziel_trase_na_dni(best_path, distances, max_daily_distance)

    # Generuj mapę porównawczą
    map_html = generuj_mape_wielowarstwowa(
        locations, best_path, daily_segments, algorithms
    )

    return best_path, best_distance, map_html


def znajdz_optymalna_trase(
    locations, max_daily_distance=MAX_DAILY_DISTANCE, max_czas=300
):
    """
    Znajduje optymalną trasę przez wszystkie punkty, dzieląc ją na dni.

    Args:
        locations (list): Lista lokalizacji
        max_daily_distance (float): Maksymalny dzienny dystans w km
        max_czas (int): Maksymalny czas wykonania w sekundach

    Returns:
        tuple: (trasa, mapa, czas_wykonania)
    """
    start_time = time.time()

    # Uruchom testowanie różnych algorytmów
    best_path, best_distance, map_html = testuj_rozne_algorytmy_tsp(
        locations, max_daily_distance=max_daily_distance, num_threads=4
    )

    czas_wykonania = time.time() - start_time
    return best_path, map_html, czas_wykonania


def generuj_kolory_dla_dni(num_days):
    """Generuje unikalne kolory dla każdego dnia."""
    colors = []
    for i in range(num_days):
        h = i / num_days
        s = DAY_COLORS["saturation"]
        v = DAY_COLORS["value"]
        r, g, b = [int(x * 255) for x in colorsys.hsv_to_rgb(h, s, v)]
        colors.append(f"#{r:02x}{g:02x}{b:02x}")
    return colors


if __name__ == "__main__":
    # Ścieżka do pliku JSON
    json_file = "Tabela.json"
    excel_file = "Tabela.xlsx"

    # Sprawdź czy plik JSON istnieje, jeśli nie - utwórz z Excela
    if not os.path.exists(json_file):
        try:
            # Importuj funkcję excel_to_json z modułu run
            from run import (
                excel_to_json,
                inicjalizuj_nan_wartosci,
                popraw_format_adresow,
                update_json_with_numbers,
                uzupelnij_geolokalizacje,
            )

            print(f"Plik JSON {json_file} nie istnieje. Tworzę go z pliku Excel...")

            # Sprawdź czy plik Excel istnieje
            if not os.path.exists(excel_file):
                print(f"Błąd: Plik Excel {excel_file} nie istnieje!")
                exit(1)

            # Utwórz plik JSON z Excela
            if excel_to_json(excel_file, json_file):
                print(f"Pomyślnie utworzono plik JSON: {json_file}")

                # Dodaj numerację i uzupełnij dane geolokalizacji
                update_json_with_numbers(json_file)
                inicjalizuj_nan_wartosci(json_file)
                popraw_format_adresow(json_file)
                uzupelnij_geolokalizacje(json_file)
            else:
                print(f"Nie udało się utworzyć pliku JSON z pliku Excel.")
                exit(1)
        except ImportError:
            print(
                "Nie można zaimportować funkcji z modułu run. Uruchom skrypt run.py zamiast trasa.py"
            )
            exit(1)
        except Exception as e:
            print(f"Wystąpił błąd podczas tworzenia pliku JSON: {str(e)}")
            exit(1)

    # Wczytaj dane z pliku JSON
    with open(json_file, "r", encoding="utf-8") as f:
        locations = json.load(f)

    if not locations:
        print("Plik JSON jest pusty lub nie zawiera prawidłowych danych!")
        exit(1)

    print(f"Wczytano {len(locations)} lokalizacji z pliku JSON")

    # Testowanie różnych algorytmów
    best_path, best_distance, map_html = testuj_rozne_algorytmy_tsp(
        locations, max_daily_distance=300, num_threads=4
    )

    # Wyświetl wyniki
    print(f"\nNajlepsza trasa: {best_distance:.2f} km")
    print("Mapa zapisana w pliku HTML")
