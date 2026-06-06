import os
import re
import time
import requests
from typing import List

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever
from langchain_openai import ChatOpenAI
from langchain_classic.retrievers.multi_query import MultiQueryRetriever
from config import JINA_API_KEY, SEMANTIC_CACHE_THRESHOLD
from utils import extract_doc_fields, clean_snippet_text, clean_output
from vectorstore import embeddings_model, pc, INDEX_NAME

# --- LLM Initialization ---
# We use OpenRouter via LangChain's ChatOpenAI interface, which supports Gemini, Claude, and OpenAI models automatically!
llm = ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini"))

query_prompt = PromptTemplate(
    input_variables=["question"],
    template=(
        """You are an AI language model assistant. Your task is to generate
     three different versions of the given user question to retrieve relevant documents
    from a vector database. By generating multiple perspectives on the user question,
    your goal is to help the user overcome some of the limitations of the distance
    based similarity search. Provide these alternative questions separated by new lines.
    Original question: {question}"""
    ),
)


# --- RAG Core Functions ---
def jina_rerank(question: str, docs: list, top_n: int = 3):
    """Rerank documents using Jina API"""
    api_key = JINA_API_KEY
    model = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v1-base-en")
    if not api_key or not docs:
        print(f"DEBUG: Jina rerank skipped - API key: {bool(api_key)}, docs: {len(docs)}")
        return docs  

    def get_text(d):
        if hasattr(d, "page_content"):
            return d.page_content
        if isinstance(d, dict) and "document" in d:
            nd = d["document"]
            if hasattr(nd, "page_content"):
                return nd.page_content
            return nd.get("page_content", nd.get("text", ""))
        return d.get("page_content", d.get("text", ""))

    documents_for_api = [{"text": get_text(d)} for d in docs]
    
    payload = {
        "model": model,
        "query": question,
        "documents": documents_for_api,
        "top_n": int(os.getenv("JINA_TOP_N", str(top_n)))
    }
    
    try:
        print(f"DEBUG: Calling Jina rerank API with {len(documents_for_api)} documents")
        resp = requests.post(
            "https://api.jina.ai/v1/rerank",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        
        if resp.status_code != 200:
            print(f"DEBUG: Jina API error {resp.status_code}: {resp.text}")
            return docs  
            
        data = resp.json()
        print(f"DEBUG: Jina API response: {data}")
        
        results = data.get("results", [])
        if not results:
            print("DEBUG: No results from Jina API")
            return docs
            
        out = []
        for r in results:
            idx = r.get("index")
            if idx is not None and 0 <= idx < len(docs):
                out.append(docs[idx])
        
        print(f"DEBUG: Jina rerank successful, returning {len(out)} documents")
        return out or docs
    except Exception as e:
        print(f"DEBUG: Jina rerank failed: {e}")
        return docs  


def build_retriever(namespace: str | None, pinecone_filter: dict | None = None):
    print(f"DEBUG: Building retriever for namespace: {namespace}, filter: {pinecone_filter}")
    
    class DirectPineconeRetriever(BaseRetriever):
        index: object
        embeddings_model: object
        namespace: str
        pinecone_filter: object  # dict or None
        
        def __init__(self, index, embeddings_model, namespace, pinecone_filter=None):
            super().__init__(
                index=index,
                embeddings_model=embeddings_model,
                namespace=namespace,
                pinecone_filter=pinecone_filter
            )
        
        def _get_relevant_documents(self, query: str) -> List[Document]:
            query_embedding = self.embeddings_model.embed_query(query)
            
            # Build query kwargs - only add filter if one was specified
            query_kwargs = dict(
                vector=query_embedding,
                top_k=5,
                namespace=self.namespace,
                include_metadata=True
            )
            if self.pinecone_filter:
                query_kwargs["filter"] = self.pinecone_filter
            
            results = self.index.query(**query_kwargs)
            
            docs = []
            for match in results['matches']:
                metadata = match.get('metadata', {})
                text_content = metadata.get('text', '')
                if not text_content:
                    text_content = metadata.get('page_content', '')
                
                doc = Document(
                    page_content=text_content,
                    metadata=metadata
                )
                docs.append(doc)
            return docs
    
    index = pc.Index(INDEX_NAME)
    base_retriever = DirectPineconeRetriever(index, embeddings_model, namespace, pinecone_filter)
    
    if llm is None:
        return base_retriever
    
    return MultiQueryRetriever.from_llm(base_retriever, llm, prompt=query_prompt)

def resolve_target_document(question: str, uploaded_files: list) -> str | None:
    """
    Detect if the user is asking about a SPECIFIC document by ordinal or explicit name.
    Returns the filename to filter on, or None if we should search all docs.

    CONSERVATIVE by design — only triggers on clear, unambiguous targeting:
      "look only at the first pdf"         → uploaded_files[0]  (ordinal)
      "search only in resume.pdf"          → "resume.pdf"       (name + targeting word)
      "what was the first document?"       → uploaded_files[0]  (ordinal)

    Does NOT trigger on:
      "what is this pdf about?"            → None  (no ordinal, no targeting word)
      "tell me about building AI agents"   → None  (filename words but no targeting intent)
    """
    if not uploaded_files:
        return None

    q = question.lower()

    # --- Pattern 1: Ordinal numbers (first/second/third...) ---
    # These are always clear intent to target a specific document.
    ordinals = {
        "first": 0, "1st": 0,
        "second": 1, "2nd": 1,
        "third": 2, "3rd": 2,
        "fourth": 3, "4th": 3,
        "fifth": 4, "5th": 4,
    }
    for word, idx in ordinals.items():
        if word in q and idx < len(uploaded_files):
            return uploaded_files[idx]

    # --- Pattern 2: Explicit filename + targeting intent word ---
    # We ONLY match a filename if the user also uses a targeting word
    # like "only", "just", "specifically", "from", "focus on" etc.
    # This prevents "what is this about?" from matching every uploaded filename.
    targeting_words = ("only", "just", "specifically", "focus on", "from the", "in the file", "in the doc", "that file", "that document", "that pdf", "that doc")
    has_targeting_intent = any(tw in q for tw in targeting_words)

    if has_targeting_intent:
        for name in uploaded_files:
            stem = os.path.splitext(name)[0].lower()
            if name.lower() in q or stem in q:
                return name

    return None



def generate_answer_stream(namespace: str, question: str, chat_history: list, uploaded_files: list = []):
    """
    Generator that yields Server-Sent Events (SSE) strings.
    All heavy Jina API calls (embedding + reranking) happen BEFORE yielding
    so that Windows does not forcibly reset the HTTP connection mid-stream.
    
    uploaded_files: ordered list of filenames uploaded in this session.
    """
    import json
    _t0 = time.perf_counter()
    index = pc.Index(INDEX_NAME)

    # -------------------------------------------------------------------------
    # 1. CHECK SEMANTIC CACHE FIRST (before doing anything expensive)
    # -------------------------------------------------------------------------
    question_embedding = embeddings_model.embed_query(question)
    try:
        cache_results = index.query(
            vector=question_embedding,
            top_k=1,
            namespace="semantic-cache",
            filter={"doc_namespace": {"$eq": namespace}},  # CRITICAL: only match cache from THIS session's namespace
            include_metadata=True
        )
        if cache_results['matches']:
            best_match = cache_results['matches'][0]
            if best_match['score'] >= float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.80")):
                cached_meta = best_match.get("metadata", {})
                cached_answer = cached_meta.get("answer")
                
                if cached_answer:
                    print(f"DEBUG: CACHE HIT! Similarity: {best_match['score']:.3f}")
                    full_answer = cached_answer + "\n\n*(Answered instantly from Semantic Cache)*"
                    yield f"data: {json.dumps({'content': full_answer})}\n\n"
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return
    except Exception as e:
        print(f"DEBUG: Cache check failed: {e}")

    # -------------------------------------------------------------------------
    # 2. Detect if user is asking about a specific document
    # -------------------------------------------------------------------------
    target_doc = resolve_target_document(question, uploaded_files)
    pinecone_filter = None
    if target_doc:
        print(f"DEBUG: User is asking specifically about '{target_doc}' — applying Pinecone filter")
        pinecone_filter = {"title": {"$eq": target_doc}}

    # -------------------------------------------------------------------------
    # 3. RUN FULL RAG PIPELINE - Do ALL network calls HERE before streaming
    # This prevents Windows from killing the Jina connection mid-stream
    # -------------------------------------------------------------------------
    print("DEBUG: Running full RAG pipeline...")
    retriever = build_retriever(namespace, pinecone_filter)
    retrieved_docs = retriever.invoke(question)
    reranked_docs = jina_rerank(question, retrieved_docs, top_n=int(os.getenv("JINA_TOP_N", "5")))
    print(f"DEBUG: Got {len(reranked_docs)} reranked docs, now starting stream...")

    import urllib.parse
    formatted_context = []
    source_snippets = []
    frontend_snippets_data = []
    for i, d in enumerate(reranked_docs, 1):
        metadata, page_content = extract_doc_fields(d)
        
        # Plain text for the LLM
        source_info_plain = f"[{i}] "
        if metadata.get('title'):
            source_info_plain += f"Source: {metadata['title']}"
        if metadata.get('section') and metadata['section'] != 'unknown':
            source_info_plain += f", {metadata['section']}"
            
        formatted_context.append(f"{source_info_plain}\n{page_content}")
        
        # Markdown links for the frontend sources UI
        snippet = clean_snippet_text(page_content)
        if snippet:
            source_info_html = f"[{i}] "
            if metadata.get('title'):
                source_info_html += f"Source: {metadata['title']}"
            
            page_num = None
            if metadata.get('section') and metadata['section'] != 'unknown':
                section = metadata['section']
                if section.startswith("page "):
                    page_num = section.split(" ")[1]
                    safe_title = urllib.parse.quote(metadata.get('title', ''))
                    source_info_html += f", [📄 Page {page_num}](#jump:{safe_title}:{page_num})"
                else:
                    source_info_html += f", {section}"
            
            # The user requested to remove the bulky text snippets from the sources section
            # and ONLY show the headings and page number badges.
            source_snippets.append(source_info_html)
            
            # Store the raw snippet data for the frontend highlighting engine
            frontend_snippets_data.append({
                "id": i,
                "filename": metadata.get('title', ''),
                "page": int(page_num) if page_num else None,
                "text": snippet
            })

    context_text = "\n\n".join(formatted_context)

    history_turns = chat_history[-6:] if len(chat_history) > 6 else chat_history
    history_text = ""
    if history_turns:
        lines = [f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}" for msg in history_turns]
        history_text = "Conversation History:\n" + "\n".join(lines) + "\n\n"

    # Build a document catalog so the LLM knows what files exist and in what order
    doc_catalog = ""
    if uploaded_files:
        catalog_lines = [f"  {i+1}. {name}" for i, name in enumerate(uploaded_files)]
        doc_catalog = "Uploaded Documents (in order):\n" + "\n".join(catalog_lines) + "\n\n"
        if target_doc:
            doc_catalog += f"Note: The user is asking specifically about document: '{target_doc}'\n\n"

    prompt_text = (
        f"{doc_catalog}"
        f"{history_text}"
        "Answer the question based only on the following context. Use inline citations [1], [2], etc. to reference specific sources from the context.\n\n"
        f"Context:\n{context_text}\n\nQuestion: {question}\n\n"
        "Instructions:\n"
        "1. Answer using only information from the provided context\n"
        "2. Use inline citations [1], [2], [3], etc. to reference specific parts of the context\n"
        "3. Use the Conversation History (if present) to understand follow-up questions\n"
        "4. You know which documents are uploaded and in what order — use this to answer questions like 'what was the first document?' or 'what is in the second file?'\n"
        "5. If the user asked to look only at a specific document, restrict your answer to that document's content\n"
        "6. If you cannot find relevant information in the context, say \"I cannot find relevant information in the provided context\"\n"
        "7. Do NOT provide source snippets - they will be added automatically\n\n"
        "Answer:"
    )

    # -------------------------------------------------------------------------
    # 4. STREAM THE LLM RESPONSE - Only the LLM stream happens here
    # -------------------------------------------------------------------------
    answer_text = ""
    for chunk in llm.stream(prompt_text):
        token = getattr(chunk, 'content', str(chunk))
        if token:
            answer_text += token
            yield f"data: {json.dumps({'content': token})}\n\n"

    answer = clean_output(answer_text)

    # Sources
    # Always show sources if the LLM used inline citations
    cited_numbers = set(int(n) for n in re.findall(r"\[(\d+)\]", answer))
    if cited_numbers:
        filtered = []
        for snippet in source_snippets:
            m = re.match(r"\[(\d+)\]", snippet.strip())
            if m and int(m.group(1)) in cited_numbers:
                filtered.append(snippet)
        if filtered:
            sources_text = "\n\n**Sources:**\n" + "\n\n".join(filtered)
            answer += sources_text
            yield f"data: {json.dumps({'content': sources_text})}\n\n"
            
            # Yield the structured snippet data for the PDF.js highlighter
            snippets_to_send = [s for s in frontend_snippets_data if s["id"] in cited_numbers]
            yield f"data: {json.dumps({'sources_data': snippets_to_send})}\n\n"

    # Save to semantic cache
    try:
        cache_id = f"cache_{int(time.time())}"
        index.upsert(
            vectors=[{
                "id": cache_id,
                "values": question_embedding,
                "metadata": {"question": question, "answer": answer, "doc_namespace": namespace}
            }],
            namespace="semantic-cache"
        )
        print("DEBUG: Saved answer to Semantic Cache!")
    except Exception as e:
        print(f"DEBUG: Failed to save to cache: {e}")

    _t1 = time.perf_counter()
    print(f"DEBUG: Stream complete in {(_t1 - _t0)*1000:.1f}ms")
    yield f"data: {json.dumps({'done': True})}\n\n"




def generate_answer_simple(namespace: str, question: str, chat_history: list[str] | list[dict]):
    _t0 = time.perf_counter()

    # ------------------------------------------------------------------------
    # SEMANTIC CACHING (PHASE 2)
    # Instead of just an exact match, we turn the user's question into a vector
    # and check if we have answered a >95% similar question for this exact PDF!
    # ------------------------------------------------------------------------
    print(f"DEBUG: Checking Semantic Cache for question: '{question}'")
    
    # 1. Turn the question into numbers (embedding)
    question_embedding = embeddings_model.embed_query(question)
    index = pc.Index(INDEX_NAME)
    
    try:
        # 2. Search the special 'semantic-cache' folder in Pinecone
        # We use a filter to ONLY check cache entries that belong to this specific PDF (namespace)
        cache_results = index.query(
            vector=question_embedding,
            top_k=1,
            namespace="semantic-cache",
            filter={"doc_namespace": {"$eq": namespace}},
            include_metadata=True
        )
        
        # 3. Check if we found a match that is extremely similar (>SEMANTIC_CACHE_THRESHOLD match)
        if cache_results['matches'] and cache_results['matches'][0]['score'] > SEMANTIC_CACHE_THRESHOLD:
            cached_answer = cache_results['matches'][0]['metadata'].get('answer')
            if cached_answer:
                print(f"DEBUG: ⚡ CACHE HIT! Similarity: {cache_results['matches'][0]['score']:.3f}")
                return cached_answer + "\n\n*(⚡ Answered instantly from Semantic Cache)*"
    except Exception as e:
        print(f"DEBUG: Cache check failed (safe to ignore): {e}")

    # =========================================================================
    # IF NO CACHE HIT: RUN THE FULL HEAVY RAG PIPELINE
    # =========================================================================

    # ── Step 1: Build retriever ──────────────────────────────────────────────
    retriever = build_retriever(namespace)
    _t1 = time.perf_counter()

    # ── Step 2: Retrieve (MultiQuery → Pinecone × N variants) ───────────────
    retrieved_docs = retriever.invoke(question)
    _t2 = time.perf_counter()
    print(f"DEBUG: Retrieved {len(retrieved_docs)} documents")

    # ── Step 3: Rerank (Jina reranker API) ──────────────────────────────────
    reranked_docs = jina_rerank(question, retrieved_docs, top_n=5)
    _t3 = time.perf_counter()
    print(f"DEBUG: Reranked to {len(reranked_docs)} documents")

    # ── Step 4: Build context ────────────────────────────────────────────────
    formatted_context = []
    source_snippets = []

    for i, d in enumerate(reranked_docs, 1):
        metadata, page_content = extract_doc_fields(d)
        source_info = f"[{i}] "
        if metadata.get('title'):
            source_info += f"Source: {metadata['title']}"
        if metadata.get('section') and metadata['section'] != 'unknown':
            source_info += f", {metadata['section']}"
        if metadata.get('position') is not None:
            try:
                source_info += f", Chunk {int(metadata['position']) + 1}"
            except Exception:
                pass
        formatted_context.append(f"{source_info}\n{page_content}")
        snippet = clean_snippet_text(page_content)
        if snippet:
            source_snippets.append(f"{source_info}\n{snippet}")

    context_text = "\n\n".join(formatted_context)
    _t4 = time.perf_counter()

    # ── Step 5: Format conversation history ─────────────────────────────────
    history_turns = chat_history[-6:] if len(chat_history) > 6 else chat_history
    history_text = ""
    if history_turns:
        lines = []
        for msg in history_turns:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        history_text = "Conversation History:\n" + "\n".join(lines) + "\n\n"

    # ── Step 6: LLM call ─────────────────────────────────────────────────────
    prompt_text = (
        f"{history_text}"
        "Answer the question based only on the following context. Use inline citations [1], [2], etc. to reference specific sources from the context.\n\n"
        f"Context:\n{context_text}\n\nQuestion: {question}\n\n"
        "Instructions:\n"
        "1. Answer using only information from the provided context\n"
        "2. Use inline citations [1], [2], [3], etc. to reference specific parts of the context\n"
        "3. Use the Conversation History (if present) to understand follow-up questions\n"
        "4. If you cannot find relevant information in the context, say \"I cannot find relevant information in the provided context\"\n"
        "5. Do NOT provide source snippets - they will be added automatically\n\n"
        "Answer:"
    )

    llm_resp = llm.invoke(prompt_text)
    answer_text = getattr(llm_resp, 'content', str(llm_resp))
    
    answer = clean_output(answer_text)
    _t5 = time.perf_counter()

    # ── Step 7: Source filtering (conditional) ───────────────────────────────
    source_keywords = ("source", "sources", "reference", "references", "citation",
                       "citations", "where did you find", "where is this from",
                       "show sources", "list sources", "which page", "what page")
    wants_sources = any(kw in question.lower() for kw in source_keywords)

    if wants_sources:
        cited_numbers = set(int(n) for n in re.findall(r"\[(\d+)\]", answer))
        filtered = []
        for snippet in source_snippets:
            m = re.match(r"\[(\d+)\]", snippet.strip())
            if m and int(m.group(1)) in cited_numbers:
                filtered.append(snippet)
        if filtered:
            answer += "\n\n**Sources:**\n" + "\n\n".join(filtered)

    _t6 = time.perf_counter()

    # ------------------------------------------------------------------------
    # SAVE TO SEMANTIC CACHE
    # Now that we spent 15 seconds generating an answer, let's save it to Pinecone
    # so we never have to do it again for this question!
    # ------------------------------------------------------------------------
    try:
        # We create a unique ID for this cache entry using the time
        cache_id = f"cache_{int(time.time())}"
        index.upsert(
            vectors=[{
                "id": cache_id,
                "values": question_embedding, # The vector representation of the question
                "metadata": {
                    "question": question,     # The raw text of the question
                    "answer": answer,         # The final LLM answer
                    "doc_namespace": namespace # Which PDF this answer belongs to!
                }
            }],
            namespace="semantic-cache"
        )
        print("DEBUG: Saved new answer to Semantic Cache!")
    except Exception as e:
        print(f"DEBUG: Failed to save to cache: {e}")

    # ── Timing summary ────────────────────────────────────────────────────────
    print("\n" + "─" * 55)
    print(f"  ⏱  RAG Pipeline  |  Q: {question[:48]!r}")
    print("─" * 55)
    print(f"  build_retriever  : {(_t1 - _t0)*1000:>7.1f} ms")
    print(f"  retrieval        : {(_t2 - _t1)*1000:>7.1f} ms  ({len(retrieved_docs)} docs fetched)")
    print(f"  reranking        : {(_t3 - _t2)*1000:>7.1f} ms  → {len(reranked_docs)} kept")
    print(f"  context build    : {(_t4 - _t3)*1000:>7.1f} ms  ({len(context_text)} chars)")
    print(f"  LLM call         : {(_t5 - _t4)*1000:>7.1f} ms")
    print(f"  source filter    : {(_t6 - _t5)*1000:>7.1f} ms")
    print(f"  TOTAL            : {(_t6 - _t0)*1000:>7.1f} ms")
    print("─" * 55 + "\n")

    return answer
