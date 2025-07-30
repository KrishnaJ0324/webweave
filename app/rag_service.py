import chromadb
import os
from dotenv import load_dotenv
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from google.generativeai import GenerativeModel, configure
import google.generativeai as genai

load_dotenv()

class RAGService:
    def __init__(self, persist_directory="chroma_store"):
        # Load API key and configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env")

        configure(api_key=api_key)
        self.model = GenerativeModel("models/gemini-1.5-flash-latest")

        # ChromaDB setup
        self.client = chromadb.PersistentClient(path=persist_directory)
        embedding_function = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        self.collection = self.client.get_or_create_collection(
            name="rag_docs",
            embedding_function=embedding_function
        )

    def answer_query(self, query):
        results = self.collection.query(query_texts=[query], n_results=5)

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        embeddings = results.get("distances", [[]])[0]

        if not documents:
            return {"error": "No relevant chunks found."}

        formatted_chunks = []
        raw_blocks = []

        for i, (doc, meta) in enumerate(zip(documents, metadatas)):
            score = 1.0 - embeddings[i] if i < len(embeddings) else 0.0
            block = {
                "chunk": doc,
                "source": meta.get("source"),
                "title": meta.get("title"),
                "type": meta.get("type"),
                "score": score
            }
            formatted_chunks.append(block)
            raw_blocks.append(doc)
        print("exit")
        
        # Gemini prompt
        prompt = (
            "You are a RAG summarizer system. Given the following text chunks from crawled web pages, "
            "filter out duplicates or irrelevant text, and produce the most accurate set of one or more non-overlapping blocks of relevant information. "
            "Each block should be factually accurate and directly related to the question: "
            f"\"{query}\".\n\n"
            "Chunks:\n\n" + "\n---\n".join(raw_blocks) +
            "\n\nReturn ONLY the refined, highly accurate information. Then give a concise summary for user clarity."
        )

        try:
            gemini_response = self.model.generate_content({
                "parts": [{"text": prompt}]
            })

            refined_answer = gemini_response.text.strip()
            print(refined_answer)

            return {
                "refined_chunks": formatted_chunks,
                "gemini_summary": refined_answer
            }

        except Exception as e:
            print(e)
            return {"error": f"Gemini generation failed: {str(e)}"}

# import chromadb
# from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# class RAGService:
#     def __init__(self, persist_directory="chroma_store"):
#         # CHANGED: Updated to the new ChromaDB persistent client initialization
#         self.client = chromadb.PersistentClient(path=persist_directory)
        
#         embedding_function = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        
#         self.collection = self.client.get_or_create_collection(
#             name="rag_docs",
#             embedding_function=embedding_function
#         )

#     def answer_query(self, query):
#         results = self.collection.query(
#             query_texts=[query], 
#             n_results=5
#         )
        
#         documents = results.get("documents", [[]])[0]
#         metadatas = results.get("metadatas", [[]])[0]

#         answers = []
#         for doc, meta in zip(documents, metadatas):
#             answers.append({
#                 "chunk": doc,
#                 "source": meta.get("source"),
#                 "type": meta.get("type"),
#                 "title": meta.get("title")
#             })
#         return {"answers": answers}