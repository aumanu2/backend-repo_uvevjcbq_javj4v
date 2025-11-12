import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from database import db, create_document, get_documents
from schemas import Userprofile, Message, Matchrequest
import stripe

# Stripe setup
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

app = FastAPI(title="ASN Location Swap API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
                        "unit_amount": 5000000,  # Rp50.000 per bulan (in cents of IDR => stripe uses smallest currency unit)
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
def create_or_update_profile(profile: ProfileCreateRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # Upsert based on email
    existing = db["userprofile"].find_one({"email": profile.email})
    data = profile.model_dump()
    if existing:
        db["userprofile"].update_one({"email": profile.email}, {"$set": data})
        return {"status": "updated"}
    else:
        create_document("userprofile", data)
        return {"status": "created"}


@app.get("/api/profile/{email}")
def get_profile(email: str):
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
class SendMessageRequest(BaseModel):
    from_email: EmailStr
    to_email: EmailStr
    content: str


@app.post("/api/chat/send")
def send_message(body: SendMessageRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    create_document("message", body.model_dump())
    return {"status": "sent"}


@app.get("/api/chat/history")
def get_history(a: EmailStr, b: EmailStr):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
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
    users = list(db["userprofile"].find({}, {"_id": 0}))
    return {"users": users}


@app.post("/api/admin/verify")
def admin_verify(req: AdminVerifyRequest):
    db["userprofile"].update_one({"email": req.email}, {"$set": {"is_verified": req.verified}})
    return {"status": "ok"}


@app.delete("/api/admin/users/{email}")
def admin_delete(email: str):
    db["userprofile"].delete_one({"email": email})
    db["message"].delete_many({"$or": [{"from_email": email}, {"to_email": email}]})
    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
