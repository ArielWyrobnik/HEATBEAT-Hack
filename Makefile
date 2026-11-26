dev:  ## API + frontend together
	./scripts/dev.sh

api:  ## API only, http://127.0.0.1:8000/docs
	.venv/bin/python -m uvicorn heatbeat_api.app:app --reload --port 8000

test-api:
	.venv/bin/python -m pytest -q tests/test_api.py

demo:  ## Streamlit input overview
	.venv/bin/streamlit run demo/app.py

.PHONY: dev api test-api demo
