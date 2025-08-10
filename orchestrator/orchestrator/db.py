import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


from .config import settings

DATABASE_URL = os.getenv("DATABASE_URL", settings.database_url)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()
