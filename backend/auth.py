import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from backend.database import get_db, User

router = APIRouter(tags=["auth"])

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def _generate_token() -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_hex(32)  # 64-char hex string


# ---- Signup ----
@router.post("/signup")
def signup(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == form_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    token = _generate_token()
    user = User(
        username=form_data.username,
        hashed_password=pwd_context.hash(form_data.password),
        auth_token=token,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"access_token": token, "token_type": "bearer", "user_id": user.id}


# ---- Login ----
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Rotate token on each login for better security
    user.auth_token = _generate_token()
    db.commit()
    db.refresh(user)

    return {"access_token": user.auth_token, "token_type": "bearer", "user_id": user.id}


# ---- Token verification dependency ----
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """Look up the user by their stored auth token."""
    user = db.query(User).filter(User.auth_token == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
