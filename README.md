# ExplainDoc - API-Based PDF RAG Application (Talking_pdf v2)

ExplainDoc is a decoupled Retrieval-Augmented Generation (RAG) chat application that allows users to upload PDFs and ask questions about their content. The project is split into a pure static frontend and a stateless FastAPI backend, making it perfect for serverless hosting.

## 🚀 Features

- **Decoupled Architecture**: Separate `frontend` (HTML/JS/CSS) and `backend` (FastAPI).
- **Stateless Sessions**: Chat history and namespace tracking powered by Upstash Redis.
- **Intelligent Retrieval**: Multi-query expansion with semantic search via Pinecone.
- **Advanced Reranking**: Jina AI Reranker (top 10 chunks) for maximum context relevance.
- **Semantic Caching**: Skips the LLM and instantly returns answers for similar/repeated questions.
- **Progress Tracking**: Simulated upload progress UI for improved user experience.

## 🏗️ Architecture Split

### 1. Frontend (`/frontend`)
- Pure HTML, Vanilla CSS, and Vanilla JS.
- Communicates with the backend entirely via REST API (`fetch`).
- Manages local session IDs using `sessionStorage`.
- **Deployment**: Can be hosted freely on **Vercel**, Netlify, or GitHub Pages.

### 2. Backend (`/backend`)
- **Framework**: FastAPI (Python).
- **LLM Routing**: LangChain with OpenRouter (Supports OpenAI, Anthropic, Gemini, etc.).
- **Vector DB**: Pinecone (`apirag-1024` index).
- **State Store**: Upstash Redis (tracks session history across requests).
- **Embeddings/Reranker**: Jina AI API.
- **Deployment**: Can be hosted freely on **Render**, Heroku, or AWS.

## 🛠️ Local Setup

### 1. Backend Setup
Navigate to the root directory and create a virtual environment:
```bash
python -m venv .venv
# Activate on Windows:
.venv\Scripts\activate
# Activate on Mac/Linux:
source .venv/bin/activate
```

Navigate to the `backend` folder and install dependencies:
```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Configuration
Copy the template `.env` file to the `backend` folder (or use `env.example` in the root):
```bash
cp env.example backend/.env
```
Ensure you fill out all the keys (OpenRouter, Pinecone, Jina, Upstash Redis).

### 3. Start the Backend (API)
```bash
cd backend
python app.py
```
*The backend will run on `http://localhost:5000`.*

### 4. Start the Frontend (UI)
Open a **new** terminal, navigate to the frontend folder, and start a local web server:
```bash
cd frontend
python -m http.server 3000
```
*Open your browser and visit `http://localhost:3000`.*

## 🚀 Production Deployment

### Deploying the Frontend (Vercel)
1. In `frontend/main.js`, change `API_BASE_URL` to your future Render URL.
2. Drag and drop the `frontend` folder directly into Vercel, or connect your GitHub repository and set the Root Directory to `frontend`.

### Deploying the Backend (Render)
1. Connect your GitHub repository to Render as a "Web Service".
2. Set the Root Directory to `backend`.
3. Set the Build Command to `pip install -r requirements.txt`.
4. Set the Start Command to `python app.py`.
5. Add all your `.env` variables to the Render dashboard.

## ⚙️ Technical Tuning

- **Semantic Cache (`SEMANTIC_CACHE_THRESHOLD`)**: Set to `0.80` to cache responses to similar questions.
- **Jina Reranker (`JINA_TOP_N`)**: Set to `10` to provide the LLM with the 10 best chunks.
- **MultiQuery**: Generates 3 versions of every question.
- **Pinecone (`top_k`)**: Fetches 5 chunks per query to speed up the reranker pipeline.
