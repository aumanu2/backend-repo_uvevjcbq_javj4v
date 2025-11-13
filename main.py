import os
import time
import random
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from database import db, create_document
from schemas import Userprofile, Message, Matchrequest, Otp
import stripe
from jose import jwt, JWTError

# Stripe setup
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Auth config
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "super-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7  # 7 days

app = FastAPI(title="ASN Location Swap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------- Models -----------------
class CheckoutSessionRequest(BaseModel):
    email: EmailStr


class ProfileCreateRequest(Userprofile):
    pass


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    nip: Optional[str] = None
    agency: Optional[str] = None
    position: Optional[str] = None
    grade: Optional[str] = None
    current_region: Optional[str] = None
    desired_region: Optional[str] = None


class SendMessageRequest(BaseModel):
    to_email: EmailStr
    content: str


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    code: str


# ----------------- Utils -----------------
def create_access_token(email: str) -> str:
    now = int(time.time())
    payload = {"sub": email, "iat": now, "exp": now + ACCESS_TOKEN_EXPIRE_SECONDS}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("Invalid auth scheme")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except (ValueError, JWTError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/")
def root():
    return {"message": "ASN Location Swap API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# ----------------- Auth (OTP) -----------------
@app.post("/api/auth/request-otp")
def request_otp(req: OTPRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    code = f"{random.randint(0, 999999):06d}"
    expires_at = int(time.time()) + 600  # 10 minutes
    db["otp"].delete_many({"email": req.email})
    create_document("otp", {"email": req.email, "code": code, "purpose": "login", "expires_at": expires_at})
    # In production, send the code via email provider. For dev/demo, we return it.
    return {"status": "ok", "message": "OTP generated. Check your email.", "debug_code": code}


@app.post("/api/auth/verify-otp")
def verify_otp(req: OTPVerify):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    rec = db["otp"].find_one({"email": req.email, "code": req.code})
    if not rec:
        raise HTTPException(status_code=400, detail="Kode OTP tidak valid")
    if int(time.time()) > int(rec.get("expires_at", 0)):
        db["otp"].delete_many({"email": req.email})
        raise HTTPException(status_code=400, detail="Kode OTP kedaluwarsa")
    db["otp"].delete_many({"email": req.email})
    token = create_access_token(req.email)
    return {"access_token": token, "token_type": "bearer", "email": req.email}


@app.get("/api/me")
def me(email: str = Depends(get_current_user)):
    return {"email": email}


# ----------------- Stripe Checkout -----------------
@app.post("/api/checkout/session")
def create_checkout_session(payload: CheckoutSessionRequest):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            customer_email=payload.email,
            line_items=[
                {
                    "price_data": {
                        "currency": "idr",
                        "product_data": {
                            "name": "Langganan ASN Swap",
                            "description": "Akses fitur pencarian, match, dan chat"
                        },
                        "unit_amount": 5000000,
                        "recurring": {"interval": "month"}
                    },
                    "quantity": 1,
                }
            ],
            success_url=os.getenv("FRONTEND_URL", "http://localhost:3000") + "/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=os.getenv("FRONTEND_URL", "http://localhost:3000") + "/",
        )
        return {"id": session.id, "url": session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------------- Profiles -----------------
@app.post("/api/profile", response_model=dict)
def create_or_update_profile(profile: ProfileCreateRequest, email: str = Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Enforce email from token
    data = profile.model_dump()
    data["email"] = email
    existing = db["userprofile"].find_one({"email": email})
    if existing:
        db["userprofile"].update_one({"email": email}, {"$set": data})
        return {"status": "updated"}
    else:
        create_document("userprofile", data)
        return {"status": "created"}


@app.get("/api/profile/{email}")
def get_profile(email: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["userprofile"].find_one({"email": email}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return doc


# ----------------- Search & Match -----------------
@app.get("/api/search")
def search_profiles(
    desired_region: Optional[str] = Query(None, description="Cari user yang menginginkan daerah ini"),
    current_region: Optional[str] = Query(None, description="Filter berdasarkan daerah kerja saat ini"),
    agency: Optional[str] = Query(None, description="Filter instansi"),
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    q = {}
    if desired_region:
        q["desired_region"] = {"$regex": desired_region, "$options": "i"}
    if current_region:
        q["current_region"] = {"$regex": current_region, "$options": "i"}
    if agency:
        q["agency"] = {"$regex": agency, "$options": "i"}
    results = list(db["userprofile"].find(q, {"_id": 0}))
    return {"results": results}


# ----------------- Chat -----------------
@app.post("/api/chat/send")
def send_message(body: SendMessageRequest, email: str = Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    create_document("message", {"from_email": email, "to_email": body.to_email, "content": body.content, "read": False})
    return {"status": "sent"}


@app.get("/api/chat/history")
def get_history(with_email: EmailStr, email: str = Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    a = email
    b = with_email
    conv = list(db["message"].find({
        "$or": [
            {"from_email": a, "to_email": b},
            {"from_email": b, "to_email": a}
        ]
    }, {"_id": 0}).sort("created_at", 1))
    return {"messages": conv}


# ----------------- Admin -----------------
class AdminVerifyRequest(BaseModel):
    email: EmailStr
    verified: bool


@app.get("/api/admin/users")
def admin_list_users():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    users = list(db["userprofile"].find({}, {"_id": 0}))
    return {"users": users}


@app.post("/api/admin/verify")
def admin_verify(req: AdminVerifyRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["userprofile"].update_one({"email": req.email}, {"$set": {"is_verified": req.verified}})
    return {"status": "ok"}


@app.delete("/api/admin/users/{email}")
def admin_delete(email: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["userprofile"].delete_one({"email": email})
    db["message"].delete_many({"$or": [{"from_email": email}, {"to_email": email}]})
    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
