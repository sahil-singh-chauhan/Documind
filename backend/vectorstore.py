import os
import time
import traceback
import hashlib
import requests
from typing import List

from langchain_core.embeddings import Embeddings
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pinecone import Pinecone

from config import (
    JINA_API_KEY, 
    JINA_EMBEDDING_DIMENSIONS, 
    EMBEDDING_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME
)

# --- Jina Embeddings Wrapper ---
class JinaEmbeddingsWrapper(Embeddings):
    def __init__(self, model_name: str, api_key: str, dimensions: int = 1024):
        self.model_name = model_name
        self.api_key = api_key
        self.dimensions = dimensions
        if not api_key:
            raise ValueError("JINA_API_KEY is required for Jina embeddings")

    def _call_jina_api(self, texts: List[str], task: str = "retrieval.passage") -> List[List[float]]:
        """Call Jina embeddings API v3"""
        payload = {
            "model": self.model_name,
            "task": task,
            "dimensions": self.dimensions,
            "late_chunking": False,
            "embedding_type": "float",
            "input": texts
        }
        
        try:
            print(f"DEBUG: Calling Jina embeddings API for {len(texts)} texts")
            resp = requests.post(
                "https://api.jina.ai/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60
            )
            
            if resp.status_code != 200:
                print(f"DEBUG: Jina API error {resp.status_code}: {resp.text}")
                raise Exception(f"Jina API error: {resp.status_code} - {resp.text}")
            
            data = resp.json()
            embeddings = [item["embedding"] for item in data["data"]]
            print(f"DEBUG: Successfully got {len(embeddings)} embeddings from Jina API")
            return embeddings
            
        except Exception as e:
            print(f"DEBUG: Jina embeddings API failed: {e}")
            raise e

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        batch_size = 50  
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            print(f"DEBUG: Processing batch {i//batch_size + 1}/{(len(texts) + batch_size - 1)//batch_size} with {len(batch)} texts")
            batch_embeddings = self._call_jina_api(batch, task="retrieval.passage")
            all_embeddings.extend(batch_embeddings)
        
        return all_embeddings

    def embed_query(self, text: str) -> List[float]:
        # Use retrieval.query task — Jina v3 uses different weights per task
        embeddings = self._call_jina_api([text], task="retrieval.query")
        return embeddings[0]

# --- Global Initialization ---
embeddings_model = JinaEmbeddingsWrapper(EMBEDDING_MODEL, JINA_API_KEY, JINA_EMBEDDING_DIMENSIONS)
pc = Pinecone(api_key=PINECONE_API_KEY)
INDEX_NAME = PINECONE_INDEX_NAME


# --- Vector Store Operations ---
def get_embedding_dimension() -> int:
    try:
        return JINA_EMBEDDING_DIMENSIONS
    except Exception:
        return 1024

def ensure_index_exists():
    dim = get_embedding_dimension()
    existing = [idx["name"] for idx in pc.list_indexes()]  # type: ignore
    if INDEX_NAME not in existing:
        pc.create_index(name=INDEX_NAME, dimension=dim, metric="cosine")

def load_document(file_path: str):
    """Load a document from disk using the correct loader based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    print(f"DEBUG: Loading file with extension: {ext}")
    
    if ext == '.pdf':
        loader = PyPDFLoader(file_path)
    elif ext in ('.docx', '.doc'):
        loader = Docx2txtLoader(file_path)
    elif ext == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"Unsupported file extension: {ext}")
    
    return loader.load()


def upsert_pdf_to_vectorstore(pdf_path: str, namespace: str, original_filename: str = None) -> int:
    # Use the original user-facing filename as the title so Pinecone metadata
    # filters (e.g. filter by title == 'Building AI Agents.pdf') work correctly.
    # Without this, the stored title would be the UUID temp filename.
    display_title = original_filename or os.path.basename(pdf_path)
    print(f"DEBUG: Loading document from {pdf_path} (title: {display_title})")
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=1000,
        chunk_overlap=150,
    )
    
    data = load_document(pdf_path)
    print(f"DEBUG: Loaded {len(data)} pages/sections from document")
    
    chunks = splitter.split_documents(data)
    print(f"DEBUG: Split into {len(chunks)} chunks")

    title = display_title  # Use the original filename, not the UUID temp name
    for idx, chunk in enumerate(chunks):
        chunk.metadata["source"] = pdf_path
        chunk.metadata["title"] = title
        if "page" in chunk.metadata:
            # Langchain extracts pages as 0-indexed. Humans and PDF viewers are 1-indexed.
            page_num = int(chunk.metadata["page"]) + 1
            chunk.metadata["page"] = page_num
            section = f"page {page_num}"
        else:
            section = "unknown"
        chunk.metadata["section"] = section
        chunk.metadata["position"] = idx

    print(f"DEBUG: Adding {len(chunks)} chunks to Pinecone namespace: {namespace}")
    
    try:
        index = pc.Index(INDEX_NAME)
        chunk_texts = [chunk.page_content for chunk in chunks]
        print(f"DEBUG: Generating embeddings for {len(chunk_texts)} chunks in batch")
        embeddings = embeddings_model.embed_documents(chunk_texts)
        print(f"DEBUG: Generated {len(embeddings)} embeddings")
        
        # Generate a stable short hash from the filename so each file gets
        # UNIQUE vector IDs. Without this, PDF-2 overwrites PDF-1's vectors
        # because they'd both get ids like chunk_0_session_xxx, chunk_1_session_xxx.
        file_hash = hashlib.md5(os.path.basename(pdf_path).encode()).hexdigest()[:8]
        
        vectors_to_upsert = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vector_data = {
                "id": f"chunk_{file_hash}_{i}_{namespace}",
                "values": embedding,
                "metadata": {
                    "text": chunk.page_content,
                    "source": chunk.metadata.get("source", ""),
                    "title": chunk.metadata.get("title", ""),
                    "section": chunk.metadata.get("section", ""),
                    "position": chunk.metadata.get("position", i)
                }
            }
            vectors_to_upsert.append(vector_data)
        
        print(f"DEBUG: Upserting {len(vectors_to_upsert)} vectors to Pinecone")
        
        UPSERT_BATCH = 100
        total_upserted = 0
        for bi in range(0, len(vectors_to_upsert), UPSERT_BATCH):
            batch = vectors_to_upsert[bi:bi + UPSERT_BATCH]
            resp = index.upsert(vectors=batch, namespace=namespace)
            total_upserted += resp.get('upserted_count', len(batch))
            print(f"DEBUG: Upserted batch {bi // UPSERT_BATCH + 1}, running total: {total_upserted}")
        print(f"DEBUG: Successfully upserted {total_upserted} vectors total")

        ready = False
        target_count = total_upserted if total_upserted > 0 else len(vectors_to_upsert)
        for _ in range(6):  # up to ~3s
            try:
                stats = index.describe_index_stats()
                ns = stats.get('namespaces', {}).get(namespace, {})
                count = ns.get('vector_count', 0)
                if count >= max(1, min(target_count, 1)):
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        print(f"DEBUG: Namespace ready: {ready}")
        
    except Exception as e:
        print(f"DEBUG: Failed to add chunks to Pinecone: {e}")
        traceback.print_exc()
        raise e
    
    return len(chunks)
