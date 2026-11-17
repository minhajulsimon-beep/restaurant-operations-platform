# Add the project to GitHub and keep using Git

This guide assumes the archive has been extracted and you can see `run.py` and `README.md` inside the `restaurant-operations-platform` folder. Upload the project files as a repository, rather than uploading only the ZIP archive.

## 1. Create an empty repository

In GitHub, create a new repository named:

```text
restaurant-operations-platform
```

Suggested description:

> Python and SQL restaurant data platform with POS reconciliation, inventory variance, purchasing checks, labor reporting, and a Power BI build kit.

For this local upload route, leave the GitHub options to add a README, `.gitignore`, or license unchecked. Those files are already included in the project. Starting with an empty remote avoids having two different initial versions of the same files.

## 2. Open a terminal in the project folder

The terminal must be in the folder that contains `run.py`. If you opened the terminal in the folder above it, enter:

```bash
cd restaurant-operations-platform
```

`cd` means “change directory.” It changes where subsequent commands run; it does not upload or move the files.

Check that the project runs:

```bash
python run.py demo
```

Then run the tests:

```bash
python run.py test
```

Use `python3` instead of `python` if that is the Python command on your computer.

## 3. Start Git tracking

Run each command separately:

```bash
git init
```

This starts a local Git repository. It has not uploaded anything.

```bash
git status
```

This shows the files Git can see and whether they have uncommitted changes. The included `.gitignore` excludes generated working data and other disposable files from normal commits. Review the list before continuing.

```bash
git add .
```

The dot means “the changes under this folder.” This stages the files for the next saved version, called a commit.

```bash
git commit -m "Build restaurant operations data platform"
```

This records the staged files as a local version. If Git says your name or email is missing, configure the identity for this repository:

```bash
git config user.name "Mohammed Minhajul Islam Saimon"
```

```bash
git config user.email "YOUR_GITHUB_EMAIL_OR_NOREPLY_ADDRESS"
```

Replace the email placeholder with your own verified address or GitHub-provided private no-reply address. Then repeat the commit command. These commands configure this repository rather than changing every repository on the computer.

## 4. Connect the GitHub repository

```bash
git branch -M main
```

This names the current branch `main`.

```bash
git remote add origin https://github.com/YOUR_USERNAME/restaurant-operations-platform.git
```

Replace `YOUR_USERNAME` with your GitHub username. `origin` is a short name for that remote repository address.

If you already added a remote, inspect it before changing anything:

```bash
git remote -v
```

Do not repeat `git remote add origin` if the correct `origin` already exists.

## 5. Upload the first commit

```bash
git push -u origin main
```

This uploads your committed version and connects your local `main` branch with the remote branch. Follow GitHub's supported sign-in flow if prompted. Do not put passwords or tokens into project files or the remote URL.

Refresh the repository page. The README, Python code, SQL, tests, and guides should be visible. If GitHub rejects the push because the remote already contains a different initial commit, stop and inspect the remote's files. Do not use a force push to bypass the difference.

## 6. Use Git for your next small change

After editing and checking a file:

```bash
git status
```

```bash
git diff
```

```bash
git add docs/walkthrough.md
```

```bash
git commit -m "Clarify the inventory usage calculation"
```

```bash
git push
```

Replace the staged filename and commit message with the change you actually made. `git diff` lets you review your changes before recording them.

## 7. Work in your browser afterward

After the repository is on GitHub, open its **Code** menu, choose **Codespaces**, and create a codespace for `main` if the option is available for your account. This gives you a browser editor and a terminal. Run the same Python commands there.

GitHub personal accounts include limited Codespaces compute and storage allowances. This is not unlimited free hosting. Check your usage and billing controls, stop an active codespace when finished, and remove unused codespaces when appropriate. GitHub documents that use becomes restricted at the included limits when additional billing has not been enabled. See [GitHub's included usage guidance](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage) and [how to create a codespace](https://docs.github.com/en/codespaces/developing-in-a-codespace/creating-a-codespace-for-a-repository).

To open the report in the browser from a codespace, run:

```bash
python run.py serve --host 0.0.0.0
```

Open the forwarded port `8000` from the editor's Ports tab and append `/dashboard.html` if needed. Keep the port's visibility private. The terminal stays occupied while it serves the report; press `Ctrl+C` to stop it. You can also download `data/demo/reports/dashboard.html` from the file explorer and open it locally.

## What to make prominent on the repository page

Use the README's business problem, architecture, run instructions, reconciliation examples, and limitations. Pin the repository to your profile if it represents work you can explain. The strongest next improvement is a small change you understand and can demonstrate, followed by a clear commit message and a passing test run.
