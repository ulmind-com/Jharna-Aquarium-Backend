from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "MyGarden"
    ENV: str = "development"

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "nursery_ecommerce"

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    ADMIN_TOKEN_EXPIRE_MINUTES: int = 525600  # 1 year

    CORS_ORIGINS: str = "*"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    # Set once a webhook is created in the Razorpay Dashboard (payment.captured
    # -> https://<backend>/orders/webhook/razorpay). Empty = webhook stays
    # dormant (ignores calls) instead of erroring, so it's safe to deploy first.
    RAZORPAY_WEBHOOK_SECRET: str = ""

    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    FIREBASE_CREDENTIALS: str = ""
    # Public Firebase project id — lets /auth/firebase verify web sign-in ID
    # tokens via Google's public certs when FIREBASE_CREDENTIALS is unset.
    # Must match the storefront's VITE_FIREBASE_PROJECT_ID — the ID token is
    # issued for that project and is rejected if the two ever drift apart.
    FIREBASE_PROJECT_ID: str = "mygurden"

    # Google OAuth: the Web client ID (aud) the mobile ID token is verified
    # against. Same value the app passes as webClientId to Google Sign-In.
    GOOGLE_CLIENT_ID: str = ""

    # Facebook Login: verify the app-scoped access token the mobile SDK returns.
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""

    # Transactional email (Resend) — used for the signup OTP. Client swaps
    # these later; leaving RESEND_API_KEY empty just logs the code (dev).
    RESEND_API_KEY: str = ""
    MAIL_ADDRESS: str = "noreply@plantnursery.com"
    MAIL_FROM_NAME: str = "MyGarden"
    OTP_TTL_MINUTES: int = 10           # how long a code stays valid
    OTP_RESEND_COOLDOWN_SECONDS: int = 60  # min gap between resends
    OTP_MAX_ATTEMPTS: int = 5           # wrong tries before a code is burned

    # Optional shared secret so an external cron can trigger the scheduled-
    # notification sweeper (belt-and-suspenders alongside the in-process loop).
    CRON_SECRET: str = ""

    # Public base URL of this backend — used to build absolute URLs for push
    # notification images (FCM needs a reachable URL, not a local asset).
    PUBLIC_BASE_URL: str = "https://nursery-backend.onrender.com"

    # AI recommendations (Groq — OpenAI-compatible). Empty key => heuristic only.
    GROQ_API_KEY: str = ""
    # Groq retired the llama-3.x chat models; gpt-oss-120b is the current
    # general model on that account and supports the agent's tool calls.
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_TIMEOUT: float = 8.0
    RECS_USE_LLM: bool = True

    # Separate Groq key for the customer-support chat agent (falls back to the
    # recommendations key if unset).
    GROQ_AGENT_API_KEY: str = ""

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
