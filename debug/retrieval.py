import chromadb
from pprint import pprint

# This script checks the content of your ChromaDB collection.
def inspect_database(persist_directory="../chroma_store", collection_name="rag_docs"):
    print(f"[*] Connecting to database at: '{persist_directory}'")
    try:
        client = chromadb.PersistentClient(path=persist_directory)
        collection = client.get_collection(name=collection_name)
        
        count = collection.count()
        print(f"[+] Successfully connected to collection '{collection_name}'.")
        print(f"    Total embedded chunks: {count}")

        if count == 0:
            print("[!] The database collection is empty. The embedding step did not add any documents.")
            return

        print("\n--- Fetching a sample of 5 embedded chunks ---")
        # Use collection.get() to retrieve records without a query
        results = collection.get(limit=5, include=["metadatas", "documents"])
        
        # Using pprint for readable output
        pprint(results)
        print("\n--- End of Report ---")

    except Exception as e:
        print(f"[!!] An error occurred: {e}")
        print("[!] This might mean the collection doesn't exist or the path is wrong.")

if __name__ == "__main__":
    inspect_database()