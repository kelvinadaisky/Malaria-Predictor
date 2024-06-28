import pandas as pd
import joblib
import requests
import folium
from folium.plugins import FastMarkerCluster
from geopy.geocoders import Nominatim
from django.shortcuts import render
from .forms import CountryForm
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

# Load preprocessor and model
preprocessor = joblib.load('preprocessor.pkl')
model = joblib.load('gradient_boosting_model.pkl')

# OpenWeather API key
weather_api_key = '237c75a26646cfb183bca03f1662cbfd'
# OpenCage Geocoding API key
geocoding_api_key = 'e7db2f2a540c47afa09af361d40f1222'

# Load malaria data from WHO
malaria_data = pd.read_csv('merged_without_city_1.csv')
malaria_data = malaria_data[['Country','ISO', 'Year', 'Deaths', 'Mortality_Rate', 'Malaria_incidence']]
# Create a dictionary for country name to ISO code mapping
country_to_iso = dict(zip(malaria_data['Country'].str.lower(), malaria_data['ISO']))

# Function to get weather data
def get_weather_data(latitude, longitude, api_key):
    # OpenWeather API for 5-day forecast
    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={api_key}&units=metric"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise ValueError(f"Failed to get data from OpenWeather API. Status code: {response.status_code}")
    
    data = response.json()
    
    if 'list' not in data:
        raise KeyError("Forecast data not found in API response.")
    
    # Calculate the average temperature for the next 30 days
    temperatures = [item['main']['temp'] for item in data['list']]
    avg_temp_c = sum(temperatures) / len(temperatures)
    
    # Get the precipitation data
    precipitation_mm = 0
    for item in data['list']:
        precipitation_mm += item.get('rain', {}).get('3h', 0)
    
    print(f"Weather data: Average temperature for the next 30 days: {avg_temp_c}°C, Total precipitation: {precipitation_mm} mm")
    return avg_temp_c, precipitation_mm

# Function to get World Bank data
def get_world_bank_data(country_code, indicator):
    url = f"http://api.worldbank.org/v2/country/{country_code}/indicator/{indicator}?format=json"
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"Failed to get data from World Bank API. Status code: {response.status_code}")
        return None
    
    data = response.json()
    if 'value' in data[1][0]:
        return data[1][0]['value']
    else:
        return None

# Function to get latitude, longitude, and continent for a country
def get_lat_lon_continent(country_name):
    try:
        # Retrieve the latitude, longitude, and continent using the OpenCage Geocoding API
        geolocator = Nominatim(user_agent="my_app")
        location = geolocator.geocode(country_name)
        if location:
            return location.point.latitude, location.point.longitude, location.address.split(", ")[-1]
        else:
            return None, None, None
    except Exception as e:
        logger.error(f"Error getting geolocation for {country_name}: {e}")
        return None, None, None

def show_all_map(request):
    try:
        # Try to get the map from the cache
        map_html = cache.get('all_map_html')
        if map_html:
            return render(request, 'map.html', {'map': map_html})

        # Generate the map
        m = folium.Map(location=[0, 0], zoom_start=2)
        marker_cluster = FastMarkerCluster(name='Malaria Incidents').add_to(m)

        for _, row in malaria_data.iterrows():
            country = row['Country']
            latitude, longitude, continent = get_lat_lon_continent(country)
            if latitude is not None and longitude is not None:
                folium.Marker(
                    location=[latitude, longitude],
                    popup=f"{country}: {row['Malaria_incidence']}",
                    icon=folium.Icon(color='red')
                ).add_to(marker_cluster)

        map_html = m.get_root().render()
        cache.set('all_map_html', map_html, timeout=3600)  # Cache the map for 1 hour
        return render(request, 'map.html', {'map': map_html})

    except Exception as e:
        # Log the error
        logger.error(f"Error generating all map: {e}")
        return render(request, 'map.html', {'error': 'An error occurred while generating the map.'})


def show_top10_map(request):
    try:
        # Try to get the map from the cache
        map_html = cache.get('top10_map_html')
        if map_html:
            return render(request, 'map.html', {'map': map_html})

        # Generate the top 10 countries by malaria incidence
        top10 = malaria_data.nlargest(10, 'Malaria_incidence')

        # Create the map
        m = folium.Map(location=[0, 0], zoom_start=2)
        marker_cluster = FastMarkerCluster(name='Top 10 Malaria Incidents').add_to(m)

        for _, row in top10.iterrows():
            country = row['Country']
            latitude, longitude, continent = get_lat_lon_continent(country)
            if latitude is not None and longitude is not None:
                folium.Marker(
                    location=[latitude, longitude],
                    popup=f"{country}: {row['Malaria_incidence']}",
                    icon=folium.Icon(color='red')
                ).add_to(marker_cluster)

        map_html = m.get_root().render()
        cache.set('top10_map_html', map_html, timeout=3600)  # Cache the map for 1 hour
        return render(request, 'map.html', {'map': map_html})

    except Exception as e:
        # Log the error
        logger.error(f"Error generating top 10 map: {e}")
        return render(request, 'map.html', {'error': 'An error occurred while generating the map.'})
