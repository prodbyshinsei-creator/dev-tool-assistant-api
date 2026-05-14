from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import logging
from vamp_engine import (
    get_token_metadata, 
    get_token_market_cap,
    prepare_launches,
    launch_single,
    sell_token
)
from volume_engine import VolumeEngine
from database import Database

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dev Tool Assistant API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize engines
volume_engine = VolumeEngine()
db = Database()

# ==================== Pydantic Models ====================

class TokenMetadataRequest(BaseModel):
    ca: str

class TokenMetadataResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None

class LaunchTokenRequest(BaseModel):
    ca: str
    dev_wallet_address: str
    dev_wallet_privkey: str
    dev_buy_sol: float
    launch_count: int = 1

class LaunchTokenResponse(BaseModel):
    success: bool
    launched_tokens: List[str] = []
    metadata_uri: Optional[str] = None
    error: Optional[str] = None

class SellTokenRequest(BaseModel):
    ca: str
    wallet_address: str
    wallet_privkey: str
    slippage: int = 25

class WalletCreate(BaseModel):
    name: str
    address: str
    privkey: str
    wallet_type: str  # 'dev' or 'volume'
    user_id: int = 1

class WalletResponse(BaseModel):
    id: int
    name: str
    address: str
    wallet_type: str
    balance: float = 0.0

class VolumeStartRequest(BaseModel):
    ca: str
    wallet_addresses: List[str]
    min_sol: float = 0.01
    max_sol: float = 0.05
    user_id: int = 1

class VolumeSessionResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    error: Optional[str] = None

class VolumeStatsResponse(BaseModel):
    txs: int
    fees_sol: float
    sold: int = 0

# ==================== Health Check ====================

@app.get("/")
def root():
    return {
        "status": "online",
        "version": "1.0.0",
        "endpoints": [
            "/vamp/metadata",
            "/vamp/launch",
            "/vamp/sell",
            "/volume/start",
            "/volume/pause/{session_id}",
            "/volume/stop/{session_id}",
            "/wallets",
            "/wallets/{wallet_id}"
        ]
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

# ==================== VAMP Endpoints ====================

@app.post("/vamp/metadata", response_model=TokenMetadataResponse)
async def fetch_metadata(req: TokenMetadataRequest):
    """Fetch token metadata from CA"""
    try:
        logger.info(f"Fetching metadata for CA: {req.ca}")
        data = get_token_metadata(req.ca)
        
        if not data:
            raise HTTPException(status_code=404, detail="Token metadata not found")
        
        # Optionally fetch market cap
        try:
            mc = get_token_market_cap(req.ca)
            if mc:
                data['market_cap'] = mc
        except Exception as e:
            logger.warning(f"Could not fetch market cap: {e}")
        
        return TokenMetadataResponse(success=True, data=data)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Metadata fetch error: {e}", exc_info=True)
        return TokenMetadataResponse(success=False, error=str(e))

@app.post("/vamp/launch", response_model=LaunchTokenResponse)
async def launch_tokens(req: LaunchTokenRequest):
    """Clone and launch token(s) on pump.fun"""
    try:
        logger.info(f"Launching {req.launch_count}x tokens from CA: {req.ca}")
        
        # Get metadata first
        meta = get_token_metadata(req.ca)
        if not meta:
            raise HTTPException(status_code=404, detail="Token metadata not found")
        
        # Prepare metadata upload (once)
        metadata_uri = prepare_launches(meta)
        if not metadata_uri:
            raise HTTPException(status_code=500, detail="Failed to upload metadata to IPFS")
        
        logger.info(f"Metadata URI: {metadata_uri}")
        
        # Launch tokens
        launched_tokens = []
        for i in range(req.launch_count):
            logger.info(f"Launching token {i+1}/{req.launch_count}...")
            mint_ca = launch_single(
                metadata_uri=metadata_uri,
                meta=meta,
                dev_wallet=req.dev_wallet_address,
                dev_buy_sol=req.dev_buy_sol,
                privkey=req.dev_wallet_privkey
            )
            
            if mint_ca:
                launched_tokens.append(mint_ca)
                logger.info(f"✅ Token {i+1} launched: {mint_ca}")
            else:
                logger.error(f"❌ Token {i+1} launch failed")
        
        if not launched_tokens:
            raise HTTPException(status_code=500, detail="All launches failed")
        
        return LaunchTokenResponse(
            success=True,
            launched_tokens=launched_tokens,
            metadata_uri=metadata_uri
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Launch error: {e}", exc_info=True)
        return LaunchTokenResponse(success=False, error=str(e))

@app.post("/vamp/sell")
async def sell_token_endpoint(req: SellTokenRequest):
    """Sell all tokens from wallet"""
    try:
        logger.info(f"Selling token {req.ca} from {req.wallet_address[:8]}...")
        success = sell_token(req.ca, req.wallet_address, req.wallet_privkey, req.slippage)
        
        if not success:
            raise HTTPException(status_code=500, detail="Sell failed")
        
        return {"success": True, "message": "Token sold successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Sell error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

# ==================== Volume Bot Endpoints ====================

@app.post("/volume/start", response_model=VolumeSessionResponse)
async def start_volume_session(req: VolumeStartRequest):
    """Start a volume generation session"""
    try:
        logger.info(f"Starting volume session for CA: {req.ca}")
        
        # Get wallet data with privkeys
        wallets_with_privkeys = []
        for wallet_addr in req.wallet_addresses:
            wallet_data = db.get_wallet_by_address(req.user_id, wallet_addr)
            if wallet_data:
                wallets_with_privkeys.append(wallet_addr)
            else:
                logger.warning(f"Wallet {wallet_addr} not found in database")
        
        if not wallets_with_privkeys:
            raise HTTPException(status_code=400, detail="No valid wallets found")
        
        session_id = volume_engine.start_session(
            user_id=req.user_id,
            ca=req.ca,
            wallets=wallets_with_privkeys,
            min_sol=req.min_sol,
            max_sol=req.max_sol,
            db=db
        )
        
        logger.info(f"✅ Volume session started: {session_id}")
        return VolumeSessionResponse(success=True, session_id=session_id)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Volume start error: {e}", exc_info=True)
        return VolumeSessionResponse(success=False, error=str(e))

@app.post("/volume/pause/{session_id}")
async def pause_volume_session(session_id: str):
    """Pause/Resume a volume session"""
    try:
        paused = volume_engine.toggle_pause(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "paused": paused
        }
    except Exception as e:
        logger.error(f"Volume pause error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/volume/stop/{session_id}")
async def stop_volume_session(session_id: str):
    """Stop a volume session"""
    try:
        logger.info(f"Stopping volume session: {session_id}")
        stats = volume_engine.stop_session(session_id)
        
        if not stats:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "success": True,
            "session_id": session_id,
            "stats": stats
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Volume stop error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/volume/status/{session_id}")
async def get_volume_status(session_id: str):
    """Get current status of a volume session"""
    try:
        session = volume_engine.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "success": True,
            "session_id": session_id,
            "status": "paused" if session.paused else "running" if not session.stopped else "stopped",
            "txs": session.txs,
            "fees_sol": round(session.fees_sol, 6),
            "ca": session.ca,
            "wallets_count": len(session.wallets)
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== Wallet Management ====================

@app.post("/wallets", response_model=WalletResponse)
async def create_wallet(wallet: WalletCreate):
    """Add a new wallet"""
    try:
        wallet_id = db.add_wallet(
            user_id=wallet.user_id,
            name=wallet.name,
            address=wallet.address,
            privkey=wallet.privkey,
            wallet_type=wallet.wallet_type
        )
        
        return WalletResponse(
            id=wallet_id,
            name=wallet.name,
            address=wallet.address,
            wallet_type=wallet.wallet_type,
            balance=0.0
        )
    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/wallets")
async def list_wallets(user_id: int = 1, wallet_type: Optional[str] = None):
    """List all wallets"""
    try:
        wallets = db.get_user_wallets(user_id, wallet_type)
        return {"success": True, "wallets": wallets}
    except Exception as e:
        logger.error(f"List wallets error: {e}")
        return {"success": False, "error": str(e)}

@app.delete("/wallets/{wallet_id}")
async def delete_wallet(wallet_id: int, user_id: int = 1):
    """Delete a wallet"""
    try:
        db.delete_wallet(user_id, wallet_id)
        return {"success": True, "message": "Wallet deleted"}
    except Exception as e:
        logger.error(f"Delete wallet error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/wallets/{wallet_id}")
async def get_wallet(wallet_id: int, user_id: int = 1):
    """Get wallet details"""
    try:
        wallet = db.get_wallet(user_id, wallet_id)
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
        return {"success": True, "wallet": wallet}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get wallet error: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    from config import Config
    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
