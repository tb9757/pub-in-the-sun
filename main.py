import base64
import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import firebase_admin
from firebase_admin import credentials, firestore
import httpx
import json
import os
from pydantic import BaseModel

load_dotenv()
app = FastAPI(title="Pub in the Sun")

HERE_API = os.getenv('HERE_API_KEY')
BASE_URL = "https://discover.search.hereapi.com/v1/discover?q=pub&limit=30"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_ROUTER_API = os.getenv('OPEN_ROUTER_API_KEY')

cred_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
if cred_json:
    cred_dict = json.loads(base64.b64decode(cred_json))
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate(os.getenv('GOOGLE_CREDENTIALS')) # connect to firestore database

firebase_admin.initialize_app(cred)
db = firestore.client()

weather_cache = {}

class SunData(BaseModel):
    pub_id: str
    pub_name: str
    address: str
    cloud_cover: int
    sun_altitude: float
    sun_azimuth: float

class UserReport(BaseModel):
    pub_id: str
    pub_name: str
    sunny: bool
    garden: str
    cloud_cover: float
    sun_altitude: float


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

def get_recent_reports(pub_id):
    reports = db.collection('reports')\
        .where(filter=firestore.FieldFilter('pub_id', '==', pub_id))\
        .order_by('time', direction=firestore.Query.DESCENDING)\
        .limit(5)\
        .stream()
    
    results = []
    for report in reports:
        r = report.to_dict()
        results.append(r)
    return results

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
    considering that the beer garden is likely to be at the back of the pub. 
    A pub on the north side of a street faces south towards the street, 
    meaning its back garden faces NORTH — which is typically bad for sunshine. 
    A pub on the south side of a street faces north towards the street, 
    meaning its back garden faces SOUTH — which is typically good for afternoon sunshine. 
    This is the opposite of what might seem intuitive — always reason carefully about 
    which way the BACK of the building faces, not the front.
    Cross reference this with the sun's azimuth to give your best guess. 
    Make clear it's a guess, but commit to it.

    If previous user reports are provided, use them to inform your verdict:
    - If multiple reports confirm the garden is at the front or back, treat this as reliable information and state it confidently rather than guessing.
    - If reports confirm it was sunny under similar conditions (similar sun altitude and azimuth), weight your verdict positively.
    - If reports confirm it was not sunny under similar conditions, weight your verdict negatively.
    - Always mention if you are drawing on previous visitor reports — it builds trust and explains your reasoning.
    - If reports are contradictory, acknowledge this and explain the uncertainty.

    If sun altitude is below 10 degrees, the sun is too low to feel warm regardless 
    of cloud cover. Say so.

    Be warm, conversational and specific — like a friend who knows their pubs. 
    Keep your verdict to 2-3 sentences. Never pretend to know which way the garden 
    faces with certainty."""
    
    reports = get_recent_reports(data.pub_id)

    if reports:
        report_text = "\n".join([
            f"- {r['time']}: garden is at the {r.get('garden_location', 'unknown')}, was sunny: {r['sunny']}"
            for r in reports
        ])
    else:
        report_text = "No previous reports for this pub."

    pub_data = f"""The pub is called {data.pub_name}, located 
    at {data.address}. Current cloud cover: {data.cloud_cover}%
    Sun altitude: ({get_altitude_description(data.sun_altitude)})
    Sun azimuth: ({get_direction_description(data.sun_azimuth)})

    Previous user reports:
    {report_text}
    """

    headers = {
        "Authorization": f"Bearer {OPEN_ROUTER_API}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "anthropic/claude-sonnet-4-5",
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

@app.post("/report")
async def post_report(data: UserReport):
    payload = {
        "pub_id": data.pub_id,
        "pub_name": data.pub_name,
        "sunny": data.sunny,
        "garden_location": data.garden,
        "cloud_cover":data.cloud_cover,
        "sun_altitude": data.sun_altitude,
        "time": datetime.datetime.now(datetime.timezone.utc)
    }
    db.collection('reports').add(payload)
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")