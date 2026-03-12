import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import anthropic

app = FastAPI()
templates = Jinja2Templates(directory=".")

# Initialize Anthropic client
client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY", "demo-key")
)

def load_json(path: str, default=None):
    """Safely load JSON with fallback"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else []

def save_json(path: str, data):
    """Save JSON data"""
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving {path}: {e}")

# Load mock data
deals_data = load_json("data/deals.json", [])
contacts_data = load_json("data/contacts.json", [])
activities_data = load_json("data/activities.json", [])

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/deals")
async def get_deals():
    """Get all deals with overdue analysis"""
    current_time = datetime.now()
    
    for deal in deals_data:
        # Calculate if deal is overdue based on last activity
        last_activity = datetime.fromisoformat(deal.get("last_activity", "2024-01-15T10:00:00"))
        days_since_activity = (current_time - last_activity).days
        
        # Mark as overdue if no activity in 7+ days for active stages
        active_stages = ["Sales Qualified Lead", "Discovery", "Proposal Sent", "Vendor Selection", "Negotiation"]
        deal["is_overdue"] = deal["stage"] in active_stages and days_since_activity >= 7
        deal["days_overdue"] = max(0, days_since_activity - 7) if deal["is_overdue"] else 0
        
    return {"deals": deals_data}

@app.get("/api/contacts")
async def get_contacts():
    """Get contacts database with lead scoring"""
    return {"contacts": contacts_data}

@app.post("/api/draft_followup")
async def draft_followup(request: Request):
    """Draft AI follow-up email for a deal"""
    body = await request.json()
    deal_id = body.get("deal_id")
    
    if not deal_id:
        raise HTTPException(status_code=400, detail="Deal ID required")
    
    # Find the deal
    deal = next((d for d in deals_data if d["id"] == deal_id), None)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    
    # Find the contact
    contact = next((c for c in contacts_data if c["company"] == deal["company"]), None)
    contact_name = contact["name"] if contact else "there"
    
    # Create AI prompt for follow-up email
    system_prompt = f"""You are Thomas Meade from Bulk Material Equipment (BME), writing a professional follow-up email for industrial equipment sales.

BME specializes in:
- Conveyor systems and belt conveyors
- Storage silos and bulk storage solutions  
- Pneumatic conveying systems
- Material handling automation
- Dust collection and air filtration

Write a personalized follow-up email that:
1. References the specific equipment type and project
2. Shows understanding of their industry needs
3. Gently pushes for next steps without being pushy
4. Mentions BME's relevant experience
5. Keeps professional but friendly tone

Current deal context:
- Company: {deal['company']}
- Project: {deal['title']}
- Value: ${deal['value']:,}
- Stage: {deal['stage']}
- Last activity: {deal['last_activity']}
- Industry: {deal.get('industry', 'industrial')}

Write only the email content (subject line + body). Be specific to their project."""

    user_prompt = f"Draft a follow-up email for this deal that's been stalled in {deal['stage']} stage."
    
    try:
        # Call Claude API
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        email_content = message.content[0].text
        
        # Log this activity
        activity = {
            "id": str(uuid.uuid4()),
            "deal_id": deal_id,
            "type": "ai_followup_draft",
            "timestamp": datetime.now().isoformat(),
            "content": email_content,
            "status": "draft"
        }
        activities_data.append(activity)
        save_json("data/activities.json", activities_data)
        
        return {
            "success": True,
            "email_content": email_content,
            "deal": deal,
            "contact_name": contact_name
        }
        
    except Exception as e:
        # Fallback to mock response if API fails
        fallback_email = f"""Subject: Following up on {deal['title']} project

Hi {contact_name},

I wanted to follow up on the {deal['title']} project we discussed. I know you're evaluating options for your ${deal['value']:,} bulk material handling system.

At BME, we've successfully implemented similar {deal['title'].lower()} solutions for companies in your industry. Our engineering team has been designing these systems for over 20 years, and we understand the unique challenges you face with material flow and efficiency.

Could we schedule a brief call this week to discuss the technical specifications and timeline? I'd love to share some case studies from similar projects we've completed.

Let me know what works best for your schedule.

Best regards,
Thomas Meade
Bulk Material Equipment (BME)
thomas@bme-equipment.com
(555) 123-4567"""

        return {
            "success": True,
            "email_content": fallback_email,
            "deal": deal,
            "contact_name": contact_name,
            "note": "Using fallback content - in production this would be AI-generated"
        }

@app.post("/api/send_followup")
async def send_followup(request: Request):
    """Simulate sending the follow-up email"""
    body = await request.json()
    deal_id = body.get("deal_id")
    email_content = body.get("email_content", "")
    
    if not deal_id:
        raise HTTPException(status_code=400, detail="Deal ID required")
    
    # Log the sent email activity
    activity = {
        "id": str(uuid.uuid4()),
        "deal_id": deal_id,
        "type": "followup_sent",
        "timestamp": datetime.now().isoformat(),
        "content": email_content,
        "status": "sent"
    }
    activities_data.append(activity)
    save_json("data/activities.json", activities_data)
    
    # Update deal's last activity
    deal = next((d for d in deals_data if d["id"] == deal_id), None)
    if deal:
        deal["last_activity"] = datetime.now().isoformat()
        save_json("data/deals.json", deals_data)
    
    return {
        "success": True,
        "message": "Follow-up email sent successfully",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/activities")
async def get_activities():
    """Get recent activities"""
    return {"activities": activities_data[-20:]}  # Last 20 activities

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)