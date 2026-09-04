# Deploying the evidence UI

The deployable artifact is the read-only Streamlit evidence UI over the shipped `outputs/`. It moves no money, calls no provider, stores no secret, and regenerates no benchmark artifact — the same contract `bailiff/lineage.py` enforces and the test suite proves. Deploying it publicly is safe by construction because there is nothing behind it to reach: the container carries only generated evidence and the code to display it.

Do not describe a deployment of this UI as a payment service, a collections product, or a production dashboard. It is the evidence surface for a deterministic synthetic benchmark.

## Local, no container

```bash
python3 -m pip install -e '.[ui]'
streamlit run app.py
```

## Local, container

```bash
docker build -t mandateguard-lab .
docker run --rm -p 8501:8501 mandateguard-lab
```

Open http://localhost:8501. The healthcheck polls Streamlit's `/_stcore/health`.

## Hugging Face Spaces (free, public URL)

Create a Space with the **Docker** SDK and push this repository to it. Spaces injects `PORT=7860`; the container honours `$PORT`, so no edit is needed. Add this block to the top of the Space's `README.md` (Spaces reads it as front matter; the repository README works unchanged if the block is prepended):

```yaml
---
title: MandateGuard Policy Lab
sdk: docker
app_port: 7860
---
```

## Streamlit Community Cloud (free, public URL)

Point a new app at this repository, `main` branch, `app.py`. Set the Python dependencies file to `requirements.txt`; Streamlit Cloud installs it and `-e .` brings the package. No secrets are required.

## Anything with a Docker runtime (Cloud Run, Fly.io, a VPS)

The image is self-contained. `PORT` is honoured, no volume is needed, and the container is stateless: killing and restarting it loses nothing because it writes nothing.

## What a deployment does not change

The command line demo, tests, benchmark, and release gates never require the UI or the container. `SHA256SUMS.txt` inside the image is the same manifest as in the repository, so a viewer can verify the served evidence matches the shipped evidence.
