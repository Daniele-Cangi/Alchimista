# Full Rizzo browser acceptance

This is the manual acceptance path for the pinned 0.3B model. It requires
internet only during the first model installation and can consume substantial
download time, disk, and RAM. Ordinary CI mocks the download and load phases.

1. Generate secrets and start the normal stack:

   ```bash
   python scripts/init_local_env.py
   docker compose up --detach --build --wait
   ```

2. Open <http://127.0.0.1:8000>, select **Privacy**, then under **Rizzo PII
   0.3B** choose **Install model**. Observe `DOWNLOADING` and
   `verifying model files`; no percentage is shown because the upstream client
   does not expose a reliable aggregate byte total.
3. At `INSTALLED`, choose **Load in memory**. Wait for `READY`, select **Rizzo
   Full**, and save. The service rejects this selection before `READY`.
4. Upload a synthetic Italian document containing names/organizations plus
   formatted synthetic identifiers. Confirm the document detail and Privacy
   evidence record `rizzo-pii`, `ml_plus_regex`, source revision
   `42d4a40ecfe31acbbe3e1d78cf4d79d38cd8c3f5`, and the selected policy.
5. Ask a question about that document. Open a citation and inspect the
   protected evidence. Open Audit and confirm the decision privacy evidence.
6. Switch to **Rizzo Lightweight**, save, and unload Full. The weights remain
   installed while RAM is released.
7. Restart Compose. Privacy must show `INSTALLED`, not `NOT_INSTALLED` or
   `READY`; loading must work without reinstalling. To prove offline behavior,
   disconnect networking only after installation, then load and analyze again.

The model directory and Alchimista SHA-256 manifest live in the
`rizzo-model-data` named volume. A missing or changed file produces `ERROR` and
never `READY`. The trusted model commit is
`a1c3c83827eca22e9675e30c1111c4641caf5901` (the resolution of `v1.5.0` at
integration time). This test establishes implemented runtime behavior; it is not a
legal or detection-accuracy certification.

## Optional automated proof

`.github/workflows/full-rizzo-acceptance.yml` runs the same lifecycle against
the actual pinned weights on manual dispatch. On a pull request it runs only
when the `full-rizzo-acceptance` label is present. Unlike the required fast CI,
this job downloads the model, requires at least one model-origin finding,
checks document and audit metadata, restarts the model/privacy services, and
loads the persisted weights again without reinstalling them.
