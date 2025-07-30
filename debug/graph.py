import pickle
import networkx as nx
import os

GRAPH_PATH = os.path.join('..', 'data', 'crawled_graph.gpickle')

print(f"[*] Inspecting graph file: {GRAPH_PATH}")

if not os.path.exists(GRAPH_PATH):
    print(f"[!] File not found. Make sure the path is correct.")
    exit()

try:
    with open(GRAPH_PATH, 'rb') as f:
        graph = pickle.load(f)

    print(f"\n[+] Graph loaded successfully.")
    print(f"    - Total nodes: {graph.number_of_nodes()}")
    print(f"    - Total edges: {graph.number_of_edges()}\n")

    if graph.number_of_nodes() == 0:
        print("[!] The graph is empty.")
    else:
        print("--- Node Details ---")
        for i, (node_id, data) in enumerate(graph.nodes(data=True)):
            print(f"\n[Node {i+1}]")
            print(f"  ID: {node_id}")
            for key, value in data.items():
                # Truncate long content for readability
                if isinstance(value, str) and len(value) > 150:
                    value = value[:150] + '...'
                print(f"  {key}: {value}")
        print("\n--- End of Report ---")

except Exception as e:
    print(f"[!!] An error occurred while inspecting the graph: {e}")