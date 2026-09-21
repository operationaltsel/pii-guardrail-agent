# Convenience targets. Works in Git Bash / WSL / Linux / macOS (uses the venv's python
# directly so it doesn't depend on `source activate` — set PY if your venv lives elsewhere).
PY ?= .venv/Scripts/python
NER_TRAIN := ner_training/src

.PHONY: help venv install-training install-service install-agent \
        dataset train-crf train-base train-lite export-onnx tune-threshold \
        evaluate-crf evaluate-model benchmark test-guardrail test-service reproduce \
        compose-up compose-down

help:
	@echo "make install-training   # torch/transformers/onnxruntime into $(PY)"
	@echo "make dataset            # generate synthetic train/dev sets"
	@echo "make train-crf          # baseline CRF (~1 min)"
	@echo "make train-lite         # fine-tune IndoBERT-lite (~20-30 min on CPU)"
	@echo "make export-onnx        # export + int8-quantize -> ner_service/model"
	@echo "make tune-threshold     # pick the entity threshold on dev"
	@echo "make evaluate-model     # dev + gold metrics for the served model"
	@echo "make benchmark          # CPU/RAM/latency (brief section F)"
	@echo "make test-guardrail     # pytest: regex, vault, redactor, ADK e2e"
	@echo "make test-service       # pytest: NER REST API contract"
	@echo "make reproduce          # the full pipeline, start to finish"
	@echo "make compose-up         # docker compose: both services locally"

venv:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip

install-training: venv
	$(PY) -m pip install -r ner_training/requirements.txt

install-service: venv
	$(PY) -m pip install -r ner_service/requirements.txt

install-agent: venv
	$(PY) -m pip install -r agent/requirements-dev.txt

dataset:
	cd $(NER_TRAIN) && ../../$(PY) generate_dataset.py --train 6000 --dev 800 --seed 42

train-crf:
	cd $(NER_TRAIN) && ../../$(PY) train_crf.py --out ../models/crf

train-lite:
	cd $(NER_TRAIN) && ../../$(PY) train_transformer.py --model ../pretrained/indobert-lite-base-p1 \
		--out ../models/indobert-lite --epochs 3 --lr 1e-4

train-base:
	cd $(NER_TRAIN) && ../../$(PY) train_transformer.py --model ../pretrained/indobert-base-p1 \
		--out ../models/indobert-base --epochs 3 --lr 5e-5

export-onnx:
	cd $(NER_TRAIN) && ../../$(PY) export_onnx.py --model ../models/indobert-lite \
		--out ../../ner_service/model --quantize

tune-threshold:
	cd $(NER_TRAIN) && ../../$(PY) tune_threshold.py --model ../../ner_service/model

evaluate-crf:
	cd $(NER_TRAIN) && ../../$(PY) evaluate.py --model ../models/crf --kind crf --name crf

evaluate-model:
	cd $(NER_TRAIN) && ../../$(PY) evaluate.py --model ../../ner_service/model --name served-model

benchmark:
	cd benchmark && ../$(PY) benchmark_ner.py --model ../ner_service/model

test-guardrail:
	cd agent && ../$(PY) -m pytest tests -q

test-service:
	cd ner_service && ../$(PY) -m pytest tests -q

reproduce: install-training dataset train-crf train-lite export-onnx tune-threshold evaluate-model benchmark
	@echo "done — see ner_training/reports/ and benchmark/results/"

compose-up:
	docker compose up --build

compose-down:
	docker compose down
