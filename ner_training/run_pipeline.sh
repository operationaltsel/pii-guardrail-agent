#!/bin/bash
# Master pipeline: wait for lite training -> export/tune/evaluate -> train base ->
# export/evaluate base (separate dir, for comparison) -> benchmark both -> summarize.
# Run from ner_training/. Logs: models/train_lite.log, models/train_base.log, pipeline.log
set -uo pipefail
cd "$(dirname "$0")"
PY=/c/Users/itdev/.venvs/pii/Scripts/python
export PYTHONIOENCODING=utf-8 PYTHONWARNINGS=ignore PYTHONUNBUFFERED=1

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "waiting for lite training to finish..."
until grep -qE "^done in|early stopping|Traceback" models/train_lite.log 2>/dev/null; do sleep 5; done
if grep -q "Traceback" models/train_lite.log; then
  log "FATAL: lite training crashed, see models/train_lite.log"; exit 1
fi
log "lite training finished: $(grep '^done in' models/train_lite.log)"

log "== export lite -> ner_service/model (int8 ONNX) =="
cd src && $PY export_onnx.py --model ../models/indobert-lite --out ../../ner_service/model --quantize
[ $? -ne 0 ] && { log "FATAL: export_onnx (lite) failed"; exit 1; }

log "== tune threshold on dev =="
$PY tune_threshold.py --model ../../ner_service/model
[ $? -ne 0 ] && { log "FATAL: tune_threshold failed"; exit 1; }

log "== evaluate served model (dev + gold) =="
$PY evaluate.py --model ../../ner_service/model --name indobert-lite
[ $? -ne 0 ] && { log "FATAL: evaluate.py (lite) failed"; exit 1; }
cd ..

log "== train IndoBERT-base (comparison) =="
cd src && $PY train_transformer.py --model ../pretrained/indobert-base-p1 --out ../models/indobert-base \
    --epochs 3 --lr 5e-5 --threads 12 --eval-subset 250 > ../models/train_base.log 2>&1
if grep -q "Traceback" ../models/train_base.log; then
  log "WARN: base training crashed, see models/train_base.log — continuing without it"
else
  log "base training finished: $(grep '^done in' ../models/train_base.log)"

  log "== export base -> models/indobert-base-onnx-int8 (comparison only, not served) =="
  $PY export_onnx.py --model ../models/indobert-base --out ../models/indobert-base-onnx-int8 --quantize
  $PY tune_threshold.py --model ../models/indobert-base-onnx-int8
  $PY evaluate.py --model ../models/indobert-base-onnx-int8 --name indobert-base
fi
cd ..

log "== benchmark served model (lite) =="
cd ../benchmark && $PY benchmark_ner.py --model ../ner_service/model --out results/ner_benchmark_lite.json
if [ -d "../ner_training/models/indobert-base-onnx-int8" ]; then
  log "== benchmark base (comparison) =="
  $PY benchmark_ner.py --model ../ner_training/models/indobert-base-onnx-int8 --out results/ner_benchmark_base.json
fi
cd ../ner_training

log "== summary =="
cd src && $PY summarize_reports.py --md | tee ../reports/comparison.md
cd ..

log "PIPELINE COMPLETE"
