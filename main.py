import yt_dlp as ytdl
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests
import os
from dotenv import load_dotenv
import tempfile
import json
import time
import random
import string

load_dotenv()
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_COOKIES = os.getenv('YOUTUBE_COOKIES', '')  # Add this line

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Remove the static files mounting since Vercel handles it differently
# app.mount("/static", StaticFiles(directory="static"), name="static")

class VideoRequest(BaseModel):
    video_id: str

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/search")
async def search_youtube(request: Request, q: str = Query(...)):
    if not YOUTUBE_API_KEY:
        return templates.TemplateResponse("_results.html", {
            "request": request,
            "results": [],
            "error": "API key missing"
        })

    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet,id",
            "q": q,
            "type": "video",
            "maxResults": 10,
            "key": YOUTUBE_API_KEY
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get('items', []):
            if item['id']['kind'] == 'youtube#video':
                # Use html module for proper entity decoding
                import html
                title = html.unescape(item['snippet']['title'])
                channel = html.unescape(item['snippet']['channelTitle'])
                
                results.append({
                    'id': item['id']['videoId'],
                    'title': title,
                    'thumbnail': item['snippet']['thumbnails']['high']['url'],
                    'author': channel
                })

        return templates.TemplateResponse("_results.html", {
            "request": request,
            "results": results
        })

    except Exception as e:
        print(f"Search failed: {str(e)}")
        return templates.TemplateResponse("_results.html", {
            "request": request,
            "results": [],
            "error": "Search failed"
        })

# Add after YOUTUBE_API_KEY initialization
def get_cookies():
    if YOUTUBE_COOKIES:
        # Use user-provided cookies if available
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(YOUTUBE_COOKIES)
            return f.name
            
    # Fallback to generated cookies
    timestamp = int(time.time())
    cookie_data = [
        f".youtube.com\tTRUE\t/\tFALSE\t{timestamp + 63072000}\tPREF\tf6=400&hl=en",
        f".youtube.com\tTRUE\t/\tFALSE\t{timestamp + 63072000}\tWIDE\t1"
    ]
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("# Netscape HTTP Cookie File\n")
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
        f.write("# This is a generated file!  Do not edit.\n\n")
        for cookie in cookie_data:
            f.write(cookie + "\n")
        return f.name

def get_random_user_agent():
    browsers = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
    ]
    return random.choice(browsers)

@app.post("/stream/{video_id}")
async def stream_audio(request: Request, video_id: str):
    try:
        info = await extract_video_info(video_id)
        if not info:
            raise ValueError("Could not get video info")
            
        formats = info.get('formats', [])
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        
        if not audio_formats:
            raise ValueError("No audio stream found")
            
        best_audio = max(audio_formats, key=lambda x: float(x.get('abr', 0) or 0))
        
        return templates.TemplateResponse("_player.html", {
            "request": request,
            "url": best_audio['url'],
            "title": info.get('title', 'Unknown Title'),
            "thumbnail": info.get('thumbnail', '')
        }, headers={
            'HX-Trigger': 'playerLoaded',
            'HX-Reswap': 'innerHTML'
        })

    except Exception as e:
        print(f"Stream failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{video_id}")
async def get_audio_url(video_id: str):
    try:
        info = await extract_video_info(video_id)
        if not info:
            raise ValueError("Could not extract video information")
        
        formats = info.get('formats', [])
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        
        if not audio_formats:
            raise ValueError("No audio formats found")
        
        best_audio = max(audio_formats, key=lambda x: float(x.get('abr', 0) or 0))
        url = best_audio.get('url')
        
        if not url:
            raise ValueError("Could not get audio URL")
        
        title = info.get('title', 'audio')
        safe_title = "".join(c for c in title if c.isalnum() or c in (' -_')).strip()
        
        return {
            "url": url,
            "title": safe_title or 'audio',
            "content_type": best_audio.get('ext', 'mp3')
        }

    except Exception as e:
        print(f"Download failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")

# Remove or modify the uvicorn run block since Vercel handles this
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)