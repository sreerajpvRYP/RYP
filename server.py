from flask import Flask, request, jsonify, send_from_directory, send_file, Response
from flask_cors import CORS
import os
import yt_dlp
import uuid
import json
import logging
import requests

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.')
CORS(app, resources={r"/*": {"origins": "*"}})

# Directories
DOWNLOADS_DIR = "downloads"
METADATA_DIR = "metadata"
ICONS_DIR = "icons"

# Create directories
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(ICONS_DIR, exist_ok=True)

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/sw.js')
def sw():
    response = send_from_directory('.', 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript'
    return response

@app.route('/icons/<path:filename>')
def icons(filename):
    try:
        return send_from_directory(ICONS_DIR, filename)
    except:
        # Return a simple SVG placeholder if icon not found
        return '''<svg width="192" height="192" xmlns="http://www.w3.org/2000/svg">
            <rect width="192" height="192" fill="#667eea"/>
            <text x="50%" y="50%" font-size="64" text-anchor="middle" dy=".3em" fill="white">YT</text>
        </svg>''', 200, {'Content-Type': 'image/svg+xml'}

@app.route('/stream-direct', methods=['POST'])
def stream_direct():
    """Direct streaming endpoint that proxies YouTube video"""
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "Missing URL"}), 400

        logger.info(f"Getting direct stream for: {url}")
        
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "best[ext=mp4]/best",
            "skip_download": True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        # Get the best direct URL
        stream_url = None
        if info.get("url"):
            stream_url = info["url"]
        elif info.get("formats"):
            # Try to find a good quality format with direct URL
            for fmt in reversed(info["formats"]):
                if fmt.get("url") and fmt.get("vcodec") != "none":
                    stream_url = fmt["url"]
                    break
        
        if not stream_url:
            return jsonify({"error": "No stream URL found"}), 404
        
        response_data = {
            "stream_url": stream_url,
            "title": info.get("title", "Unknown"),
            "thumbnail": info.get("thumbnail")
        }
        
        logger.info(f"Stream URL retrieved successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in stream_direct: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/video-info', methods=['POST'])
def video_info():
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "Missing URL"}), 400

        logger.info(f"Fetching video info for: {url}")
        
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "best",
            "skip_download": True,
            "extract_flat": False
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        
        # Get best stream URL
        stream_url = None
        if info.get("formats"):
            # Try to get a combined format first
            for f in info["formats"]:
                if f.get("vcodec") != "none" and f.get("acodec") != "none":
                    stream_url = f.get("url")
                    break
            
            # Fallback to any video format
            if not stream_url:
                for f in info["formats"]:
                    if f.get("url"):
                        stream_url = f["url"]
                        break
        
        if not stream_url:
            stream_url = info.get("url")
        
        response_data = {
            "id": info.get("id"),
            "title": info.get("title", "Unknown Title"),
            "thumbnail": info.get("thumbnail"),
            "stream_url": stream_url,
            "duration": info.get("duration"),
            "uploader": info.get("uploader")
        }
        
        logger.info(f"Successfully fetched video info: {response_data['title']}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in video_info: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.json
        url = data.get('url')
        fmt = data.get('format', 'mp4')
        quality = data.get('quality', '720p')
        video_id = data.get('video_id', str(uuid.uuid4()))
        
        if not url:
            return jsonify({"error": "Missing URL"}), 400

        logger.info(f"Downloading video: {url} (format: {fmt}, quality: {quality})")
        
        # Prepare filename
        filename = f"{video_id}.{fmt}"
        filepath = os.path.join(DOWNLOADS_DIR, filename)
        
        # Configure yt-dlp options
        if fmt == 'mp3':
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": filepath.replace('.mp3', '.%(ext)s'),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "quiet": True,
                "no_warnings": True
            }
        else:
            quality_num = quality.replace('p', '')
            ydl_opts = {
                "format": f"bestvideo[height<={quality_num}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality_num}]/best",
                "outtmpl": filepath,
                "merge_output_format": fmt,
                "quiet": True,
                "no_warnings": True
            }
        
        # Download video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        
        # Check if file was created
        if not os.path.exists(filepath):
            # For MP3, the file might have a different extension initially
            possible_files = [f for f in os.listdir(DOWNLOADS_DIR) if f.startswith(video_id)]
            if possible_files:
                old_path = os.path.join(DOWNLOADS_DIR, possible_files[0])
                os.rename(old_path, filepath)
        
        # Save metadata
        metadata = {
            "id": video_id,
            "title": info.get("title", "Unknown Title"),
            "filename": filename,
            "thumbnail": info.get("thumbnail"),
            "quality": quality,
            "format": fmt,
            "duration": info.get("duration"),
            "uploader": info.get("uploader")
        }
        
        metadata_file = os.path.join(METADATA_DIR, f"{video_id}.json")
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Successfully downloaded: {metadata['title']}")
        
        return jsonify({
            "success": True,
            "download_url": f"/stream/{filename}",
            "metadata": metadata
        })
        
    except Exception as e:
        logger.error(f"Error in download_video: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/saved-videos')
def saved_videos():
    try:
        videos = []
        
        # Read all metadata files
        if os.path.exists(METADATA_DIR):
            for filename in os.listdir(METADATA_DIR):
                if filename.endswith(".json"):
                    meta_file = os.path.join(METADATA_DIR, filename)
                    
                    try:
                        with open(meta_file, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        
                        # Check if video file exists
                        video_path = os.path.join(DOWNLOADS_DIR, meta.get("filename", ""))
                        
                        if os.path.exists(video_path):
                            videos.append(meta)
                        else:
                            # Clean up orphaned metadata
                            os.remove(meta_file)
                            logger.info(f"Removed orphaned metadata: {filename}")
                    except Exception as e:
                        logger.error(f"Error reading metadata {filename}: {str(e)}")
        
        return jsonify(videos)
        
    except Exception as e:
        logger.error(f"Error in saved_videos: {str(e)}")
        return jsonify([]), 500

@app.route('/delete/<video_id>', methods=['DELETE'])
def delete_video(video_id):
    try:
        metadata_file = os.path.join(METADATA_DIR, f"{video_id}.json")
        
        if not os.path.exists(metadata_file):
            return jsonify({"error": "Video not found"}), 404
        
        # Read metadata to get filename
        with open(metadata_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        
        # Delete video file
        video_path = os.path.join(DOWNLOADS_DIR, meta.get("filename", ""))
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.info(f"Deleted video file: {video_path}")
        
        # Delete metadata
        os.remove(metadata_file)
        logger.info(f"Deleted metadata: {metadata_file}")
        
        return jsonify({"success": True})
        
    except Exception as e:
        logger.error(f"Error in delete_video: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/stream/<path:filename>')
def stream(filename):
    try:
        file_path = os.path.join(DOWNLOADS_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
        
        # Determine MIME type
        ext = filename.split('.')[-1].lower()
        mime_types = {
            'mp4': 'video/mp4',
            'webm': 'video/webm',
            'mp3': 'audio/mpeg',
            'wav': 'audio/wav',
            'm4a': 'audio/mp4'
        }
        
        mimetype = mime_types.get(ext, 'application/octet-stream')
        
        return send_file(file_path, mimetype=mimetype)
        
    except Exception as e:
        logger.error(f"Error streaming file {filename}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['POST'])
def search_videos():
    try:
        data = request.json
        query = data.get('query')
        max_results = data.get('max_results', 10)
        
        if not query:
            return jsonify({"error": "Missing query"}), 400
        
        logger.info(f"Searching for: {query}")
        
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
        
        results = []
        if search_results and 'entries' in search_results:
            for entry in search_results['entries']:
                if entry:
                    results.append({
                        "id": entry.get("id"),
                        "title": entry.get("title", "Unknown Title"),
                        "thumbnail": entry.get("thumbnail"),
                        "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                        "duration": entry.get("duration"),
                        "uploader": entry.get("uploader")
                    })
        
        logger.info(f"Found {len(results)} results for: {query}")
        return jsonify({"results": results})
        
    except Exception as e:
        logger.error(f"Error in search_videos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "downloads_dir": os.path.exists(DOWNLOADS_DIR),
        "metadata_dir": os.path.exists(METADATA_DIR)
    })

if __name__ == "__main__":
    logger.info("🚀 Starting YouTube PWA Player Server...")
    logger.info(f"📁 Downloads directory: {os.path.abspath(DOWNLOADS_DIR)}")
    logger.info(f"📁 Metadata directory: {os.path.abspath(METADATA_DIR)}")
    app.run(host='0.0.0.0', port=5000, debug=True)
