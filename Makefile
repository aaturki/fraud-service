IMAGE := fraud-service
TAG   := $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)

install:          ## Install the package and dev tools
	pip install -e ".[dev]"

run:              ## API with auto-reload on http://localhost:8000/docs
	uvicorn fraud_service.api.app:create_app --factory --reload

run-batch:        ## Score the sample CSV, then compare with the golden file
	python -m fraud_service.batch
	python scripts/check_golden.py scored.csv

lint:             ## Style, types, and the layer contract
	ruff check src tests
	mypy src/fraud_service
	lint-imports

test:             ## The per-commit gate
	pytest -m "not slow" --cov --cov-report=term-missing --cov-fail-under=80

test-all:         ## Everything, including the slow golden-file test
	pytest

regen-golden:     ## Rewrite the golden file for a NEW model, with a reason: REASON="..."
	python scripts/regen_golden.py --reason "$(REASON)"

lock:             ## Pin every dependency for the Linux image
	uv pip compile pyproject.toml --python-version 3.12 --python-platform linux \
	    --no-annotate --no-header -o requirements.lock

image:            ## Build the production image, tagged with the git SHA
	docker build --build-arg GIT_SHA=$(TAG) -t $(IMAGE):$(TAG) -t $(IMAGE):dev .

image-size: image ## Report the image size
	docker images $(IMAGE):$(TAG) --format "{{.Repository}}:{{.Tag}} {{.Size}}"

up:               ## Full dev stack
	docker compose up --build -d && docker compose ps

smoke:            ## End-to-end check against the running container
	curl -fsS localhost:8000/v1/ready && echo
	curl -fsS localhost:8000/v1/predict -H "content-type: application/json" \
	     -d @payloads/sample.json && echo

.PHONY: install run run-batch lint test test-all regen-golden lock image image-size up smoke
