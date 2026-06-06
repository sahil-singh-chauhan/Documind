import os
from dotenv import load_dotenv

# --- Base Directories ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- Environment Setup ---
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path, override=True)  # FORCE override any stuck environment variables

print(f"DEBUG: Loaded .env from {env_path}")
print(f"DEBUG: JINA_TOP_N is currently set to: {os.getenv('JINA_TOP_N')}")

# --- Configuration Constants ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_API_BASE = os.getenv('OPENAI_API_BASE', 'https://openrouter.ai/api/v1')
PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
PINECONE_INDEX_NAME = os.getenv('PINECONE_INDEX_NAME', 'apirag-1024')
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'jina-embeddings-v3')
JINA_API_KEY = os.getenv('JINA_API_KEY')
JINA_EMBEDDING_DIMENSIONS = int(os.getenv('JINA_EMBEDDING_DIMENSIONS', '1024'))
SECRET_KEY = os.getenv('SECRET_KEY')

# --- Redis Setup (For Stateless Sessions) ---
# We read the URL and Token that you got from Upstash.
UPSTASH_REDIS_REST_URL = os.getenv('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_REST_TOKEN = os.getenv('UPSTASH_REDIS_REST_TOKEN')

# --- Caching Threshold ---
SEMANTIC_CACHE_THRESHOLD = float(os.getenv('SEMANTIC_CACHE_THRESHOLD', '0.90'))

# --- Export keys to env for packages that read automatically ---
if OPENAI_API_KEY:
    os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY
os.environ['OPENAI_API_BASE'] = OPENAI_API_BASE
if PINECONE_API_KEY:
    os.environ['PINECONE_API_KEY'] = PINECONE_API_KEY
