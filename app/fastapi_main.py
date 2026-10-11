from fastapi import FastAPI

# 실행 코드
# python -m uv run fastapi dev .\fastapi_main.py

app = FastAPI()


@app.get("/")
async def root():
    return {"message": "Hello World"}