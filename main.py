from dotenv import load_dotenv
from fastapi import FastAPI
import httpx
import os

load_dotenv()
app = FastAPI(title="Pub in the Sun")

HERE_API = os.getenv('HERE_API_KEY')
BASE_URL = "https://discover.search.hereapi.com/v1/discover?q=pub&limit=20"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_ROUTER_API = os.getenv('OPEN_ROUTER_API_KEY')

@app.get("/")
def root():
    return {"message": "Pub in The Sun is running"}

@app.get("/pubs")
async def get_pubs(lat: float, lng: float, radius: int = 1000):
    pubs = []
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}&in=circle:{lat},{lng};{radius}&apiKey={HERE_API}"
            )
    data = response.json()
    for item in data['items']:
        categories = item.get('categories', [])
        is_pub = any(
            cat.get('id') == '200-2000-0011' and cat.get('primary') == True
            for cat in categories
        )
        if is_pub:
            pubs.append({
                'title': item['title'],
                'latitude': item['position']['lat'],
                'longitude': item['position']['lng'],
                'address': item['address']['label']
                })
    return pubs

@app.get("/weather")
async def get_weather(lat: float, lng: float):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{OPEN_METEO_URL}?latitude={lat}&longitude={lng}&current=cloud_cover"
            )
    data =  response.json()
    return {"cloud_cover":data['current']['cloud_cover']}