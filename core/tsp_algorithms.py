import time

import networkx as nx


def run_nearest_neighbor(distances, n, num_threads=1):
    """
    Implementacja algorytmu najbliższego sąsiada dla TSP.

    Args:
        distances (dict): Słownik odległości między punktami
        n (int): Liczba punktów
        num_threads (int): Liczba wątków

    Returns:
        tuple: (ścieżka, odległość, czas_wykonania)
    """
    start_time = time.time()

    path = [0]  # Zaczynamy od pierwszego punktu
    unvisited = set(range(1, n))
    total_distance = 0

    while unvisited:
        current = path[-1]
        nearest = min(
            unvisited, key=lambda x: distances.get((current, x), float("inf"))
        )
        path.append(nearest)
        unvisited.remove(nearest)
        total_distance += distances.get((current, nearest), 0)

    # Dodaj powrót do punktu startowego
    path.append(0)
    total_distance += distances.get((path[-2], 0), 0)

    return path, total_distance, time.time() - start_time


def run_two_opt(path, initial_distance, distances, num_threads=1):
    """
    Implementacja algorytmu 2-opt dla TSP.

    Args:
        path (list): Początkowa ścieżka
        initial_distance (float): Początkowa odległość
        distances (dict): Słownik odległości między punktami
        num_threads (int): Liczba wątków

    Returns:
        tuple: (ścieżka, odległość, czas_wykonania)
    """
    start_time = time.time()
    best_path = path.copy()
    best_distance = initial_distance
    improved = True

    while improved:
        improved = False
        for i in range(1, len(path) - 2):
            for j in range(i + 1, len(path) - 1):
                # Oblicz zmianę odległości po zamianie
                old_dist = distances.get((path[i - 1], path[i]), 0) + distances.get(
                    (path[j], path[j + 1]), 0
                )
                new_dist = distances.get((path[i - 1], path[j]), 0) + distances.get(
                    (path[i], path[j + 1]), 0
                )

                if new_dist < old_dist:
                    # Wykonaj zamianę
                    path[i : j + 1] = path[j : i - 1 : -1]
                    best_distance += new_dist - old_dist
                    improved = True

    return path, best_distance, time.time() - start_time


def run_mst(distances, n, num_threads=1):
    """
    Implementacja algorytmu MST dla TSP.

    Args:
        distances (dict): Słownik odległości między punktami
        n (int): Liczba punktów
        num_threads (int): Liczba wątków

    Returns:
        tuple: (ścieżka, odległość, czas_wykonania)
    """
    start_time = time.time()

    # Tworzymy graf
    G = nx.Graph()
    for i in range(n):
        for j in range(i + 1, n):
            G.add_edge(i, j, weight=distances.get((i, j), float("inf")))

    # Znajdujemy MST
    mst = nx.minimum_spanning_tree(G)

    # Przechodzimy MST w kolejności pre-order
    path = list(nx.dfs_preorder_nodes(mst, 0))
    path.append(0)  # Dodaj powrót do punktu startowego

    # Oblicz całkowitą odległość
    total_distance = 0
    for i in range(len(path) - 1):
        total_distance += distances.get((path[i], path[i + 1]), 0)

    return path, total_distance, time.time() - start_time
