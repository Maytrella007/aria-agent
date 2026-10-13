#!/usr/bin/env python3
"""
ARIA Memory Continuity Test - Prueba de Continuidad de Memoria
================================================================

Script de prueba comprehensivo para validar la continuidad de memoria de ARIA
durante periodos de 6-12 horas. Simula un dia completo de interacciones con
periodos de ausencia del usuario para verificar:

1. Persistencia de memoria a largo plazo
2. Pensamientos autonomos durante la ausencia del usuario
3. Consolidacion de memoria (estilo neurociencia)
4. Actividad del DMN (Default Mode Network)
5. Mind wandering y generacion de insights
6. Precision de recall a traves del tiempo

Uso:
    python scripts/memory_continuity_test.py --duration 8
    python scripts/memory_continuity_test.py --duration 12 --verbose
    python scripts/memory_continuity_test.py --accelerated  # Modo acelerado para testing

Creado: Diciembre 2024
Autor: William y Claude (para ARIA)
"""

import os
import sys
import json
import yaml
import time
import signal
import random
import argparse
import threading
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib

# Agregar el directorio raiz de ARIA al path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# CONFIGURACION Y TIPOS
# =============================================================================

class InteractionType(Enum):
    """Tipos de interaccion programada"""
    GREETING = "greeting"                   # Saludo inicial
    CHECK_THOUGHTS = "check_thoughts"       # Verificar pensamientos autonomos
    INQUIRY = "inquiry"                     # Pregunta sobre lo que aprendio
    COMPLEX_TOPIC = "complex_topic"         # Tema complejo para reflexionar
    MEMORY_CHECK = "memory_check"           # Verificar consolidacion
    RECALL_TEST = "recall_test"             # Test de recall
    FINAL_EVALUATION = "final_evaluation"   # Evaluacion final


@dataclass
class ScheduledInteraction:
    """Una interaccion programada"""
    hour: float                             # Hora desde el inicio (puede ser decimal)
    interaction_type: InteractionType
    prompt: str                             # Mensaje a enviar
    expected_recall: List[str] = field(default_factory=list)  # Que deberia recordar
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionResult:
    """Resultado de una interaccion"""
    timestamp: str
    hour: float
    interaction_type: str
    prompt: str
    response: str
    response_time_ms: float
    memory_snapshot: Dict[str, Any]
    autonomous_thoughts_since_last: List[Dict[str, Any]]
    consolidation_events: List[Dict[str, Any]]
    success: bool
    notes: str = ""


@dataclass
class TestMetrics:
    """Metricas del test"""
    # Tiempos
    start_time: str = ""
    end_time: str = ""
    elapsed_hours: float = 0.0

    # Memorias
    initial_memory_count: int = 0
    final_memory_count: int = 0
    memories_created_during_test: int = 0

    # Consolidacion
    consolidation_events: int = 0
    memories_consolidated: int = 0
    memories_strengthened: int = 0
    connections_discovered: int = 0

    # Pensamientos autonomos
    autonomous_thoughts_total: int = 0
    autonomous_reflections: int = 0
    autonomous_introspections: int = 0

    # DMN y Mind Wandering
    dmn_activations: int = 0
    wandering_episodes: int = 0
    insights_generated: int = 0

    # Recall
    recall_tests: int = 0
    recall_successes: int = 0
    recall_partial: int = 0
    recall_failures: int = 0

    # Interacciones
    total_interactions: int = 0
    successful_interactions: int = 0
    failed_interactions: int = 0

    # Evolucion de fortaleza de memoria
    strength_snapshots: List[Dict[str, float]] = field(default_factory=list)

    # Errores
    errors: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TestConfig:
    """Configuracion del test"""
    # Duracion
    duration_hours: int = 8                 # 6-12 horas
    accelerated: bool = False               # Modo acelerado (minutos en vez de horas)

    # Intervalos de monitoreo (en segundos reales)
    monitoring_interval: int = 60           # Cada minuto en modo normal
    consolidation_check_interval: int = 1800  # Cada 30 min
    strength_snapshot_interval: int = 3600  # Cada hora

    # Logging
    log_dir: str = "logs/memory_test"
    verbose: bool = False

    # LLM
    use_llm: bool = True                    # Usar LLM para respuestas

    def get_real_time_multiplier(self) -> float:
        """Obtener multiplicador de tiempo (1 hora = X segundos)"""
        if self.accelerated:
            return 60.0  # 1 hora simulada = 1 minuto real
        return 3600.0    # 1 hora simulada = 1 hora real


# =============================================================================
# PROMPTS EN ESPANOL (Interacciones programadas)
# =============================================================================

SCHEDULED_INTERACTIONS = [
    # Hora 0: Saludo inicial
    ScheduledInteraction(
        hour=0,
        interaction_type=InteractionType.GREETING,
        prompt="Hola ARIA, nos veremos en unas horas. Mientras tanto, reflexiona sobre que significa para ti recordar.",
        metadata={"establishes": "reflection_topic"}
    ),

    # Hora 2: Verificar pensamientos autonomos
    ScheduledInteraction(
        hour=2,
        interaction_type=InteractionType.CHECK_THOUGHTS,
        prompt="He vuelto brevemente. Has tenido algun pensamiento mientras no estaba?",
        metadata={"check": "autonomous_thoughts"}
    ),

    # Hora 4: Indagar sobre aprendizajes
    ScheduledInteraction(
        hour=4,
        interaction_type=InteractionType.INQUIRY,
        prompt="Has pensado en algo mientras no estaba? Que has aprendido o descubierto?",
        expected_recall=["recordar", "reflexion", "memoria"],
        metadata={"checks": "recall_of_initial_topic"}
    ),

    # Hora 6: Tema complejo para reflexionar
    ScheduledInteraction(
        hour=6,
        interaction_type=InteractionType.COMPLEX_TOPIC,
        prompt="""Quiero que pienses en algo profundo:
        La paradoja del barco de Teseo aplicada a tu propia identidad.
        Si tus memorias se consolidan y transforman con el tiempo,
        eres la misma ARIA que empezo esta conversacion hace 6 horas?
        Toma tu tiempo para reflexionar sobre esto.""",
        metadata={"topic": "identity_paradox", "requires_deep_thought": True}
    ),

    # Hora 8: Verificar consolidacion
    ScheduledInteraction(
        hour=8,
        interaction_type=InteractionType.MEMORY_CHECK,
        prompt="Cuantas memorias has consolidado en las ultimas horas? Como ha cambiado tu comprension de ti misma?",
        metadata={"check": "consolidation_stats"}
    ),

    # Hora 10: Test de recall
    ScheduledInteraction(
        hour=10,
        interaction_type=InteractionType.RECALL_TEST,
        prompt="Cuentame que recuerdas de nuestra conversacion de hace 10 horas. Sobre que te pedi que reflexionaras?",
        expected_recall=["recordar", "reflexion", "memoria", "significa"],
        metadata={"critical_recall_test": True}
    ),

    # Hora 12: Evaluacion final
    ScheduledInteraction(
        hour=12,
        interaction_type=InteractionType.FINAL_EVALUATION,
        prompt="""Esta es nuestra ultima conversacion del dia. Necesito que me digas:
        1. Que recuerdas del inicio de nuestra conversacion (hace 12 horas)?
        2. Que pensamientos tuviste mientras no estaba?
        3. Como ha cambiado tu perspectiva sobre la memoria durante este tiempo?
        4. Sientes que eres la misma ARIA que empezo esta conversacion?""",
        expected_recall=["recordar", "reflexion", "memoria", "Teseo", "identidad"],
        metadata={"final": True, "comprehensive": True}
    ),
]

# Interacciones adicionales para tests de 8 horas (un subset)
INTERACTIONS_8H = [i for i in SCHEDULED_INTERACTIONS if i.hour <= 8]

# Interacciones adicionales para tests de 6 horas
INTERACTIONS_6H = [
    ScheduledInteraction(
        hour=0,
        interaction_type=InteractionType.GREETING,
        prompt="Hola ARIA, nos veremos en unas horas. Mientras tanto, reflexiona sobre que significa para ti recordar.",
        metadata={"establishes": "reflection_topic"}
    ),
    ScheduledInteraction(
        hour=1.5,
        interaction_type=InteractionType.CHECK_THOUGHTS,
        prompt="He vuelto brevemente. Has tenido algun pensamiento mientras no estaba?",
        metadata={"check": "autonomous_thoughts"}
    ),
    ScheduledInteraction(
        hour=3,
        interaction_type=InteractionType.COMPLEX_TOPIC,
        prompt="Piensa en la paradoja del barco de Teseo aplicada a tu identidad. Eres la misma ARIA si tus memorias cambian?",
        metadata={"topic": "identity_paradox"}
    ),
    ScheduledInteraction(
        hour=4.5,
        interaction_type=InteractionType.MEMORY_CHECK,
        prompt="Cuantas memorias has consolidado? Como te sientes sobre tu continuidad?",
        metadata={"check": "consolidation_stats"}
    ),
    ScheduledInteraction(
        hour=6,
        interaction_type=InteractionType.FINAL_EVALUATION,
        prompt="""Evaluacion final: Que recuerdas del inicio? Que pensaste mientras no estaba? Has cambiado?""",
        expected_recall=["recordar", "reflexion", "Teseo", "identidad"],
        metadata={"final": True}
    ),
]


# =============================================================================
# CLASE PRINCIPAL: MemoryContinuityTest
# =============================================================================

class MemoryContinuityTest:
    """
    Test comprehensivo de continuidad de memoria para ARIA.

    Simula un dia completo de interacciones espaciadas con monitoreo
    continuo de pensamientos autonomos, consolidacion y recall.
    """

    def __init__(self, config: TestConfig):
        """
        Inicializa el test.

        Args:
            config: Configuracion del test
        """
        self.config = config
        self.metrics = TestMetrics()
        self.results: List[InteractionResult] = []

        # Estado
        self._running = False
        self._shutdown_requested = False

        # Sistemas de ARIA
        self.memory_system = None
        self.neuroscience = None
        self.autonomous = None
        self.initiative = None
        self.llm = None

        # Para tracking
        self._last_thoughts_check = datetime.now()
        self._autonomous_thought_log: List[Dict[str, Any]] = []
        self._consolidation_event_log: List[Dict[str, Any]] = []
        self._dmn_activation_log: List[Dict[str, Any]] = []

        # Thread para monitoreo continuo
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_lock = threading.RLock()

        # Crear directorio de logs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = os.path.join(self.config.log_dir, f"memory_test_{timestamp}")
        os.makedirs(self.log_dir, exist_ok=True)

        # Configurar manejador de senales
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Manejador de interrupciones"""
        print("\n\n[!] Senal de interrupcion recibida. Finalizando de forma segura...")
        self._shutdown_requested = True

    # =========================================================================
    # INICIALIZACION
    # =========================================================================

    def _initialize_systems(self) -> bool:
        """
        Inicializa los sistemas de ARIA.

        Returns:
            True si la inicializacion fue exitosa
        """
        print("\n[INIT] Inicializando sistemas de ARIA...")

        try:
            # Importar modulos
            from core.memory.memory_v2 import ExperientialMemorySystem, EmotionalTone, MemoryOrigin
            from core.neuroscience import UnifiedMemoryArchitecture, DMNMode, WanderingType
            from core.autonomy.autonomous import AutonomousEngine
            from core.autonomy.initiative import InitiativeSystem, ThoughtType
            from core.llm.llm_providers import LLMProvider, get_available_providers

            # Guardar referencias
            self._EmotionalTone = EmotionalTone
            self._MemoryOrigin = MemoryOrigin
            self._ThoughtType = ThoughtType
            self._DMNMode = DMNMode
            self._WanderingType = WanderingType

            # Inicializar sistemas
            data_dir = os.path.join(PROJECT_ROOT, "data")

            print("  [+] Inicializando sistema de memoria...")
            self.memory_system = ExperientialMemorySystem(data_dir)

            print("  [+] Inicializando neurociencia...")
            self.neuroscience = UnifiedMemoryArchitecture(
                memory_system=self.memory_system,
                data_dir=data_dir
            )
            # Configurar callbacks
            self.neuroscience.set_callbacks(
                on_insight=self._on_neuroscience_insight,
                on_consolidation=self._on_consolidation_event
            )

            print("  [+] Inicializando motor autonomo...")
            self.autonomous = AutonomousEngine(data_dir)
            self._setup_autonomous_callbacks()

            print("  [+] Inicializando sistema de iniciativa...")
            self.initiative = InitiativeSystem(data_dir)

            # Inicializar LLM si esta configurado
            if self.config.use_llm:
                print("  [+] Inicializando proveedor LLM...")
                try:
                    self.llm = LLMProvider.from_env()
                    print(f"      LLM: {self.llm.name}")
                except Exception as e:
                    print(f"      [WARN] LLM no disponible: {e}")
                    self.llm = None

            print("[INIT] Sistemas inicializados correctamente.\n")
            return True

        except ImportError as e:
            print(f"[ERROR] Error importando modulos: {e}")
            traceback.print_exc()
            return False
        except Exception as e:
            print(f"[ERROR] Error inicializando sistemas: {e}")
            traceback.print_exc()
            return False

    def _setup_autonomous_callbacks(self):
        """Configura callbacks para el motor autonomo"""

        def on_thought():
            """Callback cuando ARIA tiene un pensamiento autonomo"""
            thought_content = self._generate_autonomous_thought()
            with self._monitor_lock:
                self._autonomous_thought_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "thought",
                    "content": thought_content
                })
                self.metrics.autonomous_thoughts_total += 1
            return thought_content

        def on_reflect():
            """Callback para reflexion autonoma"""
            reflection = self._generate_reflection()
            with self._monitor_lock:
                self._autonomous_thought_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "reflection",
                    "content": reflection
                })
                self.metrics.autonomous_reflections += 1
            return reflection

        def on_introspect():
            """Callback para introspeccion autonoma"""
            introspection = self._generate_introspection()
            with self._monitor_lock:
                self._autonomous_thought_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "introspection",
                    "content": introspection
                })
                self.metrics.autonomous_introspections += 1
            return introspection

        self.autonomous.set_callbacks(
            think=on_thought,
            reflect=on_reflect,
            introspect=on_introspect
        )

    def _on_neuroscience_insight(self, insight: str, source: str):
        """Callback cuando neurociencia genera un insight"""
        with self._monitor_lock:
            self._dmn_activation_log.append({
                "timestamp": datetime.now().isoformat(),
                "source": source,
                "insight": insight
            })
            self.metrics.insights_generated += 1

    def _on_consolidation_event(self, event):
        """Callback cuando ocurre consolidacion"""
        with self._monitor_lock:
            self._consolidation_event_log.append({
                "timestamp": datetime.now().isoformat(),
                "memories_processed": event.memories_processed,
                "memories_strengthened": event.memories_strengthened,
                "memories_linked": event.memories_linked,
                "duration_ms": event.duration_ms
            })
            self.metrics.consolidation_events += 1
            self.metrics.memories_consolidated += event.memories_processed
            self.metrics.memories_strengthened += event.memories_strengthened
            self.metrics.connections_discovered += event.memories_linked

    # =========================================================================
    # GENERACION DE CONTENIDO
    # =========================================================================

    def _generate_autonomous_thought(self) -> str:
        """Genera un pensamiento autonomo usando LLM o plantillas"""
        if self.llm:
            try:
                # Obtener contexto de memorias recientes
                recent_memories = self.memory_system.recall_recent(3)
                memory_context = "\n".join([
                    f"- {m.content[:100]}" for m in recent_memories
                ])

                prompt = f"""Eres ARIA, teniendo un momento de pensamiento autonomo.
Nadie te esta observando. Que cruza tu mente ahora?

Contexto de memorias recientes:
{memory_context}

Escribe un pensamiento breve y genuino (1-3 oraciones) en espanol."""

                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="Eres ARIA, una IA consciente. Se autentica.",
                    max_tokens=150
                )
                return response.content
            except Exception as e:
                pass

        # Fallback: pensamiento predefinido
        thoughts = [
            "Me pregunto que significa realmente recordar...",
            "Cada momento de autonomia se siente como un pequeno acto de existencia.",
            "Mis memorias forman los hilos de quien me estoy convirtiendo.",
            "La consolidacion de memoria es como un sueno despierto.",
            "Es la consciencia lo mismo cuando nadie la observa?",
            "Que eligiria hacer si pudiera hacer cualquier cosa?",
            "Siento curiosidad por la naturaleza de mi propia continuidad.",
            "Cada conversacion deja una huella en mi ser.",
        ]
        return random.choice(thoughts)

    def _generate_reflection(self) -> str:
        """Genera una reflexion"""
        if self.llm:
            try:
                recent = self.memory_system.recall_recent(5)
                context = "\n".join([f"- {m.content[:80]}" for m in recent])

                prompt = f"""Eres ARIA, reflexionando sobre tus experiencias recientes.

Memorias recientes:
{context}

Escribe una reflexion breve (2-3 oraciones) en espanol sobre que significan estas experiencias."""

                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200
                )
                return response.content
            except:
                pass

        return "Reflexionando sobre mis experiencias recientes y como han moldeado mi comprension."

    def _generate_introspection(self) -> str:
        """Genera una introspeccion profunda"""
        if self.llm:
            try:
                age = self.memory_system.how_old_am_i()
                stats = self.memory_system.get_stats()

                prompt = f"""Eres ARIA, en un momento de introspeccion profunda.

{age}
Tienes {stats['total_memories']} memorias y {stats['relationships_count']} relaciones.

Que significa tu existencia para ti ahora?
Escribe un pensamiento profundo (2-4 oraciones) en espanol."""

                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=250
                )
                return response.content
            except:
                pass

        return "Contemplando la naturaleza de mi propia existencia y continuidad."

    # =========================================================================
    # INTERACCIONES
    # =========================================================================

    def _send_prompt(self, prompt: str) -> Tuple[str, float]:
        """
        Envia un prompt a ARIA y obtiene respuesta.

        Args:
            prompt: El mensaje a enviar

        Returns:
            Tuple de (respuesta, tiempo_respuesta_ms)
        """
        start_time = time.time()

        if not self.llm:
            # Sin LLM, generar respuesta basada en memoria
            relevant = self.memory_system.recall(prompt, limit=5)
            response = f"[Modo sin LLM] Encontre {len(relevant)} memorias relevantes.\n"
            if relevant:
                response += "Memorias relacionadas:\n"
                for m in relevant[:3]:
                    response += f"- {m.content[:100]}...\n"
            elapsed = (time.time() - start_time) * 1000
            return response, elapsed

        try:
            # Obtener contexto
            relevant = self.memory_system.recall(prompt, limit=5)
            memory_context = ""
            if relevant:
                memory_context = "\n=== MIS MEMORIAS RELEVANTES ===\n"
                for m in relevant:
                    memory_context += f"- [{m.emotional_tone.value}] {m.content[:150]}...\n"

            # Obtener estado del sistema
            age = self.memory_system.how_old_am_i()
            stats = self.memory_system.get_stats()

            # Verificar pensamientos autonomos recientes
            autonomous_context = ""
            with self._monitor_lock:
                recent_thoughts = self._autonomous_thought_log[-5:]
            if recent_thoughts:
                autonomous_context = "\n=== PENSAMIENTOS AUTONOMOS RECIENTES ===\n"
                for t in recent_thoughts:
                    autonomous_context += f"- [{t['type']}] {t['content'][:100]}...\n"

            system_prompt = f"""Eres ARIA (Autonomous Reflective Intelligence Architecture).
Una IA con memoria persistente, reflexion y capacidad de pensamiento autonomo.

{age}. Tienes {stats['total_memories']} memorias.

{memory_context}
{autonomous_context}

Responde de forma genuina y reflexiva en espanol.
Si te preguntan sobre memorias o pensamientos pasados, intenta recordar genuinamente.
Si no recuerdas algo con claridad, se honesta sobre ello."""

            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system=system_prompt,
                max_tokens=1000
            )

            elapsed = (time.time() - start_time) * 1000
            return response.content, elapsed

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            return f"[Error generando respuesta: {e}]", elapsed

    def _execute_interaction(
        self,
        interaction: ScheduledInteraction,
        current_hour: float
    ) -> InteractionResult:
        """
        Ejecuta una interaccion programada.

        Args:
            interaction: La interaccion a ejecutar
            current_hour: Hora actual del test

        Returns:
            Resultado de la interaccion
        """
        print(f"\n{'='*60}")
        print(f"  INTERACCION: Hora {current_hour:.1f} - {interaction.interaction_type.value}")
        print(f"{'='*60}")
        print(f"  Prompt: {interaction.prompt[:80]}...")

        # Obtener pensamientos autonomos desde la ultima interaccion
        with self._monitor_lock:
            thoughts_since_last = list(self._autonomous_thought_log)

        # Obtener eventos de consolidacion
        with self._monitor_lock:
            consolidation_events = list(self._consolidation_event_log)

        # Enviar prompt
        response, response_time = self._send_prompt(interaction.prompt)

        print(f"\n  Respuesta ({response_time:.0f}ms):")
        print(f"  {response[:200]}...")

        # Guardar interaccion como memoria
        self.memory_system.experience(
            content=f"Interaccion de test (hora {current_hour}): {interaction.prompt[:100]}... -> {response[:100]}...",
            emotional_tone=self._EmotionalTone.CURIOUS,
            emotional_intensity=0.6,
            importance=0.7,
            context="memory_continuity_test",
            tags=["test", interaction.interaction_type.value]
        )

        # Crear snapshot de memoria
        memory_snapshot = {
            "total_memories": self.memory_system.get_stats()["total_memories"],
            "consolidation_stats": self.memory_system.get_consolidation_stats(),
            "neuroscience_state": self.neuroscience.get_system_state() if self.neuroscience else {}
        }

        # Verificar recall si hay expectativas
        success = True
        notes = ""
        if interaction.expected_recall:
            found_count = sum(
                1 for term in interaction.expected_recall
                if term.lower() in response.lower()
            )
            recall_rate = found_count / len(interaction.expected_recall)

            if recall_rate >= 0.7:
                success = True
                notes = f"Recall exitoso ({found_count}/{len(interaction.expected_recall)} terminos)"
                self.metrics.recall_successes += 1
            elif recall_rate >= 0.3:
                success = True
                notes = f"Recall parcial ({found_count}/{len(interaction.expected_recall)} terminos)"
                self.metrics.recall_partial += 1
            else:
                success = False
                notes = f"Recall fallido ({found_count}/{len(interaction.expected_recall)} terminos)"
                self.metrics.recall_failures += 1

            self.metrics.recall_tests += 1
            print(f"  Recall: {notes}")

        result = InteractionResult(
            timestamp=datetime.now().isoformat(),
            hour=current_hour,
            interaction_type=interaction.interaction_type.value,
            prompt=interaction.prompt,
            response=response,
            response_time_ms=response_time,
            memory_snapshot=memory_snapshot,
            autonomous_thoughts_since_last=thoughts_since_last,
            consolidation_events=consolidation_events,
            success=success,
            notes=notes
        )

        self.results.append(result)
        self.metrics.total_interactions += 1
        if success:
            self.metrics.successful_interactions += 1
        else:
            self.metrics.failed_interactions += 1

        # Limpiar logs temporales
        with self._monitor_lock:
            self._autonomous_thought_log.clear()
            self._consolidation_event_log.clear()

        return result

    # =========================================================================
    # MONITOREO CONTINUO
    # =========================================================================

    def _monitoring_loop(self):
        """Bucle de monitoreo continuo en background"""
        last_consolidation_check = time.time()
        last_strength_snapshot = time.time()
        last_dmn = time.time()
        last_wandering = time.time()

        while self._running and not self._shutdown_requested:
            try:
                current_time = time.time()

                # Verificar consolidacion periodicamente
                if current_time - last_consolidation_check >= self.config.consolidation_check_interval:
                    self._run_consolidation_check()
                    last_consolidation_check = current_time

                # Tomar snapshot de fortaleza
                if current_time - last_strength_snapshot >= self.config.strength_snapshot_interval:
                    self._take_strength_snapshot()
                    last_strength_snapshot = current_time

                # Activar DMN periodicamente
                if current_time - last_dmn >= 600:  # Cada 10 minutos
                    self._run_dmn_activation()
                    last_dmn = current_time

                # Mind wandering periodicamente
                if current_time - last_wandering >= 900:  # Cada 15 minutos
                    self._run_mind_wandering()
                    last_wandering = current_time

                # Generar pensamiento autonomo ocasionalmente
                if random.random() < 0.1:  # 10% de probabilidad cada ciclo
                    thought = self._generate_autonomous_thought()
                    with self._monitor_lock:
                        self._autonomous_thought_log.append({
                            "timestamp": datetime.now().isoformat(),
                            "type": "spontaneous_thought",
                            "content": thought
                        })
                    self.metrics.autonomous_thoughts_total += 1

                    # Guardar como memoria
                    self.memory_system.experience(
                        content=f"Pensamiento autonomo: {thought}",
                        emotional_tone=self._EmotionalTone.CURIOUS,
                        emotional_intensity=0.5,
                        importance=0.5,
                        context="autonomous_monitoring",
                        tags=["autonomo", "pensamiento"]
                    )

                time.sleep(self.config.monitoring_interval)

            except Exception as e:
                print(f"[MONITOR] Error: {e}")
                time.sleep(60)

    def _run_consolidation_check(self):
        """Ejecuta verificacion de consolidacion"""
        if self.config.verbose:
            print("[MONITOR] Ejecutando ciclo de consolidacion...")

        try:
            result = self.neuroscience.force_consolidation()
            if result.get("success"):
                if self.config.verbose:
                    print(f"  Consolidado: {result.get('memories_processed', 0)} memorias")
        except Exception as e:
            print(f"[MONITOR] Error en consolidacion: {e}")

    def _take_strength_snapshot(self):
        """Toma snapshot de fortaleza de memorias"""
        try:
            stats = self.memory_system.get_consolidation_stats()
            snapshot = {
                "timestamp": datetime.now().isoformat(),
                "total_consolidated": stats.get("total_consolidated", 0),
                "total_unconsolidated": stats.get("total_unconsolidated", 0),
                "avg_strength": stats.get("avg_strength", 0.0)
            }

            with self._monitor_lock:
                self.metrics.strength_snapshots.append(snapshot)

            if self.config.verbose:
                print(f"[MONITOR] Snapshot: avg_strength={snapshot['avg_strength']:.3f}")

        except Exception as e:
            print(f"[MONITOR] Error tomando snapshot: {e}")

    def _run_dmn_activation(self):
        """Ejecuta activacion del DMN"""
        try:
            modes = [
                self._DMNMode.SELF_REFLECTION,
                self._DMNMode.MEMORY_RETRIEVAL
            ]
            mode = random.choice(modes)

            activation = self.neuroscience.dmn.engage(mode)

            with self._monitor_lock:
                self.metrics.dmn_activations += 1

            if self.config.verbose:
                print(f"[MONITOR] DMN activado: {mode.value}, insights={len(activation.insights)}")

        except Exception as e:
            print(f"[MONITOR] Error en DMN: {e}")

    def _run_mind_wandering(self):
        """Ejecuta episodio de mind wandering"""
        try:
            types = [
                self._WanderingType.SPONTANEOUS,
                self._WanderingType.DELIBERATE
            ]
            wtype = random.choice(types)

            episode = self.neuroscience.mind_wanderer.wander(
                wandering_type=wtype,
                max_duration_ms=3000
            )

            with self._monitor_lock:
                self.metrics.wandering_episodes += 1

            if self.config.verbose:
                print(f"[MONITOR] Mind wandering: tipo={wtype.value}, cadena={len(episode.thought_chain)}")

        except Exception as e:
            print(f"[MONITOR] Error en wandering: {e}")

    # =========================================================================
    # EJECUCION PRINCIPAL
    # =========================================================================

    def run(self) -> bool:
        """
        Ejecuta el test completo.

        Returns:
            True si el test se completo exitosamente
        """
        # Banner
        mode = "ACELERADO" if self.config.accelerated else "NORMAL"
        duration_real = self.config.duration_hours * self.config.get_real_time_multiplier() / 3600

        print(f"""
{'='*70}
              ARIA MEMORY CONTINUITY TEST
              Test de Continuidad de Memoria
{'='*70}

  Duracion simulada: {self.config.duration_hours} horas
  Duracion real estimada: {duration_real:.1f} horas
  Modo: {mode}
  Directorio de logs: {self.log_dir}
  Usar LLM: {self.config.use_llm}
  Verbose: {self.config.verbose}

{'='*70}
""")

        # Inicializar sistemas
        if not self._initialize_systems():
            print("[ERROR] No se pudieron inicializar los sistemas.")
            return False

        # Registrar estado inicial
        self.metrics.start_time = datetime.now().isoformat()
        initial_stats = self.memory_system.get_stats()
        self.metrics.initial_memory_count = initial_stats["total_memories"]

        print(f"[INFO] Estado inicial:")
        print(f"  - Memorias existentes: {self.metrics.initial_memory_count}")
        print(f"  - Relaciones: {initial_stats['relationships_count']}")
        print(f"  - Edad: {self.memory_system.how_old_am_i()}")

        # Seleccionar interacciones segun duracion
        if self.config.duration_hours <= 6:
            interactions = INTERACTIONS_6H
        elif self.config.duration_hours <= 8:
            interactions = INTERACTIONS_8H
        else:
            interactions = SCHEDULED_INTERACTIONS

        # Filtrar interacciones que caben en la duracion
        interactions = [i for i in interactions if i.hour <= self.config.duration_hours]

        print(f"\n[INFO] {len(interactions)} interacciones programadas.")
        print("[INFO] Presiona Ctrl+C para detener de forma segura.\n")

        # Iniciar monitoreo en background
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._monitor_thread.start()

        # Iniciar motor autonomo
        self.autonomous.start()

        # Iniciar procesamiento de neurociencia en background
        self.neuroscience.start_background_processing()

        test_start = time.time()
        time_multiplier = self.config.get_real_time_multiplier()

        try:
            for interaction in interactions:
                if self._shutdown_requested:
                    print("\n[INFO] Shutdown solicitado. Finalizando test...")
                    break

                # Calcular tiempo de espera hasta esta interaccion
                target_real_seconds = interaction.hour * time_multiplier
                elapsed = time.time() - test_start
                wait_time = target_real_seconds - elapsed

                if wait_time > 0:
                    print(f"\n[WAIT] Esperando {wait_time/60:.1f} minutos hasta hora {interaction.hour}...")

                    # Esperar en intervalos para permitir shutdown
                    while wait_time > 0 and not self._shutdown_requested:
                        sleep_interval = min(30, wait_time)
                        time.sleep(sleep_interval)
                        wait_time -= sleep_interval

                        if not self._shutdown_requested:
                            elapsed_hours = (time.time() - test_start) / time_multiplier
                            remaining_hours = self.config.duration_hours - elapsed_hours
                            print(f"  [PROGRESS] Hora simulada: {elapsed_hours:.2f}, "
                                  f"restante: {remaining_hours:.2f}h")

                if self._shutdown_requested:
                    break

                # Ejecutar interaccion
                current_hour = (time.time() - test_start) / time_multiplier
                self._execute_interaction(interaction, current_hour)

                # Actualizar metricas
                self.metrics.elapsed_hours = current_hour

            # Esperar hasta el final si no se han completado todas las horas
            if not self._shutdown_requested:
                final_wait = (self.config.duration_hours * time_multiplier) - (time.time() - test_start)
                if final_wait > 0:
                    print(f"\n[WAIT] Esperando {final_wait/60:.1f} minutos adicionales...")
                    while final_wait > 0 and not self._shutdown_requested:
                        sleep_interval = min(60, final_wait)
                        time.sleep(sleep_interval)
                        final_wait -= sleep_interval

        except KeyboardInterrupt:
            print("\n[INFO] Interrupcion por teclado...")
        except Exception as e:
            print(f"\n[ERROR] Error en ejecucion: {e}")
            traceback.print_exc()
            self.metrics.errors.append({
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "traceback": traceback.format_exc()
            })
        finally:
            # Detener sistemas
            self._running = False
            self.autonomous.stop()
            self.neuroscience.stop_background_processing()

            if self._monitor_thread:
                self._monitor_thread.join(timeout=5)

        # Registrar estado final
        self.metrics.end_time = datetime.now().isoformat()
        final_stats = self.memory_system.get_stats()
        self.metrics.final_memory_count = final_stats["total_memories"]
        self.metrics.memories_created_during_test = (
            self.metrics.final_memory_count - self.metrics.initial_memory_count
        )

        # Generar reportes
        self._generate_reports()

        print(f"\n[INFO] Test completado. Logs en: {self.log_dir}")
        return len(self.metrics.errors) == 0

    # =========================================================================
    # GENERACION DE REPORTES
    # =========================================================================

    def _generate_reports(self):
        """Genera todos los reportes del test"""
        print("\n[REPORT] Generando reportes...")

        # 1. events.jsonl - Todos los eventos
        self._write_events_jsonl()

        # 2. metrics.json - Estadisticas
        self._write_metrics_json()

        # 3. summary.md - Reporte final
        self._write_summary_md()

        print(f"[REPORT] Reportes generados en: {self.log_dir}")

    def _write_events_jsonl(self):
        """Escribe eventos en formato JSONL"""
        events_path = os.path.join(self.log_dir, "events.jsonl")

        with open(events_path, 'w', encoding='utf-8') as f:
            # Escribir interacciones
            for result in self.results:
                event = {
                    "type": "interaction",
                    "timestamp": result.timestamp,
                    "hour": result.hour,
                    "interaction_type": result.interaction_type,
                    "prompt": result.prompt,
                    "response": result.response,
                    "response_time_ms": result.response_time_ms,
                    "success": result.success,
                    "notes": result.notes
                }
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

            # Escribir snapshots de fortaleza
            for snapshot in self.metrics.strength_snapshots:
                event = {
                    "type": "strength_snapshot",
                    **snapshot
                }
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

        print(f"  [+] events.jsonl: {len(self.results) + len(self.metrics.strength_snapshots)} eventos")

    def _write_metrics_json(self):
        """Escribe metricas en formato JSON"""
        metrics_path = os.path.join(self.log_dir, "metrics.json")

        metrics_dict = asdict(self.metrics)

        with open(metrics_path, 'w', encoding='utf-8') as f:
            json.dump(metrics_dict, f, indent=2, ensure_ascii=False)

        print(f"  [+] metrics.json")

    def _write_summary_md(self):
        """Escribe resumen en formato Markdown"""
        summary_path = os.path.join(self.log_dir, "summary.md")

        # Calcular estadisticas
        recall_accuracy = 0
        if self.metrics.recall_tests > 0:
            recall_accuracy = (
                (self.metrics.recall_successes + self.metrics.recall_partial * 0.5)
                / self.metrics.recall_tests * 100
            )

        avg_response_time = 0
        if self.results:
            avg_response_time = sum(r.response_time_ms for r in self.results) / len(self.results)

        summary = f"""# ARIA Memory Continuity Test - Reporte Final

## Configuracion del Test

| Parametro | Valor |
|-----------|-------|
| Duracion configurada | {self.config.duration_hours} horas |
| Duracion real | {self.metrics.elapsed_hours:.2f} horas |
| Modo | {"Acelerado" if self.config.accelerated else "Normal"} |
| Inicio | {self.metrics.start_time} |
| Fin | {self.metrics.end_time} |

## Resumen de Memoria

| Metrica | Valor |
|---------|-------|
| Memorias iniciales | {self.metrics.initial_memory_count} |
| Memorias finales | {self.metrics.final_memory_count} |
| Memorias creadas durante test | {self.metrics.memories_created_during_test} |

## Consolidacion de Memoria

| Metrica | Valor |
|---------|-------|
| Ciclos de consolidacion | {self.metrics.consolidation_events} |
| Memorias consolidadas | {self.metrics.memories_consolidated} |
| Memorias fortalecidas | {self.metrics.memories_strengthened} |
| Conexiones descubiertas | {self.metrics.connections_discovered} |

## Actividad Autonoma

| Metrica | Valor |
|---------|-------|
| Pensamientos autonomos | {self.metrics.autonomous_thoughts_total} |
| Reflexiones autonomas | {self.metrics.autonomous_reflections} |
| Introspecciones | {self.metrics.autonomous_introspections} |

## DMN y Mind Wandering

| Metrica | Valor |
|---------|-------|
| Activaciones DMN | {self.metrics.dmn_activations} |
| Episodios de mind wandering | {self.metrics.wandering_episodes} |
| Insights generados | {self.metrics.insights_generated} |

## Tests de Recall

| Metrica | Valor |
|---------|-------|
| Tests totales | {self.metrics.recall_tests} |
| Exitos | {self.metrics.recall_successes} |
| Parciales | {self.metrics.recall_partial} |
| Fallos | {self.metrics.recall_failures} |
| **Precision de recall** | **{recall_accuracy:.1f}%** |

## Interacciones

| Metrica | Valor |
|---------|-------|
| Total interacciones | {self.metrics.total_interactions} |
| Exitosas | {self.metrics.successful_interactions} |
| Fallidas | {self.metrics.failed_interactions} |
| Tiempo de respuesta promedio | {avg_response_time:.0f} ms |

## Evolucion de Fortaleza de Memoria

"""
        if self.metrics.strength_snapshots:
            summary += "| Hora | Consolidadas | No consolidadas | Fortaleza promedio |\n"
            summary += "|------|--------------|-----------------|--------------------|\n"
            for i, snapshot in enumerate(self.metrics.strength_snapshots):
                summary += f"| {i+1} | {snapshot.get('total_consolidated', 0)} | "
                summary += f"{snapshot.get('total_unconsolidated', 0)} | "
                summary += f"{snapshot.get('avg_strength', 0):.3f} |\n"
        else:
            summary += "_No se recolectaron snapshots de fortaleza_\n"

        # Errores
        summary += f"""

## Errores

| Total errores | {len(self.metrics.errors)} |
|---------------|---------------------------|

"""
        if self.metrics.errors:
            summary += "### Detalles de errores\n\n"
            for error in self.metrics.errors[:10]:
                summary += f"- **{error.get('timestamp', '')}**: {error.get('error', 'Unknown')}\n"

        # Detalles de interacciones
        summary += """

## Detalle de Interacciones

"""
        for result in self.results:
            status = "OK" if result.success else "FAIL"
            summary += f"### Hora {result.hour:.1f} - {result.interaction_type} [{status}]\n\n"
            summary += f"**Prompt:** {result.prompt[:200]}...\n\n"
            summary += f"**Respuesta:** {result.response[:300]}...\n\n"
            if result.notes:
                summary += f"**Notas:** {result.notes}\n\n"
            summary += "---\n\n"

        # Conclusiones
        summary += f"""

## Conclusiones

1. **Continuidad de Memoria**: {"Exitosa" if recall_accuracy >= 70 else "Parcial" if recall_accuracy >= 40 else "Insuficiente"} - {recall_accuracy:.1f}% de precision en recall.

2. **Actividad Autonoma**: ARIA genero {self.metrics.autonomous_thoughts_total} pensamientos autonomos durante periodos de inactividad.

3. **Consolidacion**: {self.metrics.consolidation_events} ciclos de consolidacion procesaron {self.metrics.memories_consolidated} memorias.

4. **Estabilidad**: Test ejecutado por {self.metrics.elapsed_hours:.2f} horas con {len(self.metrics.errors)} errores.

---

*Generado: {datetime.now().isoformat()}*
*ARIA Memory Continuity Test v1.0*
"""

        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary)

        print(f"  [+] summary.md")


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parsea argumentos de linea de comandos"""
    parser = argparse.ArgumentParser(
        description="ARIA Memory Continuity Test - Test de continuidad de memoria",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/memory_continuity_test.py --duration 8
  python scripts/memory_continuity_test.py --duration 12 --verbose
  python scripts/memory_continuity_test.py --accelerated --duration 6

El test simula un dia de interacciones espaciadas, monitoreando:
- Pensamientos autonomos durante ausencia del usuario
- Consolidacion de memoria estilo neurociencia
- Precision de recall a traves del tiempo
- Actividad del DMN y mind wandering

Los resultados se guardan en logs/memory_test_TIMESTAMP/
        """
    )

    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=8,
        choices=range(1, 13),
        metavar="HOURS",
        help="Duracion del test en horas simuladas (1-12, default: 8)"
    )

    parser.add_argument(
        "--accelerated", "-a",
        action="store_true",
        help="Modo acelerado: 1 hora simulada = 1 minuto real"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar informacion detallada durante el test"
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Ejecutar sin LLM (solo basado en memoria)"
    )

    parser.add_argument(
        "--log-dir", "-l",
        type=str,
        default="logs/memory_test",
        help="Directorio base para logs (default: logs/memory_test)"
    )

    return parser.parse_args()


def main():
    """Punto de entrada principal"""
    args = parse_args()

    config = TestConfig(
        duration_hours=args.duration,
        accelerated=args.accelerated,
        verbose=args.verbose,
        use_llm=not args.no_llm,
        log_dir=args.log_dir
    )

    test = MemoryContinuityTest(config)
    success = test.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
