from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from device_auth import verify_device
from fastapi.security import OAuth2PasswordRequestForm
from auth import create_access_token, get_current_admin
from fastapi.responses import HTMLResponse
import os
import psycopg2
import psycopg2
import os
import shutil
import uuid
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Smart Gate Cloud")
SECRET_KEY = "CHANGE_THIS_TO_A_LONG_RANDOM_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


# =========================
# DATABASE
# =========================

def get_db_connection():
    database_url = os.environ.get("postgresql://smart_gate_db_ar45_user:0ki4C8MKH5kT5IeB3gU8S1eqYcyojOaq@dpg-da69tpjm8hqs73eo5uc0-a/smart_gate_db_ar45")

    if not database_url:
        raise Exception("DATABASE_URL environment variable is missing")

    return psycopg2.connect(database_url)


# =========================
# MODELS
# =========================

class AccessRequest(BaseModel):
    card_uid: str


class UserRequest(BaseModel):
    name: str
    card_uid: str


class UserStatusRequest(BaseModel):
    active: bool


# =========================
# HOME
# =========================

@app.get("/")
def home():
    return {
        "message": "Smart Gate Cloud is running"
    }


@app.get("/api/health")
def health():
    return {
        "status": "online"
    }


# =========================
# RFID ACCESS
# =========================

@app.post("/api/access")
def record_access(
    data: AccessRequest,
    device: bool = Depends(verify_device)
):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT name, active
        FROM users
        WHERE card_uid = %s
        """,
        (data.card_uid,)
    )

    user = cursor.fetchone()

    if user:
        name, active = user
        status = "GRANTED" if active else "DENIED"
    else:
        name = "Unknown"
        status = "DENIED"

    cursor.execute(
        """
        INSERT INTO access_logs
        (card_uid, name, status)
        VALUES (%s, %s, %s)
        """,
        (data.card_uid, name, status)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return {
        "card_uid": data.card_uid,
        "name": name,
        "status": status
    }


# =========================
# GET ACCESS LOGS
# =========================

@app.get("/api/access-logs")
def get_access_logs(
    limit: int = 100,
    admin: str = Depends(get_current_admin)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            card_uid,
            name,
            access_date,
            access_time,
            status,
            photo_url
        FROM access_logs
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,)
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    logs = []

    for row in rows:
        logs.append({
            "id": row[0],
            "card_uid": row[1],
            "name": row[2],
            "date": str(row[3]),
            "time": str(row[4]),
            "status": row[5],
            "photo_url": row[6]
        })

    return {
        "total": len(logs),
        "logs": logs
    }


# =========================
# ADD USER / RFID CARD
# =========================

@app.post("/api/users")
def add_user(
    data: UserRequest,
    admin: str = Depends(get_current_admin)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO users (name, card_uid)
            VALUES (%s, %s)
            RETURNING id
            """,
            (data.name, data.card_uid)
        )

        user_id = cursor.fetchone()[0]

        conn.commit()

        return {
            "message": "User added",
            "id": user_id,
            "name": data.name,
            "card_uid": data.card_uid
        }

    except psycopg2.errors.UniqueViolation:

        conn.rollback()

        raise HTTPException(
            status_code=409,
            detail="Card UID already registered"
        )

    finally:

        cursor.close()
        conn.close()


# =========================
# GET USERS
# =========================

@app.get("/api/users")
def get_users(
    admin: str = Depends(get_current_admin)
):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, name, card_uid, active, created_at
        FROM users
        ORDER BY id DESC
        """
    )

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    users = []

    for row in rows:
        users.append({
            "id": row[0],
            "name": row[1],
            "card_uid": row[2],
            "active": row[3],
            "created_at": str(row[4])
        })

    return {
        "users": users
    }


# =========================
# ENABLE / DISABLE CARD
# =========================

@app.patch("/api/users/{user_id}/status")
def update_user_status(
    user_id: int,
    data: UserStatusRequest,
    admin: str = Depends(get_current_admin)
):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET active = %s
        WHERE id = %s
        RETURNING id, name, card_uid, active
        """,
        (data.active, user_id)
    )

    user = cursor.fetchone()

    conn.commit()

    cursor.close()
    conn.close()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "id": user[0],
        "name": user[1],
        "card_uid": user[2],
        "active": user[3]
    }


# =========================
# PHOTO UPLOAD
# =========================

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/upload-photo")
async def upload_photo(
    log_id: int,
    file: UploadFile = File(...)
):

    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp"
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG and WEBP images are allowed"
        )

    # Check whether access log exists
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM access_logs
        WHERE id = %s
        """,
        (log_id,)
    )

    log = cursor.fetchone()

    if not log:
        cursor.close()
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Access log not found"
        )

    # Unique filename
    extension = os.path.splitext(file.filename)[1].lower()

    filename = f"{log_id}_{uuid.uuid4()}{extension}"

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    # Save photo
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer
        )

    # Save photo path in database
    cursor.execute(
        """
        UPDATE access_logs
        SET photo_url = %s
        WHERE id = %s
        """,
        (file_path, log_id)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return {
        "message": "Photo uploaded and linked successfully",
        "log_id": log_id,
        "filename": filename,
        "photo_url": file_path
    }

    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp"
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG and WEBP images are allowed"
        )

    extension = os.path.splitext(file.filename)[1].lower()

    filename = f"{uuid.uuid4()}{extension}"

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer
        )

    return {
        "message": "Photo uploaded successfully",
        "filename": filename,
        "path": file_path
    }
# =========================
# ADMIN LOGIN
# =========================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "SmartGate@123"


@app.post("/api/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):

    if (
        form_data.username != ADMIN_USERNAME
        or form_data.password != ADMIN_PASSWORD
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    token = create_access_token(form_data.username)

    return {
        "access_token": token,
        "token_type": "bearer"
    }
# =========================
# WEB PAGES
# =========================

@app.get("/login", response_class=HTMLResponse)
def login_page():

    with open("templates/login.html", "r") as file:
        return file.read()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page():

    with open("templates/dashboard.html", "r") as file:
        return file.read()
# =========================
# ESP32 RFID API
# =========================

@app.post("/api/device/rfid-scan")
def device_rfid_scan(
    data: AccessRequest,
    device: bool = Depends(verify_device)
):

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            SELECT name, active
            FROM users
            WHERE card_uid = %s
            """,
            (data.card_uid,)
        )

        user = cursor.fetchone()

        if user:
            name, active = user

            if active:
                status = "GRANTED"
            else:
                status = "DENIED"

        else:
            name = "Unknown"
            status = "DENIED"

        cursor.execute(
            """
            INSERT INTO access_logs
            (card_uid, name, status)
            VALUES (%s, %s, %s)
            RETURNING id, access_date, access_time
            """,
            (data.card_uid, name, status)
        )

        log = cursor.fetchone()

        conn.commit()

        return {
            "success": True,
            "log_id": log[0],
            "card_uid": data.card_uid,
            "name": name,
            "date": str(log[1]),
            "time": str(log[2]),
            "status": status
        }

    finally:

        cursor.close()
        conn.close()
