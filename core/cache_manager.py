import json
import os
import pickle
import tempfile
import threading
import time
from datetime import datetime


class CacheManager:
    """
    Klasa zarządzająca cachowaniem tras i matryc odległości, z zabezpieczeniami
    przed uszkodzeniem plików i wsparciem dla wielowątkowości.
    """

    def __init__(
        self,
        cache_dir="cache",
        routes_file="cached_routes.pkl",
        matrix_file="distance_matrix.pkl",
    ):
        """
        Inicjalizuje menedżera cache z ustawieniami ścieżek.

        Args:
            cache_dir (str): Katalog dla plików cache
            routes_file (str): Nazwa pliku dla cache tras
            matrix_file (str): Nazwa pliku dla cache matrycy odległości
        """
        self.cache_dir = cache_dir
        self.routes_file = os.path.join(cache_dir, routes_file)
        self.matrix_file = os.path.join(cache_dir, matrix_file)
        self.lock = threading.RLock()  # Reentrant lock dla bezpiecznego dostępu

        # Tworzenie katalogu cache jeśli nie istnieje
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

        # Inicjalizacja cache tras
        self.routes_cache = self.load_routes_cache()

        # Inicjalizacja cache matrycy odległości
        self.matrix_cache = self.load_matrix_cache()

        # Liczniki statystyk
        self.hits = 0
        self.misses = 0

    def load_routes_cache(self):
        """
        Ładuje dane cache tras z pliku.

        Returns:
            dict: Załadowane dane lub pusty słownik jeśli plik nie istnieje
        """
        try:
            if os.path.exists(self.routes_file):
                with open(self.routes_file, "rb") as f:
                    data = pickle.load(f)
                print(f"Załadowano {len(data)} tras z cache")
                return data
            return {}
        except Exception as e:
            print(f"Błąd podczas ładowania cache tras: {str(e)}")
            # Spróbuj załadować kopię zapasową
            return self._load_backup(self.routes_file)

    def load_matrix_cache(self):
        """
        Ładuje cache matrycy odległości z pliku.

        Returns:
            dict: Załadowana matryca lub pusty słownik jeśli plik nie istnieje
        """
        try:
            if os.path.exists(self.matrix_file):
                with open(self.matrix_file, "rb") as f:
                    data = pickle.load(f)
                print(f"Załadowano cache matrycy odległości z {len(data)} rekordami")
                return data
            return {}
        except Exception as e:
            print(f"Błąd podczas ładowania cache matrycy: {str(e)}")
            # Spróbuj załadować kopię zapasową
            return self._load_backup(self.matrix_file)

    def _load_backup(self, original_file):
        """
        Próbuje załadować najnowszą kopię zapasową pliku cache.

        Args:
            original_file (str): Ścieżka do oryginalnego pliku cache

        Returns:
            dict: Dane z backupu lub pusty słownik
        """
        try:
            # Znajdź wszystkie kopie zapasowe pliku
            base_name = os.path.basename(original_file)
            backup_files = [
                f
                for f in os.listdir(self.cache_dir)
                if f.startswith(base_name) and f.endswith(".bak")
            ]

            # Jeśli są kopie zapasowe, załaduj najnowszą
            if backup_files:
                # Sortuj według czasu utworzenia (timestamp w nazwie)
                backup_files.sort(reverse=True)
                newest_backup = os.path.join(self.cache_dir, backup_files[0])

                print(f"Próba odtworzenia z backupu: {newest_backup}")
                with open(newest_backup, "rb") as f:
                    data = pickle.load(f)

                # Odtwórz oryginalny plik
                with open(original_file, "wb") as f:
                    pickle.dump(data, f)

                print(f"Pomyślnie odtworzono dane z backupu")
                return data
        except Exception as e:
            print(f"Nie udało się odtworzyć z backupu: {str(e)}")

        return {}

    def save_routes_cache(self, force=False):
        """
        Bezpiecznie zapisuje aktualny stan cache tras do pliku.

        Args:
            force (bool): Czy wymusić zapis nawet jeśli nie ma zmian

        Returns:
            bool: True jeśli operacja się powiodła
        """
        with self.lock:
            return self._safe_save(self.routes_cache, self.routes_file)

    def save_matrix_cache(self, force=False):
        """
        Bezpiecznie zapisuje aktualny stan cache matrycy do pliku.

        Args:
            force (bool): Czy wymusić zapis nawet jeśli nie ma zmian

        Returns:
            bool: True jeśli operacja się powiodła
        """
        with self.lock:
            return self._safe_save(self.matrix_cache, self.matrix_file)

    def _safe_save(self, data, file_path):
        """
        Wykonuje bezpieczny zapis danych do pliku tylko jeśli dane się zmieniły.
        """
        try:
            # Sprawdź czy plik istnieje i czy dane się zmieniły
            if os.path.exists(file_path):
                try:
                    with open(file_path, "rb") as f:
                        existing_data = pickle.load(f)

                    # Jeśli dane są takie same, nie zapisuj ponownie
                    if existing_data == data:
                        print(f"Dane w {file_path} nie zmieniły się, pomijam zapis")
                        return True
                except Exception:
                    # Jeśli wystąpił błąd odczytu, kontynuuj z zapisem
                    pass

            # Utwórz plik tymczasowy w tym samym katalogu
            file_dir = os.path.dirname(file_path)
            file_name = os.path.basename(file_path)
            prefix = file_name.split(".")[0] + "_tmp_"
            suffix = "." + file_name.split(".")[-1]

            # Zapisz do pliku tymczasowego
            with tempfile.NamedTemporaryFile(
                delete=False, prefix=prefix, suffix=suffix, dir=file_dir
            ) as tmp_file:
                tmp_path = tmp_file.name
                pickle.dump(data, tmp_file)

            # Utwórz kopię zapasową istniejącego pliku (tylko raz dziennie)
            backup_file = None
            if os.path.exists(file_path):
                today = datetime.now().strftime("%Y%m%d")
                backup_file = f"{file_path}.{today}.bak"

                # Sprawdź czy backup z dzisiaj już istnieje
                if not os.path.exists(backup_file):
                    os.rename(file_path, backup_file)
                else:
                    # Jeśli backup już istnieje, usuń stary plik bez tworzenia kopii
                    os.remove(file_path)

            # Zmień nazwę pliku tymczasowego na docelową
            os.rename(tmp_path, file_path)

            print(f"Zapisano zaktualizowane dane do {file_path}")
            return True
        except Exception as e:
            print(f"Błąd podczas bezpiecznego zapisu cache: {str(e)}")
            return False

    def _cleanup_backups(self, base_file_path):
        """
        Ogranicza liczbę kopii zapasowych pliku do 5 najnowszych.

        Args:
            base_file_path (str): Podstawowa ścieżka pliku
        """
        try:
            dir_path = os.path.dirname(base_file_path)
            base_name = os.path.basename(base_file_path)

            # Znajdź wszystkie kopie zapasowe
            backup_files = [
                f
                for f in os.listdir(dir_path)
                if f.startswith(base_name) and f.endswith(".bak")
            ]

            # Posortuj wg timestampu (od najstarszych do najnowszych)
            backup_files.sort()

            # Usuń nadmiarowe kopie, zachowując 5 najnowszych
            if len(backup_files) > 5:
                for old_file in backup_files[:-5]:
                    old_path = os.path.join(dir_path, old_file)
                    try:
                        os.remove(old_path)
                        print(f"Usunięto starą kopię zapasową: {old_file}")
                    except Exception as e:
                        print(
                            f"Nie udało się usunąć kopii zapasowej {old_file}: {str(e)}"
                        )
        except Exception as e:
            print(f"Błąd podczas czyszczenia kopii zapasowych: {str(e)}")

    def get_route(self, start_lat, start_lng, end_lat, end_lng):
        """
        Pobiera trasę z cache, jeśli jest dostępna.

        Args:
            start_lat (float): Szerokość geograficzna punktu początkowego
            start_lng (float): Długość geograficzna punktu początkowego
            end_lat (float): Szerokość geograficzna punktu końcowego
            end_lng (float): Długość geograficzna punktu końcowego

        Returns:
            tuple: (polyline_coords, distance_km) lub (None, None) jeśli nie ma w cache
        """
        with self.lock:
            cache_key = f"{start_lat},{start_lng}|{end_lat},{end_lng}"
            reverse_key = f"{end_lat},{end_lng}|{start_lat},{start_lng}"

            # Sprawdzenie w cache
            if cache_key in self.routes_cache:
                self.hits += 1
                return self.routes_cache[cache_key]
            elif reverse_key in self.routes_cache:
                # Jeśli mamy trasę w przeciwną stronę, możemy ją odwrócić
                polyline_coords, distance_km = self.routes_cache[reverse_key]
                if polyline_coords:
                    # Odwracamy współrzędne dla przeciwnego kierunku
                    reversed_coords = polyline_coords[::-1]
                    # Zapisujemy do cache dla przyszłych zapytań
                    self.routes_cache[cache_key] = (reversed_coords, distance_km)
                    self.hits += 1
                    return reversed_coords, distance_km
                else:
                    # Jeśli to tylko odległość bez współrzędnych trasy
                    self.routes_cache[cache_key] = (None, distance_km)
                    self.hits += 1
                    return None, distance_km

            # Brak w cache
            self.misses += 1
            return None, None

    def add_route(
        self,
        start_lat,
        start_lng,
        end_lat,
        end_lng,
        polyline_coords,
        distance_km,
        auto_save=True,
    ):
        """
        Dodaje trasę do cache.

        Args:
            start_lat (float): Szerokość geograficzna punktu początkowego
            start_lng (float): Długość geograficzna punktu początkowego
            end_lat (float): Szerokość geograficzna punktu końcowego
            end_lng (float): Długość geograficzna punktu końcowego
            polyline_coords (list): Lista punktów trasy
            distance_km (float): Odległość w kilometrach
            auto_save (bool): Czy automatycznie zapisać cache po dodaniu

        Returns:
            bool: True jeśli operacja się powiodła
        """
        with self.lock:
            try:
                cache_key = f"{start_lat},{start_lng}|{end_lat},{end_lng}"
                reverse_key = f"{end_lat},{end_lng}|{start_lat},{start_lng}"

                # Zapisz trasę w obu kierunkach
                self.routes_cache[cache_key] = (polyline_coords, distance_km)

                # Dla trasy w przeciwnym kierunku odwracamy punkty
                if polyline_coords:
                    reversed_coords = polyline_coords[::-1]
                    self.routes_cache[reverse_key] = (reversed_coords, distance_km)
                else:
                    self.routes_cache[reverse_key] = (None, distance_km)

                # Automatycznie zapisz jeśli potrzeba
                if auto_save:
                    self.save_routes_cache()

                return True
            except Exception as e:
                print(f"Błąd podczas dodawania trasy do cache: {str(e)}")
                return False

    def get_matrix_entry(self, matrix_key):
        """
        Pobiera wpis matrycy odległości z cache.
        """
        with self.lock:
            if matrix_key in self.matrix_cache:
                self.hits += 1
                print(f"Znaleziono matrycę w cache (klucz: {matrix_key[:8]}...)")
                return self.matrix_cache[matrix_key]
            self.misses += 1
            print(f"Brak matrycy w cache (klucz: {matrix_key[:8]}...)")
            return None

    def add_matrix_entry(self, matrix_key, matrix_data, auto_save=True):
        """
        Dodaje wpis matrycy odległości do cache tylko jeśli jest nowy.
        """
        with self.lock:
            try:
                # Sprawdź czy matryca już istnieje
                if matrix_key in self.matrix_cache:
                    existing_data = self.matrix_cache[matrix_key].get("data")
                    if existing_data == matrix_data:
                        print(
                            f"Matryca już istnieje w cache (klucz: {matrix_key[:8]}...)"
                        )
                        return True

                # Zapisz z timestampem dla śledzenia aktualizacji
                entry = {
                    "data": matrix_data,
                    "timestamp": time.time(),
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self.matrix_cache[matrix_key] = entry

                # Automatycznie zapisz jeśli potrzeba
                if auto_save:
                    print(
                        f"Zapisuję nową matrycę do cache (klucz: {matrix_key[:8]}...)"
                    )
                    self.save_matrix_cache()

                return True
            except Exception as e:
                print(f"Błąd podczas dodawania matrycy do cache: {str(e)}")
                return False

    def get_cache_stats(self):
        """
        Zwraca statystyki wykorzystania cache.

        Returns:
            dict: Statystyki cache
        """
        total = self.hits + self.misses
        hit_rate = (self.hits / total) * 100 if total > 0 else 0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_rate": f"{hit_rate:.2f}%",
            "routes_cache_size": len(self.routes_cache),
            "matrix_cache_size": len(self.matrix_cache),
        }

    def generate_cache_report(self, output_file="cache_report.json"):
        """
        Generuje raport stanu cache i zapisuje go do pliku JSON.

        Args:
            output_file (str): Nazwa pliku raportu

        Returns:
            str: Ścieżka do zapisanego pliku
        """
        with self.lock:
            report = {
                "timestamp": time.time(),
                "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "stats": self.get_cache_stats(),
                "files": {
                    "routes_cache": {
                        "path": self.routes_file,
                        "size_bytes": (
                            os.path.getsize(self.routes_file)
                            if os.path.exists(self.routes_file)
                            else 0
                        ),
                        "entries": len(self.routes_cache),
                    },
                    "matrix_cache": {
                        "path": self.matrix_file,
                        "size_bytes": (
                            os.path.getsize(self.matrix_file)
                            if os.path.exists(self.matrix_file)
                            else 0
                        ),
                        "entries": len(self.matrix_cache),
                    },
                },
                "backups": self._get_backup_info(),
            }

            # Zapisz raport do pliku
            report_path = os.path.join(self.cache_dir, output_file)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4, ensure_ascii=False)

            return report_path

    def _get_backup_info(self):
        """
        Zbiera informacje o kopiach zapasowych.

        Returns:
            dict: Informacje o backupach
        """
        backups = {"routes": [], "matrix": []}

        try:
            # Znajdź backupy dla tras
            routes_base = os.path.basename(self.routes_file)
            for file in os.listdir(self.cache_dir):
                if file.startswith(routes_base) and file.endswith(".bak"):
                    file_path = os.path.join(self.cache_dir, file)
                    backups["routes"].append(
                        {
                            "filename": file,
                            "size_bytes": os.path.getsize(file_path),
                            "timestamp": os.path.getmtime(file_path),
                        }
                    )

            # Znajdź backupy dla matrycy
            matrix_base = os.path.basename(self.matrix_file)
            for file in os.listdir(self.cache_dir):
                if file.startswith(matrix_base) and file.endswith(".bak"):
                    file_path = os.path.join(self.cache_dir, file)
                    backups["matrix"].append(
                        {
                            "filename": file,
                            "size_bytes": os.path.getsize(file_path),
                            "timestamp": os.path.getmtime(file_path),
                        }
                    )

            # Posortuj backupy według czasu modyfikacji (od najnowszego)
            backups["routes"].sort(key=lambda x: x["timestamp"], reverse=True)
            backups["matrix"].sort(key=lambda x: x["timestamp"], reverse=True)

        except Exception as e:
            print(f"Błąd podczas pobierania informacji o backupach: {str(e)}")

        return backups

    def verify_cache_integrity(self, json_file_path):
        """
        Weryfikuje integralność plików cache przez porównanie z danymi z pliku JSON.

        Args:
            json_file_path (str): Ścieżka do pliku JSON z lokalizacjami

        Returns:
            bool: True jeśli cache jest poprawny, False w przeciwnym wypadku
        """
        try:
            # Sprawdź czy pliki cache istnieją
            routes_exists = os.path.exists(self.routes_file)
            matrix_exists = os.path.exists(self.matrix_file)

            if not routes_exists and not matrix_exists:
                print("Pliki cache nie istnieją. Potrzebne będzie ponowne obliczenie.")
                return False

            # Wczytaj dane JSON
            if not os.path.exists(json_file_path):
                print(f"Plik JSON {json_file_path} nie istnieje.")
                return False

            with open(json_file_path, "r", encoding="utf-8") as f:
                locations = json.load(f)

            # Sprawdź czy wszystkie lokalizacje mają współrzędne
            locations_with_coords = [
                loc
                for loc in locations
                if "latitude" in loc
                and "longitude" in loc
                and loc["latitude"] is not None
                and loc["longitude"] is not None
            ]

            # Jeśli cache istnieje, sprawdź jego zawartość
            if routes_exists:
                routes_size = os.path.getsize(self.routes_file)
                routes_count = len(self.routes_cache)

                # Oczekiwana minimalna liczba tras w cache
                expected_min_routes = len(locations_with_coords) * (
                    len(locations_with_coords) - 1
                )

                if (
                    routes_count < expected_min_routes / 4 or routes_size < 1024
                ):  # Przynajmniej 25% oczekiwanych tras
                    print(
                        f"Cache tras wydaje się niekompletny: {routes_count} tras, oczekiwano co najmniej {expected_min_routes/4}"
                    )
                    return False

            # Sprawdź integralność matrycy
            if matrix_exists and self.matrix_cache:
                # Sprawdź czy matryca zawiera wszystkie lokalizacje
                for entry in self.matrix_cache.values():
                    if "data" in entry and "locations" in entry["data"]:
                        cache_locations = entry["data"]["locations"]
                        if (
                            len(cache_locations) == len(locations_with_coords) + 1
                        ):  # +1 dla lokalizacji startowej
                            print(
                                "Matryca odległości zawiera prawidłową liczbę lokalizacji."
                            )
                            return True

                print("Matryca odległości nie zawiera wszystkich lokalizacji.")
                return False

            return True
        except Exception as e:
            print(f"Błąd podczas weryfikacji cache: {str(e)}")
            return False

    def cleanup_cache_directory(self):
        """
        Usuwa niepotrzebne pliki z katalogu cache, zachowując tylko najnowsze kopie zapasowe.

        Returns:
            int: Liczba usuniętych plików
        """
        import glob

        try:
            deleted_count = 0

            # Znajdź wszystkie pliki tymczasowe
            temp_files = glob.glob(os.path.join(self.cache_dir, "*_tmp_*"))
            for tmp_file in temp_files:
                try:
                    os.remove(tmp_file)
                    deleted_count += 1
                    print(f"Usunięto plik tymczasowy: {os.path.basename(tmp_file)}")
                except Exception as e:
                    print(
                        f"Nie udało się usunąć pliku tymczasowego {tmp_file}: {str(e)}"
                    )

            # Ogranicz liczbę kopii zapasowych dla każdego pliku podstawowego
            for base_file in [self.routes_file, self.matrix_file]:
                self._cleanup_backups(base_file)

            # Usuń stare pliki raportów, pozostawiając 3 najnowsze
            report_files = glob.glob(os.path.join(self.cache_dir, "cache_report*.json"))
            if len(report_files) > 3:
                # Sortuj według daty modyfikacji (od najstarszych)
                report_files.sort(key=os.path.getmtime)

                # Usuń nadmiarowe pliki
                for old_report in report_files[:-3]:
                    try:
                        os.remove(old_report)
                        deleted_count += 1
                        print(f"Usunięto stary raport: {os.path.basename(old_report)}")
                    except Exception as e:
                        print(f"Nie udało się usunąć raportu {old_report}: {str(e)}")

            # Usuń stare pliki wyników TSP, zachowując 5 najnowszych
            tsp_files = glob.glob(os.path.join(self.cache_dir, "tsp_results_*.json"))
            if len(tsp_files) > 5:
                # Sortuj według daty modyfikacji
                tsp_files.sort(key=os.path.getmtime)

                # Usuń nadmiarowe pliki
                for old_tsp in tsp_files[:-5]:
                    try:
                        os.remove(old_tsp)
                        deleted_count += 1
                        print(f"Usunięto stary wynik TSP: {os.path.basename(old_tsp)}")
                    except Exception as e:
                        print(f"Nie udało się usunąć wyniku TSP {old_tsp}: {str(e)}")

            return deleted_count
        except Exception as e:
            print(f"Błąd podczas czyszczenia katalogu cache: {str(e)}")
            return 0

    def print_cache_stats(self):
        """
        Wyświetla szczegółowe statystyki cache.
        """
        total = self.hits + self.misses
        hit_rate = (self.hits / total) * 100 if total > 0 else 0

        print("\n==== STATYSTYKI CACHE ====")
        print(f"Trafienia w cache: {self.hits}")
        print(f"Chybienia cache: {self.misses}")
        print(f"Łączne zapytania: {total}")
        print(f"Skuteczność cache: {hit_rate:.2f}%")
        print(f"Rozmiar cache tras: {len(self.routes_cache)} tras")
        print(f"Rozmiar cache matryc: {len(self.matrix_cache)} matryc")

        # Sprawdź rozmiar plików cache
        if os.path.exists(self.routes_file):
            routes_size = os.path.getsize(self.routes_file) / (1024 * 1024)
            print(f"Rozmiar pliku cache tras: {routes_size:.2f} MB")

        if os.path.exists(self.matrix_file):
            matrix_size = os.path.getsize(self.matrix_file) / (1024 * 1024)
            print(f"Rozmiar pliku cache matryc: {matrix_size:.2f} MB")

        print("==========================\n")
