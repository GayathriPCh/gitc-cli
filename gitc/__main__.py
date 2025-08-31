#!/usr/bin/env python3
"""
gitc — Enhanced Git CLI wrappers for common workflows.

Dependencies: Python 3.8+ and `git` in PATH. Uses only standard library + Typer.
Install Typer (once):  pip install typer[all]

Examples:
    # 1) Regex Branch Search (local + remote unified)
    gitc find-branch "DEV_.*" --regex
    gitc find-branch "feature/*"                 # glob (default)

    # 2) Local Dev Activity by Date
    gitc activity --since "yesterday" --branch "DEV_*"
    gitc activity --since "2025-08-01" --until "2025-08-30" --branch "feature/*,hotfix/*"

    # 3) Check Unused/Stale Branches
    # List stale branches (12 weeks)
    gitc stale 12w
    # Delete local stale branches but keep "featureX" and "hotfixY"
    gitc stale 12w --delete --keep "featureX,hotfixY"
    # Force delete all other stale branches except protected + --keep
    gitc stale 12w --delete --force --keep "featureX,hotfixY"


    # 4) Commit Message Search → Cherry-pick Helper
    gitc search "Restore Dialog"
    gitc search "Restore Dialog" --ignore-case --since "2025-08-01"
    gitc search "Restore Dialog" --pick 2
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import fnmatch
import os
import re
import subprocess
from typing import List, Optional, Tuple

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True,
                 help="gitc — Enhanced Git CLI wrappers (Typer + subprocess).")

# -------------------------
# Utilities
# -------------------------

SHORT_DATE_FMT = "%Y-%m-%d"

def run(cmd: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def ensure_git_repo() -> None:
    rc, out, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out != "true":
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def parse_age(expr: str) -> dt.timedelta:
    """Parse durations like 30d, 12w, 6m, 1y into timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy])\s*", expr.lower())
    if not m:
        raise typer.BadParameter("Use formats like 30d, 12w, 6m, 1y")
    n = int(m.group(1))
    unit = m.group(2)
    days = {"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n
    return dt.timedelta(days=days)

def to_regex(pattern: str, is_regex: bool) -> re.Pattern:
    if is_regex:
        return re.compile(pattern)
    globs = [g.strip() for g in pattern.split(",") if g.strip()]
    regex = "|".join(fnmatch.translate(g).rstrip("\\Z") for g in globs) or ".*"
    return re.compile(regex)

def pad(s: str, w: int) -> str:
    s = s if s is not None else ""
    return s[:w].ljust(w)

def print_table(rows: List[List[str]], headers: List[str]) -> None:
    cols = list(zip(*(headers, *rows))) if rows else [headers]
    widths = [max(len(str(c)) for c in col) for col in cols]
    line = "  ".join(pad(h, w) for h, w in zip(headers, widths))
    typer.secho(line, bold=True)
    for r in rows:
        typer.echo("  ".join(pad(c, w) for c, w in zip(r, widths)))

# -------------------------
# Core data helpers
# -------------------------

@dataclasses.dataclass
class RefInfo:
    name: str
    scope: str           # "local" or "remote"
    upstream: str
    commit_date: Optional[str]
    last_commit_ts: Optional[int]

def list_refs(include_locals: bool = True, include_remotes: bool = True) -> List[RefInfo]:
    ensure_git_repo()
    ref_kinds = []
    if include_locals:
        ref_kinds.append("refs/heads")
    if include_remotes:
        ref_kinds.append("refs/remotes")
    if not ref_kinds:
        return []
    fmt = "%(refname:short)|%(committerdate:iso-strict)|%(upstream:short)|%(authordate:unix)"
    rc, out, err = run(["git", "for-each-ref", f"--format={fmt}", *ref_kinds])
    if rc != 0:
        typer.secho(err or "git for-each-ref failed", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    rows = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        refname, date_iso, upstream, ts = parts
        scope = "remote" if refname.startswith(("origin/", "upstream/")) or refname.count("/") >= 2 else "local"
        last_ts = int(ts) if ts.isdigit() else None
        rows.append(RefInfo(refname, scope, upstream, date_iso, last_ts))
    return rows

def resolve_branches(pattern: str, is_regex: bool, include_remotes: bool, include_locals: bool) -> List[RefInfo]:
    rx = to_regex(pattern, is_regex)
    refs = list_refs(include_locals=include_locals, include_remotes=include_remotes)
    return [r for r in refs if rx.fullmatch(r.name) or rx.search(r.name)]

# -------------------------
# Commands
# -------------------------

@app.command("find-branch")
def find_branch(pattern: str,
                regex: bool = typer.Option(False, "--regex"),
                locals: bool = typer.Option(True, "--locals/--no-locals"),
                remotes: bool = typer.Option(True, "--remotes/--no-remotes")):
    """Find branches across local & remotes."""
    matches = resolve_branches(pattern, regex, remotes, locals)
    if not matches:
        typer.secho("No branches matched.", fg=typer.colors.YELLOW)
        raise typer.Exit()
    rows = [[r.name, r.scope, r.upstream or "-", r.commit_date or "-"]
            for r in sorted(matches, key=lambda x: (x.scope, x.name.lower()))]
    print_table(rows, headers=["BRANCH", "SCOPE", "UPSTREAM", "LAST_COMMIT"])

@app.command("activity")
def activity(since: str = typer.Option(..., "--since"),
             until: Optional[str] = typer.Option(None, "--until"),
             branch: str = typer.Option("*", "--branch"),
             regex: bool = typer.Option(False, "--regex"),
             author: Optional[str] = typer.Option(None, "--author"),
             limit: int = typer.Option(0, "--limit")):
    """Show commits filtered by branch patterns."""
    refs = resolve_branches(branch, regex, include_remotes=False, include_locals=True)
    if not refs:
        typer.secho("No local branches matched.", fg=typer.colors.YELLOW)
        raise typer.Exit()

    total = 0
    for r in sorted(refs, key=lambda x: x.name.lower()):
        cmd = ["git", "log", r.name, f"--since={since}"]
        if until: cmd.append(f"--until={until}")
        cmd += ["--pretty=%h|%ad|%s", "--date=short"]
        if author: cmd.append(f"--author={author}")
        if limit > 0: cmd += [f"--max-count={limit}"]
        rc, out, err = run(cmd)
        if rc != 0: continue
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if not lines: continue
        typer.secho(f"\n[{r.name}] — {len(lines)} commit(s)", bold=True)
        total += len(lines)
        for ln in lines:
            try: h, d, s = ln.split("|", 2)
            except ValueError: h, d, s = ln, "", ""
            typer.echo(f"  {pad(h,8)}  {pad(d,10)}  {s}")
    if total == 0:
        typer.secho("\nNo activity found.", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"\nTotal commits: {total}", bold=True)

@app.command("stale")
def stale_branches(age: str,  # positional now
                   include_remotes: bool = typer.Option(False, "--remotes"),
                   keep: str = typer.Option("", "--keep", help="Comma-separated branches to preserve in addition to protected ones"),
                   regex: bool = typer.Option(False, "--regex"),
                   delete: bool = typer.Option(False, "--delete"),
                   force: bool = typer.Option(False, "--force")):
    """List candidate stale branches. Optionally delete local stale branches."""
    ensure_git_repo()
    cutoff = now() - parse_age(age)
    rc, cur, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = cur if rc == 0 else None

    refs = list_refs(True, include_remotes)

    # Default protected branches never touched
    protected = ["main", "master", "develop", "dev"]
    keep_rx = to_regex(",".join(protected + [b.strip() for b in keep.split(",") if b.strip()]), regex)

    stale_rows, victims = [], []
    for r in refs:
        if keep_rx and (keep_rx.fullmatch(r.name) or keep_rx.search(r.name)):
            continue  # skip protected / explicitly kept branches
        if r.name == current_branch:
            continue
        if r.last_commit_ts is None:
            continue
        last_dt = dt.datetime.fromtimestamp(r.last_commit_ts, dt.timezone.utc)
        if last_dt <= cutoff:
            stale_rows.append([r.name, r.scope, (r.upstream or "-"), last_dt.strftime(SHORT_DATE_FMT)])
            if r.scope == "local":
                victims.append(r.name)

    if not stale_rows:
        typer.secho("No stale branches found.", fg=typer.colors.YELLOW)
        raise typer.Exit()
    
    print_table(stale_rows, headers=["BRANCH", "SCOPE", "UPSTREAM", "LAST_COMMIT"])

    if delete and victims:
        typer.secho("\nDeleting local stale branches...", bold=True)
        for v in victims:
            cmd = ["git", "branch", "-D" if force else "-d", v]
            rc, out, err = run(cmd)
            typer.echo(f"  deleted: {v}" if rc == 0 else f"  failed: {v} — {err or out}")

@app.command("search")
def search_commits(query: str,
                   all: bool = typer.Option(True, "--all/--no-all"),
                   ignore_case: bool = typer.Option(False, "--ignore-case", "-i"),
                   author: Optional[str] = typer.Option(None, "--author"),
                   since: Optional[str] = typer.Option(None, "--since"),
                   until: Optional[str] = typer.Option(None, "--until"),
                   pick: Optional[int] = typer.Option(None, "--pick"),
                   show: int = typer.Option(20, "--show")):
    """Search commits by message and optionally cherry-pick one."""
    ensure_git_repo()
    cmd = ["git", "log"]
    if all: cmd.append("--all")
    cmd += ["--pretty=%h|%ad|%s", "--date=short", f"--grep={query}"]
    if ignore_case: cmd.append("--regexp-ignore-case")
    if author: cmd.append(f"--author={author}")
    if since: cmd.append(f"--since={since}")
    if until: cmd.append(f"--until={until}")
    if show > 0: cmd.append(f"--max-count={show}")
    rc, out, err = run(cmd)
    if rc != 0:
        typer.secho(err or "git log failed", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if not lines:
        typer.secho("No matching commits.", fg=typer.colors.YELLOW)
        raise typer.Exit()
    hashes, rows = [], []
    for idx, ln in enumerate(lines, start=1):
        try: h, d, s = ln.split("|", 2)
        except ValueError: h, d, s = ln, "", ""
        hashes.append(h)
        rows.append([str(idx), h, d, s])
    print_table(rows, headers=["#", "HASH", "DATE", "MESSAGE"])
    if pick is not None:
        if pick < 1 or pick > len(hashes):
            typer.secho(f"--pick must be between 1 and {len(hashes)}", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        target = hashes[pick-1]
        typer.secho(f"\nCherry-picking {target} ...", bold=True)
        rc, out, err = run(["git", "cherry-pick", target])
        typer.echo(out if rc == 0 else (err or out))

# -------------------------
# Entry
# -------------------------

def main():
    try:
        app()
    except KeyboardInterrupt:
        typer.secho("\nAborted.", fg=typer.colors.RED)

if __name__ == "__main__":
    main()
