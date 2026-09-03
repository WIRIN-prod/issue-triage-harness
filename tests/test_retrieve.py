"""Retrieval behaviour that the spike (DECISIONS.md D15) showed we must not regress."""

import json
from pathlib import Path

import pytest

from graph.retrieve import GraphIndex, Context, match, retrieve
from graph.vocab import Term, Vocabulary

DATA = Path("data")
GRAPH = DATA / "graphs" / "litellm-raw.json"
REPO = DATA / "repos" / "litellm"


@pytest.fixture
def vocab() -> Vocabulary:
    return Vocabulary(repo="acme/thing", commit="abc123", terms=[
        Term(text="anthropic", kind="provider", target="pkg/llms/anthropic", weight=2.0),
        Term(text="bedrock", kind="provider", target="pkg/llms/bedrock", weight=2.0),
        Term(text="claude sonnet 4", kind="model", target="pkg/llms/anthropic", weight=3.0),
        Term(text="auto router", kind="module", target="pkg/router_strategy/auto_router", weight=1.5),
    ])


def test_unknown_terms_do_not_match(vocab):
    assert match(vocab, "please help", "my code is broken and nothing works") == []


def test_matches_provider_named_in_title(vocab):
    hits = match(vocab, "anthropic streaming is broken", "")
    assert [m.text for m in hits] == ["anthropic"]


def test_longer_match_subsumes_the_shorter_one_it_contains(vocab):
    hits = match(vocab, "claude sonnet 4 fails", "")
    texts = [m.text for m in hits]
    assert "claude sonnet 4" in texts
    assert "anthropic" not in texts  # not literally present; only via the model's target


def test_title_outweighs_a_mention_inside_a_code_block(vocab):
    """A provider pasted in a config block is incidental; the title is the subject."""
    hits = match(
        vocab,
        "auto router ignores model_info",
        "here is my config:\n```yaml\nmodel: bedrock/claude\nregion: us-east-1\n```",
    )
    by_text = {m.text: m.weight for m in hits}
    assert by_text["auto router"] > by_text["bedrock"]


def test_empty_context_when_nothing_in_the_repo_vocabulary_matches(vocab, tmp_path):
    graph = tmp_path / "g.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}))
    ctx = retrieve(GraphIndex(graph), vocab, "llm", "")
    assert ctx.is_empty
    assert "no repo vocabulary matched" in ctx.reason
    assert ctx.est_tokens == 0


# --- integration: needs the cloned repo and built graph (gitignored) ---

needs_data = pytest.mark.skipif(
    not (GRAPH.exists() and REPO.exists()),
    reason="run `graph build` first — repo checkout and graph are not committed",
)


@pytest.fixture(scope="module")
def live():
    from graph import vocab as V
    return (
        GraphIndex(GRAPH, repo_root="data/repos/litellm"),
        V.build(REPO, "BerriAI/litellm", "658f5066"),
    )


@needs_data
def test_junk_issue_gets_no_context(live):
    idx, v = live
    assert retrieve(idx, v, "llm", "").is_empty


@needs_data
def test_provider_issue_resolves_to_that_provider(live):
    idx, v = live
    ctx = retrieve(idx, v, "openrouter entries disagree with openrouter.ai on price", "")
    assert ctx.modules and "openrouter" in ctx.modules[0]


@needs_data
def test_context_respects_the_token_budget(live):
    idx, v = live
    ctx = retrieve(idx, v, "bedrock anthropic streaming broken", "x" * 200, budget_tokens=300)
    assert ctx.est_tokens <= 600  # one block may overshoot; further blocks must not be added
