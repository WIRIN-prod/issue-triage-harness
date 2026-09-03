"""Fetch a repo at a pinned commit and extract its code graph.

Pinned to a SHA rather than a branch on purpose: litellm's default branch is
`litellm_internal_staging` and moves constantly. A moving ref would make the graph
unreproducible and silently invalidate every dataset hash built against it.

Extraction is graphify's AST pass — deterministic, no LLM, no API key. Cost is
seconds of CPU, which is why the graph can be a hard dependency of the labelling
pipeline without dragging a bill along with it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepoPin:
    owner_repo: str          # "BerriAI/litellm"
    commit: str              # full 40-char SHA
    package: str = "litellm"  # top-level package to sparse-checkout
    exclude: tuple[str, ...] = ("/proxy/",)

    @property
    def slug(self) -> str:
        return self.owner_repo.split("/")[-1]


LITELLM = RepoPin(
    owner_repo="BerriAI/litellm",
    commit="658f50663d19f613a3f5caf998168da019764ad8",
)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def fetch(pin: RepoPin, dest: Path) -> Path:
    """Sparse, blobless checkout of one package at one commit (~93MB for litellm)."""
    root = dest / pin.slug
    if (root / ".git").is_dir():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True).stdout.strip()
        if head == pin.commit:
            return root
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], root)
    _run(["git", "remote", "add", "origin", f"https://github.com/{pin.owner_repo}.git"], root)
    _run(["git", "sparse-checkout", "init", "--cone"], root)
    _run(["git", "sparse-checkout", "set", pin.package], root)
    _run(["git", "fetch", "--depth", "1", "--filter=blob:none", "origin", pin.commit], root)
    _run(["git", "checkout", "FETCH_HEAD"], root)
    return root


def source_files(root: Path, pin: RepoPin) -> list[Path]:
    return [
        p for p in sorted(root.rglob("*.py"))
        if not any(x in str(p) for x in pin.exclude) and not p.name.startswith("test_")
    ]


def _graphify_python() -> str:
    """graphify installs as a uv tool with its own interpreter; find it, don't guess."""
    which = subprocess.run(["which", "graphify"], capture_output=True, text=True).stdout.strip()
    if not which:
        raise RuntimeError("graphify not on PATH — `uv tool install graphifyy`")
    return Path(which).read_text().splitlines()[0].lstrip("#!").strip()


EXTRACT = """
import json, sys
from pathlib import Path
from graphify.extract import extract

def main():
    files = [Path(p) for p in json.loads(Path(sys.argv[1]).read_text())]
    res = extract(files, cache_root=Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(res))
    print(json.dumps({"nodes": len(res["nodes"]), "edges": len(res["edges"])}))

if __name__ == "__main__":
    main()
"""


def extract_graph(root: Path, pin: RepoPin, out: Path, scratch: Path,
                  cold: bool = True) -> dict:
    """Extract the code graph. Cold by default, and that default is load-bearing.

    graphify caches per-file extraction results, but the cache changes the *output*:
    an incremental build over a warm cache yielded 74,223 edges where a cold build
    over the identical file list yields 81,188 — roughly 7,000 cross-file references
    resolved differently depending on extraction order. Cold builds are
    byte-identical run to run; incremental ones are not.

    Since the graph feeds both labelling and every eval run, a graph that changes
    under you would silently invalidate comparisons — so the cache is cleared unless
    a caller explicitly opts out for local iteration speed.
    """
    if cold:
        shutil.rmtree(root / "graphify-out", ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)
    files = source_files(root, pin)
    scratch.mkdir(parents=True, exist_ok=True)
    manifest = scratch / "files.json"
    manifest.write_text(json.dumps([str(p) for p in files]))
    script = scratch / "_extract.py"
    script.write_text(EXTRACT)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [_graphify_python(), str(script), str(manifest), str(root), str(out)],
        capture_output=True, text=True, check=True,
    )
    stats = json.loads(proc.stdout.strip().splitlines()[-1])
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return {"files": len(files), **stats, "graph_sha256": digest}


# Pinned output of a cold build at LITELLM.commit. A mismatch means either the
# extractor version moved or the checkout did — both invalidate downstream results.
EXPECTED_GRAPH_SHA256 = "fe81e62f463ddc05"


def build(pin: RepoPin = LITELLM, data: Path = Path("data"),
          scratch: Path = Path(".cache"), cold: bool = True) -> dict:
    root = fetch(pin, data / "repos")
    out = data / "graphs" / f"{pin.slug}-raw.json"
    stats = extract_graph(root, pin, out, scratch, cold=cold)
    stats["matches_pin"] = stats["graph_sha256"].startswith(EXPECTED_GRAPH_SHA256)
    return {"repo": pin.owner_repo, "commit": pin.commit, "graph": str(out), **stats}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
