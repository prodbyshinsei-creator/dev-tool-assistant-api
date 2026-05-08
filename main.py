from fastapi import FastAPI
from pydantic import BaseModel
from vamp_engine import get_token_metadata

app = FastAPI()

class TokenRequest(BaseModel):
    ca: str

@app.get("/")
def root():
    return {"status": "online"}

@app.post("/vamp/metadata")
def metadata(req: TokenRequest):
    return get_token_metadata(req.ca)
