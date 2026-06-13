import os

import chromadb
from dotenv import load_dotenv
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from anthropic import Anthropic

load_dotenv()

# Embedding model — MUST match the one used in app/embedder.py
EMBED_MODEL = "all-MiniLM-L6-v2"
# Anthropic chat model used to refine/summarize retrieved chunks
ANTHROPIC_MODEL = "claude-haiku-4-5"


class RAGService:
    def __init__(self, persist_directory="chroma_store"):
        # Load API key and configure the Anthropic client
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in .env")

        self.client_llm = Anthropic(api_key=api_key)
        self.model = ANTHROPIC_MODEL

        # ChromaDB setup
        self.client = chromadb.PersistentClient(path=persist_directory)
        embedding_function = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
        self.collection = self.client.get_or_create_collection(
            name="rag_docs",
            embedding_function=embedding_function
        )

    def answer_query(self, query):
        results = self.collection.query(query_texts=[query], n_results=5)

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not documents:
            return {"error": "No relevant chunks found."}

        formatted_chunks = []
        raw_blocks = []

        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            score = 1.0 - distances[i] if i < len(distances) else 0.0
            block = {
                "chunk": doc,
                "source": meta.get("source"),
                "title": meta.get("title"),
                "type": meta.get("type"),
                "score": score
            }
            formatted_chunks.append(block)
            raw_blocks.append(doc)

        # Prompt the LLM to refine + summarize the retrieved chunks
        prompt = (
            "You are a RAG summarizer system. Given the following text chunks from crawled web pages, "
            "filter out duplicates or irrelevant text, and produce the most accurate set of one or more non-overlapping blocks of relevant information. "
            "Each block should be factually accurate and directly related to the question: "
            f"\"{query}\".\n\n"
            "Chunks:\n\n" + "\n---\n".join(raw_blocks) +
            "\n\nReturn ONLY the refined, highly accurate information. Then give a concise summary for user clarity."
        )

        try:
            response = self.client_llm.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            refined_answer = "".join(
                block.text for block in response.content if block.type == "text"
            ).strip()

            return {
                "refined_chunks": formatted_chunks,
                "summary": refined_answer,
            }

        except Exception as e:
            return {"error": f"LLM generation failed: {str(e)}"}
