# Read-only evidence UI for the MandateGuard Policy Lab.
#
# This container serves the five Streamlit evidence screens over the shipped
# generated outputs/. It moves no money, calls no provider, needs no secret,
# and regenerates nothing: the same read-only contract the UI itself proves
# in bailiff/lineage.py and tests. It is a presentation surface for the
# deterministic synthetic benchmark, not a payment service.
#
#   docker build -t mandateguard-lab .
#   docker run --rm -p 8501:8501 mandateguard-lab
#
# Hosts that inject a port (Hugging Face Spaces, Cloud Run) are honoured via
# $PORT; the default stays Streamlit's 8501.

FROM python:3.12-slim

WORKDIR /lab

# Layer the dependency install before the source copy so an evidence or doc
# change does not reinstall the world.
COPY pyproject.toml README.md ./
COPY bailiff ./bailiff
RUN pip install --no-cache-dir -e '.[ui]'

COPY app.py ./
COPY outputs ./outputs
COPY FINDINGS.md ROBUSTNESS.md ARCHITECTURE.md SHA256SUMS.txt ./

# The offline flag is belt and braces: the UI opens no socket during render
# and the lineage layer traps provider calls, but the container states its
# intent explicitly.
ENV MANDATEGUARD_OFFLINE=1
ENV PORT=8501
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python3 -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8501\")}/_stcore/health')" || exit 1

CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
