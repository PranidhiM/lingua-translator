
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import bcrypt
import torch
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


# --------------------------------------------------
# Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'translator.db'}",
)
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("Set JWT_SECRET in backend/.env")

JWT_ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.getenv("TOKEN_MINUTES", "60"))

MODEL_NAME = "facebook/nllb-200-distilled-600M"

LANGUAGES = {
    "en": {"name": "English", "code": "eng_Latn"},
    "hi": {"name": "Hindi", "code": "hin_Deva"},
    "te": {"name": "Telugu", "code": "tel_Telu"},
}


# --------------------------------------------------
# Database
# --------------------------------------------------

class Base(DeclarativeBase):
    pass


connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Translation(Base):
    __tablename__ = "translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    source_language: Mapped[str] = mapped_column(String(10), nullable=False)
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------
# Request/response schemas
# --------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str


class TranslateRequest(BaseModel):
    source_language: str = "en"
    target_language: str = "hi"
    text: str = Field(min_length=1, max_length=5000)


class TranslationResponse(BaseModel):
    id: int
    source_language: str
    target_language: str
    source_text: str
    translated_text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------
# Authentication
# --------------------------------------------------

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue.",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found.",
        )
    return user


# --------------------------------------------------
# Hugging Face translation model
# --------------------------------------------------

@lru_cache(maxsize=1)
def load_translation_model():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    model.eval()
    return tokenizer, model


def translate_text(text: str, source: str, target: str) -> str:
    if source not in LANGUAGES or target not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Choose English, Hindi, or Telugu.",
        )

    if source == target:
        return text

    try:
        tokenizer, model = load_translation_model()
        tokenizer.src_lang = LANGUAGES[source]["code"]

        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        target_id = tokenizer.convert_tokens_to_ids(
            LANGUAGES[target]["code"]
        )

        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=target_id,
                max_new_tokens=512,
                num_beams=4,
            )

        return tokenizer.batch_decode(
            generated,
            skip_special_tokens=True,
        )[0]

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Translation model error: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Translation model could not be loaded. "
                "Check your internet connection, model download, "
                "and available memory, then retry."
            ),
        )


# --------------------------------------------------
# FastAPI application and CORS
# --------------------------------------------------

app = FastAPI(
    title="Universal Translator API",
    version="1.0.0",
    description="Translation, authentication, history, and analytics.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Universal Translator API is running"}


@app.get("/api/health")
def health():
    return {"status": "ok", "database": "configured"}


@app.get("/api/languages")
def get_languages():
    return {
        key: value["name"]
        for key, value in LANGUAGES.items()
    }


# --------------------------------------------------
# Registration and login
# --------------------------------------------------

@app.post("/api/auth/register", status_code=201)
def register(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower().strip()

    existing = db.scalar(
        select(User).where(User.email == email)
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    password_hash = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.commit()

    return {"message": "Registration successful. Please log in."}


@app.post("/api/auth/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower().strip()
    user = db.scalar(
        select(User).where(User.email == email)
    )

    if user is None or not bcrypt.checkpw(
        data.password.encode("utf-8"),
        user.password_hash.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password.",
        )

    return TokenResponse(
        access_token=create_access_token(user.id),
        email=user.email,
    )


# --------------------------------------------------
# Translation and persistent history
# --------------------------------------------------

@app.post("/api/translate", response_model=TranslationResponse)
def translate(
    data: TranslateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = data.source_language
    target = data.target_language
    text = data.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Enter text to translate.")

    if source not in LANGUAGES or target not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported language selection.",
        )

    result = translate_text(text, source, target)

    record = Translation(
        user_id=user.id,
        source_language=source,
        target_language=target,
        source_text=text,
        translated_text=result,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return record


@app.get("/api/history", response_model=list[TranslationResponse])
def history(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))

    return list(
        db.scalars(
            select(Translation)
            .where(Translation.user_id == user.id)
            .order_by(Translation.id.desc())
            .limit(limit)
        ).all()
    )


@app.delete("/api/history/{translation_id}")
def delete_history(
    translation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.scalar(
        select(Translation).where(
            Translation.id == translation_id,
            Translation.user_id == user.id,
        )
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Translation not found.")

    db.delete(record)
    db.commit()
    return {"message": "Translation deleted."}


# --------------------------------------------------
# Data science analytics
# --------------------------------------------------

@app.get("/api/analytics")
def analytics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.scalar(
        select(func.count(Translation.id)).where(
            Translation.user_id == user.id
        )
    ) or 0

    language_rows = db.execute(
        select(
            Translation.source_language,
            Translation.target_language,
            func.count(Translation.id),
        )
        .where(Translation.user_id == user.id)
        .group_by(
            Translation.source_language,
            Translation.target_language,
        )
        .order_by(func.count(Translation.id).desc())
    ).all()

    daily_rows = db.execute(
        select(
            func.date(Translation.created_at),
            func.count(Translation.id),
        )
        .where(Translation.user_id == user.id)
        .group_by(func.date(Translation.created_at))
        .order_by(func.date(Translation.created_at))
    ).all()

    return {
        "total_translations": total,
        "language_pairs": [
            {
                "source": LANGUAGES.get(source, {}).get("name", source),
                "target": LANGUAGES.get(target, {}).get("name", target),
                "count": count,
            }
            for source, target, count in language_rows
        ],
        "daily_activity": [
            {"date": str(day), "count": count}
            for day, count in daily_rows
        ],
    }
