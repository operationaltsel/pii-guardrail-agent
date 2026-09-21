# Deployment (bonus — brief bagian G)

Status pengerjaan tugas ini: **manifest Kubernetes disiapkan lengkap** (Deployment,
Service, HPA, PDB, NetworkPolicy, health probes) di [`deploy/k8s/`](../deploy/k8s), dan
**diverifikasi lokal** lewat `docker compose` (image yang sama persis yang dipakai di GKE).
Deploy sungguhan ke cluster GKE tidak dijalankan karena butuh akun GCP berbayar (project,
Artifact Registry, cluster) di luar scope take-home test ini — bagian ini menjelaskan
persis langkah yang akan dijalankan.

## Kenapa desainnya begini

* **Dua Deployment terpisah** (`ner-service`, `cs-agent`) — sesuai requirement brief NER
  sebagai service terpisah, dan karena keduanya punya karakteristik beban kerja berbeda:
  `ner-service` CPU-bound (inferensi ONNX), `cs-agent` I/O-bound (menunggu Gemini). Scaling
  keduanya independen lewat HPA berbasis CPU masing-masing.
* **`ner-service` di-scale minimal 2 replika** dengan `PodDisruptionBudget minAvailable: 1`
  — begini caranya `cs-agent` tidak fail-closed setiap kali satu pod NER di-restart/
  di-evict oleh node upgrade.
* **`NetworkPolicy`** membatasi siapa saja yang boleh bicara ke `ner-service` hanya
  `cs-agent` — karena `ner-service` adalah jalur PII, prinsip least-privilege network.
* **Resource requests/limits** di manifest diambil dari angka nyata hasil
  [`benchmark/benchmark_ner.py`](../benchmark/benchmark_ner.py), bukan tebakan — lihat
  [performance.md](performance.md).
* **`readOnlyRootFilesystem: true`** pada `ner-service` — service ini tidak menulis file
  apa pun saat runtime (model sudah ada di image), jadi filesystem read-only mengurangi
  permukaan serangan kalau ada RCE.

## Langkah deploy ke GKE (belum dijalankan, didokumentasikan untuk direview)

```bash
# 1. Buat cluster (Autopilot paling sederhana untuk beban kerja kecil seperti ini)
gcloud container clusters create-auto pii-guardrail-cluster --region asia-southeast2

# 2. Build & push image ke Artifact Registry
gcloud artifacts repositories create pii-guardrail --repository-format=docker \
    --location=asia-southeast2

docker build -t asia-southeast2-docker.pkg.dev/PROJECT/pii-guardrail/pii-ner-service:v1 \
    ner_service/
docker push asia-southeast2-docker.pkg.dev/PROJECT/pii-guardrail/pii-ner-service:v1

docker build -t asia-southeast2-docker.pkg.dev/PROJECT/pii-guardrail/nusatel-cs-agent:v1 \
    agent/
docker push asia-southeast2-docker.pkg.dev/PROJECT/pii-guardrail/nusatel-cs-agent:v1

# 3. Ganti placeholder REGISTRY/... di deploy/k8s/*.yaml dengan path Artifact Registry di
#    atas, lalu buat secret API key Gemini
kubectl apply -f deploy/k8s/namespace.yaml
kubectl create secret generic cs-agent-secrets -n pii-guardrail \
    --from-literal=google-api-key=$GOOGLE_API_KEY
kubectl apply -f deploy/k8s/

# 4. Verifikasi
kubectl -n pii-guardrail get pods,hpa,pdb
kubectl -n pii-guardrail port-forward svc/cs-agent 8000:8000
curl localhost:8000/list-apps
```

## Verifikasi lokal yang SUDAH dijalankan (setara, tanpa cluster)

```bash
cp .env.example .env   # isi GOOGLE_API_KEY
docker compose up --build
# ner-service: http://localhost:8001/health/ready
# cs-agent:    http://localhost:8000/list-apps
```

`docker-compose.yml` memakai image yang identik dengan yang di-build untuk GKE
(`ner_service/Dockerfile`, `agent/Dockerfile`), plus `healthcheck`/`depends_on:
condition: service_healthy` yang meniru `readinessProbe` Kubernetes — cara memvalidasi
kedua image dan urutan startup tanpa perlu cluster sungguhan.

## Observability

* `ner-service` mengekspos `/metrics` (Prometheus format: request count, histogram
  latency inferensi, jumlah entity per label) — manifest sudah diberi anotasi
  `prometheus.io/scrape: "true"` untuk auto-discovery oleh Prometheus di cluster.
* Kedua service punya `/health/live` (proses hidup) dan `/health/ready` (model sudah
  dimuat / dependency siap) terpisah, dipakai `livenessProbe`/`readinessProbe`/
  `startupProbe` masing-masing.
* Log guardrail (`before_model` di [`callbacks.py`](../agent/agents/cs_agent/guardrail/callbacks.py))
  mencatat **hitungan** entity yang terdeteksi per giliran dan latency, **tidak pernah**
  nilai PII itu sendiri — aman untuk dikirim ke log aggregator terpusat.
