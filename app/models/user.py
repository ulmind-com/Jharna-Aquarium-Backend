from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = None


class OtpRequest(BaseModel):
    email: EmailStr


class OtpVerify(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=8)


class SignupComplete(BaseModel):
    """Final step: the signup token (proof of a verified email) plus profile."""
    signup_token: str
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class AdminCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    permissions: list[str] = []  # section keys this admin may access


class AdminUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    permissions: list[str] | None = None


class UserPublic(BaseModel):
    id: str
    name: str
    email: EmailStr
    phone: str | None = None
    avatar: str | None = None
    role: str = "user"
    is_super: bool = False
    permissions: list[str] | None = None  # None = full access (owner / legacy admin)
    addresses: list = []
    cart: list = []
    created_at: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = None
    avatar: str | None = None
    addresses: list | None = None
    cart: list | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic

