from fastapi import FastAPI, HTTPException
import httpx
import logging
from contextlib import asynccontextmanager

# Setup logging to track the download and indexing process
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory dictionary to store card data for fast lookup
card_database = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup logic to download the latest bulk JSON and index it.
    """
    logger.info("Initializing: Fetching Scryfall bulk data information...")
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            # 1. Query Scryfall's bulk data endpoint for 'default-cards'
            bulk_meta_res = await client.get("https://api.scryfall.com/bulk-data/default-cards")
            bulk_meta_res.raise_for_status()
            download_uri = bulk_meta_res.json()["download_uri"]

            # 2. Download the actual JSON dataset
            logger.info(f"Downloading dataset from {download_uri}...")
            response = await client.get(download_uri)
            response.raise_for_status()
            
            # 3. Parse JSON and index it by name (lowercase for case-insensitive search)
            cards = response.json()
            for card in cards:
                card_database[card["name"].lower()] = card
            
            logger.info(f"Ready. Indexed {len(card_database)} cards in memory.")
        except Exception as e:
            logger.error(f"Critical error during startup data load: {e}")
    
    yield
    # Clear memory on shutdown
    card_database.clear()

app = FastAPI(
    title="TCG Price API", 
    description="A simple API using local card data from Scryfall bulk JSON",
    lifespan=lifespan
)

@app.get("/")
async def root():
    status = "Ready" if card_database else "Data loading..."
    return {"message": f"TCG Price API is {status}. Use /price/{{card_name}} to search."}

@app.get("/price/{card_name}")
async def get_card_price(card_name: str):
    """
    Retrieves pricing information from the locally indexed JSON data.
    """
    if not card_database:
        raise HTTPException(status_code=503, detail="The database is still initializing. Please wait a moment.")

    name_query = card_name.lower()
    
    # Perform an exact name match (case-insensitive)
    data = card_database.get(name_query)
    
    if not data:
        raise HTTPException(status_code=404, detail="Card not found in the local dataset.")

    # Extract and return the card info
    return {
        "name": data.get("name"),
        "set_name": data.get("set_name"),
        "prices": data.get("prices", {}),
        "scryfall_uri": data.get("scryfall_uri"),
        "image": data.get("image_uris", {}).get("normal")
    }
