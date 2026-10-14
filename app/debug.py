from app.company_knowledge import get_documents_path
from app.document_store import read_documents


def main():
    path = get_documents_path()
    documents = read_documents(path)

    print("문서 개수:", len(documents))
    if documents:
        print("첫 문서:", documents[0])

    print("문서 개수:", len(documents))  # 52

    print("모두 문자열:", all(isinstance(doc, str) for doc in documents))  # True


if __name__ == "__main__":
    main()
