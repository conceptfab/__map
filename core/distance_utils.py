from geopy.distance import geodesic


def oblicz_odleglosc(lat1, lon1, lat2, lon2):
    """
    Oblicza odległość między dwoma punktami na powierzchni Ziemi.

    Args:
        lat1 (float): Szerokość geograficzna pierwszego punktu
        lon1 (float): Długość geograficzna pierwszego punktu
        lat2 (float): Szerokość geograficzna drugiego punktu
        lon2 (float): Długość geograficzna drugiego punktu

    Returns:
        float: Odległość w kilometrach
    """
    return geodesic((lat1, lon1), (lat2, lon2)).kilometers
