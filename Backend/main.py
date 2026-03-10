from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Backend.database import engine
from Backend.models import Base
from Backend.monitor_engine import monitor_engine
from Backend.routes.hosts import router

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await monitor_engine.start()
    try:
        yield
    finally:
        await monitor_engine.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
