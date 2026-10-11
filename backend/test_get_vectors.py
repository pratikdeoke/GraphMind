from services.vector.milvus_service import get_milvus_service
milvus = get_milvus_service()

res = milvus.collection.query(expr="id != ''", limit=1, output_fields=["id", "text", "user_id"])
print("RAW QUERY:", res)

if res:
    user_id = res[0]['user_id']
    print(f"Testing for user {user_id}")
    vectors = milvus.get_user_vectors(user_id=user_id, limit=2)
    print(vectors)
