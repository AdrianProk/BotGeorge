import requests
from datetime import datetime

#lat, lon = 47.56, 7.59

variables = [
    "temperature_2m",
    "precipitation",
    "windspeed_10m",
    "cloudcover",
    "shortwave_radiation"
]


def fetchWetherData(lat, lon):

    url = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={lat}&longitude={lon}"
    f"&hourly={','.join(variables)}"
    "&forecast_days=1"
    "&timezone=UTC"
    )

    print("Hole Wetterdaten von:", url)
    resp = requests.get(url)
    data = resp.json()

    # Wir nehmen die letzte Zeitstufe
    times = data["hourly"]["time"]
    latest_index = len(times) - 1
    latest_time = times[latest_index]

    print(f"\nWetter für {lat:.2f},{lon:.2f} am {latest_time} UTC:\n")

    for var in variables:
        unit = data["hourly_units"][var]
        value = data["hourly"][var][latest_index]
        print(f"{var:15s}: {value} {unit}")
    
    return data

def fetchCoordinates(CityName):

    CityURL = (
        "https://geocoding-api.open-meteo.com/v1/search?name="
        f"{CityName}&count=1"
    )

    resp = requests.get(CityURL)
    #data contains all data from the city... most of it.
    data = resp.json()

    lat = data["results"][0]["latitude"]
    lon = data["results"][0]["longitude"]

    print(f"{lat} and {lon}")
    return lat, lon

def fetchMap(CityName):
    lat, lon = fetchCoordinates(CityName)

    url = (
        "https://staticmap.openstreetmap.de/staticmap.php"
        f"?center={lat},{lon}"
        "&zoom=13&size=600x400&maptype=mapnik"
    )

    resp = requests.get(url)
    with open("test_map.png", "wb") as f:
        f.write(resp.content)
    print("done")
#Tests   

#lat, lon = fetchCoordinates("Rheinfelden (Baden)")

#fetchWetherData(lat, lon)

fetchMap("Basel")