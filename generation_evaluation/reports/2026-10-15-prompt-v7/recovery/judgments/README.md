# Recovered v7 judgments

JSON bodies are reconstructed from the four designated rollout logs. Each JSON file has a `.source.md` sidecar with one-based source line numbers and extraction method. No historical command or shell script was executed; only literal data and narrowly interpreted assignment patches were extracted.

- `development-judgments-initial.json`: 36 responses, 126 required checks; content={'pass': 24, 'partial': 10, 'fail': 2, 'uncertain': 0}.
- `development-judgments-rechecked.json`: 36 responses, 126 required checks; content={'pass': 24, 'partial': 10, 'fail': 2, 'uncertain': 0}.
- `final-1-judgments.json`: 24 responses, 90 required checks; content={'pass': 14, 'partial': 8, 'fail': 2, 'uncertain': 0}.
- `final-boundary-judgments.json`: 12 responses, 48 required checks; content={'pass': 6, 'partial': 0, 'fail': 6, 'uncertain': 0}.
- `final-2-judgments.json`: 24 responses, 90 required checks; content={'pass': 10, 'partial': 13, 'fail': 1, 'uncertain': 0}.
- `final-2-judgments-rechecked.json`: 24 responses, 90 required checks; content={'pass': 10, 'partial': 14, 'fail': 0, 'uncertain': 0}.
- `final-3-judgments.json`: 24 responses, 90 required checks; content={'pass': 11, 'partial': 13, 'fail': 0, 'uncertain': 0}.
- `final-3-judgments-rechecked.json`: 24 responses, 90 required checks; content={'pass': 11, 'partial': 13, 'fail': 0, 'uncertain': 0}.

The response-judgment sets are development, final-1, final-2, and final-3. `final-boundary-judgments.json` is the separate H09/H12 boundary correction. Initial and rechecked versions are retained separately where the logs show both.
