# МедВед.Код2 API foundation

FastAPI backend foundation with demo authorization and an in-memory survey session service.
Emergency rules and MAX host verification are completed in subsequent feature branches.

Run from `apps/api` after installing `requirements-backend.txt` and setting a random
`SESSION_SIGNING_KEY` of at least 32 characters and `DEMO_MODE=true`:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
