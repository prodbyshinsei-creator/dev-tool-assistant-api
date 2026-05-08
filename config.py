import os


class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

    HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "")

    RPC_URL = os.environ.get(
        "RPC_URL",
        f"https://mainnet.helius-rpc.com/?api-key={os.environ.get('HELIUS_API_KEY', '')}"
    )

    DB_PATH = os.environ.get("DB_PATH", "volume_bot.db")

    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")

    DEFAULT_SLIPPAGE = int(os.environ.get("DEFAULT_SLIPPAGE", 15))

    PRIORITY_FEE = float(os.environ.get("PRIORITY_FEE", 0.001))

    JITO_FEE = float(os.environ.get("JITO_FEE", 0.0005))
