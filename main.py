import os
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv
from typing import Callable, List, Dict, Any
from datetime import datetime
import hashlib
import hmac
import uuid
import logging
import json
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("api")



app = FastAPI()

message_status_store = {}
recent_requests: List[Dict[str, Any]] = []
MAX_STORED_REQUESTS = 100


@app.post("/send-whatsapp-message")
async def send_whatsapp_message(phone_number: str, message: str = "Hello! I'm Mayank. This is a test message sent from Whatsapp API. Bye!", language_code: str = "en_US"):
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
            "body": message,
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            
            if "messages" in result and len(result["messages"]) > 0:
                message_id = result["messages"][0]["id"]
                message_status_store[message_id] = {
                    "phone_number": phone_number,
                    "status": "sent",
                    "details": {}
                }
                
            return {
                "status": "message_sent",
                "api_response": result,
                "note": "This only confirms the API accepted your request. Check webhook for delivery status."
            }
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"WhatsApp API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send WhatsApp message: {str(e)}")
    
async def verify_webhook_signature(request: Request):
    """Verify that incoming webhooks are from Meta using the signature"""
    app_secret = os.getenv("META_APP_SECRET")
    signature = request.headers.get("x-hub-signature-256", "")
    
    if not signature:
        return True 
    
    body = await request.body()
    
    # Generate the expected signature
    expected_signature = "sha256=" + hmac.new(
        app_secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    
    return True

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, verified: bool = Depends(verify_webhook_signature)):
    """Receive webhook notifications from WhatsApp"""
    body = await request.json()
    
    # Handle webhook verification challenge
    if "hub.mode" in body and body["hub.mode"] == "subscribe":
        if body["hub.verify_token"] == os.environ.get("WEBHOOK_VERIFY_TOKEN", "your_verify_token"):
            return {"hub.challenge": body["hub.challenge"]}
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")
    
    # Process status updates
    try:
        if "entry" in body:
            for entry in body["entry"]:
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        process_message_status_updates(change.get("value", {}))
        
        return {"status": "received"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process webhook: {str(e)}")

def process_message_status_updates(data: Dict[str, Any]):
    """Process message status updates from webhooks"""
    # Handle delivery status updates
    if "statuses" in data:
        for status in data["statuses"]:
            message_id = status.get("id")
            if message_id in message_status_store:
                message_status_store[message_id]["status"] = status.get("status")
                message_status_store[message_id]["details"] = status
                print(f"Message {message_id} status updated to: {status.get('status')}")

@app.get("/message-status/{message_id}")
async def get_message_status(message_id: str):
    """Get the delivery status of a message"""
    if message_id in message_status_store:
        return message_status_store[message_id]
    raise HTTPException(status_code=404, detail="Message ID not found")

@app.get("/all-message-statuses")
async def get_all_message_statuses():
    """Get statuses of all tracked messages"""
    return message_status_store

@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> Response:
    """Log all requests and responses"""
    request_id = str(uuid.uuid4())
    request_path = request.url.path
    request_query = str(request.query_params)
    client_host = request.client.host if request.client else "unknown"
    
    start_time = time.time()
    
    request_body = ""
    if request_path != "/whatsapp/webhook": #webhooks too large to be logged so skipping
        try:
            body_bytes = await request.body()
            request.scope["_body"] = body_bytes 
            if body_bytes:
                try:
                    request_body = body_bytes.decode()
                except UnicodeDecodeError:
                    request_body = "[binary data]"
        except Exception as e:
            request_body = f"[Error reading body: {str(e)}]"
    
    try:
        response = await call_next(request)
        status_code = response.status_code
        error_detail = None
    except Exception as e:
        logger.exception(f"Request failed: {str(e)}")
        status_code = 500
        error_detail = str(e)
        raise
    finally:
        duration = time.time() - start_time
        
        log_entry = {
            "id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
            "method": request.method,
            "path": request_path,
            "query": request_query,
            "client_ip": client_host,
            "status_code": status_code,
            "duration_ms": round(duration * 1000, 2),
            "body": request_body if request_body else None,
            "error": error_detail
        }
        
        logger.info(f"Request: {log_entry['method']} {log_entry['path']} - Status: {log_entry['status_code']} - Duration: {log_entry['duration_ms']}ms")
        
        recent_requests.append(log_entry)
        if len(recent_requests) > MAX_STORED_REQUESTS:
            recent_requests.pop(0)
        
    return response

@app.get("/monitoring/requests")
async def get_recent_requests():
    """Endpoint to view recent request logs"""
    return {"requests": recent_requests}