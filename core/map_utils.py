import folium

from ..config import DAY_COLORS, LINE_STYLES


def generuj_mape_wielowarstwowa(locations, best_path, daily_segments, algorithms):
    """
    Generuje mapę HTML z wieloma warstwami informacji.

    Args:
        locations (list): Lista lokalizacji
        best_path (list): Najlepsza znaleziona ścieżka
        daily_segments (list): Segmenty dzienne
        algorithms (dict): Wyniki różnych algorytmów

    Returns:
        str: Ścieżka do wygenerowanego pliku HTML
    """
    # Utwórz mapę
    mapa = folium.Map(
        location=[52.0, 19.0], zoom_start=6, tiles="OpenStreetMap"  # Środek Polski
    )

    # Dodaj warstwy
    warstwy = {
        "Lokalizacje": folium.FeatureGroup(name="Lokalizacje"),
        "Trasy": folium.FeatureGroup(name="Trasy"),
        "Numery": folium.FeatureGroup(name="Numery"),
        "Adresy": folium.FeatureGroup(name="Adresy"),
    }

    # Dodaj lokalizacje
    for item in locations:
        folium.Marker(
            location=[item["latitude"], item["longitude"]],
            popup=f"<b>{item.get('Miasto', '')}</b><br>#{item.get('numer', '')}",
            tooltip=item.get("Miasto", ""),
        ).add_to(warstwy["Lokalizacje"])

    # Dodaj trasy
    colors = generuj_kolory_dla_dni(len(daily_segments))

    for day_idx, day in enumerate(daily_segments):
        for segment in day["segments"]:
            from_idx, to_idx = segment
            from_loc = locations[from_idx]
            to_loc = locations[to_idx]

            # Pobierz styl linii dla najlepszego algorytmu
            line_style = LINE_STYLES.get("Najbliższy sąsiad + 2-opt", {})
            color = colors[day_idx]

            # Dodaj linię trasy
            folium.PolyLine(
                [
                    (from_loc["latitude"], from_loc["longitude"]),
                    (to_loc["latitude"], to_loc["longitude"]),
                ],
                color=color,
                weight=line_style.get("weight", 4),
                opacity=line_style.get("opacity", 0.8),
                dash_array=line_style.get("dash_array", None),
            ).add_to(warstwy["Trasy"])

    # Dodaj warstwy do mapy
    for warstwa in warstwy.values():
        warstwa.add_to(mapa)

    # Dodaj kontrolkę warstw
    folium.LayerControl().add_to(mapa)

    # Zapisz mapę
    output_file = "mapa_wszystkich_tras.html"
    mapa.save(output_file)

    return output_file
