"""Export a fine-tuned model to ONNX (fp32) and optionally dynamic-quantise it to int8.

Why ONNX Runtime for serving?
* the service image does not need PyTorch (~1.5 GB smaller)
* graph optimisations + int8 MatMul kernels -> lower CPU latency and RAM
* int8 dynamic quantisation needs no calibration data; accuracy impact is measured, not assumed

Usage:
    python export_onnx.py --model ../models/indobert-lite --out ../models/indobert-lite-onnx-int8 --quantize
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import torch
from transformers import AutoModelForTokenClassification


class LogitsOnly(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.model(input_ids=input_ids, attention_mask=attention_mask, token_type_ids=token_type_ids).logits


def export(model_dir: Path, out: Path, quantize: bool, opset: int = 17) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    model = AutoModelForTokenClassification.from_pretrained(model_dir).eval()
    dummy = torch.ones(1, 16, dtype=torch.long)
    fp32 = out / ("model_fp32.onnx" if quantize else "model.onnx")
    t0 = time.time()
    torch.onnx.export(
        LogitsOnly(model), (dummy, dummy, torch.zeros_like(dummy)), str(fp32),
        input_names=["input_ids", "attention_mask", "token_type_ids"], output_names=["logits"],
        dynamic_axes={n: {0: "batch", 1: "seq"} for n in ("input_ids", "attention_mask", "token_type_ids", "logits")},
        opset_version=opset, dynamo=False)
    info = {"export_sec": round(time.time() - t0, 1), "fp32_mb": round(fp32.stat().st_size / 2**20, 1)}
    if quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        from onnxruntime.quantization.shape_inference import quant_pre_process

        # quant_pre_process (symbolic shape inference) gives more stable int8 scales, but its
        # shape inferencer can fail on some exported graphs ("Incomplete symbolic shape
        # inference") — fall back gracefully rather than lose the whole export over a
        # best-effort optimisation.
        pre = out / "model_preprocessed.onnx"
        quant_input = fp32
        try:
            quant_pre_process(str(fp32), str(pre))
            quant_input = pre
            info["pre_processed"] = True
        except Exception as err:  # noqa: BLE001 - deliberately broad, this step is optional
            print(f"warning: quant_pre_process failed ({err}); quantizing without it", flush=True)
            info["pre_processed"] = False
        q = out / "model.onnx"
        quantize_dynamic(str(quant_input), str(q), weight_type=QuantType.QInt8, per_channel=True)
        info["int8_mb"] = round(q.stat().st_size / 2**20, 1)
        fp32.unlink()  # keep only what we serve
        pre.unlink(missing_ok=True)
    for f in ("tokenizer.json", "labels.json"):
        shutil.copy(model_dir / f, out / f)
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--quantize", action="store_true")
    args = ap.parse_args()
    info = export(Path(args.model), Path(args.out), args.quantize)
    meta_path = Path(args.model) / "training_meta.json"
    card = {"model_version": Path(args.out).name, "quantized_int8": args.quantize, **info}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        card.update(base_model=Path(meta["base_model"]).name, params_millions=meta["params_millions"],
                    best_dev_f1=meta["best_dev_f1"])
    (Path(args.out) / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(json.dumps(card, indent=2))


if __name__ == "__main__":
    main()
