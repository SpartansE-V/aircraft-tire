PY=.venv/bin/python
PIP=.venv/bin/pip

.PHONY: setup generate scans logs train test run all clean lint

# On macOS, lightgbm needs OpenMP: `brew install libomp` (the LightGBM baseline
# model degrades gracefully if it is missing — headline MixedLM/Weibull still run).
setup:
	python3.11 -m venv .venv
	$(PIP) install --upgrade pip wheel setuptools
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

generate:
	$(PY) -m treadcast.generate_data

scans:
	$(PY) -m treadcast.generate_scans

logs:
	$(PY) -m treadcast.generate_defect_logs

train:
	$(PY) -m treadcast.train

test:
	$(PY) -m pytest

run:
	$(PY) -m streamlit run src/treadcast/app.py

lint:
	$(PY) -m ruff check src tests

# Full pipeline: data -> scans -> defect logs -> models -> tests
all: generate scans logs train test

clean:
	rm -rf data artifacts
