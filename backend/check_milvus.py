from pymilvus import connections, utility, Collection

def check_milvus():
    print("Connecting to Milvus...")
    connections.connect("default", host="localhost", port="19530")
    
    collections = utility.list_collections()
    print(f"\nAvailable Collections: {collections}")
    
    target_collection = "financial_memory"
    
    if target_collection in collections:
        collection = Collection(target_collection)
        print(f"\nLoading '{target_collection}' into memory...")
        collection.load()
        
        print(f"\n--- '{target_collection}' Details ---")
        print(f"Total Entities: {collection.num_entities}")
        print(f"Schema: {collection.schema}")
        
        try:
            print("\nTrying to query top 5 entities...")
            # Query all records
            results = collection.query(expr="id != ''", limit=10, output_fields=["id", "text", "user_id"])
            for res in results:
                print(res)
        except Exception as e:
            print(f"Could not query rows: {e}")
    else:
        print(f"\nCollection '{target_collection}' not found.")

if __name__ == "__main__":
    check_milvus()
