from dotenv import load_dotenv
from fastapi import FastAPI
import httpx
import os

load_dotenv()
app = FastAPI(title="Pub in the Sun")

HERE_API = os.getenv('HERE_API_KEY')
BASE_URL = "https://discover.search.hereapi.com/v1/discover?q=pub&limit=20"

@app.get("/")
def root():
    return {"message": "Pub in the Sun is running"}

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