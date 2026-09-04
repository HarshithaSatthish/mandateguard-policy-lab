"""Read-only Razorpay Test Mode proof viewer.

This screen never loads credentials, opens a socket, creates a Payment Link or
modifies an artifact. It only renders the sanitized files under
``docs/testmode_evidence`` so a judge can inspect the provider-backed success
and refusal proofs without reading raw JSON by hand.

Run with:
    streamlit run provider_proof_app.py
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import streamlit as st
except ImportError:  # pragma: no cover - command-line fallback
    st = None

from bailiff.provider_proof import EVIDENCE_FILES, load_provider_proofs


ROOT = Path(__file__).resolve().parent


def _short(value: object, n: int = 18) -> str:
    text = str(value or "—")
    return text if len(text) <= n else text[:n] + "…"


def render() -> None:
    st.set_page_config(page_title="MandateGuard Provider Proof", page_icon="✓", layout="wide")
    st.title("MandateGuard — Provider Proof")
    st.caption(
        "Read-only evidence over sanitized Razorpay Test Mode artifacts. "
        "No credentials are loaded and no provider call can be made from this page."
    )

    bundle = load_provider_proofs(ROOT)
    summary = bundle.summary()
    if not bundle.artifacts:
        st.warning(
            "No sanitized Test Mode evidence is present in this checkout yet. "
            "Expected docs/testmode_evidence/testmode_*.json artifacts."
        )
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Fallback execution", "VERIFIED" if summary["successful_fallback_verified"] else "NOT VERIFIED")
    c2.metric("Captured postcondition", "VERIFIED" if summary["recovery_verified"] else "NOT VERIFIED")
    c3.metric("Already-paid zero-write", "VERIFIED" if summary["already_paid_zero_write_verified"] else "NOT VERIFIED")

    st.divider()
    st.subheader("1 · Permitted recovery")
    success = bundle.artifacts.get("success", {})
    receipt = success.get("receipt") if isinstance(success.get("receipt"), dict) else {}
    st.code(
        "\n".join(
            [
                f"financial truth       {success.get('financial_truth', '—')}",
                f"execution state       {success.get('execution_state', '—')}",
                f"reason                {success.get('reason_code', '—')}",
                f"order                 {_short(receipt.get('order_id'))}",
                f"payment link          {_short(receipt.get('payment_link_id'))}",
                f"prewrite resolution   {receipt.get('prewrite_resolution', '—')}",
                f"prewrite evidence     {_short(receipt.get('prewrite_evidence_hash'), 24)}",
            ]
        ),
        language="text",
    )

    st.subheader("2 · Independent captured-payment proof")
    proof_blob = bundle.artifacts.get("recovery_proof", {})
    proof = proof_blob.get("proof") if isinstance(proof_blob.get("proof"), dict) else {}
    st.code(
        "\n".join(
            [
                f"recovery verified     {proof_blob.get('recovery_verified', False)}",
                f"provider action       {_short(proof.get('provider_action_id'))}",
                f"captured payment      {_short(proof.get('payment_id'))}",
                f"amount minor          {proof.get('amount_minor', '—')}",
                f"currency              {proof.get('currency', '—')}",
                f"postcondition hash    {_short(proof.get('postcondition_evidence_hash'), 24)}",
                f"RecoveryProof hash    {_short(proof_blob.get('recovery_proof_hash'), 24)}",
            ]
        ),
        language="text",
    )

    st.subheader("3 · Refusal proof — already paid")
    block = bundle.artifacts.get("safe_block_zero_write", {})
    st.code(
        "\n".join(
            [
                f"provider order        {_short(block.get('order_id'))}",
                f"provider state        {str(block.get('order_status', '—')).upper()}",
                f"decision              {block.get('recoverytruth_result', '—')}",
                f"executed              {block.get('executed', '—')}",
                f"Payment Links before  {block.get('payment_links_before', '—')}",
                f"Payment Links after   {block.get('payment_links_after', '—')}",
                f"zero new writes       {block.get('zero_new_fallback_writes', '—')}",
            ]
        ),
        language="text",
    )

    if summary["already_paid_zero_write_verified"]:
        st.success("PAID → SAFE_BLOCK_ALREADY_PAID → Payment Links 0 → 0")
    else:
        st.error("The sanitized already-paid evidence does not satisfy the zero-write proof contract.")

    st.divider()
    with st.expander("Raw sanitized artifacts"):
        for key, filename in EVIDENCE_FILES.items():
            st.markdown(f"**{filename}**")
            value = bundle.artifacts.get(key)
            if value is None:
                st.caption("not present")
            else:
                st.code(json.dumps(value, indent=2, sort_keys=True), language="json")


if __name__ == "__main__":
    if st is None:
        raise SystemExit("streamlit is not installed. Run: pip install -e '.[ui]'")
    render()
