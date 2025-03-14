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

load_dotenv()
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# Update the FastAPI app initialization
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
    # Example cookies that might help bypass restrictions
    cookie_data = [
        f".youtube.com\tTRUE\t/\tFALSE\t2147483647\tCONSENT\tYES+",
        f".youtube.com\tTRUE\t/\tFALSE\t2147483647\tVISITOR_INFO1_LIVE\trandom_value"
    ]
    
    # Create temporary cookie file in Netscape format
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("# Netscape HTTP Cookie File\n")  # Required header
        f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
        f.write("# This is a generated file!  Do not edit.\n\n")
        
        for cookie in cookie_data:
            f.write(cookie + "\n")
        return f.name

@app.post("/stream/{video_id}")
async def stream_audio(request: Request, video_id: str):
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Add cookies to ydl_opts
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'cookiefile': get_cookies()  # Add cookie file
        }
        
        with ytdl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
        if not info:
            raise ValueError("Could not get video info")
            
        formats = info.get('formats', [])
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
        
        if not audio_formats:
            raise ValueError("No audio stream found")
            
        best_audio = max(audio_formats, key=lambda x: float(x.get('abr', 0) or 0))
        
        # Get the direct audio URL and other metadata
        audio_url = best_audio['url']
        title = info.get('title', 'Unknown Title')
        thumbnail = info.get('thumbnail', '')
        
        return templates.TemplateResponse("_player.html", {
            "request": request,
            "url": audio_url,
            "title": title,
            "thumbnail": thumbnail
        }, headers={
            'HX-Trigger': 'playerLoaded'
        })

    except Exception as e:
        print(f"Stream failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{video_id}")
async def download_audio(video_id: str):
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'extract_audio': True,
            'cookiefile': get_cookies(),  # Add cookie file
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }]
        }
        
        with ytdl.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            url = info['url']
            
            # Handle Unicode characters in title
            from html import unescape
            from urllib.parse import unquote
            title = unquote(unescape(info.get('title', 'audio')))
            
            # Create a safe filename
            import re
            safe_title = re.sub(r'[^\x00-\x7F]+', '', title)  # Remove non-ASCII
            safe_title = re.sub(r'[<>:"/\\|?*]', '', safe_title)  # Remove invalid filename chars
            safe_title = safe_title.strip() or 'audio'  # Fallback if empty
            
            response = requests.get(url, stream=True)
            return StreamingResponse(
                response.iter_content(chunk_size=8192),
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": f'attachment; filename="{safe_title}.mp3"'.encode('ascii', 'ignore').decode()
                }
            )

    except Exception as e:
        print(f"Download failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Remove or modify the uvicorn run block since Vercel handles this
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)