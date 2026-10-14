# 질문과 분류 카테고리를 LangChain에 전달하는 함수
def generate_assistant_response(
    response: dict, category: str, *, provider: str | None = None
) -> dict:
    # 이 함수가 호출될 때 LangChain 실행기를 가져오기
    from sanaebi_assistant import process_response

    # 받은 response의 ok·text·reason을 바꾸지 않고 카테고리와 함께 전달
    if provider is not None:
        return process_response(
            response, classification_label=category, provider=provider
        )
    return process_response(response, classification_label=category)
