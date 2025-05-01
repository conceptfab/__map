# Globalne ustawienia dla systemu planowania tras

# Ustawienia OSRM API z mechanizmem awaryjnym
OSRM_SERVERS = [
    "https://routing.openstreetmap.de",  # Używamy tylko HTTPS
    "https://router.project-osrm.org",  # Dodatkowy serwer
]

# Parametry zapytań OSRM
OSRM_TIMEOUT = 45  # Zwiększony timeout do 45 sekund
OSRM_MAX_RETRIES = 3  # Zwiększona liczba prób
OSRM_RETRY_DELAY = 2  # Zwiększone opóźnienie między próbami

# Awaryjne obliczanie odległości (gdy serwery niedostępne)
USE_DIRECT_DISTANCE_FALLBACK = True  # Pozwala na użycie odległości po linii prostej

# Ustawienia geolokalizacji
NOMINATIM_USER_AGENT = "my_route_planner"
GEOLOCATION_MAX_RETRIES = 5
GEOLOCATION_DELAY = 2

# Ustawienia TSP
MAX_DAILY_DISTANCE = 1000
DEFAULT_THREADS = 4

# Ustawienia cache
CACHE_FILE = "cached_routes.pkl"

# Ustawienia map
DEFAULT_MAP_FILE = "index.html"
ROUTES_MAP_FILE = "mapa_wszystkich_tras.html"

# Predefiniowane kolory dla każdego algorytmu (10 dni)
ALGORITHM_COLORS = {
    "nearest_neighbor": [  # Czerwono-żółta paleta
        "#FF0000",  # Czerwony
        "#FF8000",  # Pomarańczowy
        "#FFFF00",  # Żółty
        "#804000",  # Brązowy
        "#FF4000",  # Pomarańczowo-czerwony
        "#FFC000",  # Złoty
        "#FF6000",  # Ciemny pomarańczowy
        "#FFE000",  # Jasny żółty
        "#802000",  # Ciemny brązowy
        "#FFA000",  # Bursztynowy
    ],
    "two_opt": [  # Niebiesko-zielona paleta
        "#0000FF",  # Niebieski
        "#00FF00",  # Zielony
        "#00FFFF",  # Cyjan
        "#000080",  # Granatowy
        "#008000",  # Ciemny zielony
        "#0080FF",  # Jasny niebieski
        "#00FF80",  # Morski
        "#004080",  # Ciemny błękit
        "#008080",  # Morski ciemny
        "#80FF80",  # Jasny zielony
    ],
    "mst_approx": [  # Fioletowo-różowa paleta
        "#FF00FF",  # Magenta
        "#8000FF",  # Fioletowy
        "#FF0080",  # Różowy
        "#400080",  # Ciemny fiolet
        "#800040",  # Bordowy
        "#FF80FF",  # Jasny róż
        "#800080",  # Purpurowy
        "#FF0040",  # Malinowy
        "#400040",  # Bakłażanowy
        "#FF80C0",  # Jasny różowy
    ],
    "default": [  # Kolorowa paleta
        "#FF0000",  # Czerwony
        "#00FF00",  # Zielony
        "#0000FF",  # Niebieski
        "#FFFF00",  # Żółty
        "#FF00FF",  # Magenta
        "#00FFFF",  # Cyjan
        "#FF8000",  # Pomarańczowy
        "#8000FF",  # Fioletowy
        "#008000",  # Ciemny zielony
        "#FF0080",  # Różowy
    ],
}

# Style linii dla różnych algorytmów
LINE_STYLES = {
    "nearest_neighbor": {
        "weight": 3,  # cieńsza linia dla najgorszego algorytmu
        "opacity": 0.7,  # mniejsza nieprzezroczystość
    },
    "two_opt": {
        "weight": 6,  # najgrubsza linia (najlepszy algorytm)
        "opacity": 0.9,  # największa nieprzezroczystość
    },
    "mst_approx": {
        "weight": 4,  # średnia grubość dla algorytmu o średniej wydajności
        "opacity": 0.8,  # średnia nieprzezroczystość
    },
}

# Ustawienia kolorów dla dni
DAY_COLORS = {
    "saturation": 0.9,  # Nasycenie kolorów (0-1)
    "value": 0.9,  # Jasność kolorów (0-1)
    "weight": 3,  # Grubość linii
    "opacity": 0.8,  # Przezroczystość linii (0-1)
    "border": {
        "weight": 5,  # Grubość obramowania
        "opacity": 0.3,  # Przezroczystość obramowania (0-1)
    },
}

# Ustawienia cache
CACHE_SETTINGS = {
    "cache_dir": "cache",
    "routes_cache_file": "cached_routes.pkl",
    "matrix_cache_file": "distance_matrix.pkl",
    "tsp_results_dir": "tsp_results",
    "auto_save_frequency": 10,  # Zapis co ile operacji
    "max_backups": 5,  # Maksymalna liczba kopii zapasowych
    "cache_report_file": "cache_report.json",
    "safety_features": {
        "use_tempfile": True,  # Używaj plików tymczasowych
        "create_backups": True,  # Twórz kopie zapasowe
        "verify_after_write": True,  # Weryfikuj po zapisie
        "auto_recover": True,  # Automatycznie odtwarzaj z backupu
    },
}

# Ustawienia czyszczenia cache
CACHE_CLEANUP = {
    "auto_cleanup": False,  # Automatyczne czyszczenie starych plików
    "max_age_days": 30,  # Maksymalny wiek cache w dniach
    "min_disk_space_mb": 100,  # Minimalny dostępny rozmiar dysku
    "cleanup_on_startup": False,  # Czy czyścić przy starcie
}
