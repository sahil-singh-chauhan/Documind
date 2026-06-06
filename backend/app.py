import os
import time
import uuid
import shutil
import json
import asyncio

from fastapi import FastAPI, UploadFile, File, Request, Header
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from upstash_redis import Redis

from config import UPLOAD_DIR, SECRET_KEY, BASE_DIR, UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN
from vectorstore import ensure_index_exists, upsert_pdf_to_vectorstore, pc, INDEX_NAME
from rag import generate_answer_simple, generate_answer_stream

# ------------------------------------------------------------------------
# 1. Initialize Upstash Redis Client
# We use Redis to store chat history so our FastAPI app is "stateless".
# This means if the server restarts, we don't lose the chat history!
# ------------------------------------------------------------------------
try:
    redis_client = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)
    print("DEBUG: Connected to Upstash Redis successfully.")
except Exception as e:
    print(f"DEBUG: Failed to connect to Redis: {e}")
    redis_client = None

# --- FastAPI app ---
app = FastAPI(title="RAG CHAT")

# Serve uploaded files statically so the frontend can display real PDFs
# Real URLs handle #page=X jumps much better than blob URLs
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# ------------------------------------------------------------------------
# 2. CORS Middleware (Cross-Origin Resource Sharing)
# Because we plan to host the frontend on Vercel and backend on Render,
# they will be on different domains. CORS tells the browser it's safe 
# to allow Vercel to talk to Render.
# ------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Ensure Vector Index Exists ---
try:
    ensure_index_exists()
    print(f"DEBUG: Pinecone index '{INDEX_NAME}' ensured.")
except Exception as e:
    print(f"DEBUG: Failed to ensure Pinecone index: {e}")

# ----------------------------
# Helper: Session Management with Redis
# ----------------------------
def get_session_data(session_id: str) -> dict:
    """Fetch the session dictionary from Redis for a given session ID."""
    if not redis_client or not session_id:
        return {"chat_history": [], "namespace": None}
    
    # Redis stores everything as strings, so we parse the JSON back into a Python dictionary
    data_str = redis_client.get(f"session:{session_id}")
    if data_str:
        # If it exists, return it!
        return json.loads(data_str) if isinstance(data_str, str) else data_str
    
    # If it's a brand new session, return an empty template
    return {"chat_history": [], "namespace": None}

def save_session_data(session_id: str, data: dict):
    """Save the session dictionary to Redis, expiring after 24 hours."""
    if redis_client and session_id:
        # Convert the Python dictionary into a JSON string and save it to Redis
        # ex=86400 tells Redis to automatically delete it after 24 hours (cleanup!)
        redis_client.set(f"session:{session_id}", json.dumps(data), ex=86400)

# ----------------------------
# Routes
# ----------------------------

@app.get("/")
async def root():
    return {"message": "DocuMind API Backend is running!"}

@app.post("/upload")
async def upload_pdf(request: Request, file: UploadFile = File(...), x_session_id: str = Header(None)):
    """
    Expects the frontend to send an 'x-session-id' header.
    We use this ID to group the PDF chunks and chat history together in Redis.
    """
    if not file.filename:
        return JSONResponse({"success": False, "error": "No selected file"}, status_code=400)
    
    # Accept PDF, DOCX, DOC, and TXT
    allowed_ext = ('.pdf', '.docx', '.doc', '.txt')
    if not file.filename.lower().endswith(allowed_ext):
        return JSONResponse({"success": False, "error": f"Only {', '.join(allowed_ext)} files are supported"}, status_code=400)

    # If the frontend forgot to send a session ID, we generate a random UUID for them
    session_id = x_session_id or str(uuid.uuid4())
    
    # The Pinecone namespace will be tied to the session so all PDFs for this session group together
    namespace = f"session_{session_id}"
    
    try:
        # Save with original extension so the loader can identify the file type!
        ext = os.path.splitext(file.filename)[1].lower()
        file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{ext}")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        print(f"DEBUG: Saved PDF to {file_path}, starting embedding...")
        
        # Run the embedding + upsert in a background thread so the server stays responsive.
        # Pass the original filename so it's stored as the title in Pinecone metadata.
        original_name = file.filename
        loop = asyncio.get_event_loop()
        num_chunks = await loop.run_in_executor(
            None, upsert_pdf_to_vectorstore, file_path, namespace, original_name
        )
        
        # 3. Update REDIS: append this file to the ordered upload list
        session_data = get_session_data(session_id)
        if not session_data.get("namespace"):
            session_data["namespace"] = namespace
        # Keep an ordered list of uploaded file names (for "first pdf" / "second doc" queries)
        uploaded_files = session_data.get("uploaded_files", [])
        original_name = file.filename  # preserve the real filename
        if original_name not in uploaded_files:
            uploaded_files.append(original_name)
        session_data["uploaded_files"] = uploaded_files
        
        # Track the physical file path so we can delete it later
        local_files = session_data.get("local_files", [])
        if file_path not in local_files:
            local_files.append(file_path)
        session_data["local_files"] = local_files
        
        save_session_data(session_id, session_data)
        
        # We send the session_id, the file list, and the static file URL back to the frontend
        file_url = f"/uploads/{os.path.basename(file_path)}"
        return {
            "success": True, 
            "message": "File uploaded and processed", 
            "chunks": num_chunks, 
            "session_id": session_id, 
            "uploaded_files": uploaded_files,
            "file_url": file_url
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/chat")
async def chat(request: Request, x_session_id: str = Header(None)):
    """
    The chat endpoint. The frontend MUST send the 'x-session-id' header 
    so we can look up their specific chat history in Redis.
    """
    try:
        data = await request.json()
        question = data.get("question")
        if not question:
            return JSONResponse({"error": "No message provided"}, status_code=400)
            
        if not x_session_id:
            return JSONResponse({"error": "Missing X-Session-ID header. Please upload a document first."}, status_code=400)

        # 1. Fetch the user's specific session from Redis!
        session_data = get_session_data(x_session_id)
        namespace = session_data.get("namespace")
        chat_history = session_data.get("chat_history", [])
        uploaded_files = session_data.get("uploaded_files", [])  # ordered list of filenames
        
        if not namespace:
            return JSONResponse({"error": "Session expired or no document uploaded."}, status_code=400)
        
        # 2. Return a StreamingResponse
        def event_generator():
            full_answer = ""
            for chunk in generate_answer_stream(namespace, question, chat_history, uploaded_files):
                # We need to extract the text from the JSON chunk to save it to history
                try:
                    if chunk.startswith("data: "):
                        chunk_data = json.loads(chunk[6:].strip())
                        if "content" in chunk_data:
                            full_answer += chunk_data["content"]
                except Exception as e:
                    print(f"DEBUG: Error parsing chunk for history: {e}")
                    
                yield chunk
            
            # Now save to Redis after the stream finishes!
            chat_history.append({"role": "user", "content": question})
            chat_history.append({"role": "assistant", "content": full_answer})
            session_data["chat_history"] = chat_history
            save_session_data(x_session_id, session_data)

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/check_status")
async def check_status(request: Request):
    """Debug endpoint to check Pinecone status"""
    namespace = request.session.get("namespace")
    if not namespace:
        return {"status": "No active document"}
        
    try:
        index = pc.Index(INDEX_NAME)
        stats = index.describe_index_stats()
        ns_stats = stats.get('namespaces', {}).get(namespace, {})
        
        # Verify with a test query
        chunks = []
        if ns_stats.get('vector_count', 0) > 0:
            query_embedding = [0.0] * 1024  # dummy query
            results = index.query(
                vector=query_embedding,
                top_k=3,
                namespace=namespace,
                include_metadata=True
            )
            chunks = []
            for match in results['matches']:
                metadata = match.get('metadata', {})
                chunks.append({
                    'id': match['id'],
                    'score': match['score'],
                    'title': metadata.get('title', ''),
                    'source': metadata.get('source', ''),
                    'section': metadata.get('section', ''),
                    'position': metadata.get('position', '')
                })

        return {"namespace": namespace, "chunks": chunks}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """
    Completely obliterate a session's data to prevent free-tier resource leaks.
    - Deletes physical files from the local disk.
    - Deletes the Pinecone namespace.
    - Deletes the session state from Upstash Redis.
    """
    try:
        data = get_session_data(session_id)
        if not data:
            return {"success": True, "message": "Session already empty or missing"}

        # 1. Delete physical PDFs
        local_files = data.get("local_files", [])
        for file_path in local_files:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"DEBUG: Deleted physical file {file_path}")

        # 2. Delete Pinecone Namespace
        namespace = data.get("namespace")
        if namespace:
            try:
                # Use the global Pinecone client from vectorstore.py
                index = pc.Index(INDEX_NAME)
                index.delete(delete_all=True, namespace=namespace)
                print(f"DEBUG: Deleted Pinecone namespace {namespace}")
            except Exception as e:
                print(f"DEBUG: Failed to delete Pinecone namespace: {e}")

        # 3. Delete Redis Key
        if redis_client:
            redis_client.delete(f"session:{session_id}")
            print(f"DEBUG: Deleted Redis session:{session_id}")

        return {"success": True, "message": "Session fully cleaned up"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  [SUCCESS] PDF RAG Assistant running at -> http://localhost:{port}\n")
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=True,       # dev only — remove in production
        log_level="warning", # Suppress noisy 'INFO: GET /' access logs

    )
