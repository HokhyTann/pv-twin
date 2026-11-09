from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.routers import assets, health, sites

app = FastAPI(title="PV Digital Twin API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Layout payloads are large and repetitive JSON (~5-10x smaller gzipped).
app.add_middleware(GZipMiddleware, minimum_size=1024)

for r in (health.router, sites.router, assets.router):
    app.include_router(r, prefix="/api/v1")
