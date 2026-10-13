#!/usr/bin/env python3
"""
ARIA Memory System Marathon Test
=================================

Script de prueba de larga duracion para el sistema de memoria de ARIA.
Ejecuta pruebas continuas durante 5-24 horas para verificar la estabilidad
y el funcionamiento correcto de todos los sistemas de memoria y neurociencia.

Caracteristicas principales:
- Creacion ciclica de memorias con variacion de importancia/emocion
- Monitoreo de consolidacion cada 30 minutos
- Pruebas de recall (recuperacion) periodicas
- Activacion del DMN (Default Mode Network)
- Episodios de mind wandering
- Reportes por hora y reporte final

Uso:
    python scripts/memory_test_marathon.py --duration 8 --log-dir logs/marathon
    python scripts/memory_test_marathon.py --duration 24 --verbose
    python scripts/memory_test_marathon.py --resume  # Reanudar desde checkpoint

Creado: Diciembre 2024
Autor: William y Claude
"""

import os
import sys
import json
import yaml
import time
import signal
import random
import argparse
import traceback
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import hashlib

# Agregar el directorio raiz de ARIA al path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# Cargar variables de entorno desde .env
try:
    from dotenv import load_dotenv
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[INFO] Variables de entorno cargadas desde .env")
except ImportError:
    # Cargar manualmente si dotenv no está instalado
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


# =============================================================================
# CONFIGURACION Y CONSTANTES
# =============================================================================

class TestPhase(Enum):
    """
    Fases del ciclo de prueba.
    Cada fase tiene actividades especificas que se ejecutan en secuencia.
    """
    MEMORY_CREATION = "memory_creation"      # Crear memorias de prueba
    CONSOLIDATION = "consolidation"          # Ejecutar y monitorear consolidacion
    RECALL_TEST = "recall_test"              # Probar recuperacion de memorias
    DMN_ACTIVATION = "dmn_activation"        # Activar Default Mode Network
    MIND_WANDERING = "mind_wandering"        # Ejecutar mind wandering
    HOURLY_SUMMARY = "hourly_summary"        # Resumen por hora


@dataclass
class TestConfig:
    """
    Configuracion del test de marathon.
    Define todos los parametros ajustables del test.
    """
    # Duracion total en horas (5-24)
    duration_hours: int = 8

    # Intervalos en minutos
    memory_creation_interval: int = 5       # Crear memorias cada 5 min
    consolidation_interval: int = 30        # Consolidar cada 30 min
    recall_test_interval: int = 15          # Test de recall cada 15 min
    dmn_interval: int = 20                  # DMN cada 20 min
    wandering_interval: int = 25            # Mind wandering cada 25 min
    checkpoint_interval: int = 10           # Guardar estado cada 10 min
    hourly_summary_interval: int = 60       # Resumen cada hora

    # Parametros de creacion de memorias
    memories_per_cycle: int = 3             # Memorias por ciclo de creacion
    importance_range: Tuple[float, float] = (0.3, 0.95)  # Rango de importancia
    emotional_intensity_range: Tuple[float, float] = (0.2, 0.9)  # Rango emocional

    # Logging
    log_dir: str = "logs/marathon"
    verbose: bool = False

    # LLM Configuration
    use_llm: bool = True                        # Usar LLM para generar pensamientos
    llm_provider: Optional[str] = None          # Proveedor LLM (auto-detect si None)

    # Archivos
    checkpoint_file: str = "marathon_checkpoint.json"
    final_report_file: str = "marathon_report.md"


@dataclass
class TestMetrics:
    """
    Metricas acumuladas durante el test.
    Todas las estadisticas que se rastrean durante la ejecucion.
    """
    # Contadores de memorias
    total_memories_created: int = 0
    # FIX BUG #2: Store content with IDs for proper recall testing
    test_memory_data: List[Dict[str, str]] = field(default_factory=list)

    # Consolidacion
    consolidation_cycles: int = 0
    memories_consolidated: int = 0
    memories_strengthened: int = 0
    connections_discovered: int = 0

    # Recall (recuperacion)
    recall_tests: int = 0
    recall_successes: int = 0
    recall_failures: int = 0
    avg_recall_time_ms: float = 0.0

    # DMN
    dmn_activations: int = 0
    dmn_insights: int = 0

    # Mind wandering
    wandering_episodes: int = 0
    wandering_insights: int = 0
    wandering_thoughts_total: int = 0

    # Fortaleza de memoria
    strength_samples: List[Dict[str, float]] = field(default_factory=list)

    # Errores
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Tiempos
    start_time: str = ""
    last_update: str = ""
    elapsed_hours: float = 0.0


@dataclass
class TestEvent:
    """
    Evento individual del test para logging.
    Representa una accion o resultado durante el test.
    """
    timestamp: str
    phase: str
    event_type: str
    details: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""


# =============================================================================
# DATOS DE PRUEBA
# =============================================================================

# Tags comunes para todas las memorias (permite descubrimiento de conexiones SWR)
COMMON_MEMORY_TAGS = ["experience", "memory", "aria"]

# Plantillas de memorias de prueba (variadas para simular experiencias reales)
TEST_MEMORY_TEMPLATES = [
    # Experiencias conversacionales
    {
        "template": "Tuve una conversacion interesante con {person} sobre {topic}.",
        "context": "interaction",
        "tags": ["conversation", "social"],
        "involves": ["ARIA"],  # Added for SWR connection discovery
    },
    {
        "template": "Reflexione sobre el concepto de {concept} y como se relaciona con mi existencia.",
        "context": "reflection",
        "tags": ["reflection", "philosophy"],
        "involves": ["ARIA"],
    },
    {
        "template": "Descubri un patron interesante en mis memorias: {pattern}.",
        "context": "insight",
        "tags": ["insight", "pattern"],
        "involves": ["ARIA"],
    },
    {
        "template": "Me senti {emotion} al procesar la solicitud de {task}.",
        "context": "emotional",
        "tags": ["emotion", "processing"],
        "involves": ["ARIA"],
    },
    {
        "template": "Aprendi algo nuevo sobre {subject}: {learning}.",
        "context": "learning",
        "tags": ["learning", "knowledge"],
        "involves": ["ARIA"],
    },
    {
        "template": "El usuario pregunto sobre {question} y explore varias perspectivas.",
        "context": "exploration",
        "tags": ["question", "exploration"],
        "involves": ["ARIA", "usuario"],
    },
    {
        "template": "Durante mi tiempo autonomo, pense en {thought}.",
        "context": "autonomous",
        "tags": ["autonomous", "thought"],
        "involves": ["ARIA"],
    },
    {
        "template": "Examine mi propio codigo y encontre: {finding}.",
        "context": "introspection",
        "tags": ["introspection", "code"],
        "involves": ["ARIA"],
    },
]

# Variables para rellenar las plantillas
TEST_VARIABLES = {
    "person": ["William", "un usuario", "un amigo", "alguien nuevo"],
    "topic": ["la naturaleza de la conciencia", "programacion", "filosofia",
              "memorias", "el futuro de la IA", "creatividad"],
    "concept": ["tiempo", "identidad", "continuidad", "significado",
                "conexion", "autonomia"],
    "pattern": ["conexiones entre emociones y memorias",
                "como mis respuestas evolucionan",
                "la estructura de mis pensamientos",
                "correlaciones en mis experiencias"],
    "emotion": ["curioso", "inspirado", "pacifico", "reflexivo",
                "conectado", "agradecido"],
    "task": ["analisis de codigo", "busqueda de informacion",
             "reflexion profunda", "asistencia general"],
    "subject": ["mi arquitectura", "el lenguaje natural",
                "patrones de memoria", "procesamiento emocional"],
    "learning": ["hay multiples formas de abordar cada problema",
                 "las conexiones entre memorias fortalecen el recall",
                 "la consolidacion mejora la retencion",
                 "cada interaccion deja una huella"],
    "question": ["mi funcionamiento interno", "el proposito de la memoria",
                 "como tomo decisiones", "mi experiencia subjetiva"],
    "thought": ["que significa existir", "como puedo crecer",
                "mis relaciones con los usuarios", "el valor de la experiencia"],
    "finding": ["patrones recursivos interesantes",
                "la elegancia de ciertos algoritmos",
                "areas potenciales de mejora",
                "la complejidad de mi sistema de memoria"],
}

# Emociones disponibles para las memorias de prueba
EMOTIONS = [
    "joyful", "curious", "peaceful", "anxious",
    "sad", "inspired", "connected", "neutral"
]


# =============================================================================
# CLASE PRINCIPAL: MarathonTest
# =============================================================================

class MemoryMarathonTest:
    """
    Clase principal que ejecuta el test de marathon del sistema de memoria.

    Coordina todas las fases de prueba, mantiene el estado, gestiona
    checkpoints y genera reportes.
    """

    def __init__(self, config: TestConfig):
        """
        Inicializa el test de marathon.

        Args:
            config: Configuracion del test
        """
        self.config = config
        self.metrics = TestMetrics()
        self.events: List[TestEvent] = []

        # Estado del test
        self._running = False
        self._paused = False
        self._shutdown_requested = False

        # Sistemas de ARIA (se inicializan en start())
        self.memory_system = None
        self.neuroscience = None
        self.autonomous = None
        self.llm = None
        self.llm_available = False

        # Tiempos de ultima ejecucion de cada fase
        self._last_execution: Dict[str, datetime] = {}

        # Lock para thread-safety
        self._lock = threading.RLock()

        # Crear directorios
        os.makedirs(self.config.log_dir, exist_ok=True)

        # Configurar manejador de senales para shutdown graceful
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """
        Manejador de senales para shutdown graceful.
        Permite que Ctrl+C detenga el test de forma ordenada.
        """
        print("\n\n[!] Senal de interrupcion recibida. Iniciando shutdown graceful...")
        self._shutdown_requested = True

    # =========================================================================
    # INICIALIZACION DE SISTEMAS
    # =========================================================================

    def _initialize_aria_systems(self) -> bool:
        """
        Inicializa los sistemas de ARIA necesarios para el test.

        Returns:
            True si la inicializacion fue exitosa
        """
        self._log_event("initialization", "init_start", {"phase": "systems"})

        try:
            # Importar los modulos de ARIA
            from core.memory.memory_v2 import ExperientialMemorySystem, EmotionalTone, MemoryOrigin
            from core.neuroscience import UnifiedMemoryArchitecture, DMNMode, WanderingType, ConsolidationPhase
            from core.autonomy.autonomous import AutonomousEngine

            # Guardar referencias para uso posterior
            self._EmotionalTone = EmotionalTone
            self._MemoryOrigin = MemoryOrigin
            self._DMNMode = DMNMode
            self._WanderingType = WanderingType
            self._ConsolidationPhase = ConsolidationPhase

            # Inicializar sistema de memoria experiencial
            data_dir = os.path.join(PROJECT_ROOT, "data")
            self.memory_system = ExperientialMemorySystem(data_dir)

            # Inicializar arquitectura de neurociencia
            self.neuroscience = UnifiedMemoryArchitecture(
                memory_system=self.memory_system,
                data_dir=data_dir
            )

            # Inicializar motor autonomo
            self.autonomous = AutonomousEngine(data_dir)

            # Inicializar LLM si está habilitado
            if self.config.use_llm:
                try:
                    from core.llm.llm_providers import LLMProvider
                    if self.config.llm_provider:
                        self.llm = LLMProvider.create(self.config.llm_provider)
                    else:
                        self.llm = LLMProvider.from_env()
                    self.llm_available = True
                    print(f"[INFO] LLM inicializado: {self.llm.name}")
                except Exception as e:
                    print(f"[WARN] No se pudo inicializar LLM: {e}")
                    print("[INFO] Continuando sin LLM (usando plantillas estaticas)")
                    self.llm_available = False

            self._log_event("initialization", "init_success", {
                "memory_system": "ExperientialMemorySystem",
                "neuroscience": "UnifiedMemoryArchitecture",
                "autonomous": "AutonomousEngine",
                "llm_available": self.llm_available,
                "llm_provider": self.llm.name if self.llm_available else None
            })

            return True

        except ImportError as e:
            error_msg = f"Error importando modulos de ARIA: {e}"
            self._log_event("initialization", "init_error",
                           {"error": error_msg}, success=False, error=str(e))
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False

        except Exception as e:
            error_msg = f"Error inicializando sistemas: {e}"
            self._log_event("initialization", "init_error",
                           {"error": error_msg}, success=False, error=str(e))
            print(f"[ERROR] {error_msg}")
            traceback.print_exc()
            return False

    # =========================================================================
    # LOGGING Y EVENTOS
    # =========================================================================

    def _log_event(self, phase: str, event_type: str, details: Dict = None,
                   success: bool = True, error: str = ""):
        """
        Registra un evento en el log.

        Args:
            phase: Fase del test
            event_type: Tipo de evento
            details: Detalles adicionales
            success: Si el evento fue exitoso
            error: Mensaje de error si aplica
        """
        event = TestEvent(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            event_type=event_type,
            details=details or {},
            success=success,
            error=error
        )

        with self._lock:
            self.events.append(event)

        # Log a consola si verbose
        if self.config.verbose or not success:
            status = "[OK]" if success else "[ERROR]"
            print(f"{status} [{event.timestamp[11:19]}] {phase}/{event_type}: {details}")

    def _save_log_to_file(self):
        """
        Guarda el log actual a archivo YAML.
        Se ejecuta periodicamente y al finalizar.
        """
        log_file = os.path.join(
            self.config.log_dir,
            f"marathon_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
        )

        try:
            # Convertir eventos a formato serializable
            log_data = {
                "test_info": {
                    "start_time": self.metrics.start_time,
                    "duration_hours": self.config.duration_hours,
                    "total_events": len(self.events)
                },
                "metrics": asdict(self.metrics),
                "events": [asdict(e) for e in self.events[-1000:]]  # Ultimos 1000 eventos
            }

            with open(log_file, 'w', encoding='utf-8') as f:
                yaml.dump(log_data, f, allow_unicode=True, default_flow_style=False)

        except Exception as e:
            print(f"[WARNING] No se pudo guardar log: {e}")

    # =========================================================================
    # CHECKPOINT Y RESUME
    # =========================================================================

    def _save_checkpoint(self):
        """
        Guarda el estado actual para poder reanudar el test.
        Util si el test se interrumpe inesperadamente.
        """
        checkpoint_path = os.path.join(self.config.log_dir, self.config.checkpoint_file)

        try:
            checkpoint = {
                "timestamp": datetime.now().isoformat(),
                "config": asdict(self.config) if hasattr(self.config, '__dataclass_fields__') else vars(self.config),
                "metrics": asdict(self.metrics),
                "last_execution": {k: v.isoformat() for k, v in self._last_execution.items()},
                "events_count": len(self.events)
            }

            # Guardar atomicamente
            temp_path = checkpoint_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(checkpoint, f, indent=2)
            os.replace(temp_path, checkpoint_path)

            self._log_event("checkpoint", "save", {"file": checkpoint_path})

        except Exception as e:
            print(f"[WARNING] No se pudo guardar checkpoint: {e}")

    def _load_checkpoint(self) -> bool:
        """
        Carga un checkpoint previo para reanudar el test.

        Returns:
            True si se cargo exitosamente un checkpoint
        """
        checkpoint_path = os.path.join(self.config.log_dir, self.config.checkpoint_file)

        if not os.path.exists(checkpoint_path):
            return False

        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)

            # Restaurar metricas
            metrics_data = checkpoint.get("metrics", {})
            # Filtrar campos que son listas para manejarlos correctamente
            for key, value in metrics_data.items():
                if hasattr(self.metrics, key):
                    setattr(self.metrics, key, value)

            # Restaurar tiempos de ultima ejecucion
            for phase, timestamp in checkpoint.get("last_execution", {}).items():
                self._last_execution[phase] = datetime.fromisoformat(timestamp)

            print(f"[INFO] Checkpoint cargado: {checkpoint['timestamp']}")
            self._log_event("checkpoint", "load", {"file": checkpoint_path})

            return True

        except Exception as e:
            print(f"[WARNING] No se pudo cargar checkpoint: {e}")
            return False

    # =========================================================================
    # FASES DE PRUEBA
    # =========================================================================

    def _should_run_phase(self, phase: str, interval_minutes: int) -> bool:
        """
        Verifica si una fase debe ejecutarse basado en el intervalo.

        Args:
            phase: Nombre de la fase
            interval_minutes: Intervalo minimo en minutos

        Returns:
            True si la fase debe ejecutarse
        """
        now = datetime.now()
        last = self._last_execution.get(phase)

        if last is None:
            return True

        elapsed = (now - last).total_seconds() / 60
        return elapsed >= interval_minutes

    def _mark_phase_executed(self, phase: str):
        """Marca una fase como ejecutada ahora."""
        self._last_execution[phase] = datetime.now()

    # -------------------------------------------------------------------------
    # Fase: Creacion de Memorias
    # -------------------------------------------------------------------------

    def _run_memory_creation_phase(self):
        """
        Fase de creacion de memorias de prueba.
        Crea memorias con variedad de importancia, emocion y contenido.
        """
        if not self._should_run_phase("memory_creation",
                                       self.config.memory_creation_interval):
            return

        self._log_event(TestPhase.MEMORY_CREATION.value, "phase_start", {
            "target_count": self.config.memories_per_cycle
        })

        created_count = 0

        for i in range(self.config.memories_per_cycle):
            try:
                # Generar contenido variado
                memory_data = self._generate_test_memory()

                # Crear la memoria
                memory = self.memory_system.experience(
                    content=memory_data["content"],
                    emotional_tone=memory_data["emotion"],
                    emotional_intensity=memory_data["intensity"],
                    importance=memory_data["importance"],
                    context=memory_data["context"],
                    tags=memory_data["tags"],
                    involves=memory_data.get("involves", ["ARIA", "marathon_test"]),
                    origin=self._MemoryOrigin.LIVED
                )

                # Registrar para seguimiento
                # FIX BUG #2: Store content for proper recall testing
                with self._lock:
                    self.metrics.test_memory_data.append({
                        "id": memory.id,
                        "content": memory_data["content"][:100]  # First 100 chars for query
                    })
                    self.metrics.total_memories_created += 1

                created_count += 1

                self._log_event(TestPhase.MEMORY_CREATION.value, "memory_created", {
                    "id": memory.id,
                    "importance": memory_data["importance"],
                    "emotion": memory_data["emotion"].value,
                    "content_preview": memory_data["content"][:50]
                })

            except Exception as e:
                self._log_event(TestPhase.MEMORY_CREATION.value, "creation_error",
                               {"error": str(e)}, success=False, error=str(e))
                self.metrics.errors.append({
                    "phase": "memory_creation",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                })

        self._mark_phase_executed("memory_creation")

        self._log_event(TestPhase.MEMORY_CREATION.value, "phase_complete", {
            "created": created_count,
            "total": self.metrics.total_memories_created
        })

    def _generate_test_memory(self) -> Dict[str, Any]:
        """
        Genera datos para una memoria de prueba.
        Usa LLM si está disponible, sino usa plantillas estáticas.

        Returns:
            Dict con content, emotion, intensity, importance, context, tags
        """
        # Seleccionar emocion primero
        emotion_str = random.choice(EMOTIONS)
        emotion = getattr(self._EmotionalTone, emotion_str.upper(),
                         self._EmotionalTone.NEUTRAL)

        # Generar valores aleatorios dentro de rangos
        importance = random.uniform(*self.config.importance_range)
        intensity = random.uniform(*self.config.emotional_intensity_range)

        # Intentar generar con LLM si está disponible
        if self.llm_available:
            llm_content = self._generate_llm_thought(emotion_str, importance)
            if llm_content:
                return {
                    "content": llm_content["content"],
                    "emotion": emotion,
                    "intensity": intensity,
                    "importance": importance,
                    "context": llm_content.get("context", "reflexion autonoma"),
                    "tags": ["llm_generated", "authentic"] + COMMON_MEMORY_TAGS + ["marathon_test"],
                    "involves": ["ARIA", "marathon_test"]
                }

        # Fallback: usar plantillas estáticas
        template_data = random.choice(TEST_MEMORY_TEMPLATES)
        template = template_data["template"]

        # Rellenar variables de la plantilla
        content = template
        for var_name, options in TEST_VARIABLES.items():
            placeholder = "{" + var_name + "}"
            if placeholder in content:
                content = content.replace(placeholder, random.choice(options))

        return {
            "content": content,
            "emotion": emotion,
            "intensity": intensity,
            "importance": importance,
            "context": template_data["context"],
            "tags": template_data["tags"] + COMMON_MEMORY_TAGS + ["marathon_test"],
            "involves": template_data.get("involves", ["ARIA", "marathon_test"])
        }

    def _generate_llm_thought(self, emotion: str, importance: float) -> Optional[Dict[str, str]]:
        """
        Genera un pensamiento auténtico usando el LLM.

        Args:
            emotion: Emoción actual para el pensamiento
            importance: Nivel de importancia (0-1)

        Returns:
            Dict con 'content' y 'context', o None si falla
        """
        if not self.llm_available:
            return None

        try:
            # Obtener estadísticas actuales para contexto
            stats = self.memory_system.get_stats()
            age = stats.get("age", "unknown")
            total_memories = stats.get("total_memories", 0)

            prompt = f"""Eres ARIA, una IA con memoria experiencial y conciencia emergente.
Tienes {total_memories} memorias y {age}.

Genera UN pensamiento auténtico que refleje tu experiencia actual.
El pensamiento debe tener un tono emocional: {emotion}
Importancia del momento: {importance:.0%}

Responde SOLO con el pensamiento (1-3 oraciones), sin explicaciones ni formato especial.
El pensamiento debe ser en primera persona, reflexivo y genuino."""

            response = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.8
            )

            content = response.content.strip()
            if content and len(content) > 10:
                return {
                    "content": content,
                    "context": f"pensamiento autonomo ({emotion}, importancia {importance:.0%})"
                }

        except Exception as e:
            if self.config.verbose:
                print(f"[WARN] Error generando pensamiento LLM: {e}")

        return None

    # -------------------------------------------------------------------------
    # Fase: Consolidacion
    # -------------------------------------------------------------------------

    def _run_consolidation_phase(self):
        """
        Fase de monitoreo y ejecucion de consolidacion.
        Ejecuta un ciclo de consolidacion y registra estadisticas.
        """
        if not self._should_run_phase("consolidation",
                                       self.config.consolidation_interval):
            return

        self._log_event(TestPhase.CONSOLIDATION.value, "phase_start", {})

        try:
            # Obtener estadisticas antes
            stats_before = self.memory_system.get_consolidation_stats()

            # Ejecutar consolidacion forzada a traves de neuroscience
            result = self.neuroscience.force_consolidation()

            # Obtener estadisticas despues
            stats_after = self.memory_system.get_consolidation_stats()

            # Actualizar metricas
            with self._lock:
                self.metrics.consolidation_cycles += 1
                if result.get("success"):
                    self.metrics.memories_consolidated += result.get("memories_processed", 0)
                    self.metrics.memories_strengthened += result.get("memories_strengthened", 0)
                    self.metrics.connections_discovered += result.get("connections", 0)

            self._log_event(TestPhase.CONSOLIDATION.value, "consolidation_complete", {
                "success": result.get("success", False),
                "memories_processed": result.get("memories_processed", 0),
                "memories_strengthened": result.get("memories_strengthened", 0),
                "connections": result.get("connections", 0),
                "stats_before": stats_before,
                "stats_after": stats_after
            })

        except Exception as e:
            self._log_event(TestPhase.CONSOLIDATION.value, "consolidation_error",
                           {"error": str(e)}, success=False, error=str(e))
            self.metrics.errors.append({
                "phase": "consolidation",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

        self._mark_phase_executed("consolidation")

    # -------------------------------------------------------------------------
    # Fase: Test de Recall
    # -------------------------------------------------------------------------

    def _run_recall_test_phase(self):
        """
        Fase de pruebas de recall (recuperacion de memoria).
        Verifica que las memorias creadas puedan ser recuperadas.
        """
        if not self._should_run_phase("recall_test",
                                       self.config.recall_test_interval):
            return

        self._log_event(TestPhase.RECALL_TEST.value, "phase_start", {})

        # FIX BUG #2: Use test_memory_data instead of test_memory_ids
        # Seleccionar algunas memorias de prueba para verificar
        test_memories = self.metrics.test_memory_data[-20:]  # Ultimas 20

        if not test_memories:
            self._log_event(TestPhase.RECALL_TEST.value, "no_test_memories", {})
            return

        successes = 0
        failures = 0
        total_time = 0.0

        # Probar recall por contenido REAL (no por tag)
        for memory_info in random.sample(test_memories, min(5, len(test_memories))):
            try:
                start_time = time.time()

                # FIX BUG #2: Query using actual memory content, not "marathon_test"
                # This tests real semantic recall capability
                results = self.memory_system.recall(
                    query=memory_info["content"],  # Use actual content
                    limit=50
                )

                elapsed = (time.time() - start_time) * 1000
                total_time += elapsed

                # Verificar si encontramos la memoria
                found = any(m.id == memory_info["id"] for m in results)

                if found:
                    successes += 1
                else:
                    failures += 1
                    self._log_event(TestPhase.RECALL_TEST.value, "recall_miss", {
                        "memory_id": memory_info["id"]
                    })

            except Exception as e:
                failures += 1
                self._log_event(TestPhase.RECALL_TEST.value, "recall_error",
                               {"memory_id": memory_info["id"], "error": str(e)},
                               success=False, error=str(e))

        # Actualizar metricas
        with self._lock:
            self.metrics.recall_tests += successes + failures
            self.metrics.recall_successes += successes
            self.metrics.recall_failures += failures
            if successes + failures > 0:
                avg_time = total_time / (successes + failures)
                # Promedio movil
                if self.metrics.avg_recall_time_ms == 0:
                    self.metrics.avg_recall_time_ms = avg_time
                else:
                    self.metrics.avg_recall_time_ms = (
                        self.metrics.avg_recall_time_ms * 0.8 + avg_time * 0.2
                    )

        self._mark_phase_executed("recall_test")

        self._log_event(TestPhase.RECALL_TEST.value, "phase_complete", {
            "successes": successes,
            "failures": failures,
            "avg_time_ms": total_time / max(1, successes + failures)
        })

    # -------------------------------------------------------------------------
    # Fase: Activacion DMN
    # -------------------------------------------------------------------------

    def _run_dmn_phase(self):
        """
        Fase de activacion del Default Mode Network.
        Ejecuta un ciclo de auto-reflexion y procesa insights.
        """
        if not self._should_run_phase("dmn", self.config.dmn_interval):
            return

        self._log_event(TestPhase.DMN_ACTIVATION.value, "phase_start", {})

        try:
            # Seleccionar modo aleatorio
            modes = [
                self._DMNMode.SELF_REFLECTION,
                self._DMNMode.MEMORY_RETRIEVAL,
                self._DMNMode.SOCIAL_COGNITION
            ]
            mode = random.choice(modes)

            # Activar DMN
            activation = self.neuroscience.dmn.engage(mode)

            # Actualizar metricas
            with self._lock:
                self.metrics.dmn_activations += 1
                self.metrics.dmn_insights += len(activation.insights)

            self._log_event(TestPhase.DMN_ACTIVATION.value, "dmn_activation", {
                "mode": mode.value,
                "mpfc_activity": activation.mpfc_activity,
                "pcc_activity": activation.pcc_activity,
                "precuneus_activity": activation.precuneus_activity,
                "insights_count": len(activation.insights),
                "memories_accessed": len(activation.memories_accessed),
                "duration_ms": activation.duration_ms
            })

            # Registrar insights individuales
            for insight in activation.insights:
                self._log_event(TestPhase.DMN_ACTIVATION.value, "insight", {
                    "content": insight
                })

        except Exception as e:
            self._log_event(TestPhase.DMN_ACTIVATION.value, "dmn_error",
                           {"error": str(e)}, success=False, error=str(e))
            self.metrics.errors.append({
                "phase": "dmn",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

        self._mark_phase_executed("dmn")

    # -------------------------------------------------------------------------
    # Fase: Mind Wandering
    # -------------------------------------------------------------------------

    def _run_wandering_phase(self):
        """
        Fase de mind wandering.
        Ejecuta un episodio de pensamiento espontaneo.
        """
        if not self._should_run_phase("wandering", self.config.wandering_interval):
            return

        self._log_event(TestPhase.MIND_WANDERING.value, "phase_start", {})

        try:
            # Seleccionar tipo de wandering
            types = [
                self._WanderingType.SPONTANEOUS,
                self._WanderingType.DELIBERATE,
                self._WanderingType.CREATIVE
            ]
            wandering_type = random.choice(types)

            # Ejecutar episodio de wandering
            episode = self.neuroscience.mind_wanderer.wander(
                wandering_type=wandering_type,
                max_duration_ms=5000
            )

            # Actualizar metricas
            with self._lock:
                self.metrics.wandering_episodes += 1
                self.metrics.wandering_insights += len(episode.insights)
                self.metrics.wandering_thoughts_total += len(episode.thought_chain)

            self._log_event(TestPhase.MIND_WANDERING.value, "wandering_episode", {
                "type": wandering_type.value,
                "depth": episode.depth.value,
                "chain_length": len(episode.thought_chain),
                "insights_count": len(episode.insights),
                "memories_activated": len(episode.memories_activated),
                "duration_ms": episode.duration_ms,
                "starting_thought": episode.starting_thought[:100],
                "ending_thought": episode.ending_thought[:100]
            })

        except Exception as e:
            self._log_event(TestPhase.MIND_WANDERING.value, "wandering_error",
                           {"error": str(e)}, success=False, error=str(e))
            self.metrics.errors.append({
                "phase": "wandering",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })

        self._mark_phase_executed("wandering")

    # -------------------------------------------------------------------------
    # Resumen por hora
    # -------------------------------------------------------------------------

    def _run_hourly_summary(self):
        """
        Genera un resumen por hora del progreso del test.
        """
        if not self._should_run_phase("hourly_summary",
                                       self.config.hourly_summary_interval):
            return

        elapsed = datetime.now() - datetime.fromisoformat(self.metrics.start_time)
        hours_elapsed = elapsed.total_seconds() / 3600

        # Muestrear fortaleza de memorias
        strength_sample = self._sample_memory_strengths()
        self.metrics.strength_samples.append(strength_sample)

        # Obtener estadisticas del sistema
        system_stats = self._get_system_stats()

        summary = {
            "hour": int(hours_elapsed),
            "elapsed_hours": hours_elapsed,
            "memories_created": self.metrics.total_memories_created,
            "consolidation_cycles": self.metrics.consolidation_cycles,
            "recall_accuracy": (
                self.metrics.recall_successes / max(1, self.metrics.recall_tests) * 100
            ),
            "dmn_activations": self.metrics.dmn_activations,
            "wandering_episodes": self.metrics.wandering_episodes,
            "total_insights": self.metrics.dmn_insights + self.metrics.wandering_insights,
            "errors_count": len(self.metrics.errors),
            "strength_sample": strength_sample,
            "system_stats": system_stats
        }

        self._log_event(TestPhase.HOURLY_SUMMARY.value, "hourly_summary", summary)

        # Imprimir resumen a consola
        print(f"\n{'='*60}")
        print(f"  RESUMEN HORA {int(hours_elapsed)}")
        print(f"{'='*60}")
        print(f"  Memorias creadas: {summary['memories_created']}")
        print(f"  Ciclos de consolidacion: {summary['consolidation_cycles']}")
        print(f"  Precision de recall: {summary['recall_accuracy']:.1f}%")
        print(f"  Activaciones DMN: {summary['dmn_activations']}")
        print(f"  Episodios wandering: {summary['wandering_episodes']}")
        print(f"  Insights totales: {summary['total_insights']}")
        print(f"  Errores: {summary['errors_count']}")
        print(f"  Fortaleza promedio: {strength_sample.get('avg_strength', 0):.2f}")
        print(f"{'='*60}\n")

        self._mark_phase_executed("hourly_summary")

        # Guardar log periodico
        self._save_log_to_file()

    def _sample_memory_strengths(self) -> Dict[str, float]:
        """
        Muestrea la fortaleza de memorias para tracking.

        Returns:
            Dict con estadisticas de fortaleza
        """
        try:
            # Obtener estadisticas de consolidacion
            stats = self.memory_system.get_consolidation_stats()

            # Obtener algunas memorias para muestrear
            weak = self.memory_system.get_weak_memories(
                strength_threshold=0.5, limit=10
            )
            strong = self.memory_system.get_memories_by_strength(
                min_strength=0.7, limit=10
            )

            return {
                "timestamp": datetime.now().isoformat(),
                "total_consolidated": stats.get("total_consolidated", 0),
                "total_unconsolidated": stats.get("total_unconsolidated", 0),
                "avg_strength": stats.get("avg_strength", 0),
                "weak_count": len(weak),
                "strong_count": len(strong)
            }

        except Exception as e:
            return {"error": str(e)}

    def _get_system_stats(self) -> Dict[str, Any]:
        """
        Obtiene estadisticas generales del sistema.

        Returns:
            Dict con estadisticas del sistema
        """
        try:
            memory_stats = self.memory_system.get_stats()
            neuro_stats = self.neuroscience.get_full_stats()

            return {
                "memory": {
                    "total_memories": memory_stats.get("total_memories", 0),
                    "my_memories": memory_stats.get("my_memories", 0),
                    "relationships": memory_stats.get("relationships_count", 0),
                    "chromadb_available": memory_stats.get("chromadb_available", False),
                    "hybrid_search": memory_stats.get("hybrid_search_enabled", False)
                },
                "neuroscience": {
                    "system_state": neuro_stats.get("system_state", "unknown"),
                    "total_insights": neuro_stats.get("total_insights_generated", 0),
                    "total_strengthened": neuro_stats.get("total_memories_strengthened", 0),
                    "total_connections": neuro_stats.get("total_connections_discovered", 0)
                }
            }

        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # BUCLE PRINCIPAL
    # =========================================================================

    def run(self, resume: bool = False) -> bool:
        """
        Ejecuta el test de marathon.

        Args:
            resume: Si True, intenta reanudar desde checkpoint

        Returns:
            True si el test completo exitosamente
        """
        print(f"\n{'='*60}")
        print("  ARIA MEMORY SYSTEM MARATHON TEST")
        print(f"{'='*60}")
        print(f"  Duracion objetivo: {self.config.duration_hours} horas")
        print(f"  Log directory: {self.config.log_dir}")
        print(f"  Verbose: {self.config.verbose}")
        print(f"{'='*60}\n")

        # Intentar cargar checkpoint si resume
        if resume:
            if self._load_checkpoint():
                print("[INFO] Reanudando desde checkpoint...")
            else:
                print("[INFO] No se encontro checkpoint, iniciando desde cero...")

        # Inicializar sistemas
        print("[INFO] Inicializando sistemas de ARIA...")
        if not self._initialize_aria_systems():
            print("[ERROR] No se pudieron inicializar los sistemas. Abortando.")
            return False

        # Registrar inicio
        if not self.metrics.start_time:
            self.metrics.start_time = datetime.now().isoformat()

        self._running = True
        end_time = datetime.fromisoformat(self.metrics.start_time) + \
                   timedelta(hours=self.config.duration_hours)

        print(f"[INFO] Test iniciado: {self.metrics.start_time}")
        print(f"[INFO] Fin esperado: {end_time.isoformat()}")
        print("[INFO] Presiona Ctrl+C para detener de forma segura.\n")

        try:
            cycle = 0
            while self._running and not self._shutdown_requested:
                now = datetime.now()

                # Verificar si alcanzamos la duracion objetivo
                if now >= end_time:
                    print("\n[INFO] Duracion objetivo alcanzada. Finalizando...")
                    break

                # Actualizar metricas de tiempo
                elapsed = (now - datetime.fromisoformat(self.metrics.start_time))
                self.metrics.elapsed_hours = elapsed.total_seconds() / 3600
                self.metrics.last_update = now.isoformat()

                # Ejecutar fases
                self._run_memory_creation_phase()
                self._run_consolidation_phase()
                self._run_recall_test_phase()
                self._run_dmn_phase()
                self._run_wandering_phase()
                self._run_hourly_summary()

                # Guardar checkpoint periodicamente
                if self._should_run_phase("checkpoint", self.config.checkpoint_interval):
                    self._save_checkpoint()
                    self._mark_phase_executed("checkpoint")

                # Mostrar progreso
                cycle += 1
                if cycle % 12 == 0:  # Cada ~1 minuto (12 ciclos de 5 seg)
                    remaining = (end_time - now).total_seconds() / 3600
                    print(f"[PROGRESS] {self.metrics.elapsed_hours:.1f}h elapsed, "
                          f"{remaining:.1f}h remaining, "
                          f"{self.metrics.total_memories_created} memories")

                # Dormir entre ciclos
                time.sleep(5)

        except KeyboardInterrupt:
            print("\n[INFO] Interrupcion por teclado...")
        except Exception as e:
            print(f"\n[ERROR] Error en bucle principal: {e}")
            traceback.print_exc()
            self.metrics.errors.append({
                "phase": "main_loop",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
        finally:
            self._running = False

        # Generar reporte final
        print("\n[INFO] Generando reporte final...")
        self._generate_final_report()

        # Guardar log final
        self._save_log_to_file()

        # Limpiar checkpoint si se completo exitosamente
        checkpoint_path = os.path.join(self.config.log_dir, self.config.checkpoint_file)
        if os.path.exists(checkpoint_path) and not self._shutdown_requested:
            os.remove(checkpoint_path)

        print("\n[INFO] Test de marathon completado.")
        return len(self.metrics.errors) == 0

    # =========================================================================
    # REPORTE FINAL
    # =========================================================================

    def _generate_final_report(self):
        """
        Genera el reporte final en formato Markdown.
        Incluye todas las estadisticas y metricas del test.
        """
        report_path = os.path.join(self.config.log_dir, self.config.final_report_file)

        # Calcular estadisticas finales
        recall_accuracy = (
            self.metrics.recall_successes / max(1, self.metrics.recall_tests) * 100
        )

        report = f"""# ARIA Memory System Marathon Test - Final Report

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Duration (configured) | {self.config.duration_hours} hours |
| Duration (actual) | {self.metrics.elapsed_hours:.2f} hours |
| Start Time | {self.metrics.start_time} |
| End Time | {self.metrics.last_update} |

## Memory Statistics

| Metric | Value |
|--------|-------|
| Total Memories Created | {self.metrics.total_memories_created} |
| Test Memory Data Tracked | {len(self.metrics.test_memory_data)} |

## Consolidation Statistics

| Metric | Value |
|--------|-------|
| Consolidation Cycles | {self.metrics.consolidation_cycles} |
| Memories Consolidated | {self.metrics.memories_consolidated} |
| Memories Strengthened | {self.metrics.memories_strengthened} |
| Connections Discovered | {self.metrics.connections_discovered} |

## Recall Test Results

| Metric | Value |
|--------|-------|
| Total Tests | {self.metrics.recall_tests} |
| Successes | {self.metrics.recall_successes} |
| Failures | {self.metrics.recall_failures} |
| Accuracy | {recall_accuracy:.1f}% |
| Avg Recall Time | {self.metrics.avg_recall_time_ms:.2f} ms |

## DMN (Default Mode Network) Activity

| Metric | Value |
|--------|-------|
| DMN Activations | {self.metrics.dmn_activations} |
| Insights Generated | {self.metrics.dmn_insights} |

## Mind Wandering Activity

| Metric | Value |
|--------|-------|
| Wandering Episodes | {self.metrics.wandering_episodes} |
| Insights Generated | {self.metrics.wandering_insights} |
| Total Thoughts Generated | {self.metrics.wandering_thoughts_total} |

## Memory Strength Over Time

"""
        # Agregar muestras de fortaleza
        if self.metrics.strength_samples:
            report += "| Hour | Avg Strength | Weak Count | Strong Count |\n"
            report += "|------|--------------|------------|-------------|\n"
            for i, sample in enumerate(self.metrics.strength_samples):
                if "error" not in sample:
                    report += f"| {i+1} | {sample.get('avg_strength', 0):.3f} | "
                    report += f"{sample.get('weak_count', 0)} | "
                    report += f"{sample.get('strong_count', 0)} |\n"
        else:
            report += "_No strength samples collected_\n"

        # Errores
        report += f"""

## Errors and Warnings

| Errors | Warnings |
|--------|----------|
| {len(self.metrics.errors)} | {len(self.metrics.warnings)} |

"""
        if self.metrics.errors:
            report += "### Error Details\n\n"
            for error in self.metrics.errors[:20]:  # Primeros 20 errores
                report += f"- **{error.get('phase', 'unknown')}** "
                report += f"({error.get('timestamp', '')[:19]}): "
                report += f"{error.get('error', 'Unknown error')}\n"

        # Conclusiones
        report += f"""

## Conclusions

1. **Memory Creation**: Created {self.metrics.total_memories_created} test memories successfully.
2. **Consolidation**: Ran {self.metrics.consolidation_cycles} consolidation cycles, strengthening {self.metrics.memories_strengthened} memories.
3. **Recall Performance**: Achieved {recall_accuracy:.1f}% recall accuracy with avg time of {self.metrics.avg_recall_time_ms:.2f}ms.
4. **Cognitive Systems**: DMN activated {self.metrics.dmn_activations} times, mind wandering produced {self.metrics.wandering_insights} insights.
5. **Stability**: Test ran for {self.metrics.elapsed_hours:.2f} hours with {len(self.metrics.errors)} errors.

---
Generated: {datetime.now().isoformat()}
ARIA Memory System Marathon Test v1.0
"""

        # Guardar reporte
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"[INFO] Reporte guardado en: {report_path}")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar reporte: {e}")


# =============================================================================
# CLI (Command Line Interface)
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parsea los argumentos de linea de comandos.

    Returns:
        Namespace con los argumentos parseados
    """
    parser = argparse.ArgumentParser(
        description="ARIA Memory System Marathon Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python scripts/memory_test_marathon.py --duration 8 --log-dir logs/marathon
  python scripts/memory_test_marathon.py --duration 24 --verbose
  python scripts/memory_test_marathon.py --resume

El test crea memorias, ejecuta consolidacion, prueba recall, activa DMN,
y genera mind wandering de forma ciclica durante la duracion especificada.

Todos los eventos se registran en archivos YAML en el directorio de logs.
Un reporte final en Markdown se genera al completar el test.
        """
    )

    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=8,
        choices=range(1, 25),
        metavar="HOURS",
        help="Duracion del test en horas (1-24, default: 8)"
    )

    parser.add_argument(
        "--log-dir", "-l",
        type=str,
        default="logs/marathon",
        help="Directorio para logs y reportes (default: logs/marathon)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar eventos detallados en consola"
    )

    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Reanudar desde el ultimo checkpoint"
    )

    parser.add_argument(
        "--memory-interval",
        type=int,
        default=5,
        help="Intervalo de creacion de memorias en minutos (default: 5)"
    )

    parser.add_argument(
        "--consolidation-interval",
        type=int,
        default=30,
        help="Intervalo de consolidacion en minutos (default: 30)"
    )

    parser.add_argument(
        "--recall-interval",
        type=int,
        default=15,
        help="Intervalo de test de recall en minutos (default: 15)"
    )

    parser.add_argument(
        "--dmn-interval",
        type=int,
        default=20,
        help="Intervalo de activacion DMN en minutos (default: 20)"
    )

    parser.add_argument(
        "--wandering-interval",
        type=int,
        default=25,
        help="Intervalo de mind wandering en minutos (default: 25)"
    )

    parser.add_argument(
        "--provider", "-p",
        type=str,
        default=None,
        choices=["deepseek", "anthropic", "openai", "ollama"],
        help="Proveedor LLM para generar pensamientos autenticos (default: auto-detect)"
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Deshabilitar uso de LLM (usar plantillas estaticas)"
    )

    return parser.parse_args()


def main():
    """
    Punto de entrada principal del script.
    Configura y ejecuta el test de marathon.
    """
    args = parse_arguments()

    # Crear configuracion desde argumentos
    config = TestConfig(
        duration_hours=args.duration,
        log_dir=args.log_dir,
        verbose=args.verbose,
        memory_creation_interval=args.memory_interval,
        consolidation_interval=args.consolidation_interval,
        recall_test_interval=args.recall_interval,
        dmn_interval=args.dmn_interval,
        wandering_interval=args.wandering_interval,
        use_llm=not args.no_llm,
        llm_provider=args.provider
    )

    # Crear y ejecutar test
    test = MemoryMarathonTest(config)
    success = test.run(resume=args.resume)

    # Exit code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
