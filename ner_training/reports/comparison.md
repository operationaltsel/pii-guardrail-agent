| Model | Backend | Dev F1 | Gold F1 (strict) | Gold F1 (lenient) | Recall | Leak rate | Over-redaction | PERSON F1 | ADDRESS F1 | p50 ms | p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| crf | crf | 0.8732 | 0.864 | 0.952 | 0.8438 | 0.0197 | 0.0309 | 0.8276 | 0.9143 | 0.7 | 1.8 |
| indobert-base | onnx | 0.9842 | 0.9766 | 0.9922 | 0.9766 | 0.002 | 0.006 | 0.9737 | 0.9808 | 12.07 | 26.85 |
| indobert-lite | onnx | 0.9756 | 0.9844 | 0.9922 | 0.9844 | 0.002 | 0.0033 | 0.9868 | 0.9808 | 24.74 | 52.6 |

| Benchmark | Backend | Model load (s) | RAM footprint (MB) | Peak RAM (MB) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|---|---|
| ner_benchmark_base | onnx | 0.585 | 162.4 | 200.5 | 15.51 | 42.53 | 76.54 |
| ner_benchmark_lite | onnx | 0.632 | 77.6 | 115.5 | 32.26 | 62.09 | 104.82 |
