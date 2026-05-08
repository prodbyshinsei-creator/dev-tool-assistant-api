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
    try:
        data = get_token_metadata(req.ca)

        return {
            "success": True,
            "data": data
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
