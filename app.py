import time
import os
import logging
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

data_dir = os.path.join(os.path.dirname(__file__), 'public', 'data')
cache_dir = os.path.join(os.path.dirname(__file__), '.cache')
os.makedirs(data_dir, exist_ok=True)
os.makedirs(cache_dir, exist_ok=True)

# Cache configuration
CACHE_TTL = 300  # 5 minutes in seconds
cache_file = os.path.join(cache_dir, 'youtube_cache.json')

def load_cache():
    """Load cache from file"""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
    return {}

def save_cache(cache_data):
    """Save cache to file"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cache: {e}")

def is_cache_valid(timestamp_str):
    """Check if cache is still valid"""
    try:
        cache_time = datetime.fromisoformat(timestamp_str)
        return datetime.now() - cache_time < timedelta(seconds=CACHE_TTL)
    except:
        return False

def write_to_file(filename, content):
    """Write content to file in the data directory"""
    filepath = os.path.join(data_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath

def format_views(view_count):
    """Format view count to readable string"""
    try:
        count = int(view_count)
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M views"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K views"
        else:
            return f"{count} views"
    except:
        return "0 views"

# Game configuration
games = {
    "Valorant": {"query": "Valorant gameplay", "fallback_image": "assets/img/new.png"},
    "GTA V": {"query": "GTA V gameplay", "fallback_image": "assets/img/gtav.png"},
    "League of Legends": {"query": "League of Legends gameplay", "fallback_image": "assets/img/league-legends.png"},
    "Mobile Legends": {"query": "Mobile Legends gameplay", "fallback_image": "assets/img/mobile_legends.jpg"}
}

# Initialize YouTube API
API_KEY = os.getenv('YOUTUBE_API_KEY')
if not API_KEY:
    logger.error("YOUTUBE_API_KEY not found in environment variables")
    logger.info("Please create a .env file with YOUTUBE_API_KEY=your_api_key_here")
    exit(1)

try:
    youtube = build('youtube', 'v3', developerKey=API_KEY)
    logger.info("YouTube API initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize YouTube API: {e}")
    exit(1)

def search_game_videos(game_name, query):
    """Search for game videos using YouTube Data API"""
    try:
        # Search for live streams or recent videos
        request = youtube.search().list(
            part='snippet',
            q=query,
            type='video',
            videoCategoryId='20',  # Gaming category
            order='viewCount',
            maxResults=5,
            relevanceLanguage='en'
        )
        
        response = request.execute()
        
        if not response.get('items'):
            logger.warning(f"No videos found for {game_name}")
            return None
        
        # Get the most popular video
        video = response['items'][0]
        video_id = video['id']['videoId']
        
        # Get detailed video statistics
        stats_request = youtube.videos().list(
            part='statistics,snippet',
            id=video_id
        )
        
        stats_response = stats_request.execute()
        
        if not stats_response.get('items'):
            return None
        
        video_data = stats_response['items'][0]
        
        # Extract data
        view_count = video_data['statistics'].get('viewCount', '0')
        thumbnails = video_data['snippet']['thumbnails']
        
        # Get the best quality thumbnail available
        thumbnail_url = (
            thumbnails.get('maxres', {}).get('url') or
            thumbnails.get('high', {}).get('url') or
            thumbnails.get('medium', {}).get('url') or
            thumbnails.get('default', {}).get('url', '')
        )
        
        return {
            'views': format_views(view_count),
            'raw_views': view_count,
            'image_url': thumbnail_url,
            'video_id': video_id,
            'title': video_data['snippet']['title']
        }
        
    except HttpError as e:
        if e.resp.status == 403:
            logger.error("YouTube API quota exceeded or invalid API key")
        elif e.resp.status == 429:
            logger.error("YouTube API rate limit exceeded")
        else:
            logger.error(f"YouTube API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to search videos for {game_name}: {e}")
        return None

try:
    cache = load_cache()
    
    while True:
        for game_name, config in games.items():
            try:
                logger.info(f"Fetching data for {game_name}")
                
                # Check cache first
                cache_key = game_name.lower().replace(" ", "_")
                cached_data = cache.get(cache_key)
                
                if cached_data and is_cache_valid(cached_data.get('timestamp', '')):
                    logger.info(f"Using cached data for {game_name}")
                    video_data = cached_data['data']
                else:
                    # Fetch fresh data from YouTube API
                    video_data = search_game_videos(game_name, config['query'])
                    
                    if video_data:
                        # Update cache
                        cache[cache_key] = {
                            'timestamp': datetime.now().isoformat(),
                            'data': video_data
                        }
                        save_cache(cache)
                    else:
                        logger.warning(f"Failed to fetch data for {game_name}, using fallback")
                        continue
                
                # Write to files
                views_filename = f'{cache_key}_views.txt'
                image_filename = f'{cache_key}_image_url.txt'
                
                write_to_file(views_filename, video_data['views'])
                write_to_file(image_filename, video_data['image_url'])
                
                logger.info(f"Updated {game_name}: {video_data['views']}, Title: {video_data['title'][:50]}...")
                
                # Small delay between API calls to avoid rate limiting
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to process {game_name}: {e}")
        
        # Wait before next update cycle
        logger.info(f"Waiting {CACHE_TTL} seconds before next update...")
        time.sleep(CACHE_TTL)

except KeyboardInterrupt:
    logger.info("Scraper stopped by user")
except Exception as e:
    logger.error(f"An unexpected error occurred: {e}")
finally:
    logger.info("YouTube data fetcher stopped")
