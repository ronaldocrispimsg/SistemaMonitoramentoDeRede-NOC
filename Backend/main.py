from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import os
from Backend.database import engine, SessionLocal
from Backend.models import Base, User
from Backend.monitor_engine import monitor_engine
from Backend.routes.hosts import router
from Backend.snmp_engine import reset_snmp_backoff
from Backend.security import hash_password
from Backend.mq_manager import mq_manager

Base.metadata.create_all(bind=engine)

def create_default_admin():
    db = SessionLocal()
    try:
        default_admin_password = os.getenv("NOC_DEFAULT_ADMIN_PASSWORD")
        if not default_admin_password:
            print("Banco de dados: NOC_DEFAULT_ADMIN_PASSWORD não configurada. Usuário admin padrão não será criado.")
            return

        if not db.query(User).filter(User.username == "admin").first():
            novo_admin = User(
                username="admin",
                password_hash=hash_password(default_admin_password),
                must_change_password=True
            )
            db.add(novo_admin)
            db.commit()
            print("Banco de dados: usuario admin criado com sucesso!")
        else:
            print("Banco de dados: usuario admin já existe.")
    finally:
        db.close()

create_default_admin()



@asynccontextmanager
async def lifespan(app: FastAPI):
    reset_snmp_backoff()
    await mq_manager.connect()
    await mq_manager.start_consumers()
    await monitor_engine.start()
    try:
        yield
    finally:
        await monitor_engine.stop()
        await mq_manager.close()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
