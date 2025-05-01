from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from db import get_all_stats, get_sandwich_highlights, get_sandwich_by_id
import uvicorn

app = FastAPI(
    title="Sandwich Attack Statistics API",
    description="API for retrieving statistics about sandwich attacks on Solana DEXs",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")

@app.get("/stats", 
         summary="Get all statistics",
         description="Retrieves comprehensive statistics about sandwich attacks including profit token stats, most targeted tokens, programs, pools, and bot profits.")
async def get_stats():
    return await get_all_stats()

@app.get("/highlights",
         summary="Get sandwich highlights",
         description="Retrieves highlights of sandwich attacks including the most profitable sandwiches and the latest sandwiches.")
async def get_highlights():
    return await get_sandwich_highlights()

@app.get("/sandwiches/{sandwich_id}",
         summary="Get sandwich details",
         description="Retrieves detailed information about a specific sandwich attack by its ID.")
async def get_sandwich(sandwich_id: str):
    sandwich = await get_sandwich_by_id(sandwich_id)
    if not sandwich:
        raise HTTPException(status_code=404, detail="Sandwich not found")
    return sandwich

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True) 