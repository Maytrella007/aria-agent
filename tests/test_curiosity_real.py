"""
Test REAL End-to-End: Curiosity Engine con DeepSeek + Web real

NO usa mocks. Hace búsquedas reales, fetch de páginas reales,
y usa DeepSeek como LLM para generar queries y evaluar calidad.
"""

import json
import os
import shutil
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.autonomy.curiosity import CuriosityEngine, ContentQualityFilter, CuriosityConfig
from core.tools.web_search import WebSearchTool
from core.tools.web_fetch import WebFetchTool
from core.tools.curiosity_tool import CuriosityTool
from core.llm.llm_providers import LLMProvider

# =============================================================================
# Constants
# =============================================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def llm():
    """Initialize DeepSeek LLM."""
    if not DEEPSEEK_API_KEY:
        pytest.skip("DEEPSEEK_API_KEY environment variable not set")
    print("\n[1/5] Conectando a DeepSeek...")
    llm = LLMProvider.create("deepseek", api_key=DEEPSEEK_API_KEY, model="deepseek-chat")

    # Test connection
    response = llm.chat(
        messages=[{"role": "user", "content": "Responde solo 'OK' si funcionas."}],
        max_tokens=10,
    )
    print(f"  DeepSeek responde: {response.content.strip()}")
    assert response.content, "DeepSeek no respondió"
    return llm


@pytest.fixture(scope="session")
def web_tools():
    """Initialize web tools."""
    print("\n[2/5] Inicializando herramientas web...")
    search_tool = WebSearchTool()
    fetch_tool = WebFetchTool()

    # Test search
    result = search_tool.execute(query="python programming", num_results=2)
    assert result.success, f"Web search failed: {result.error}"
    print(f"  Web search OK: {len(result.output)} chars")

    return search_tool, fetch_tool


@pytest.fixture(scope="session")
def engine_and_log(llm, web_tools):
    """Wire up the curiosity engine with real callbacks."""
    print("\n[3/5] Configurando CuriosityEngine...")

    search_tool, fetch_tool = web_tools
    data_dir = tempfile.mkdtemp(prefix="aria_real_test_")

    engine = CuriosityEngine(data_dir=data_dir)
    engine.config.max_searches_per_session = 2
    engine.config.max_fetches_per_search = 2

    ingest_log = []

    def real_search(query, num_results=5):
        result = search_tool.execute(query=query, num_results=num_results)
        return result.output if result.success else None

    def real_fetch(url):
        result = fetch_tool.execute(url=url, max_chars=8000)
        return result.output if result.success else None

    def real_ingest(content, source_url="", topic="", auto_curiosity=True):
        # Log instead of actual RAG ingest for this test
        ingest_log.append({
            "content_length": len(content),
            "source_url": source_url,
            "topic": topic,
        })
        return max(1, len(content) // 500)

    def real_llm_fn(prompt, max_tokens=150):
        response = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a helpful assistant. Be concise and return only what is asked.",
            max_tokens=max_tokens,
        )
        return response.content if response else None

    engine.set_tools(
        search_fn=real_search,
        fetch_fn=real_fetch,
        ingest_fn=real_ingest,
        llm_fn=real_llm_fn,
        memory_fn=lambda q: [],
    )

    print(f"  Engine configurado en {data_dir}")

    yield engine, ingest_log

    # Cleanup
    shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture(scope="session")
def engine(engine_and_log):
    """Return just the engine from the engine_and_log fixture."""
    return engine_and_log[0]


@pytest.fixture(scope="session")
def ingest_log(engine_and_log):
    """Return just the ingest_log from the engine_and_log fixture."""
    return engine_and_log[1]


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.slow
def test_explore_now(engine, ingest_log):
    """Test: exploración bajo demanda con LLM real."""
    print("\n[4/5] Test: explore_now('inteligencia artificial 2026')...")
    print("  Buscando en web, leyendo páginas, evaluando calidad...")

    start = time.time()
    report = engine.explore_now("inteligencia artificial 2026", add_to_interests=True)
    elapsed = time.time() - start

    print(f"\n  === REPORTE ===")
    for line in report.split("\n"):
        print(f"  {line}")
    print(f"  Tiempo total: {elapsed:.1f}s")

    # Validaciones
    assert "inteligencia artificial" in report.lower() or "Investigué" in report
    assert engine._daily_explorations >= 1
    assert engine._daily_searches >= 1

    # Quality filter stats
    print(f"\n  Quality filter stats:")
    print(f"    Passed:   {engine._quality_stats['passed']}")
    print(f"    Rejected: {engine._quality_stats['rejected']}")
    print(f"    LLM-checked: {engine._quality_stats['llm_checked']}")

    # Ingest log
    print(f"\n  RAG ingest log ({len(ingest_log)} entries):")
    for entry in ingest_log:
        print(f"    [{entry['topic']}] {entry['source_url'][:60]}... ({entry['content_length']} chars)")


@pytest.mark.slow
def test_autonomous_exploration(engine):
    """Test: una ronda autónoma (topic selection + exploration)."""
    print("\n[5/5] Test: exploración autónoma (_do_exploration)...")

    # Feed some conversation context
    engine.feed_conversation([
        {"role": "user", "content": "Estoy investigando sobre quantum computing y sus aplicaciones en criptografía"},
        {"role": "assistant", "content": "La computación cuántica tiene implicaciones profundas para la criptografía..."},
    ])

    print(f"  Conversation topics extraídos: {engine._conversation_topics}")

    prev_explorations = len(engine.session_explorations)
    engine._do_exploration()

    if len(engine.session_explorations) > prev_explorations:
        exp = engine.session_explorations[-1]
        print(f"\n  === EXPLORACIÓN AUTÓNOMA ===")
        print(f"  Topic: {exp.topic}")
        print(f"  Source: {exp.source}")
        print(f"  Query: {exp.query}")
        print(f"  URLs visitadas: {len(exp.urls_visited)}")
        for url in exp.urls_visited[:3]:
            print(f"    - {url[:80]}")
        print(f"  Chunks ingested: {exp.chunks_ingested}")
        print(f"  Duración: {exp.duration_seconds}s")
        if exp.summary:
            print(f"  Summary: {exp.summary[:200]}")

        # Quality scores
        scores = exp.metadata.get("quality_scores", [])
        if scores:
            print(f"\n  Quality scores:")
            for s in scores:
                print(f"    {s['url'][:50]}... h={s['heuristic']}, llm={s['llm']}")
    else:
        print("  (No se ejecutó — posiblemente bloqueada por límites)")


@pytest.mark.slow
def test_status(engine):
    """Show final status."""
    print("\n\n" + "=" * 60)
    print("ESTADO FINAL DEL ENGINE")
    print("=" * 60)
    status = engine.get_status()
    for line in status.split("\n"):
        print(f"  {line}")


# =============================================================================
# Main (for manual execution)
# =============================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s", "--tb=short"]))
