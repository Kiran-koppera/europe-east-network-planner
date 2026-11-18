.PHONY: install data run test lint serve all
install:  ## create .venv and install
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
data:     ## download the feed and GeoNames cities into data/raw
	.venv/bin/python -m planner download
run:      ## full pipeline -> output/
	.venv/bin/python -m planner run
test:
	.venv/bin/pytest --cov=planner
lint:
	.venv/bin/ruff check src tests
serve:    ## preview the site on http://localhost:8000
	python3 -m http.server 8000 -d output/site
all: data run test
