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
async def root(lat, lng):
    pub_names = []
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}&in=circle:{lat},{lng};r=1000&apiKey={HERE_API}")
    for item in response.json()['items']:
        pub_names.append(item['title'])
    return pub_names