import os
from fastapi import FastAPI, HTTPException
import httpx
from dotenv import load_dotenv

app = FastAPI()


@app.post("/send-whatsapp-message")
async def send_whatsapp_message(phone_number: str, template_name: str = "hello_world", language_code: str = "en_US"):
    load_dotenv()
    token = os.getenv("WHATSAPP_API_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")

    url = f"https://graph.facebook.com/v22.0/{phone_id}/messages"

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {
            "preview_url": True,
            "body": "Hello! I'm Mayank. This is a test message sent from Whatsapp API. Bye!",
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"WhatsApp API error: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to send WhatsApp message: {str(e)}"
        )