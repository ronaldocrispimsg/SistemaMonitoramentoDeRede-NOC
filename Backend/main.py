from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from Backend.database import engine
from Backend.models import Base
from Backend.routes.hosts import router
from Backend.scheduler import start_scheduler

Base.metadata.create_all(bind=engine)


app = FastAPI()
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Permite que o seu HTML acesse a API
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    start_scheduler()