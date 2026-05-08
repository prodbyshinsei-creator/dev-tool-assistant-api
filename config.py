import os

class Config:
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]
    HELIUS_RPC: str = os.environ.get(
        "HELIUS_RPC",
        "https://mainnet.helius-rpc.com/?api-key=YOUR_KEY_HERE"
    )
    DB_PATH: str = os.environ.get("DB_PATH", "volume_bot.db")
