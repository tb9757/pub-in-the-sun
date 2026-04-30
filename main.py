from dotenv import load_dotenv
from fastapi import FastAPI
import json
import httpx
import os

app = FastAPI(title="Pub in the Sun")
load_dotenv()

HERE_API = os.getenv('HERE_API_KEY')
BASE_URL = "https://discover.search.hereapi.com/v1/discover?q=pub&limit=20"

@app.get("/")
def root():
    return {"message": "Pub in the Sun is running"}

@app.get("/pubs")
async def get_pubs(lat: float, lng: float, radius: int = 1000):
    pubs = []
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}&in=circle:{lat},{lng};r=1000&apiKey={HERE_API}")
    for item in response.json()['items']:
        pubs.append({'title':item['title'],
                     'latitude':item['position']['lat'])
    return pubs