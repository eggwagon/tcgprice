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
                name = card["name"].lower()
                if name not in card_database:
                    card_database[name] = []
                card_database[name].append(card)
            
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

@app.get("/price/{card_name:path}")
async def get_card_price(card_name: str, set: str = None):
    """
    Retrieves pricing information. Optional 'set' parameter filters by set code or set name.
    """
    if not card_database:
        raise HTTPException(status_code=503, detail="The database is still initializing. Please wait a moment.")

    # Normalize slashes to match Scryfall's " // " format for split cards
    # and convert to lowercase for the dictionary lookup.
    name_query = card_name.replace("//", " // ").replace("  //  ", " // ").lower().strip()
    
    versions = card_database.get(name_query)

    # Fallback to starts-with search if no exact match found
    if not versions:
        # Find the first card name that starts with the user's query
        matching_key = next((name for name in card_database.keys() if name.startswith(name_query)), None)
        if matching_key:
            versions = card_database[matching_key]

    if not versions:
        raise HTTPException(status_code=404, detail="Card not found in the local dataset.")

    # Filter by set if provided
    if set:
        set_query = set.lower()
        # Search through versions for a match on set code or set name
        matched = [c for c in versions if c["set"].lower() == set_query or c["set_name"].lower() == set_query]
        
        if not matched:
            raise HTTPException(status_code=404, detail=f"Card '{card_name}' found, but no printing exists for set '{set}'.")
        data = matched[0]
    else:
        # Default to the first printing if no set is specified
        data = versions[0]

    # Extract and return the card info
    return {
        "name": data.get("name"),
        "set_name": data.get("set_name"),
        "set_code": data.get("set"),
        "prices": data.get("prices", {}),
        "scryfall_uri": data.get("scryfall_uri"),
        "image": data.get("image_uris", {}).get("normal")
    }