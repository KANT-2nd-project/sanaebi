from app.documents.context import DocumentContextProvider


def main():
    snapshot = DocumentContextProvider().snapshot()
    print("문서 개수:", len(snapshot.documents))
    print("Snapshot:", snapshot.fingerprint)


if __name__ == "__main__":
    main()
