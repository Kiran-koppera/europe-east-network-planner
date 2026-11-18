"""Shared constants. Everything that is an assumption lives here, so it can be reviewed in one place."""
from __future__ import annotations

FEED_URL = "https://gtfs.gis.flix.tech/gtfs_generic_eu.zip"
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"

# Team scope: Network Planning - Europe East.
EUROPE_EAST = {
    "PL": "Poland", "CZ": "Czechia", "SK": "Slovakia", "HU": "Hungary", "RO": "Romania",
    "BG": "Bulgaria", "HR": "Croatia", "SI": "Slovenia", "RS": "Serbia", "BA": "Bosnia and Herzegovina",
    "UA": "Ukraine", "MD": "Moldova", "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia",
}

# GTFS stops carry an IANA timezone; in this feed it identifies the country reliably.
TZ_TO_COUNTRY = {
    "Europe/Rome": "IT", "Europe/Berlin": "DE", "Europe/Warsaw": "PL", "Europe/Paris": "FR",
    "Europe/Zagreb": "HR", "Europe/London": "GB", "Europe/Lisbon": "PT", "Europe/Bucharest": "RO",
    "Europe/Prague": "CZ", "Europe/Stockholm": "SE", "Europe/Madrid": "ES", "Europe/Bratislava": "SK",
    "Europe/Oslo": "NO", "Europe/Kyiv": "UA", "Europe/Kiev": "UA", "Europe/Helsinki": "FI",
    "Europe/Copenhagen": "DK", "Europe/Amsterdam": "NL", "Europe/Vienna": "AT", "Europe/Zurich": "CH",
    "Europe/Brussels": "BE", "Europe/Sofia": "BG", "Europe/Budapest": "HU", "Europe/Belgrade": "RS",
    "Europe/Vilnius": "LT", "Europe/Ljubljana": "SI", "Europe/Chisinau": "MD", "Europe/Luxembourg": "LU",
    "Europe/Sarajevo": "BA", "Europe/Riga": "LV", "Europe/Tallinn": "EE", "Europe/Athens": "GR",
    "Europe/Istanbul": "TR", "Europe/Vaduz": "LI", "Europe/Podgorica": "ME", "Europe/Skopje": "MK",
    "Europe/Tirane": "AL", "Europe/Dublin": "IE", "Europe/Monaco": "MC", "Europe/Malta": "MT",
    "Atlantic/Canary": "ES", "Atlantic/Madeira": "PT", "Atlantic/Azores": "PT",
}

# A stop belongs to a GeoNames city (population >= 15,000) if it lies within this radius.
CITY_RADIUS_KM = 12.0

# Demand-gap model.
GRAVITY_MIN_POP = 100_000          # both cities in a candidate pair
GRAVITY_MIN_KM = 150               # shorter trips are dominated by rail/regional transport
GRAVITY_MAX_KM = 1_200             # longer trips are dominated by air
LOW_FREQUENCY_WEEKLY = 14          # fewer than ~1 departure per day per direction
MERGE_RADIUS_KM = 15               # GeoNames lists some city districts separately; merge into the largest
# Destinations outside this feed's market (Turkey has its own Flix feed).
EXCLUDED_COUNTRIES = {"TR"}
# Regions where scheduled commercial coach service is not operable (occupation or front line).
# GeoNames admin1 codes. Review whenever the situation changes.
EXCLUDED_REGIONS = {
    "UA": {"05": "Donetsk", "07": "Kharkiv", "08": "Kherson", "11": "Crimea", "14": "Luhansk",
           "20": "Sevastopol", "21": "Sumy", "26": "Zaporizhzhia"},
}

# Data-quality thresholds.
MAX_BUS_SPEED_KMH = 120.0          # straight-line speed between consecutive stops
MAX_TRAIN_SPEED_KMH = 250.0

# Draft timetable for the line dossier.
ROAD_FACTOR = 1.25                 # road distance / straight-line distance
COACH_SPEED_KMH = 70.0             # average commercial speed incl. city access
BREAK_AFTER_H = 4.5                # Regulation (EC) No 561/2006, Art. 7
BREAK_MIN = 45
