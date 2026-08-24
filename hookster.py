import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI()


class TradeSignal(BaseModel):
    exchange: str
    pair: str
    signal: str
    leverage: int
    price: float
    timestamp: str = None


FREQTRADE_API_URL = "http://localhost:8080/api/v1"
USERNAME = "Freqtrader"
PASSWORD = "SuperSecret1!"


def get_access_token():
    response = requests.post(f"{FREQTRADE_API_URL}/token/login", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise HTTPException(status_code=400, detail="Failed to authenticate with Freqtrade API")


@app.post("/webhook/")
async def receive_signal(signal: TradeSignal):
    access_token = get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    if signal.signal == "enter_long" or signal.signal == "enter_short":
        side = "long" if signal.signal == "enter_long" else "short"
        response = requests.post(
            f"{FREQTRADE_API_URL}/forceenter",
            headers=headers,
            json={"pair": signal.pair, "side": side, "price": signal.price},
        )
    elif signal.signal == "exit_long" or signal.signal == "exit_short":
        trade_id = (
            "your_trade_id"  # This needs to be dynamically determined or passed in the signal
        )
        response = requests.post(f"{FREQTRADE_API_URL}/forceexit/{trade_id}", headers=headers)
    else:
        return {"status": "error", "message": "Invalid signal type"}

    if response.status_code == 200:
        return {"status": "success", "data": response.json()}
    else:
        return {"status": "error", "message": "Failed to execute trade", "details": response.text}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
