import os
import time
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://netspot:netspot_password@localhost:5432/netspot")
logger = logging.getLogger("netspot.database")

# Engine síncrono (para endpoints FastAPI síncronos)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,    # PING PREVENTIVO: Testa conexão antes de reusar do pool
    pool_recycle=1800,     # RECICLAGEM AUTOMÁTICA: Recicla conexões a cada 30 min (1800s)
    pool_size=20,          # Tamanho base do pool de conexões
    max_overflow=10,       # Conexões extras temporárias para picos de tráfego
    pool_timeout=30        # Tempo máximo de espera por uma conexão livre
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Engine assíncrono (para monitoramento e scheduler assíncronos)
ASYNC_DATABASE_URL = DATABASE_URL
if ASYNC_DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = ASYNC_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

def wait_for_database(max_retries: int = 15, delay_seconds: float = 2.0) -> bool:
    """
    Loop de retentativa para aguardar a inicializacao do PostgreSQL antes
    de executar migracoes, criacao de tabelas ou aceitar requisicoes HTTP.
    """
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Conexão com PostgreSQL estabelecida com sucesso!")
            return True
        except Exception as e:
            logger.warning(
                f"Aguardando PostgreSQL ({attempt}/{max_retries}): {e}. Retentando em {delay_seconds}s..."
            )
            time.sleep(delay_seconds)
    logger.error("Falha ao conectar no PostgreSQL após várias tentativas.")
    return False

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
