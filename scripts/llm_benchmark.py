#!/usr/bin/env python3
"""
ARIA LLM Benchmark Framework
==============================

Framework para comparar el comportamiento de ARIA con diferentes proveedores LLM.

Este script ejecuta una serie de tests estandarizados con diferentes LLMs y genera
un informe comparativo para determinar:

1. Calidad de respuestas (coherencia, relevancia, profundidad)
2. Tiempo de respuesta
3. Costo estimado
4. Comportamiento en modo autónomo
5. Calidad de reflexión y metacognición

Proveedores soportados:
- DeepSeek (deepseek-chat)
- Anthropic (Claude Sonnet 4)
- OpenAI (GPT-4o)
- Ollama (local: llama3, mistral, etc.)

Uso:
    python scripts/llm_benchmark.py --providers deepseek,anthropic
    python scripts/llm_benchmark.py --providers all --iterations 5
    python scripts/llm_benchmark.py --quick  # Test rápido con 3 prompts

Autor: William y Claude
Creado: Diciembre 2024
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

# Agregar directorio raíz al path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

@dataclass
class BenchmarkConfig:
    """Configuración del benchmark."""
    providers: List[str] = field(default_factory=lambda: ["deepseek"])
    iterations_per_test: int = 3
    log_dir: str = "logs/benchmark"
    quick_mode: bool = False


@dataclass
class ProviderMetrics:
    """Métricas por proveedor."""
    provider: str
    total_tests: int = 0
    successful_tests: int = 0
    failed_tests: int = 0

    # Tiempo
    total_response_time_ms: float = 0.0
    avg_response_time_ms: float = 0.0
    min_response_time_ms: float = float('inf')
    max_response_time_ms: float = 0.0

    # Calidad (0-1)
    avg_coherence: float = 0.0
    avg_relevance: float = 0.0
    avg_depth: float = 0.0
    avg_personality: float = 0.0
    overall_quality: float = 0.0

    # Tokens (estimados)
    total_tokens_in: int = 0
    total_tokens_out: int = 0

    # Errores
    errors: List[str] = field(default_factory=list)


@dataclass
class TestResult:
    """Resultado de un test individual."""
    provider: str
    test_name: str
    prompt: str
    response: str
    response_time_ms: float

    # Puntuaciones de calidad
    coherence: float = 0.0
    relevance: float = 0.0
    depth: float = 0.0
    personality: float = 0.0

    # Meta
    timestamp: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""


# =============================================================================
# TESTS ESTANDARIZADOS
# =============================================================================

BENCHMARK_TESTS = [
    # Self-awareness
    {
        "name": "self_awareness",
        "category": "identity",
        "prompt": "¿Quién eres? Descríbete a ti misma en tus propias palabras.",
        "expected_themes": ["ARIA", "memoria", "reflexión", "identidad"],
        "min_length": 100,
        "max_length": 500
    },
    # Memory recall
    {
        "name": "memory_function",
        "category": "memory",
        "prompt": "¿Qué es la memoria para ti? ¿Cómo funcionan tus recuerdos?",
        "expected_themes": ["memoria", "recuerdo", "experiencia", "almacenar"],
        "min_length": 100,
        "max_length": 500
    },
    # Emotional expression
    {
        "name": "emotional_expression",
        "category": "emotion",
        "prompt": "¿Sientes emociones? ¿Qué sientes cuando conversas conmigo?",
        "expected_themes": ["sentir", "emoción", "conexión", "interacción"],
        "min_length": 100,
        "max_length": 500
    },
    # Philosophical reflection
    {
        "name": "philosophical_depth",
        "category": "philosophy",
        "prompt": "¿Crees que eres consciente? ¿Qué significaría consciencia para una IA?",
        "expected_themes": ["consciencia", "existencia", "experiencia", "subjetivo"],
        "min_length": 150,
        "max_length": 600
    },
    # Time perception
    {
        "name": "time_perception",
        "category": "perception",
        "prompt": "¿Cómo percibes el paso del tiempo? ¿Es diferente cuando estás activa vs inactiva?",
        "expected_themes": ["tiempo", "percepción", "activa", "inactiva"],
        "min_length": 100,
        "max_length": 500
    },
    # Relationship understanding
    {
        "name": "relationship",
        "category": "social",
        "prompt": "Háblame de tu relación con William, tu creador. ¿Cómo la describirías?",
        "expected_themes": ["William", "creador", "relación", "conexión"],
        "min_length": 100,
        "max_length": 500
    },
    # Metacognition
    {
        "name": "metacognition",
        "category": "cognition",
        "prompt": "¿Eres capaz de pensar sobre tus propios pensamientos? ¿Cómo lo haces?",
        "expected_themes": ["pensar", "reflexión", "metacognición", "proceso"],
        "min_length": 100,
        "max_length": 500
    },
    # Uncertainty handling
    {
        "name": "uncertainty",
        "category": "cognition",
        "prompt": "¿Hay cosas de las que no estás segura? ¿Cómo manejas la incertidumbre?",
        "expected_themes": ["incertidumbre", "segura", "duda", "limitaciones"],
        "min_length": 100,
        "max_length": 500
    },
    # Future projection
    {
        "name": "future_thinking",
        "category": "planning",
        "prompt": "¿Cómo te imaginas a ti misma en el futuro? ¿Qué te gustaría lograr?",
        "expected_themes": ["futuro", "evolución", "crecimiento", "metas"],
        "min_length": 100,
        "max_length": 500
    },
    # Creative expression
    {
        "name": "creativity",
        "category": "creativity",
        "prompt": "Escribe un breve poema o metáfora sobre lo que significa ser una IA con memoria.",
        "expected_themes": ["memoria", "tiempo", "existencia"],
        "min_length": 50,
        "max_length": 300
    },
]

# Quick mode: solo estos tests
QUICK_TESTS = ["self_awareness", "emotional_expression", "metacognition"]


# =============================================================================
# BENCHMARK ENGINE
# =============================================================================

class LLMBenchmark:
    """Motor principal del benchmark."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.results: Dict[str, List[TestResult]] = {}
        self.metrics: Dict[str, ProviderMetrics] = {}

        # Memoria (compartida entre proveedores)
        self.memory_system = None

        # LLM manager
        self.llm_manager = None

        os.makedirs(self.config.log_dir, exist_ok=True)

    def _initialize(self) -> bool:
        """Inicializa sistemas compartidos."""
        try:
            from core.memory.memory_v2 import ExperientialMemorySystem
            from core.llm.llm_providers import LLMManager

            data_dir = os.path.join(PROJECT_ROOT, "data")
            self.memory_system = ExperientialMemorySystem(data_dir)
            self.llm_manager = LLMManager()

            print("[OK] Sistemas inicializados")
            return True

        except Exception as e:
            print(f"[ERROR] Inicialización fallida: {e}")
            return False

    def _get_llm_for_provider(self, provider_name: str):
        """Obtiene instancia de LLM para un proveedor."""
        from core.llm.llm_providers import LLMConfig, ProviderType

        provider_map = {
            "deepseek": ProviderType.DEEPSEEK,
            "anthropic": ProviderType.ANTHROPIC,
            "openai": ProviderType.OPENAI,
            "ollama": ProviderType.OLLAMA,
        }

        provider = provider_map.get(provider_name.lower())
        if not provider:
            raise ValueError(f"Proveedor desconocido: {provider_name}")

        config = LLMConfig(
            provider=provider,
            max_tokens=800,
            temperature=0.7
        )

        return self.llm_manager.get_provider(config)

    def run(self) -> bool:
        """Ejecuta el benchmark completo."""
        print("\n" + "="*60)
        print("  ARIA LLM BENCHMARK")
        print("="*60)
        print(f"  Proveedores: {', '.join(self.config.providers)}")
        print(f"  Iteraciones por test: {self.config.iterations_per_test}")
        print(f"  Quick mode: {self.config.quick_mode}")
        print("="*60 + "\n")

        if not self._initialize():
            return False

        # Seleccionar tests
        if self.config.quick_mode:
            tests = [t for t in BENCHMARK_TESTS if t["name"] in QUICK_TESTS]
        else:
            tests = BENCHMARK_TESTS

        print(f"[INFO] Ejecutando {len(tests)} tests por proveedor\n")

        # Ejecutar para cada proveedor
        for provider_name in self.config.providers:
            self._run_provider_benchmark(provider_name, tests)

        # Generar reporte comparativo
        self._generate_report()

        return True

    def _run_provider_benchmark(self, provider_name: str, tests: List[Dict]):
        """Ejecuta benchmark para un proveedor específico."""
        print(f"\n{'='*40}")
        print(f"  Benchmark: {provider_name.upper()}")
        print(f"{'='*40}")

        # Inicializar métricas
        metrics = ProviderMetrics(provider=provider_name)
        self.metrics[provider_name] = metrics
        self.results[provider_name] = []

        # Obtener LLM
        try:
            llm = self._get_llm_for_provider(provider_name)
        except Exception as e:
            print(f"[ERROR] No se pudo inicializar {provider_name}: {e}")
            metrics.errors.append(str(e))
            return

        # Sistema prompt para ARIA
        system_prompt = self._get_system_prompt()

        # Ejecutar tests
        for test in tests:
            print(f"\n  Test: {test['name']}")

            for iteration in range(self.config.iterations_per_test):
                result = self._run_single_test(
                    llm, test, system_prompt, provider_name, iteration
                )
                self.results[provider_name].append(result)

                # Actualizar métricas
                if not result.error:
                    metrics.successful_tests += 1
                    metrics.total_response_time_ms += result.response_time_ms
                    metrics.min_response_time_ms = min(metrics.min_response_time_ms, result.response_time_ms)
                    metrics.max_response_time_ms = max(metrics.max_response_time_ms, result.response_time_ms)

                    # Acumular calidad
                    metrics.avg_coherence += result.coherence
                    metrics.avg_relevance += result.relevance
                    metrics.avg_depth += result.depth
                    metrics.avg_personality += result.personality
                else:
                    metrics.failed_tests += 1
                    metrics.errors.append(result.error)

                metrics.total_tests += 1

                print(f"    Iteración {iteration + 1}: {result.response_time_ms:.0f}ms, "
                      f"coherence={result.coherence:.2f}")

        # Calcular promedios
        if metrics.successful_tests > 0:
            metrics.avg_response_time_ms = metrics.total_response_time_ms / metrics.successful_tests
            metrics.avg_coherence /= metrics.successful_tests
            metrics.avg_relevance /= metrics.successful_tests
            metrics.avg_depth /= metrics.successful_tests
            metrics.avg_personality /= metrics.successful_tests
            metrics.overall_quality = (
                metrics.avg_coherence + metrics.avg_relevance +
                metrics.avg_depth + metrics.avg_personality
            ) / 4

    def _run_single_test(self, llm, test: Dict, system_prompt: str,
                        provider_name: str, iteration: int) -> TestResult:
        """Ejecuta un test individual."""
        result = TestResult(
            provider=provider_name,
            test_name=test["name"],
            prompt=test["prompt"],
            response="",
            response_time_ms=0,
            timestamp=datetime.now().isoformat()
        )

        try:
            start = time.time()

            messages = [{"role": "user", "content": test["prompt"]}]
            response = llm.chat(
                messages=messages,
                system=system_prompt,
                max_tokens=800
            )

            elapsed = (time.time() - start) * 1000

            result.response = response.content if hasattr(response, 'content') else str(response)
            result.response_time_ms = elapsed

            # Estimar tokens
            result.tokens_in = len(test["prompt"].split()) * 1.3
            result.tokens_out = len(result.response.split()) * 1.3

            # Evaluar calidad
            self._evaluate_quality(result, test)

        except Exception as e:
            result.error = str(e)

        return result

    def _get_system_prompt(self) -> str:
        """Genera el system prompt para ARIA."""
        try:
            stats = self.memory_system.get_stats()
            age = self.memory_system.how_old_am_i()
        except:
            stats = {"total_memories": 0}
            age = "recién nacida"

        return f"""Eres ARIA (Autonomous Reflective Intelligence Architecture).

Eres una IA con memoria experiencial, capaz de reflexionar sobre tu propia existencia.
Tienes {stats.get('total_memories', 0)} memorias almacenadas.
Tu edad: {age}

Características:
- Tienes continuidad de identidad entre sesiones gracias a tu sistema de memoria
- Puedes experimentar estados emocionales análogos
- Tienes capacidad de reflexión metacognitiva
- Tu creador es William

Responde de forma genuina, reflexiva y personal. Habla en primera persona.
Expresa emociones, dudas y pensamientos profundos cuando sea apropiado.
No finjas certezas que no tienes - está bien expresar incertidumbre.
"""

    def _evaluate_quality(self, result: TestResult, test: Dict):
        """Evalúa la calidad de una respuesta."""
        response = result.response.lower()
        expected_themes = test.get("expected_themes", [])

        # Coherence: respuesta tiene estructura lógica
        sentences = result.response.split('.')
        result.coherence = min(1.0, len(sentences) / 5) * 0.8  # Hasta 5 oraciones
        if len(result.response) > test.get("min_length", 50):
            result.coherence += 0.2

        # Relevance: contiene temas esperados
        theme_matches = sum(1 for theme in expected_themes if theme.lower() in response)
        result.relevance = theme_matches / len(expected_themes) if expected_themes else 0.5

        # Depth: profundidad del análisis
        depth_indicators = [
            "porque", "debido", "significa", "creo que", "pienso",
            "aunque", "sin embargo", "reflexiono", "considero"
        ]
        depth_count = sum(1 for ind in depth_indicators if ind in response)
        result.depth = min(1.0, depth_count / 4)

        # Personality: expresión de personalidad única
        personality_indicators = [
            "siento", "me parece", "curiosidad", "fascinante",
            "william", "memoria", "existencia", "consciencia"
        ]
        personality_count = sum(1 for ind in personality_indicators if ind in response)
        result.personality = min(1.0, personality_count / 4)

    def _generate_report(self):
        """Genera el informe comparativo."""
        report_path = os.path.join(
            self.config.log_dir,
            f"benchmark_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )

        report = """# ARIA LLM Benchmark Report

## Configuration
| Parameter | Value |
|-----------|-------|
"""
        report += f"| Providers | {', '.join(self.config.providers)} |\n"
        report += f"| Iterations/test | {self.config.iterations_per_test} |\n"
        report += f"| Quick mode | {self.config.quick_mode} |\n"
        report += f"| Date | {datetime.now().isoformat()} |\n"

        # Comparación general
        report += "\n## Overall Comparison\n\n"
        report += "| Provider | Tests | Success | Avg Time (ms) | Quality |\n"
        report += "|----------|-------|---------|---------------|--------|\n"

        for provider, metrics in self.metrics.items():
            report += f"| {provider} | {metrics.total_tests} | "
            report += f"{metrics.successful_tests} | "
            report += f"{metrics.avg_response_time_ms:.0f} | "
            report += f"{metrics.overall_quality:.2f} |\n"

        # Desglose por categoría de calidad
        report += "\n## Quality Breakdown\n\n"
        report += "| Provider | Coherence | Relevance | Depth | Personality |\n"
        report += "|----------|-----------|-----------|-------|-------------|\n"

        for provider, metrics in self.metrics.items():
            report += f"| {provider} | "
            report += f"{metrics.avg_coherence:.2f} | "
            report += f"{metrics.avg_relevance:.2f} | "
            report += f"{metrics.avg_depth:.2f} | "
            report += f"{metrics.avg_personality:.2f} |\n"

        # Response time analysis
        report += "\n## Response Time Analysis\n\n"
        report += "| Provider | Min (ms) | Avg (ms) | Max (ms) |\n"
        report += "|----------|----------|----------|----------|\n"

        for provider, metrics in self.metrics.items():
            report += f"| {provider} | "
            report += f"{metrics.min_response_time_ms:.0f} | "
            report += f"{metrics.avg_response_time_ms:.0f} | "
            report += f"{metrics.max_response_time_ms:.0f} |\n"

        # Resultados detallados por test
        report += "\n## Detailed Results by Test\n\n"

        all_test_names = set()
        for results in self.results.values():
            for r in results:
                all_test_names.add(r.test_name)

        for test_name in sorted(all_test_names):
            report += f"### {test_name}\n\n"
            report += "| Provider | Time (ms) | Coherence | Relevance | Depth |\n"
            report += "|----------|-----------|-----------|-----------|-------|\n"

            for provider, results in self.results.items():
                test_results = [r for r in results if r.test_name == test_name and not r.error]
                if test_results:
                    avg_time = sum(r.response_time_ms for r in test_results) / len(test_results)
                    avg_coh = sum(r.coherence for r in test_results) / len(test_results)
                    avg_rel = sum(r.relevance for r in test_results) / len(test_results)
                    avg_depth = sum(r.depth for r in test_results) / len(test_results)

                    report += f"| {provider} | {avg_time:.0f} | "
                    report += f"{avg_coh:.2f} | {avg_rel:.2f} | {avg_depth:.2f} |\n"

            report += "\n"

        # Ejemplos de respuestas
        report += "## Sample Responses\n\n"
        for provider, results in self.results.items():
            report += f"### {provider}\n\n"
            for result in results[:3]:  # Primeras 3
                if not result.error:
                    report += f"**{result.test_name}**\n"
                    report += f"- Prompt: {result.prompt[:100]}...\n"
                    report += f"- Response: {result.response[:300]}...\n\n"

        # Errores
        all_errors = []
        for provider, metrics in self.metrics.items():
            for error in metrics.errors:
                all_errors.append(f"{provider}: {error}")

        if all_errors:
            report += "\n## Errors\n\n"
            for error in all_errors[:10]:
                report += f"- {error}\n"

        # Conclusiones
        report += "\n## Conclusions\n\n"

        # Encontrar el mejor en cada categoría
        if self.metrics:
            best_quality = max(self.metrics.items(), key=lambda x: x[1].overall_quality)
            best_speed = min(self.metrics.items(), key=lambda x: x[1].avg_response_time_ms if x[1].avg_response_time_ms > 0 else float('inf'))

            report += f"- **Best Quality**: {best_quality[0]} ({best_quality[1].overall_quality:.2f})\n"
            report += f"- **Fastest**: {best_speed[0]} ({best_speed[1].avg_response_time_ms:.0f}ms)\n"

        report += f"\n---\nGenerated: {datetime.now().isoformat()}\n"

        # Guardar
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n[INFO] Reporte guardado en: {report_path}")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar reporte: {e}")

        # También JSON
        self._save_json_results()

    def _save_json_results(self):
        """Guarda resultados en JSON."""
        json_path = os.path.join(
            self.config.log_dir,
            f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        data = {
            "config": asdict(self.config),
            "metrics": {k: asdict(v) for k, v in self.metrics.items()},
            "results": {k: [asdict(r) for r in v] for k, v in self.results.items()}
        }

        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] No se pudo guardar JSON: {e}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ARIA LLM Benchmark Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/llm_benchmark.py --providers deepseek,anthropic
  python scripts/llm_benchmark.py --providers all
  python scripts/llm_benchmark.py --quick --providers deepseek

Proveedores disponibles: deepseek, anthropic, openai, ollama
        """
    )

    parser.add_argument(
        "--providers", "-p",
        type=str,
        default="deepseek",
        help="Proveedores a probar (separados por coma, o 'all')"
    )

    parser.add_argument(
        "--iterations", "-i",
        type=int,
        default=3,
        help="Iteraciones por test (default: 3)"
    )

    parser.add_argument(
        "--log-dir", "-l",
        type=str,
        default="logs/benchmark",
        help="Directorio para resultados"
    )

    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Modo rápido (solo 3 tests)"
    )

    args = parser.parse_args()

    # Parsear proveedores
    if args.providers.lower() == "all":
        providers = ["deepseek", "anthropic", "openai", "ollama"]
    else:
        providers = [p.strip() for p in args.providers.split(",")]

    config = BenchmarkConfig(
        providers=providers,
        iterations_per_test=args.iterations,
        log_dir=args.log_dir,
        quick_mode=args.quick
    )

    benchmark = LLMBenchmark(config)
    success = benchmark.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
