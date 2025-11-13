"""
Database Schemas for ASN Location Swap Platform

Each Pydantic model below maps to a MongoDB collection (lowercase of class name).
Use these schemas to validate incoming/outgoing data.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr


class Userprofile(BaseModel):
    """
    Collection name: "userprofile"
    Stores user profile and subscription/verification status
    """
    email: EmailStr = Field(..., description="User email (primary identifier)")
    name: str = Field(..., description="Nama lengkap")
    nip: Optional[str] = Field(None, description="NIP (opsional)")
    agency: str = Field(..., description="Instansi asal")
    position: str = Field(..., description="Jabatan")
    grade: str = Field(..., description="Golongan")
    current_region: str = Field(..., description="Daerah kerja sekarang")
    desired_region: str = Field(..., description="Daerah yang diinginkan")
    is_subscribed: bool = Field(False, description="Status langganan aktif")
    is_verified: bool = Field(False, description="Ditandai admin sebagai terverifikasi")


class Message(BaseModel):
    """
    Collection name: "message"
    Stores chat messages between two users
    """
    from_email: EmailStr = Field(..., description="Pengirim")
    to_email: EmailStr = Field(..., description="Penerima")
    content: str = Field(..., description="Isi pesan")
    read: bool = Field(False, description="Sudah dibaca")


class Matchrequest(BaseModel):
    """
    Collection name: "matchrequest"
    Optional: record of expressed interest to match
    """
    requester_email: EmailStr
    target_email: EmailStr
    note: Optional[str] = None


class Otp(BaseModel):
    """
    Collection name: "otp"
    One-time passcodes for magic-link/OTP login
    """
    email: EmailStr = Field(..., description="Email pengguna")
    code: str = Field(..., description="6 digit OTP")
    purpose: str = Field("login", description="Tujuan OTP")
    expires_at: int = Field(..., description="Unix timestamp expiry (seconds)")
