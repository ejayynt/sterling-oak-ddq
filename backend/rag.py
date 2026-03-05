import os
import time
import logging
from dotenv import load_dotenv
from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlite_vec import serialize_float32
from mistralai import Mistral

from backend.database import get_vec_connection

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Load API key from project-root .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

client = Mistral(api_key=os.environ.get("MISTRAL_API_KEY", ""))

EMBED_MODEL = "mistral-embed"      # 1024 dimensions
CHAT_MODEL = "mistral-small-latest"  # fast, accurate, great for compliance


# ---------------------------------------------------------------------------
# Rate-limit aware API wrapper
# ---------------------------------------------------------------------------
def _call_with_retry(fn, label="API call", max_retries=5, base_delay=10):
    """Call fn() with exponential backoff on ANY error."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries:
                log.error(f"[{label}] All {max_retries} retries exhausted: {e}")
                raise
            delay = base_delay * (attempt + 1)
            log.warning(f"[{label}] Attempt {attempt+1} failed: {e}")
            log.warning(f"[{label}] Waiting {delay}s before retry...")
            time.sleep(delay)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using Mistral embeddings."""
    def _do():
        response = client.embeddings.create(model=EMBED_MODEL, inputs=texts)
        return [item.embedding for item in response.data]
    return _call_with_retry(_do, label="embed_batch")


def embed_single(text: str) -> list[float]:
    """Embed a single text string."""
    results = embed_texts([text])
    return results[0]


def generate_text(system_prompt: str, user_prompt: str) -> str:
    """Generate text using Mistral chat API."""
    def _do():
        response = client.chat.complete(
            model=CHAT_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content
    return _call_with_retry(_do, label="generate")


# ---------------------------------------------------------------------------
# Document ingestion
# ---------------------------------------------------------------------------

def extract_text_from_docx(file_path: str) -> str:
    """Extract all non-empty paragraph text from a .docx file."""
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])


def ingest_reference_document(file_path: str, doc_name: str, user_id: int):
    """Chunk a .docx, embed each chunk, and store in sqlite-vec with user isolation."""
    text = extract_text_from_docx(file_path)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_text(text)

    # Batch-embed all chunks at once (much faster, fewer API calls)
    log.info(f"Ingesting {len(chunks)} chunks from {doc_name} for user {user_id}")
    vectors = embed_texts(chunks)

    conn = get_vec_connection()
    cursor = conn.cursor()

    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        cursor.execute(
            "INSERT INTO document_embeddings (embedding, user_id, doc_name, chunk_text) VALUES (?, ?, ?, ?)",
            (serialize_float32(vector), user_id, doc_name, chunk),
        )

    conn.commit()
    conn.close()
    log.info(f"Finished ingesting {doc_name} ({len(chunks)} chunks)")


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a strict compliance assistant for an institutional asset management firm.
Answer the question using ONLY the provided context.
If the context does not explicitly contain the answer, output exactly: 'Not found in references.'
Do not hallucinate or use outside knowledge. Keep it concise and professional."""


def generate_answer_for_question(question: str, user_id: int) -> dict:
    """Retrieve top-3 context chunks via KNN (scoped to user), then ask the LLM to answer."""
    question_vector = embed_single(question)

    conn = get_vec_connection()
    cursor = conn.cursor()

    # Fetch extra results, then filter by user_id in Python
    # (sqlite-vec KNN doesn't support WHERE on auxiliary columns)
    cursor.execute(
        """
        SELECT rowid, distance, user_id, doc_name, chunk_text
        FROM document_embeddings
        WHERE embedding MATCH ?
          AND k = 15
        ORDER BY distance
    """,
        (serialize_float32(question_vector),),
    )

    all_results = cursor.fetchall()
    conn.close()

    # Filter to only this user's embeddings, take top 3
    results = [r for r in all_results if r[2] == user_id][:3]

    if not results:
        return {
            "answer": "Not found in references.",
            "citation": "None",
            "snippet": "None",
            "confidence": 0,
        }

    # Build context from top chunks
    context_text = "\n\n".join(
        [f"Source: {row[3]}\nText: {row[4]}" for row in results]
    )
    best_distance = results[0][1]
    best_citation = results[0][3]
    best_snippet = results[0][4]

    # Confidence: cosine distance 0 = identical, 2 = opposite
    confidence = max(0, round((1 - best_distance) * 100))

    user_prompt = f"Context:\n{context_text}\n\nQuestion: {question}"
    answer = generate_text(SYSTEM_PROMPT, user_prompt)

    if "Not found in references" in answer:
        return {
            "answer": "Not found in references.",
            "citation": "None",
            "snippet": "None",
            "confidence": 0,
        }

    return {
        "answer": answer,
        "citation": best_citation,
        "snippet": best_snippet,
        "confidence": confidence,
    }
