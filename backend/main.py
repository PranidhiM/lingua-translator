
import hashlib
import logging
import os
import secrets
import smtplib
from fastapi.middleware.cors import CORSMiddlewa
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
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
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


# =========================================================
# 1. CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'translator.db'}",
)

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is missing. Add it to backend/.env")

JWT_ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.getenv("TOKEN_MINUTES", "60"))
RESET_LINK_MINUTES = 30
MODEL_NAME = "facebook/nllb-200-distilled-600M"

LANGUAGES = {
    "en": {"name": "English", "code": "eng_Latn"},
    "hi": {"name": "Hindi", "code": "hin_Deva"},
    "te": {"name": "Telugu", "code": "tel_Telu"},
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =========================================================
# 2. DATABASE SETUP
# =========================================================

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# 3. DATABASE MODELS
# =========================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Translation(Base):
    __tablename__ = "translations"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    source_language: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    target_language: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


Base.metadata.create_all(bind=engine)


# =========================================================
# 4. FASTAPI APP AND CORS
# =========================================================

app = FastAPI(
    title="English Hindi Telugu Translator API",
    version="1.0.0",
    description=(
        "Translator with authentication, translation history, "
        "analytics, password reset and admin statistics."
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "https://lingua-translator.vercel.app",
        "https://lingua-translator-jejqrbbxf-pranidhimar-4710s-projects.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# =========================================================
# 5. REQUEST AND RESPONSE SCHEMAS
# =========================================================

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    source_language: str
    target_language: str


class TranslationResponse(BaseModel):
    id: int
    source_language: str
    target_language: str
    source_text: str
    translated_text: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)


class PasswordResetResponse(BaseModel):
    message: str


# =========================================================
# 6. AUTHENTICATION HELPERS
# =========================================================

security = HTTPBearer(auto_error=False)


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(
        minutes=TOKEN_MINUTES
    )
    payload = {"sub": str(user_id), "exp": expires}
    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


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
        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token.",
            )

        user = db.get(User, int(user_id))

    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token.",
        )

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User account not found.",
        )

    return user


# =========================================================
# 7. PASSWORD RESET HELPERS
# =========================================================

def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_reset_email(email: str, token: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL")

    frontend_url = os.getenv(
        "FRONTEND_URL",
        "http://localhost:5173",
    ).rstrip("/")

    missing = [
        name
        for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USER": smtp_user,
            "SMTP_PASSWORD": smtp_password,
            "FROM_EMAIL": from_email,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing email settings: " + ", ".join(missing)
        )

    reset_url = f"{frontend_url}/?reset_token={token}"

    message = EmailMessage()
    message["Subject"] = "Reset your Translator password"
    message["From"] = from_email
    message["To"] = email

    message.set_content(
        "A password reset was requested for your Translator account.\n\n"
        f"Open this link to reset your password:\n{reset_url}\n\n"
        f"This link expires in {RESET_LINK_MINUTES} minutes and can "
        "only be used once.\n"
        "If you did not request this, ignore this email."
    )

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=20,
    ) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


# =========================================================
# 8. HUGGING FACE TRANSLATION MODEL
# =========================================================

@lru_cache(maxsize=1)
def load_translation_model():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    model.eval()
    return tokenizer, model


def translate_text(
    text: str,
    source_language: str,
    target_language: str,
) -> str:
    if source_language not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported source language.",
        )

    if target_language not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported target language.",
        )

    if source_language == target_language:
        return text

    try:
        tokenizer, model = load_translation_model()

        tokenizer.src_lang = LANGUAGES[source_language]["code"]

        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )

        target_token_id = tokenizer.convert_tokens_to_ids(
            LANGUAGES[target_language]["code"]
        )

        with torch.inference_mode():
            generated_tokens = model.generate(
                **inputs,
                forced_bos_token_id=target_token_id,
                max_new_tokens=512,
            )

        return tokenizer.batch_decode(
            generated_tokens,
            skip_special_tokens=True,
        )[0]

    except HTTPException:
        raise

    except Exception:
        logger.exception("Translation failed")
        raise HTTPException(
            status_code=500,
            detail=(
                "Translation failed. Check the model download, "
                "network connection and backend logs."
            ),
        )


# =========================================================
# 9. BASIC ENDPOINTS
# =========================================================

@app.get("/")
def root():
    return {"message": "Translator API is running."}


@app.get("/api/health")
def health():
    return {"status": "healthy"}


@app.get("/api/languages")
def get_languages():
    return LANGUAGES


# =========================================================
# 10. REGISTER
# =========================================================

@app.post("/api/auth/register", status_code=201)
def register(
    data: RegisterRequest,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower().strip()

    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )

    password_hash = bcrypt.hashpw(
        data.password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    user = User(
        email=email,
        password_hash=password_hash,
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)

    except Exception:
        db.rollback()
        logger.exception("Registration failed")
        raise HTTPException(
            status_code=500,
            detail="Registration failed.",
        )

    return {
        "message": "Registration successful.",
        "user_id": user.id,
        "email": user.email,
    }


# =========================================================
# 11. LOGIN
# =========================================================

@app.post("/api/auth/login", response_model=TokenResponse)
def login(
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    email = str(data.email).lower().strip()

    user = db.scalar(
        select(User).where(User.email == email)
    )

    password_valid = False

    if user:
        try:
            password_valid = bcrypt.checkpw(
                data.password.encode("utf-8"),
                user.password_hash.encode("utf-8"),
            )
        except (ValueError, TypeError):
            password_valid = False

    if not user or not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password.",
        )

    return TokenResponse(
        access_token=create_access_token(user.id),
        user_id=user.id,
        email=user.email,
    )



# =========================================================
# 15. FORGOT PASSWORD
# =========================================================

# =========================================================
# FORGOT PASSWORD
# =========================================================

@app.post(
    "/api/auth/forgot-password",
    response_model=PasswordResetResponse,
)
def forgot_password(
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    generic_message = (
        "If an account exists for that email, "
        "a password-reset link will be sent."
    )

    email = str(data.email).strip().lower()

    # Find the registered user.
    try:
        user = db.scalar(
            select(User).where(User.email == email)
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to look up password-reset account")
        raise HTTPException(
            status_code=500,
            detail="Unable to process the password-reset request.",
        )

    # Do not reveal whether an email is registered.
    if user is None:
        return PasswordResetResponse(message=generic_message)

    now = datetime.now(timezone.utc)

    try:
        # Invalidate previous unused reset tokens.
        previous_tokens = db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ).all()

        for old_token in previous_tokens:
            old_token.used_at = now

        # Generate a secure, one-time reset token.
        raw_token = secrets.token_urlsafe(32)

        reset_record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(
                minutes=RESET_LINK_MINUTES
            ),
        )

        # Save the hashed token before sending the email.
        db.add(reset_record)
        db.commit()
        db.refresh(reset_record)

    except Exception:
        db.rollback()
        logger.exception("Failed to create password-reset token")
        raise HTTPException(
            status_code=500,
            detail="Could not create the password-reset request.",
        )

    try:
        # Send the reset link using SMTP.
        send_reset_email(user.email, raw_token)

    except Exception:
        logger.exception("Failed to send password-reset email")

        # Invalidate the token if sending the email fails.
        try:
            reset_record.used_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to invalidate reset token")

        raise HTTPException(
            status_code=500,
            detail=(
                "Password-reset email could not be sent. "
                "Check SMTP settings in backend/.env "
                "and the backend terminal."
            ),
        )

    return PasswordResetResponse(message=generic_message)
"""

@app.post(
    "/api/auth/forgot-password",
    response_model=PasswordResetResponse,
)
def forgot_password(
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    generic_message = (
        "If an account exists for that email, "
        "a password-reset link will be sent."
    )

    email = str(data.email).strip().lower()

    try:
        # Find the registered user.
        user = db.scalar(
            select(User).where(User.email == email)
        )

        # Do not reveal whether an email is registered.
        if user is None:
            return {"message": generic_message}

        now = datetime.now(timezone.utc)

        # Invalidate previous unused reset links.
        previous_tokens = db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ).all()

        for old_token in previous_tokens:
            old_token.used_at = now

        # Generate a secure, one-time reset token.
        raw_token = secrets.token_urlsafe(32)

        reset_record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(
                minutes=RESET_LINK_MINUTES
            ),
        )

        # Save the hashed token in SQL before sending email.
        db.add(reset_record)
        db.commit()
        db.refresh(reset_record)

    except Exception:
        db.rollback()
        logging.exception(
            "Database error while creating password reset token"
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not create the password reset request. "
                "Check the backend logs."
            ),
        )

    try:
        # Send the reset link using Gmail SMTP.
        send_reset_email(user.email, raw_token)

        return {"message": generic_message}

    except Exception:
        logging.exception(
            "Failed to send password reset email"
        )

        # Disable the token because its email was not delivered.
        try:
            reset_record.used_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            logging.exception(
                "Could not invalidate the failed reset token"
            )

        raise HTTPException(
            status_code=500,
            detail=(
                "Password reset email could not be sent. "
                "Check SMTP settings in backend/.env "
                "and the backend terminal."
            ),
        )
"""

# =========================================================
# 13. RESET PASSWORD
# =========================================================

@app.post(
    "/api/auth/reset-password",
    response_model=PasswordResetResponse,
)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    token_hash = hash_reset_token(payload.token)

    reset_record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
    )

    if reset_record is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or already-used reset link.",
        )

    now = datetime.now(timezone.utc)
    expiry = reset_record.expires_at

    # SQLite may return a datetime without timezone information.
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry <= now:
        reset_record.used_at = now
        db.commit()

        raise HTTPException(
            status_code=400,
            detail="This reset link has expired. Request a new one.",
        )

    user = db.get(User, reset_record.user_id)

    if user is None:
        raise HTTPException(
            status_code=400,
            detail="The account associated with this link no longer exists.",
        )

    try:
        user.password_hash = bcrypt.hashpw(
            payload.new_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("utf-8")

        outstanding_tokens = db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ).all()

        for record in outstanding_tokens:
            record.used_at = now

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Password reset failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to reset the password.",
        )

    return {
        "message": "Password reset successfully. Please log in."
    }


# =========================================================
# 14. TRANSLATE AND SAVE
# =========================================================

@app.post("/api/translate", response_model=TranslationResponse)
def translate(
    data: TranslateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source_language = data.source_language.lower().strip()
    target_language = data.target_language.lower().strip()
    source_text = data.text.strip()

    if not source_text:
        raise HTTPException(
            status_code=400,
            detail="Please enter text to translate.",
        )

    translated_text = translate_text(
        source_text,
        source_language,
        target_language,
    )

    translation = Translation(
        user_id=current_user.id,
        source_language=source_language,
        target_language=target_language,
        source_text=source_text,
        translated_text=translated_text,
    )

    try:
        db.add(translation)
        db.commit()
        db.refresh(translation)

    except Exception:
        db.rollback()
        logger.exception("Saving translation failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to save the translation.",
        )

    return translation


# =========================================================
# 15. TRANSLATION HISTORY
# =========================================================

@app.get(
    "/api/history",
    response_model=list[TranslationResponse],
)
def get_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Translation)
        .where(Translation.user_id == current_user.id)
        .order_by(Translation.id.desc())
        .limit(500)
    ).all()


@app.delete("/api/history/{translation_id}")
def delete_history_item(
    translation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    translation = db.scalar(
        select(Translation).where(
            Translation.id == translation_id,
            Translation.user_id == current_user.id,
        )
    )

    if translation is None:
        raise HTTPException(
            status_code=404,
            detail="Translation not found.",
        )

    db.delete(translation)
    db.commit()

    return {"message": "Translation deleted successfully."}


@app.delete("/api/history")
def clear_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    translations = db.scalars(
        select(Translation).where(
            Translation.user_id == current_user.id
        )
    ).all()

    deleted_count = len(translations)

    for translation in translations:
        db.delete(translation)

    db.commit()

    return {
        "message": "Translation history cleared.",
        "deleted_count": deleted_count,
    }


# =========================================================
# 16. USER ANALYTICS
# =========================================================

@app.get("/api/analytics")
def analytics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total_translations = db.scalar(
        select(func.count(Translation.id)).where(
            Translation.user_id == current_user.id
        )
    ) or 0

    language_pairs = db.execute(
        select(
            Translation.source_language,
            Translation.target_language,
            func.count(Translation.id),
        )
        .where(Translation.user_id == current_user.id)
        .group_by(
            Translation.source_language,
            Translation.target_language,
        )
        .order_by(func.count(Translation.id).desc())
    ).all()

    daily_activity = db.execute(
        select(
            func.date(Translation.created_at),
            func.count(Translation.id),
        )
        .where(Translation.user_id == current_user.id)
        .group_by(func.date(Translation.created_at))
        .order_by(func.date(Translation.created_at))
    ).all()

    return {
        "total_translations": total_translations,
        "language_pairs": [
            {
                "source_language": source,
                "target_language": target,
                "count": count,
            }
            for source, target, count in language_pairs
        ],
        "daily_activity": [
            {
                "date": str(day),
                "count": count,
            }
            for day, count in daily_activity
        ],
    }


# =========================================================
# 17. ADMIN REGISTRATION ANALYTICS
# =========================================================

@app.get("/api/admin/registrations")
def registration_analytics(
    admin: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    admin_email = os.getenv(
        "ADMIN_EMAIL", ""
    ).lower().strip()

    if not admin_email or admin.email.lower() != admin_email:
        raise HTTPException(
            status_code=403,
            detail="Administrator access required.",
        )

    total_users = db.scalar(
        select(func.count(User.id))
    ) or 0

    daily_rows = db.execute(
        select(
            func.date(User.created_at),
            func.count(User.id),
        )
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
    ).all()

    recent_users = db.scalars(
        select(User)
        .order_by(User.id.desc())
        .limit(100)
    ).all()

    return {
        "total_registered_users": total_users,
        "registrations_by_day": [
            {
                "date": str(day),
                "count": count,
            }
            for day, count in daily_rows
        ],
        "recent_users": [
            {
                "id": user.id,
                "email": user.email,
                "registered_at": user.created_at,
            }
            for user in recent_users
        ],
    }
