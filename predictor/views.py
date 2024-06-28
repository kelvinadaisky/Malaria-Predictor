import pandas as pd
import joblib
import requests
import folium
from folium.plugins import MarkerCluster
from geopy.geocoders import Nominatim
from django.shortcuts import render
from .forms import CountryForm
from django.core.cache import cache
import psutil
import os

# Load preprocessor and model
preprocessor = joblib.load('preprocessor.pkl')
model = joblib.load('gradient_boosting_model.pkl')

# OpenWeather API key
weather_api_key = '237c75a26646cfb183bca03f1662cbfd'
# OpenCage Geocoding API key
geocoding_api_key = 'e7db2f2a540c47afa09af361d40f1222'

# Load malaria data from WHO
malaria_data = pd.read_csv('merged_without_city_1.csv', usecols=['Country', 'ISO', 'Year', 'Deaths', 'Mortality_Rate', 'Malaria_incidence'])
# Create a dictionary for country name to ISO code mapping
country_to_iso = dict(zip(malaria_data['Country'].str.lower(), malaria_data['ISO']))

# Function to log memory usage
def log_memory_usage():
    process = psutil.Process(os.getpid())
    print(f"Memory usage: {process.memory_info().rss / (1024 * 1024):.2f} MB")

# Function to get weather data
def get_weather_data(latitude, longitude, api_key):
    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={latitude}&lon={longitude}&appid={api_key}&units=metric"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise ValueError(f"Failed to get data from OpenWeather API. Status code: {response.status_code}")
    
    data = response.json()
    
    if 'list' not in data:
        raise KeyError("Forecast data not found in API response.")
    
    temperatures = [item['main']['temp'] for item in data['list']]
    avg_temp_c = sum(temperatures) / len(temperatures)
    
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
        print(f"Failed to get data from World Bank API for {indicator}. Status code: {response.status_code}")
        return None
    
    data = response.json()
    
    if not data or len(data) < 2 or not data[1]:
        print(f"No data found for {indicator} from World Bank API.")
        return None
    
    for entry in data[1]:
        if entry.get('value') is not None:
            return entry['value']
    
    print(f"No valid value found for {indicator} from World Bank API.")
    return None

# Function to get malaria data from WHO CSV
def get_malaria_data(country_name, year):
    record = malaria_data[(malaria_data['Country'].str.lower() == country_name.lower()) & (malaria_data['Year'] == 2021)]
    if not record.empty:
        print("Malaria data:")
        print(record.iloc[0])
        return record.iloc[0].to_dict()
    else:
        print(f"No malaria data found for {country_name} in {year}.")
        return None

# Function to get latitude, longitude and continent using OpenCage Geocoding API
def get_lat_lon_continent(country_name, api_key):
    url = f"https://api.opencagedata.com/geocode/v1/json?q={country_name}&key={api_key}"
    response = requests.get(url)
    data = response.json()
    
    if data['results']:
        geometry = data['results'][0]['geometry']
        components = data['results'][0]['components']
        latitude = geometry['lat']
        longitude = geometry['lng']
        continent = components.get('continent', 'Unknown')
        print(f"Geolocation data: Latitude: {latitude}, Longitude: {longitude}, Continent: {continent}")
        return latitude, longitude, continent
    else:
        print(f"Could not get geolocation for {country_name}. Response: {data}")
        return None, None, None

def malaria_risk_map(request):
    return render(request, 'predictor/malaria_risk_map.html')

# Function to get country information
def get_country_info(country_code, country_name):
    latitude, longitude, continent = get_lat_lon_continent(country_name, geocoding_api_key)
    if latitude is None or longitude is None:
        return None

    country_info = {
        'ISO': country_code,
        'Country': country_name,
        'Year': 2024,
        'Latitude': latitude,
        'Longitude': longitude,
        'Continent': continent
    }
    
    try:
        population = get_world_bank_data(country_code, 'SP.POP.TOTL') or 0
        gdp = get_world_bank_data(country_code, 'NY.GDP.MKTP.CD') or 0
        country_info['TPopulation'] = population
        country_info['TPopulationMale'] = get_world_bank_data(country_code, 'SP.POP.TOTL.MA.IN') or 0
        country_info['TPopulationFemale'] = get_world_bank_data(country_code, 'SP.POP.TOTL.FE.IN') or 0
        country_info['GDP'] = gdp / population if population else 0        
        malaria_info = get_malaria_data(country_name, 2024)
        if malaria_info:
            country_info['Deaths'] = malaria_info['Deaths']
            country_info['Mortality_Rate'] = malaria_info['Mortality_Rate']
            country_info['Malaria_incidence'] = malaria_info['Malaria_incidence']
        else:
            return None
        
        country_info['Healthcare Access Quality'] = get_world_bank_data(country_code, 'SH.UHC.SRVS.CV.XD') or 0  # health expenditure per capita
        country_info['Hospital_beds'] = get_world_bank_data(country_code, 'SH.MED.BEDS.ZS') or 0  # hospital beds per 1000
    except ValueError as e:
        print(e)
        return None
    
    try:
        avg_temp_c, precipitation_mm = get_weather_data(latitude, longitude, weather_api_key)
        country_info['avg_temp_c'] = avg_temp_c
        country_info['precipitation_mm'] = precipitation_mm
    except Exception as e:
        print(e)
        return None
    
    return country_info

# Function to predict malaria
def predict_malaria(user_data):
    user_data_preprocessed = preprocessor.transform(user_data)
    prediction = model.predict(user_data_preprocessed)
    prediction = max(prediction[0], 0)
    return prediction

# Function to assess safety
def assess_safety(malaria_cases):
    if malaria_cases <= 100:
        return "Low risk"
    elif malaria_cases <= 1000:
        return "Medium risk"
    else:
        return "High risk"

def index(request):
    if request.method == 'POST':
        form = CountryForm(request.POST)
        if form.is_valid():
            country_name = form.cleaned_data['country'].strip().lower()
            country_code = country_to_iso.get(country_name)

            if not country_code:
                return render(request, 'predictor/index.html', {'form': form, 'error': 'Country not found in the list.'})

            country_info = get_country_info(country_code, country_name.title())
            if not country_info:
                return render(request, 'predictor/index.html', {'form': form, 'error': 'Failed to retrieve all necessary data.'})

            user_data = pd.DataFrame([country_info])
            malaria_cases = predict_malaria(user_data)
            risk_level = assess_safety(malaria_cases)

            return render(request, 'predictor/index.html', {'form': form, 'result': f'Predicted malaria cases: {malaria_cases:.2f}', 'risk': f'Risk level: {risk_level}'})
    else:
        form = CountryForm()

    return render(request, 'predictor/index.html', {'form': form})

# Function to process countries in batches
def process_countries_in_batches(batch_size=10):
    country_risks = []
    countries = list(country_to_iso.items())
    for i in range(0, len(countries), batch_size):
        batch = countries[i:i+batch_size]
        for country, iso in batch:
            try:
                country_info = get_country_info(iso, country.title())
                if not country_info:
                    continue

                user_data = pd.DataFrame([country_info])
                malaria_cases = predict_malaria(user_data)
                country_risks.append((country.title(), malaria_cases, country_info['Latitude'], country_info['Longitude']))
            except Exception as e:
                print(f"Error processing {country}: {e}")
                continue
        log_memory_usage()  # Log memory usage after each batch
    return country_risks

# Function to generate a map for the top 10 countries with high risk of malaria outbreaks
def show_top10_map(request):
    cached_map = cache.get('top10_map')
    if cached_map:
        return render(request, 'predictor/malaria_top10_map.html')

    geolocator = Nominatim(user_agent="malaria_predictor")
    world_map = folium.Map(location=[0, 0], zoom_start=2)
    marker_cluster = MarkerCluster().add_to(world_map)

    # Process countries in batches
    country_risks = process_countries_in_batches()

    # Sort and select top 10 countries
    country_risks.sort(key=lambda x: x[1], reverse=True)
    top10_countries = country_risks[:10]

    for country, malaria_cases, lat, lon in top10_countries:
        risk_level = assess_safety(malaria_cases)
        if risk_level == "High risk":
            color = 'red'
        elif risk_level == "Medium risk":
            color = 'orange'
        else:
            color = 'green'

        folium.Marker(
            location=[lat, lon],
            popup=f"{country}: {risk_level}",
            icon=folium.Icon(color=color)
        ).add_to(marker_cluster)

    world_map.save('predictor/static/predictor/malaria_top10_map.html')
    cache.set('top10_map', 'predictor/static/predictor/malaria_top10_map.html', timeout=60*60*24)  # Cache for 24 hours
    return render(request, 'predictor/malaria_top10_map.html')

# Function to generate a map for all countries with malaria risk levels
def show_all_map(request):
    cached_map = cache.get('all_map')
    if cached_map:
        return render(request, 'predictor/malaria_all_map.html')

    geolocator = Nominatim(user_agent="malaria_predictor")
    world_map = folium.Map(location=[0, 0], zoom_start=2)
    marker_cluster = MarkerCluster().add_to(world_map)

    # Process countries in batches
    country_risks = process_countries_in_batches()

    for country, malaria_cases, lat, lon in country_risks:
        risk_level = assess_safety(malaria_cases)

        if risk_level == "High risk":
            color = 'red'
        elif risk_level == "Medium risk":
            color = 'orange'
        else:
            color = 'green'

        folium.Marker(
            location=[lat, lon],
            popup=f"{country}: {risk_level}",
            icon=folium.Icon(color=color)
        ).add_to(marker_cluster)

    world_map.save('predictor/static/predictor/malaria_all_map.html')
    cache.set('all_map', 'predictor/static/predictor/malaria_all_map.html', timeout=60*60*24)  # Cache for 24 hours
    return render(request, 'predictor/malaria_all_map.html')

