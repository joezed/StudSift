# Contributing

Thanks for considering a contribution to StudSift.

1. Open an issue to discuss non-trivial changes first.
2. Fork the repository and create a feature branch.
3. Keep the application usable without third-party Python packages when possible.
4. Run `python -m unittest -v test_server.py` and `node --check web/app.js` before opening a pull request.
5. Add tests when changing bag allocation, CSV persistence or set-picking rules.
6. Do not commit the `data/` folder, real API keys, user photos or personal inventories.

Bug reports should include the Python version, operating system, reproduction steps and **redacted** errors; never paste your API key.

All source-code contributions are submitted under the project's MIT licence.