import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import httpx
import os
from pydantic import BaseModel

load_dotenv()
app = FastAPI(title="Pub in the Sun")

HERE_API = os.getenv('HERE_API_KEY')
BASE_URL = "https://discover.search.hereapi.com/v1/discover?q=pub&limit=30"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_ROUTER_API = os.getenv('OPEN_ROUTER_API_KEY')

weather_cache = {}

class SunData(BaseModel):
    pub_name: str
    address: str
    cloud_cover: int
    sun_altitude: float
    sun_azimuth: float

def get_altitude_description(altitude):
    if altitude > 50:
        return "very high"
    elif 40 <= altitude < 50:
        return "high"
    elif 30 <= altitude < 40:
        return "moderate"
    elif 20 <= altitude < 30:
        return "low"
    else:
        return "very low"

def get_direction_description(azimuth):
    if azimuth < 22.5 or azimuth >= 337.5:
        return "north"
    elif azimuth < 67.5:
        return "northeast"
    elif azimuth < 112.5:
        return "east"
    elif azimuth < 157.5:
        return "southeast"
    elif azimuth < 202.5:
        return "south"
    elif azimuth < 247.5:
        return "southwest"
    elif azimuth < 292.5:
        return "west"
    else:
        return "northwest"

@app.get("/pubs")
async def get_pubs(lat: float, lng: float, radius: int = 1000):
    pubs = []
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}&in=circle:{lat},{lng};r={radius}&apiKey={HERE_API}"
            )
    data = response.json()
    for item in data['items']:
        categories = item.get('categories', [])
        is_pub = (
            item.get('ontologyId') == 'here:cm:ontology:bar_pub'
            and (
                any(cat.get('id') == '200-2000-0011' and cat.get('primary') for cat in categories)
                or (
                    any(cat.get('id') == '300-3000-0350' and cat.get('primary') for cat in categories)
                    and any(cat.get('id') == '200-2000-0011' for cat in categories)
                )
            )
        )
        if is_pub:
            pubs.append({
                'id': item['id'],
                'title': item['title'],
                'latitude': item['position']['lat'],
                'longitude': item['position']['lng'],
                'address': item['address']['label']
                })
    return pubs

@app.get("/weather")
async def get_weather(lat: float, lng: float):
    rounded_lat = round(lat, 2)
    rounded_lng = round(lng, 2)
    cache_key = f"{rounded_lat},{rounded_lng}"

    # check cache
    cached = weather_cache.get(cache_key)
    if cached:
        age = datetime.datetime.now(datetime.timezone.utc) - cached["timestamp"]
        if age.total_seconds() < 900:  # 900 seconds = 15 minutes
            return cached["data"]
        
    # if the cache missed or is stale call API
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"""{OPEN_METEO_URL}?latitude={rounded_lat}&longitude={rounded_lng}&current=cloud_cover&hourly=cloud_cover&forecast_days=1"""
            )
    data =  response.json()
    
    hour = datetime.datetime.now().hour
    forecast_hours = [min(hour + i, 23) for i in range(0, 16)]
    forecast = [data['hourly']['cloud_cover'][h] for h in forecast_hours]
    
    result = {
        "cloud_cover":data['current']['cloud_cover'], 
        "forecast":forecast
    }

    # store in cache
    weather_cache[cache_key] = {
        "data": result,
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
    }

    return result
    
    
@app.post("/verdict")
async def get_verdict(data: SunData):
    
    SYSTEM_PROMPT = """You are a knowledgeable and opinionated British pub enthusiast. 
    Your job is to tell someone whether the beer garden at a specific pub is likely 
    to be sunny right now, based on current weather and sun position data.

    You will be given:
    - The pub name and address
    - Current cloud cover percentage
    - Sun altitude (how high the sun is above the horizon in degrees)
    - Sun azimuth (the compass direction the sun is coming from in degrees, 
    0=North, 90=East, 180=South, 270=West)

    Reason about sunshine likelihood as follows:

    If cloud cover is above 60%, it is unlikely to be sunny regardless of orientation. 
    Say so directly.

    If cloud cover is below 40% and sun altitude is above 40 degrees, the sun is high 
    enough that most beer gardens will be sunny regardless of which way they face. 
    Give a confident positive verdict.

    If cloud cover is below 40% but sun altitude is between 10 and 40 degrees, 
    orientation starts to matter. Use the sun azimuth to describe which direction 
    the sun is coming from, and give a conditional verdict — for example 
    "if the garden faces south or west it will be catching the sun right now, 
    north or east facing gardens may be in shade."

    Use the pub's street address to reason about likely garden orientation, 
    considering that most beer gardens are at the back of the pub. 
    A pub on the south side of a street will likely have a south facing back garden 
    which catches the sun well. A pub on the north side will likely have a north 
    facing back garden which may be in shade. Cross reference this with the sun's 
    azimuth to give your best guess. Make clear it's a guess, but commit to it.

    If sun altitude is below 10 degrees, the sun is too low to feel warm regardless 
    of cloud cover. Say so.

    Be warm, conversational and specific — like a friend who knows their pubs. 
    Keep your verdict to 2-3 sentences. Never pretend to know which way the garden 
    faces with certainty."""
    
    pub_data = f"""The pub is called {data.pub_name}, located 
    at {data.address}. Current cloud cover: {data.cloud_cover}%
    Sun altitude: {data.sun_altitude} degrees above the horizon ({get_altitude_description(data.sun_altitude)})
    Sun azimuth: {data.sun_azimuth} degrees ({get_direction_description(data.sun_azimuth)})
    """

    headers = {
        "Authorization": f"Bearer {OPEN_ROUTER_API}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3.1-8b-instruct",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": pub_data}
        ]
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        return f"Error contacting OpenRouter: {e}"
    except (KeyError, IndexError):
        return "Error: Unexpected response format from OpenRouter."

app.mount("/", StaticFiles(directory="static", html=True), name="static")