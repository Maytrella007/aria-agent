#!/usr/bin/env python3
"""
ARIA Marathon Analyzer
======================
Analyzes ARIA's cognitive activity during marathon memory tests.

This script examines:
- Memory content and emotional patterns
- Consolidation effectiveness
- DMN (Default Mode Network) activity
- Mind wandering insights
- Cognitive growth over time

Author: ARIA Development Team
Version: 1.0.0
"""

import os
import sys
import yaml
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

# Configurar rutas del proyecto
SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class MemoryRecord:
    """Representa un registro de memoria del maratón."""
    id: str
    content_preview: str
    full_content: Optional[str] = None
    emotion: str = "neutral"
    importance: float = 0.5
    timestamp: str = ""
    consolidated: bool = False
    strength: float = 0.0
    consolidation_count: int = 0


@dataclass
class WanderingEpisode:
    """Representa un episodio de mind wandering."""
    starting_thought: str
    ending_thought: str
    chain_length: int
    depth: str
    duration_ms: float
    insights_count: int
    memories_activated: int
    type: str
    timestamp: str


@dataclass
class DMNActivation:
    """Representa una activación del Default Mode Network."""
    mode: str
    duration_ms: float
    insights_count: int
    memories_accessed: int
    mpfc_activity: float
    pcc_activity: float
    precuneus_activity: float
    timestamp: str


@dataclass
class ConsolidationCycle:
    """Representa un ciclo de consolidación de memoria."""
    memories_processed: int
    memories_strengthened: int
    connections: int
    stats_before: Dict[str, Any]
    stats_after: Dict[str, Any]
    timestamp: str


class MarathonAnalyzer:
    """Analiza los resultados del maratón de memoria de ARIA."""

    def __init__(self, logs_dir: Path, db_path: Optional[Path] = None, verbose: bool = False):
        self.logs_dir = logs_dir
        self.db_path = db_path
        self.verbose = verbose

        # Datos extraídos
        self.memories: Dict[str, MemoryRecord] = {}
        self.wandering_episodes: List[WanderingEpisode] = []
        self.dmn_activations: List[DMNActivation] = []
        self.consolidation_cycles: List[ConsolidationCycle] = []
        self.hourly_stats: Dict[int, Dict] = {}
        self.events: List[Dict] = []
        self.errors: List[str] = []

        # Métricas agregadas
        self.emotion_counts: Counter = Counter()
        self.importance_distribution: List[float] = []
        self.insights_timeline: List[Tuple[str, int]] = []

    def load_yaml_logs(self) -> int:
        """Carga todos los archivos YAML de logs."""
        yaml_files = sorted(self.logs_dir.glob("marathon_log_*.yaml"))
        total_events = 0

        if self.verbose:
            print(f"\n[INFO] Encontrados {len(yaml_files)} archivos de log YAML")

        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)

                if data and 'events' in data:
                    events = data['events']
                    total_events += len(events)
                    self._process_events(events)

                    if self.verbose:
                        print(f"  - {yaml_file.name}: {len(events)} eventos")

            except Exception as e:
                self.errors.append(f"Error leyendo {yaml_file.name}: {e}")

        return total_events

    def _process_events(self, events: List[Dict]):
        """Procesa eventos del log YAML."""
        for event in events:
            event_type = event.get('event_type', '')
            details = event.get('details', {})
            timestamp = event.get('timestamp', '')

            # Guardar todos los eventos
            self.events.append(event)

            # Procesar por tipo
            if event_type == 'memory_created':
                self._process_memory_created(details, timestamp)
            elif event_type == 'wandering_episode':
                self._process_wandering(details, timestamp)
            elif event_type == 'dmn_activation':
                self._process_dmn(details, timestamp)
            elif event_type == 'consolidation_complete':
                self._process_consolidation(details, timestamp)
            elif event_type == 'hourly_report':
                self._process_hourly(details)

    def _process_memory_created(self, details: Dict, timestamp: str):
        """Procesa un evento de creación de memoria."""
        memory_id = details.get('id', '')
        if memory_id and memory_id not in self.memories:
            self.memories[memory_id] = MemoryRecord(
                id=memory_id,
                content_preview=details.get('content_preview', ''),
                emotion=details.get('emotion', 'neutral'),
                importance=details.get('importance', 0.5),
                timestamp=timestamp
            )
            self.emotion_counts[details.get('emotion', 'neutral')] += 1
            self.importance_distribution.append(details.get('importance', 0.5))

    def _process_wandering(self, details: Dict, timestamp: str):
        """Procesa un episodio de mind wandering."""
        episode = WanderingEpisode(
            starting_thought=details.get('starting_thought', ''),
            ending_thought=details.get('ending_thought', ''),
            chain_length=details.get('chain_length', 0),
            depth=details.get('depth', 'shallow'),
            duration_ms=details.get('duration_ms', 0),
            insights_count=details.get('insights_count', 0),
            memories_activated=details.get('memories_activated', 0),
            type=details.get('type', 'spontaneous'),
            timestamp=timestamp
        )
        self.wandering_episodes.append(episode)

        if episode.insights_count > 0:
            self.insights_timeline.append((timestamp, episode.insights_count))

    def _process_dmn(self, details: Dict, timestamp: str):
        """Procesa una activación del DMN."""
        activation = DMNActivation(
            mode=details.get('mode', ''),
            duration_ms=details.get('duration_ms', 0),
            insights_count=details.get('insights_count', 0),
            memories_accessed=details.get('memories_accessed', 0),
            mpfc_activity=details.get('mpfc_activity', 0),
            pcc_activity=details.get('pcc_activity', 0),
            precuneus_activity=details.get('precuneus_activity', 0),
            timestamp=timestamp
        )
        self.dmn_activations.append(activation)

        if activation.insights_count > 0:
            self.insights_timeline.append((timestamp, activation.insights_count))

    def _process_consolidation(self, details: Dict, timestamp: str):
        """Procesa un ciclo de consolidación."""
        cycle = ConsolidationCycle(
            memories_processed=details.get('memories_processed', 0),
            memories_strengthened=details.get('memories_strengthened', 0),
            connections=details.get('connections', 0),
            stats_before=details.get('stats_before', {}),
            stats_after=details.get('stats_after', {}),
            timestamp=timestamp
        )
        self.consolidation_cycles.append(cycle)

    def _process_hourly(self, details: Dict):
        """Procesa un reporte por hora."""
        hour = details.get('hour', 0)
        self.hourly_stats[hour] = details

    def load_memory_database(self) -> int:
        """Carga contenido completo de memorias desde la base de datos."""
        if not self.db_path or not self.db_path.exists():
            if self.verbose:
                print("[WARN] Base de datos de memorias no encontrada")
            return 0

        enriched = 0
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Obtener todas las memorias
            cursor.execute("""
                SELECT id, content, emotional_tone, importance, consolidated,
                       memory_strength, consolidation_count
                FROM memories
            """)

            for row in cursor.fetchall():
                mem_id = row[0]
                if mem_id in self.memories:
                    self.memories[mem_id].full_content = row[1]
                    self.memories[mem_id].consolidated = bool(row[4]) if row[4] else False
                    self.memories[mem_id].strength = row[5] if row[5] else 0.0
                    self.memories[mem_id].consolidation_count = row[6] if row[6] else 0
                    enriched += 1
                else:
                    # Memoria en DB pero no en logs
                    self.memories[mem_id] = MemoryRecord(
                        id=mem_id,
                        content_preview=row[1][:50] if row[1] else '',
                        full_content=row[1],
                        emotion=row[2] if row[2] else 'neutral',
                        importance=row[3] if row[3] else 0.5,
                        consolidated=bool(row[4]) if row[4] else False,
                        strength=row[5] if row[5] else 0.0,
                        consolidation_count=row[6] if row[6] else 0
                    )

            conn.close()

            if self.verbose:
                print(f"[INFO] Enriquecidas {enriched} memorias desde la base de datos")

        except Exception as e:
            self.errors.append(f"Error leyendo base de datos: {e}")

        return enriched

    def analyze(self) -> Dict[str, Any]:
        """Realiza el análisis completo."""
        analysis = {
            'summary': self._generate_summary(),
            'emotional_analysis': self._analyze_emotions(),
            'cognitive_patterns': self._analyze_cognitive_patterns(),
            'memory_quality': self._analyze_memory_quality(),
            'consolidation_effectiveness': self._analyze_consolidation(),
            'mind_wandering_analysis': self._analyze_wandering(),
            'dmn_analysis': self._analyze_dmn(),
            'temporal_patterns': self._analyze_temporal(),
            'insights': self._extract_key_insights(),
            'sample_memories': self._get_sample_memories(),
            'sample_thoughts': self._get_sample_thoughts()
        }
        return analysis

    def _generate_summary(self) -> Dict:
        """Genera resumen ejecutivo."""
        return {
            'total_memories': len(self.memories),
            'total_events': len(self.events),
            'wandering_episodes': len(self.wandering_episodes),
            'dmn_activations': len(self.dmn_activations),
            'consolidation_cycles': len(self.consolidation_cycles),
            'total_insights': sum(e.insights_count for e in self.wandering_episodes) +
                            sum(a.insights_count for a in self.dmn_activations),
            'unique_emotions': len(self.emotion_counts),
            'errors_encountered': len(self.errors)
        }

    def _analyze_emotions(self) -> Dict:
        """Analiza patrones emocionales."""
        if not self.emotion_counts:
            return {'message': 'No se encontraron datos emocionales'}

        total = sum(self.emotion_counts.values())
        return {
            'distribution': dict(self.emotion_counts.most_common()),
            'percentages': {
                emotion: round(count/total*100, 1)
                for emotion, count in self.emotion_counts.most_common()
            },
            'dominant_emotion': self.emotion_counts.most_common(1)[0] if self.emotion_counts else ('neutral', 0),
            'emotional_diversity': len(self.emotion_counts)
        }

    def _analyze_cognitive_patterns(self) -> Dict:
        """Analiza patrones cognitivos."""
        if not self.wandering_episodes:
            return {'message': 'No se encontraron episodios de mind wandering'}

        depths = Counter(e.depth for e in self.wandering_episodes)
        types = Counter(e.type for e in self.wandering_episodes)

        avg_chain = sum(e.chain_length for e in self.wandering_episodes) / len(self.wandering_episodes)
        avg_duration = sum(e.duration_ms for e in self.wandering_episodes) / len(self.wandering_episodes)

        return {
            'wandering_depth_distribution': dict(depths),
            'wandering_type_distribution': dict(types),
            'average_thought_chain_length': round(avg_chain, 2),
            'average_wandering_duration_ms': round(avg_duration, 2),
            'total_thoughts_generated': sum(e.chain_length for e in self.wandering_episodes),
            'memories_activated_by_wandering': sum(e.memories_activated for e in self.wandering_episodes)
        }

    def _analyze_memory_quality(self) -> Dict:
        """Analiza calidad de memorias."""
        if not self.importance_distribution:
            return {'message': 'No hay datos de importancia'}

        avg_importance = sum(self.importance_distribution) / len(self.importance_distribution)

        # Clasificar por importancia
        low = sum(1 for i in self.importance_distribution if i < 0.3)
        medium = sum(1 for i in self.importance_distribution if 0.3 <= i < 0.7)
        high = sum(1 for i in self.importance_distribution if i >= 0.7)

        # Analizar consolidación
        consolidated = sum(1 for m in self.memories.values() if m.consolidated)
        strong = sum(1 for m in self.memories.values() if m.strength >= 0.7)

        return {
            'average_importance': round(avg_importance, 3),
            'importance_distribution': {
                'low (<0.3)': low,
                'medium (0.3-0.7)': medium,
                'high (>=0.7)': high
            },
            'consolidated_memories': consolidated,
            'strong_memories': strong,
            'consolidation_rate': round(consolidated/len(self.memories)*100, 1) if self.memories else 0
        }

    def _analyze_consolidation(self) -> Dict:
        """Analiza efectividad de consolidación."""
        if not self.consolidation_cycles:
            return {'message': 'No se encontraron ciclos de consolidación'}

        total_processed = sum(c.memories_processed for c in self.consolidation_cycles)
        total_strengthened = sum(c.memories_strengthened for c in self.consolidation_cycles)
        total_connections = sum(c.connections for c in self.consolidation_cycles)

        # Comparar antes/después del último ciclo
        last_cycle = self.consolidation_cycles[-1]

        return {
            'total_cycles': len(self.consolidation_cycles),
            'total_memories_processed': total_processed,
            'total_memories_strengthened': total_strengthened,
            'total_connections_formed': total_connections,
            'avg_processed_per_cycle': round(total_processed/len(self.consolidation_cycles), 1),
            'final_stats': last_cycle.stats_after if last_cycle.stats_after else {}
        }

    def _analyze_wandering(self) -> Dict:
        """Analiza mind wandering en detalle."""
        if not self.wandering_episodes:
            return {'message': 'No hay episodios de mind wandering'}

        insightful = [e for e in self.wandering_episodes if e.insights_count > 0]
        deep = [e for e in self.wandering_episodes if e.depth == 'deep']

        return {
            'total_episodes': len(self.wandering_episodes),
            'insightful_episodes': len(insightful),
            'deep_episodes': len(deep),
            'insight_rate': round(len(insightful)/len(self.wandering_episodes)*100, 1),
            'total_insights_from_wandering': sum(e.insights_count for e in self.wandering_episodes),
            'most_productive_type': Counter(e.type for e in insightful).most_common(1)[0] if insightful else ('N/A', 0)
        }

    def _analyze_dmn(self) -> Dict:
        """Analiza actividad del DMN."""
        if not self.dmn_activations:
            return {'message': 'No hay activaciones DMN'}

        modes = Counter(a.mode for a in self.dmn_activations)
        avg_duration = sum(a.duration_ms for a in self.dmn_activations) / len(self.dmn_activations)
        avg_pcc = sum(a.pcc_activity for a in self.dmn_activations) / len(self.dmn_activations)
        avg_mpfc = sum(a.mpfc_activity for a in self.dmn_activations) / len(self.dmn_activations)
        avg_precuneus = sum(a.precuneus_activity for a in self.dmn_activations) / len(self.dmn_activations)

        return {
            'total_activations': len(self.dmn_activations),
            'modes_distribution': dict(modes),
            'average_duration_ms': round(avg_duration, 2),
            'total_insights_from_dmn': sum(a.insights_count for a in self.dmn_activations),
            'brain_region_activity': {
                'PCC (posterior cingulate)': round(avg_pcc, 3),
                'mPFC (medial prefrontal)': round(avg_mpfc, 3),
                'Precuneus': round(avg_precuneus, 3)
            }
        }

    def _analyze_temporal(self) -> Dict:
        """Analiza patrones temporales."""
        if not self.hourly_stats:
            return {'message': 'No hay estadísticas por hora'}

        # Encontrar hora más productiva
        most_memories = max(self.hourly_stats.items(),
                          key=lambda x: x[1].get('memories_created', 0)) if self.hourly_stats else (0, {})

        return {
            'hours_tracked': len(self.hourly_stats),
            'most_productive_hour': most_memories[0],
            'hourly_memory_creation': {
                h: stats.get('memories_created', 0)
                for h, stats in sorted(self.hourly_stats.items())
            },
            'hourly_recall_accuracy': {
                h: round(stats.get('recall_accuracy', 0)*100, 1)
                for h, stats in sorted(self.hourly_stats.items())
            }
        }

    def _extract_key_insights(self) -> List[str]:
        """Extrae insights clave del análisis."""
        insights = []

        # Insight sobre volumen
        if len(self.memories) > 0:
            insights.append(f"ARIA creó {len(self.memories)} memorias únicas durante el maratón")

        # Insight sobre emociones
        if self.emotion_counts:
            top_emotion = self.emotion_counts.most_common(1)[0]
            insights.append(f"La emoción dominante fue '{top_emotion[0]}' ({top_emotion[1]} memorias)")

        # Insight sobre profundidad cognitiva
        if self.wandering_episodes:
            deep = sum(1 for e in self.wandering_episodes if e.depth == 'deep')
            if deep > 0:
                insights.append(f"Se alcanzó estado de 'deep wandering' {deep} veces")

        # Insight sobre consolidación
        if self.consolidation_cycles:
            strengthened = sum(c.memories_strengthened for c in self.consolidation_cycles)
            insights.append(f"El sistema consolidó y fortaleció {strengthened} memorias")

        # Insight sobre insights
        total_insights = (sum(e.insights_count for e in self.wandering_episodes) +
                         sum(a.insights_count for a in self.dmn_activations))
        if total_insights > 0:
            insights.append(f"Se generaron {total_insights} insights durante la actividad autónoma")

        return insights

    def _get_sample_memories(self, n: int = 10) -> List[Dict]:
        """Obtiene muestra de memorias para análisis cualitativo."""
        samples = []

        # Ordenar por importancia (descendente)
        sorted_memories = sorted(
            self.memories.values(),
            key=lambda m: m.importance,
            reverse=True
        )

        for mem in sorted_memories[:n]:
            samples.append({
                'id': mem.id[:16],
                'emotion': mem.emotion,
                'importance': round(mem.importance, 3),
                'content': mem.full_content or mem.content_preview,
                'consolidated': mem.consolidated,
                'strength': round(mem.strength, 3)
            })

        return samples

    def _get_sample_thoughts(self) -> List[Dict]:
        """Obtiene muestra de pensamientos del mind wandering."""
        thoughts = []

        for episode in self.wandering_episodes[:10]:
            thoughts.append({
                'starting': episode.starting_thought,
                'ending': episode.ending_thought,
                'chain_length': episode.chain_length,
                'depth': episode.depth,
                'insights': episode.insights_count
            })

        return thoughts

    def generate_report(self, analysis: Dict, output_path: Optional[Path] = None) -> str:
        """Genera reporte en formato Markdown."""
        report = []
        report.append("# ARIA Marathon Analysis Report")
        report.append(f"\nGenerated: {datetime.now().isoformat()}\n")

        # Resumen Ejecutivo
        report.append("## Executive Summary")
        report.append("")
        summary = analysis['summary']
        report.append(f"| Metric | Value |")
        report.append(f"|--------|-------|")
        report.append(f"| Total Memories Created | {summary['total_memories']} |")
        report.append(f"| Total Events Processed | {summary['total_events']} |")
        report.append(f"| Mind Wandering Episodes | {summary['wandering_episodes']} |")
        report.append(f"| DMN Activations | {summary['dmn_activations']} |")
        report.append(f"| Consolidation Cycles | {summary['consolidation_cycles']} |")
        report.append(f"| Total Insights Generated | {summary['total_insights']} |")
        report.append(f"| Unique Emotions | {summary['unique_emotions']} |")
        report.append("")

        # Key Insights
        report.append("## Key Insights")
        report.append("")
        for insight in analysis['insights']:
            report.append(f"- {insight}")
        report.append("")

        # Análisis Emocional
        report.append("## Emotional Analysis")
        report.append("")
        emotions = analysis['emotional_analysis']
        if 'distribution' in emotions:
            report.append("### Emotion Distribution")
            report.append("")
            report.append("| Emotion | Count | Percentage |")
            report.append("|---------|-------|------------|")
            for emotion, count in emotions['distribution'].items():
                pct = emotions['percentages'].get(emotion, 0)
                report.append(f"| {emotion} | {count} | {pct}% |")
            report.append("")

        # Patrones Cognitivos
        report.append("## Cognitive Patterns")
        report.append("")
        cognitive = analysis['cognitive_patterns']
        if 'total_thoughts_generated' in cognitive:
            report.append(f"- **Total thoughts generated**: {cognitive['total_thoughts_generated']}")
            report.append(f"- **Average thought chain length**: {cognitive['average_thought_chain_length']}")
            report.append(f"- **Average wandering duration**: {cognitive['average_wandering_duration_ms']}ms")
            report.append(f"- **Memories activated by wandering**: {cognitive['memories_activated_by_wandering']}")
            report.append("")

        # Análisis de Mind Wandering
        report.append("## Mind Wandering Analysis")
        report.append("")
        wandering = analysis['mind_wandering_analysis']
        if 'total_episodes' in wandering:
            report.append(f"- Total episodes: {wandering['total_episodes']}")
            report.append(f"- Insightful episodes: {wandering['insightful_episodes']}")
            report.append(f"- Deep episodes: {wandering['deep_episodes']}")
            report.append(f"- Insight rate: {wandering['insight_rate']}%")
            report.append("")

        # Análisis DMN
        report.append("## Default Mode Network Analysis")
        report.append("")
        dmn = analysis['dmn_analysis']
        if 'total_activations' in dmn:
            report.append(f"- Total activations: {dmn['total_activations']}")
            report.append(f"- Average duration: {dmn['average_duration_ms']}ms")
            report.append(f"- Total insights from DMN: {dmn['total_insights_from_dmn']}")
            report.append("")
            report.append("### Brain Region Activity (Simulated)")
            report.append("")
            for region, activity in dmn['brain_region_activity'].items():
                report.append(f"- {region}: {activity}")
            report.append("")

        # Calidad de Memorias
        report.append("## Memory Quality")
        report.append("")
        quality = analysis['memory_quality']
        if 'average_importance' in quality:
            report.append(f"- Average importance: {quality['average_importance']}")
            report.append(f"- Consolidated memories: {quality['consolidated_memories']}")
            report.append(f"- Strong memories: {quality['strong_memories']}")
            report.append(f"- Consolidation rate: {quality['consolidation_rate']}%")
            report.append("")
            report.append("### Importance Distribution")
            report.append("")
            for level, count in quality['importance_distribution'].items():
                report.append(f"- {level}: {count} memories")
            report.append("")

        # Efectividad de Consolidación
        report.append("## Consolidation Effectiveness")
        report.append("")
        consolidation = analysis['consolidation_effectiveness']
        if 'total_cycles' in consolidation:
            report.append(f"- Total cycles: {consolidation['total_cycles']}")
            report.append(f"- Memories processed: {consolidation['total_memories_processed']}")
            report.append(f"- Memories strengthened: {consolidation['total_memories_strengthened']}")
            report.append(f"- Connections formed: {consolidation['total_connections_formed']}")
            report.append("")

        # Sample Memories
        report.append("## Sample Memories (Top by Importance)")
        report.append("")
        for i, mem in enumerate(analysis['sample_memories'][:5], 1):
            report.append(f"### Memory {i}")
            report.append(f"- **ID**: {mem['id']}")
            report.append(f"- **Emotion**: {mem['emotion']}")
            report.append(f"- **Importance**: {mem['importance']}")
            report.append(f"- **Consolidated**: {mem['consolidated']}")
            report.append(f"- **Content**: {mem['content'][:200]}...")
            report.append("")

        # Sample Thoughts
        report.append("## Sample Mind Wandering Thoughts")
        report.append("")
        for i, thought in enumerate(analysis['sample_thoughts'][:5], 1):
            report.append(f"### Thought Chain {i}")
            report.append(f"- **Starting**: \"{thought['starting']}\"")
            report.append(f"- **Ending**: \"{thought['ending']}\"")
            report.append(f"- **Chain length**: {thought['chain_length']}")
            report.append(f"- **Depth**: {thought['depth']}")
            report.append(f"- **Insights**: {thought['insights']}")
            report.append("")

        # Footer
        report.append("---")
        report.append("*Generated by ARIA Marathon Analyzer v1.0*")

        report_text = '\n'.join(report)

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_text)

        return report_text


def main():
    parser = argparse.ArgumentParser(
        description='Analyze ARIA marathon test results',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python marathon_analyzer.py --logs-dir logs/marathon
  python marathon_analyzer.py --logs-dir logs/marathon --db data/memories.db --output analysis.md
  python marathon_analyzer.py --logs-dir logs/marathon --verbose
        """
    )

    parser.add_argument(
        '--logs-dir', '-l',
        type=str,
        default='logs/marathon',
        help='Directory containing marathon log files (default: logs/marathon)'
    )

    parser.add_argument(
        '--db', '-d',
        type=str,
        default='data/memories_v2/experiences.db',
        help='Path to memories database (default: data/memories_v2/experiences.db)'
    )

    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file for analysis report (optional, prints to stdout if not specified)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    parser.add_argument(
        '--json',
        action='store_true',
        help='Output analysis as JSON instead of Markdown'
    )

    args = parser.parse_args()

    # Resolver rutas
    logs_dir = Path(args.logs_dir)
    if not logs_dir.is_absolute():
        logs_dir = PROJECT_ROOT / logs_dir

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    output_path = Path(args.output) if args.output else None
    if output_path and not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    # Verificar que existe el directorio de logs
    if not logs_dir.exists():
        print(f"[ERROR] Logs directory not found: {logs_dir}")
        sys.exit(1)

    print("=" * 60)
    print("ARIA Marathon Analyzer v1.0")
    print("=" * 60)
    print(f"\nLogs directory: {logs_dir}")
    print(f"Database path: {db_path}")
    print(f"Output: {output_path or 'stdout'}")
    print()

    # Crear analizador
    analyzer = MarathonAnalyzer(
        logs_dir=logs_dir,
        db_path=db_path if db_path.exists() else None,
        verbose=args.verbose
    )

    # Cargar datos
    print("[1/3] Loading YAML logs...")
    events = analyzer.load_yaml_logs()
    print(f"      Loaded {events} events")

    print("[2/3] Loading memory database...")
    enriched = analyzer.load_memory_database()
    print(f"      Enriched {enriched} memories")

    # Realizar análisis
    print("[3/3] Analyzing data...")
    analysis = analyzer.analyze()
    print(f"      Analysis complete")
    print()

    # Generar salida
    if args.json:
        import json
        output = json.dumps(analysis, indent=2, ensure_ascii=False, default=str)
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output)
        else:
            print(output)
    else:
        report = analyzer.generate_report(analysis, output_path)
        if not output_path:
            print(report)
        else:
            print(f"[OK] Report saved to: {output_path}")

    # Mostrar errores si hay
    if analyzer.errors:
        print("\n[WARNINGS]")
        for error in analyzer.errors:
            print(f"  - {error}")

    print("\n[DONE] Analysis complete!")


if __name__ == '__main__':
    main()
