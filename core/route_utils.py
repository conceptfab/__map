def podziel_trase_na_dni(path, distances, max_daily_distance):
    """
    Dzieli trasę na segmenty dzienne, nie przekraczające maksymalnej dziennej odległości.

    Args:
        path (list): Lista indeksów punktów w kolejności odwiedzania
        distances (dict): Słownik odległości między punktami
        max_daily_distance (float): Maksymalna dzienna odległość w km

    Returns:
        list: Lista segmentów dziennych, każdy zawierający listę segmentów i całkowitą odległość
    """
    daily_segments = []
    current_day = []
    current_distance = 0

    for i in range(len(path) - 1):
        from_idx = path[i]
        to_idx = path[i + 1]
        segment_distance = distances.get((from_idx, to_idx), 0)

        # Jeśli dodanie kolejnego segmentu przekroczy limit, zakończ dzień
        if current_distance + segment_distance > max_daily_distance and current_day:
            daily_segments.append(
                {"segments": current_day, "distance": current_distance}
            )
            current_day = []
            current_distance = 0

        current_day.append((from_idx, to_idx))
        current_distance += segment_distance

    # Dodaj ostatni dzień
    if current_day:
        daily_segments.append({"segments": current_day, "distance": current_distance})

    return daily_segments
