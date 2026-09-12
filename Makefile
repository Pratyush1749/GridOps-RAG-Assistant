.PHONY: help install sync seed seed-docs gen-data api streamlit eval eval-baseline eval-hybrid eval-rerank eval-hyde eval-crag eval-all eval-diff test lint format


help:
	@echo "ADV RAG (GridOps) - Available commands"
	@echo ""
	@echo "  make install       - create venv & install all deps (one-time)"
	@echo "  make sync          - sync deps with pyproject.toml"
	@echo "  make gen-data      - regenerate synthetic grid-ops SQL data + document corpus"
	@echo "  make seed          - run migrations, seed users, ingest docs into Qdrant"
	@echo "  make api           - start FastAPI backend (:8000)"
	@echo "  make streamlit     - start Streamlit UI (:8501)"
	@echo "  make eval          - run baseline + all profiles, then diff them"
	@echo "  make test          - run pytest"
	@echo "  make lint          - run ruff check"
	@echo "  make format        - run ruff format"


install:
	cd backend && uv python pin 3.12 && uv venv --python 3.12 && uv sync --extra dev

sync:
	cd backend && uv sync --extra dev

seed:
	cd backend && uv run python scripts/seed_db.py

seed-docs:
	cd backend && uv run python -c "from scripts.seed_db import seed_docs; seed_docs()"

# Regenerate the synthetic dataset. Order matters: the document corpus is
# generated *from* the seeded SQL rows, so the DB migration must be applied
# (make seed) between these two steps.
gen-data:
	cd backend && uv run python scripts/data_pipeline/generate_grid_ops_db.py
	@echo ">> Now run 'make seed' to apply the migration, then:"
	@echo ">>   cd backend && uv run python scripts/data_pipeline/generate_grid_ops_docs.py --force"

api:
	cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

streamlit:
	cd backend && uv run streamlit run scripts/streamlit_app.py


eval-baseline:
	cd backend && uv run python -m eval.run_ragas --profile naive

eval-hybrid:
	cd backend && uv run python -m eval.run_ragas --profile hybrid

eval-rerank:
	cd backend && uv run python -m eval.run_ragas --profile hybrid+rerank

eval-hyde:
	cd backend && uv run python -m eval.run_ragas --profile hybrid+rerank+hyde --filter hyde

eval-crag:
	cd backend && uv run python -m eval.run_ragas --profile hybrid+rerank+crag --filter crag

eval-all:
	cd backend && uv run python -m eval.run_ragas --profile all

eval: eval-baseline eval-all
	$(MAKE) eval-diff

eval-diff:
	@cd backend && \
	latest_naive=$$(ls -t eval/results/*_naive.json 2>/dev/null | head -1); \
	latest_all=$$(ls -t eval/results/*_all.json 2>/dev/null | head -1); \
	if [ -n "$$latest_naive" ] && [ -n "$$latest_all" ]; then \
	  uv run python -m eval.diff "$$latest_naive" "$$latest_all"; \
	else \
	  echo "Need at least one *_naive.json and one *_all.json in backend/eval/results/"; \
	fi

validate:
	cd backend && uv run python scripts/validate_goldens.py


test:
	cd backend && uv run pytest tests/ -v

lint:
	cd backend && uv run ruff check .

format:
	cd backend && uv run ruff format .


eval-legacy:
	@echo "Use: make eval-baseline"
