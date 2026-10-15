# Publish StudSift on GitHub

The ZIP is ready to publish as an open-source repository; publishing does **not** happen automatically.

## Create the repository

1. On GitHub, select **New repository**: https://github.com/new
2. Name it `studsift` (or any name you prefer), add a short description, choose **Public**, and **do not** pre-create README or a licence (both are included). Once created, push the files using the instructions below.
3. Extract the release ZIP on your PC. Open a terminal inside `StudSift-v0.1.0`.
4. With Git installed and your GitHub authentication configured, run:

```bash
git init
git add .
git commit -m "Initial public preview v0.1.0"
git branch -M main
git remote add origin https://github.com/joezed/studsift.git
git push -u origin main
```

Replace `joezed` with your GitHub username and repository name if different. Review your staged files before committing: `git status` should **not** show any `data/` files or private keys.

## Create a downloadable release

On GitHub open **Releases → Draft a new release**. Create tag **`v0.1.0`**, target `main`, title **`StudSift v0.1.0 — first public preview`**. Paste the contents of `CHANGELOG.md` into the notes. Attach the `StudSift-v0.1.0-GitHub-Release.zip` file as a downloadable release asset and mark it **pre-release**.

### Users upgrading from a previous private version

Never replace or publish your own `data/` folder. Back up the full existing `data/` directory and copy it into the *extracted new application folder*, then launch normally.

### GitHub safety checklist

- [ ] Public repo uses MIT licence, and LEGO affiliation disclaimer is visible.
- [ ] No `data/`, CSV inventory, API key, photos, or private credentials committed.
- [ ] GitHub Actions tests pass on the default branch.
- [ ] Release title, tag, notes and ZIP asset added.
- [ ] A fresh Windows machine with Python and webcam successfully completes a real scan and a set import (recommended before promoting from pre-release).