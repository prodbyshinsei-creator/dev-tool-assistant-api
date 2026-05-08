import os


class Config:
    # Telegram
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

    # Database
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    DB_PATH: str = os.environ.get("DB_PATH", "volume_bot.db")

    # Solana / Helius
    HELIUS_RPC: str = os.environ.get(
        "HELIUS_RPC",
        "https://mainnet.helius-rpc.com/?api-key=YOUR_HELIUS_KEY"
    )

    # Optional APIs
    BIRDEYE_API_KEY: str = os.environ.get("BIRDEYE_API_KEY", "")
    SHYFT_API_KEY: str = os.environ.get("SHYFT_API_KEY", "")

    # Environment
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "production")

    # Server
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", 8080))
