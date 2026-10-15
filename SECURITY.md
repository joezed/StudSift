# Security and privacy

StudSift is intended only for one user on their own computer. The HTTP server binds to `127.0.0.1` and has **no login mechanism**. **Do not** expose it through port forwarding, proxies, tunnels, or public hosting; no threat model or hardening has been completed for that environment.

- Webcam images are transmitted to the **Brickognize API** when you scan. StudSift does not store the captures in the inventory CSVs.
- Rebrickable set imports transmit the set ID and your **Rebrickable API key** to the Rebrickable API over HTTPS.
- The API key is saved in `data/config.json`, which is **excluded from Git**; treat it as a secret and do not upload the `data/` folder.
- Set images are loaded from remote URLs returned by Rebrickable.
- Do not edit CSV data while the app is running. Back up `data/` before upgrading.

Please report sensitive vulnerabilities privately to the repository maintainer via GitHub's private vulnerability reporting if enabled, rather than publishing working exploits as issues.