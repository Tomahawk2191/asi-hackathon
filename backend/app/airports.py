"""Tiny lookup table for major US airports referenced by routing UI."""
AIRPORTS: dict[str, tuple[float, float]] = {
    "KJFK": (40.6413, -73.7781),
    "KLGA": (40.7769, -73.8740),
    "KEWR": (40.6925, -74.1687),
    "KBOS": (42.3656, -71.0096),
    "KDCA": (38.8512, -77.0402),
    "KIAD": (38.9531, -77.4565),
    "KATL": (33.6407, -84.4277),
    "KMIA": (25.7959, -80.2870),
    "KFLL": (26.0726, -80.1527),
    "KORD": (41.9742, -87.9073),
    "KMDW": (41.7868, -87.7522),
    "KDFW": (32.8998, -97.0403),
    "KIAH": (29.9844, -95.3414),
    "KHOU": (29.6454, -95.2789),
    "KDEN": (39.8617, -104.6732),
    "KSLC": (40.7899, -111.9791),
    "KPHX": (33.4342, -112.0116),
    "KLAS": (36.0840, -115.1537),
    "KLAX": (33.9416, -118.4085),
    "KSAN": (32.7338, -117.1933),
    "KSFO": (37.6188, -122.3754),
    "KSJC": (37.3639, -121.9289),
    "KSEA": (47.4502, -122.3088),
    "KPDX": (45.5898, -122.5951),
    "KMSP": (44.8848, -93.2223),
    "KDTW": (42.2124, -83.3534),
    "KCLT": (35.2140, -80.9431),
    "KPHL": (39.8729, -75.2437),
    "KBWI": (39.1754, -76.6683),
    "KMCO": (28.4312, -81.3081),
    "KTPA": (27.9755, -82.5332),
}


def coords(icao: str) -> tuple[float, float]:
    icao = icao.upper().strip()
    if not icao.startswith("K") and len(icao) == 3:
        icao = "K" + icao
    if icao not in AIRPORTS:
        raise KeyError(f"unknown airport {icao!r}; supported: {sorted(AIRPORTS)}")
    return AIRPORTS[icao]
