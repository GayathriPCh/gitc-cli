# gitc-cli

Enhanced Git CLI wrappers for productivity.

## Install

For normal users (from GitHub):

```bash
pip install git+https://github.com/GayathriPCh/gitc-cli.git
```

For development (editable mode):

```bash
git clone https://github.com/GayathriPCh/gitc-cli.git
cd gitc-cli
pip install -e .
```

## Updating

### Normal users

To get the latest changes from the repo:

```bash
pip install --upgrade git+https://github.com/GayathriPCh/gitc-cli.git
```

### Developers (editable mode)

1. Pull latest code:

```bash
git pull origin main
```

2. Changes are live immediately due to editable install.
3. If you added new files or changed `pyproject.toml`:

```bash
pip install -e .
```

## Usage

```bash
# Find branches matching a pattern (local + remote)
gitc find-branch "DEV_*"
```

```bash
# Show commits since yesterday on branches matching DEV_*
gitc activity --since yesterday --branch "DEV_*"
```

```bash
  # List stale branches (12 weeks)
    gitc stale 12w
    # Delete local stale branches but keep "featureX" and "hotfixY"
    gitc stale 12w --delete --keep "featureX,hotfixY"
    # Force delete all other stale branches except protected + --keep
    gitc stale 12w --delete --force --keep "featureX,hotfixY"```

```bash
# Search commit messages for a keyword
gitc search "Restore Dialog"
```

## Features

* Regex-like branch search (local + remote unified view)
* Activity report by branch & time range
* Detect unused/stale local branches
* Commit message search with easy cherry-pick lookup

## Notes

* Requires Python 3.8+ and Git installed.
* Works in any Git repository after installation.

## Troubleshooting PATH on Windows

After installing, you may see this warning:

```bash
WARNING: The script gitc.exe is installed in '...Python313\Scripts' which is not on PATH.
```

### Fix:

1. Add this folder to your **PATH** (replace with your Python version):

```bash
C:\Users\<Your-windowsusername>\AppData\Roaming\Python\Python313\Scripts
```

* Open **Start Menu → "Edit environment variables for your account"**
* Edit the **PATH** variable
* Add the path above
* Restart PowerShell

2. Verify:

```bash
gitc --help
```

### Alternative:

You can always run without touching PATH:

```bash
python -m gitc --help
```
