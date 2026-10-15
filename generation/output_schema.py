"""Strict structured-output schema for the public generation response."""

ANSWER_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

OPENAI_ANSWER_RESPONSE_FORMAT: dict[str, object] = {
    "type": "json_schema",
    "json_schema": {
        "name": "generation_answer",
        "strict": True,
        "schema": ANSWER_JSON_SCHEMA,
    },
}
