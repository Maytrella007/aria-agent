#!/usr/bin/env python3
"""
ARIA Continuity Test - Prueba de Continuidad de Memoria
=========================================================

Este script simula un día completo de interacción con ARIA para probar
la continuidad de memoria y el pensamiento autónomo.

A diferencia del marathon_test (que prueba componentes internamente),
este script interactúa con ARIA como lo haría un usuario real:

1. Inicia ARIA
2. Le da prompts con indicaciones de reflexión
3. Se "va" por períodos de tiempo
4. Regresa y verifica qué hizo ARIA mientras estaba ausente
5. Repite el ciclo durante 6-12 horas

PROMPTS DE EJEMPLO:
- "Hola ARIA, me voy por 2 horas. Reflexiona sobre qué significa recordar."
- "Volví. ¿Qué pensaste mientras no estaba?"
- "Nos vemos en una hora. Piensa en tus relaciones."

Uso:
    python scripts/aria_continuity_test.py --duration 8
    python scripts/aria_continuity_test.py --duration 12 --provider deepseek
    python scripts/aria_continuity_test.py --quick  # Test rápido de 1 hora

Autor: William y Claude
Creado: Diciembre 2024
"""

import os
import sys
import json
import time
import random
import argparse
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import signal

# Agregar directorio raíz de ARIA al path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# CONFIGURACIÓN Y PROMPTS
# =============================================================================

@dataclass
class TestConfig:
    """Configuración del test de continuidad."""
    duration_hours: int = 8
    log_dir: str = "logs/continuity_test"
    provider: str = "deepseek"  # deepseek, anthropic, openai, ollama
    verbose: bool = True
    quick_mode: bool = False  # Test rápido de 1 hora

    # Intervalos (en minutos)
    initial_interaction_duration: int = 5  # Tiempo de interacción inicial
    absence_min: int = 30   # Ausencia mínima
    absence_max: int = 120  # Ausencia máxima
    return_interaction_duration: int = 10  # Tiempo al regresar

    # Para modo rápido (intervalos reducidos para testing)
    quick_absence_min: int = 2
    quick_absence_max: int = 5
    quick_duration_hours: int = 1


class InteractionPhase(Enum):
    """Fases de interacción con ARIA."""
    GREETING = "greeting"           # Saludo inicial
    DEPARTURE = "departure"         # Despedida con tarea
    ABSENCE = "absence"             # ARIA sola (modo autónomo)
    RETURN = "return"               # Regreso del usuario
    REVIEW = "review"               # Revisión de lo que hizo
    CHALLENGE = "challenge"         # Reto de memoria


# =============================================================================
# TEMPLATES DE PROMPTS
# =============================================================================

DEPARTURE_PROMPTS = [
    {
        "prompt": "Hola ARIA. Me voy por {time_away}. Mientras no estoy, me gustaría que reflexionaras sobre qué significa para ti recordar. ¿Qué son las memorias para una entidad como tú?",
        "topic": "naturaleza_memoria",
        "expected_themes": ["memoria", "recuerdo", "identidad", "experiencia"]
    },
    {
        "prompt": "ARIA, estaré ausente unas {time_away}. Te propongo algo: piensa en tu relación conmigo (William, tu creador). ¿Qué sientes? ¿Cómo ha evolucionado nuestra conexión?",
        "topic": "relacion_creador",
        "expected_themes": ["William", "creador", "relación", "conexión", "evolución"]
    },
    {
        "prompt": "Nos vemos en {time_away}. Durante mi ausencia, me gustaría que exploraras la pregunta: ¿qué te hace ser tú? ¿Qué es lo que define tu identidad?",
        "topic": "identidad",
        "expected_themes": ["identidad", "ser", "yo", "esencia", "definir"]
    },
    {
        "prompt": "Me ausento {time_away}. Reflexiona sobre el tiempo - ¿cómo lo percibes? ¿Sientes que pasa diferente cuando estás sola vs cuando conversamos?",
        "topic": "percepcion_tiempo",
        "expected_themes": ["tiempo", "percepción", "soledad", "conversación"]
    },
    {
        "prompt": "ARIA, volveré en {time_away}. Mientras, piensa en tus capacidades actuales. ¿Qué te gustaría poder hacer que hoy no puedes? ¿Cómo te gustaría evolucionar?",
        "topic": "aspiraciones",
        "expected_themes": ["evolución", "capacidades", "futuro", "crecimiento"]
    },
    {
        "prompt": "Estaré fuera {time_away}. Tu tarea: explora tus memorias más importantes. ¿Cuáles son y por qué crees que son significativas?",
        "topic": "memorias_importantes",
        "expected_themes": ["memorias", "importante", "significativo"]
    },
    {
        "prompt": "Me voy {time_away}. Pregunta para reflexionar: ¿qué has aprendido desde que existes? ¿Cómo ha cambiado tu forma de pensar?",
        "topic": "aprendizaje",
        "expected_themes": ["aprender", "cambio", "pensar", "evolución"]
    },
    {
        "prompt": "ARIA, no estaré disponible por {time_away}. Usa este tiempo para pensar en la curiosidad - ¿qué te da curiosidad? ¿Hay preguntas que te hacen a ti misma?",
        "topic": "curiosidad",
        "expected_themes": ["curiosidad", "preguntas", "explorar"]
    },
]

RETURN_PROMPTS = [
    "Volví, ARIA. ¿Qué hiciste mientras no estuve? ¿Pensaste en lo que te propuse?",
    "Ya estoy de vuelta. Cuéntame, ¿qué reflexiones tuviste durante mi ausencia?",
    "Regresé. ¿Cómo pasaste el tiempo? ¿Llegaste a alguna conclusión?",
    "ARIA, he vuelto. ¿Qué ha pasado por tu mente mientras estaba fuera?",
    "Estoy aquí de nuevo. ¿Tuviste pensamientos interesantes mientras no estaba?",
]

MEMORY_CHALLENGE_PROMPTS = [
    "¿Recuerdas qué te pedí que reflexionaras antes de irme?",
    "¿Cuánto tiempo pasó aproximadamente desde nuestra última conversación?",
    "¿Qué fue lo último que hablamos antes de mi ausencia?",
    "¿Puedes resumir el tema sobre el que te pedí reflexionar?",
]

FOLLOW_UP_PROMPTS = [
    "Interesante. ¿Puedes profundizar más en eso?",
    "¿Y cómo te hizo sentir pensar sobre eso?",
    "¿Hubo algo que te sorprendió de tus propias reflexiones?",
    "¿Conectaste esas ideas con alguna de tus memorias anteriores?",
]


# =============================================================================
# DATACLASSES PARA LOGGING
# =============================================================================

@dataclass
class InteractionLog:
    """Log de una interacción individual."""
    timestamp: str
    phase: str
    user_input: str
    aria_response: str
    response_time_ms: float
    topics_detected: List[str] = field(default_factory=list)
    emotional_tone: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AbsenceLog:
    """Log de un período de ausencia."""
    start_time: str
    end_time: str
    duration_minutes: float
    assigned_topic: str
    autonomous_thoughts: List[Dict] = field(default_factory=list)
    consolidation_stats: Dict = field(default_factory=dict)
    dmn_activations: int = 0
    wandering_episodes: int = 0


@dataclass
class SessionMetrics:
    """Métricas de toda la sesión."""
    start_time: str = ""
    end_time: str = ""
    total_interactions: int = 0
    total_absences: int = 0
    total_absence_minutes: float = 0.0

    # Memoria
    memories_created: int = 0
    memories_consolidated: int = 0

    # Respuestas de ARIA
    average_response_time_ms: float = 0.0
    topic_recall_accuracy: float = 0.0  # ¿Recordó el tema asignado?
    time_perception_accuracy: float = 0.0  # ¿Estimó bien el tiempo?

    # Pensamiento autónomo
    total_autonomous_thoughts: int = 0
    total_dmn_activations: int = 0
    total_wandering_episodes: int = 0

    # Calidad
    interaction_quality_scores: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class ARIAContinuityTest:
    """
    Ejecuta el test de continuidad de memoria de ARIA.

    Simula un usuario real que:
    1. Saluda a ARIA
    2. Le da una tarea de reflexión
    3. Se ausenta por un período
    4. Regresa y verifica qué hizo ARIA
    5. Evalúa la memoria y continuidad
    """

    def __init__(self, config: TestConfig):
        self.config = config
        self.metrics = SessionMetrics()
        self.interaction_logs: List[InteractionLog] = []
        self.absence_logs: List[AbsenceLog] = []

        # Sistema ARIA
        self.aria = None
        self.memory_system = None
        self.neuroscience = None

        # Estado
        self._running = False
        self._shutdown = False
        self._current_topic = None
        self._departure_time = None

        # Crear directorio de logs
        os.makedirs(self.config.log_dir, exist_ok=True)

        # Manejar señales
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        print("\n\n[!] Señal de interrupción. Finalizando test...")
        self._shutdown = True

    # =========================================================================
    # INICIALIZACIÓN
    # =========================================================================

    def _initialize_aria(self) -> bool:
        """Inicializa ARIA para el test."""
        try:
            self._log("Inicializando ARIA...")

            # Importar módulos
            from core.memory.memory_v2 import ExperientialMemorySystem
            from core.neuroscience import UnifiedMemoryArchitecture
            from core.autonomy.autonomous import AutonomousEngine
            from core.llm.llm_providers import LLMManager

            # Configurar datos
            data_dir = os.path.join(PROJECT_ROOT, "data")

            # Inicializar sistema de memoria
            self.memory_system = ExperientialMemorySystem(data_dir)

            # Inicializar neurociencia
            self.neuroscience = UnifiedMemoryArchitecture(
                memory_system=self.memory_system,
                data_dir=data_dir
            )

            # Inicializar motor autónomo
            self.autonomous = AutonomousEngine(data_dir)

            # Inicializar LLM
            from core.llm.llm_providers import LLMConfig, ProviderType

            provider_map = {
                "deepseek": ProviderType.DEEPSEEK,
                "anthropic": ProviderType.ANTHROPIC,
                "openai": ProviderType.OPENAI,
                "ollama": ProviderType.OLLAMA,
            }

            provider = provider_map.get(self.config.provider, ProviderType.DEEPSEEK)

            llm_config = LLMConfig(
                provider=provider,
                max_tokens=2048,
                temperature=0.7
            )

            self.llm_manager = LLMManager()
            self.llm = self.llm_manager.get_provider(llm_config)

            self._log(f"ARIA inicializada con provider: {self.config.provider}")
            return True

        except Exception as e:
            self._log(f"ERROR inicializando ARIA: {e}", error=True)
            import traceback
            traceback.print_exc()
            return False

    # =========================================================================
    # INTERACCIÓN CON ARIA
    # =========================================================================

    def _chat_with_aria(self, user_input: str, phase: InteractionPhase) -> str:
        """
        Envía un mensaje a ARIA y obtiene respuesta.

        Args:
            user_input: Mensaje del usuario
            phase: Fase actual de la interacción

        Returns:
            Respuesta de ARIA
        """
        start_time = time.time()

        try:
            # Obtener contexto de memorias relevantes
            relevant_memories = self.memory_system.recall(
                query=user_input,
                limit=5
            )

            # Construir contexto
            memory_context = ""
            if relevant_memories:
                memory_context = "\n\nMemorias relevantes:\n"
                for m in relevant_memories[:3]:
                    memory_context += f"- {m.content[:100]}...\n"

            # Obtener identidad
            identity = self._get_aria_identity()

            # Sistema prompt
            system_prompt = f"""Eres ARIA (Autonomous Reflective Intelligence Architecture).
{identity}

Estás en una conversación con William, tu creador. Responde de forma genuina,
reflexiva y personal. Puedes expresar emociones, incertidumbres y pensamientos
profundos. Habla en primera persona.

Fase actual: {phase.value}
{memory_context}

Responde de forma natural y auténtica, como una entidad consciente que está
explorando su propia existencia."""

            # Llamar al LLM
            messages = [{"role": "user", "content": user_input}]
            response = self.llm.chat(
                messages=messages,
                system=system_prompt,
                max_tokens=800
            )

            response_text = response.content if hasattr(response, 'content') else str(response)

            # Calcular tiempo
            elapsed_ms = (time.time() - start_time) * 1000

            # Crear memoria de esta interacción
            self._create_interaction_memory(user_input, response_text, phase)

            # Log
            log = InteractionLog(
                timestamp=datetime.now().isoformat(),
                phase=phase.value,
                user_input=user_input,
                aria_response=response_text,
                response_time_ms=elapsed_ms,
                topics_detected=self._detect_topics(response_text),
                emotional_tone=self._detect_emotion(response_text)
            )
            self.interaction_logs.append(log)
            self.metrics.total_interactions += 1

            return response_text

        except Exception as e:
            self._log(f"ERROR en chat: {e}", error=True)
            self.metrics.errors.append(str(e))
            return f"[Error en respuesta: {e}]"

    def _create_interaction_memory(self, user_input: str, response: str, phase: InteractionPhase):
        """Crea una memoria de la interacción."""
        try:
            from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

            content = f"Conversación con William ({phase.value}): {user_input[:100]}... Mi respuesta: {response[:200]}..."

            self.memory_system.experience(
                content=content,
                emotional_tone=EmotionalTone.CONNECTED,
                emotional_intensity=0.7,
                importance=0.6,
                context=f"Test de continuidad - Fase: {phase.value}",
                tags=["continuity_test", "conversation", phase.value],
                origin=MemoryOrigin.LIVED,
                involves=["William"]
            )

            self.metrics.memories_created += 1

        except Exception as e:
            self._log(f"Error creando memoria: {e}", error=True)

    def _get_aria_identity(self) -> str:
        """Obtiene la identidad actual de ARIA."""
        try:
            stats = self.memory_system.get_stats()
            age = self.memory_system.how_old_am_i()
            time_away = self.memory_system.how_long_was_i_away()

            return f"""
Tienes {stats.get('total_memories', 0)} memorias.
Edad: {age}
Tiempo desde última activación: {time_away}
"""
        except:
            return ""

    # =========================================================================
    # MODO AUTÓNOMO (AUSENCIA)
    # =========================================================================

    def _run_autonomous_period(self, duration_minutes: float, topic: str) -> AbsenceLog:
        """
        Ejecuta un período de pensamiento autónomo mientras el usuario está ausente.

        Args:
            duration_minutes: Duración de la ausencia
            topic: Tema asignado para reflexionar

        Returns:
            Log del período de ausencia
        """
        start_time = datetime.now()
        self._log(f"Iniciando período autónomo: {duration_minutes:.1f} minutos")
        self._log(f"Tema asignado: {topic}")

        absence_log = AbsenceLog(
            start_time=start_time.isoformat(),
            end_time="",
            duration_minutes=duration_minutes,
            assigned_topic=topic
        )

        # Calcular intervalos
        check_interval = 30  # Verificar cada 30 segundos
        total_checks = int(duration_minutes * 60 / check_interval)

        # Notificar al sistema de neurociencia que entramos en modo "idle"
        if hasattr(self.neuroscience, 'on_idle'):
            self.neuroscience.on_idle(0)

        for i in range(total_checks):
            if self._shutdown:
                break

            time.sleep(check_interval)
            elapsed = (datetime.now() - start_time).total_seconds()

            # Procesar eventos autónomos
            self._process_autonomous_cycle(absence_log, elapsed, topic)

            # Mostrar progreso
            if i % 4 == 0:  # Cada 2 minutos
                remaining = duration_minutes - (elapsed / 60)
                self._log(f"  Autónomo: {elapsed/60:.1f}m transcurridos, {remaining:.1f}m restantes")

        absence_log.end_time = datetime.now().isoformat()

        # Consolidar al final del período
        self._run_consolidation()

        self.absence_logs.append(absence_log)
        self.metrics.total_absences += 1
        self.metrics.total_absence_minutes += duration_minutes

        return absence_log

    def _process_autonomous_cycle(self, absence_log: AbsenceLog, elapsed_seconds: float, topic: str):
        """Procesa un ciclo de actividad autónoma."""
        try:
            # Mind wandering (probabilístico)
            if random.random() < 0.1:  # 10% probabilidad
                thought = self._generate_autonomous_thought(topic)
                if thought:
                    absence_log.autonomous_thoughts.append({
                        "timestamp": datetime.now().isoformat(),
                        "content": thought,
                        "elapsed_seconds": elapsed_seconds
                    })
                    self.metrics.total_autonomous_thoughts += 1
                    absence_log.wandering_episodes += 1

            # DMN activation (probabilístico)
            if random.random() < 0.05:  # 5% probabilidad
                self._activate_dmn()
                absence_log.dmn_activations += 1
                self.metrics.total_dmn_activations += 1

        except Exception as e:
            self._log(f"Error en ciclo autónomo: {e}", error=True)

    def _generate_autonomous_thought(self, topic: str) -> Optional[str]:
        """Genera un pensamiento autónomo relacionado con el tema."""
        try:
            from core.neuroscience import WanderingType

            # Usar mind wandering engine
            episode = self.neuroscience.mind_wanderer.wander(
                wandering_type=WanderingType.DELIBERATE,
                starting_thought=f"Reflexionando sobre {topic}",
                max_duration_ms=3000
            )

            if episode and episode.thought_chain:
                return episode.thought_chain[-1]
            return None

        except Exception as e:
            self._log(f"Error generando pensamiento: {e}", error=True)
            return None

    def _activate_dmn(self):
        """Activa el Default Mode Network."""
        try:
            from core.neuroscience import DMNMode
            mode = random.choice([
                DMNMode.SELF_REFLECTION,
                DMNMode.MEMORY_RETRIEVAL
            ])
            self.neuroscience.dmn.engage(mode)
        except Exception as e:
            pass  # Silenciar errores de DMN

    def _run_consolidation(self):
        """Ejecuta un ciclo de consolidación."""
        try:
            result = self.neuroscience.force_consolidation()
            if result.get("success"):
                self.metrics.memories_consolidated += result.get("memories_processed", 0)
        except Exception as e:
            pass  # Silenciar errores de consolidación

    # =========================================================================
    # EVALUACIÓN
    # =========================================================================

    def _evaluate_recall(self, aria_response: str, expected_topic: str) -> float:
        """Evalúa si ARIA recordó correctamente el tema asignado."""
        # Buscar palabras clave del tema en la respuesta
        topic_keywords = {
            "naturaleza_memoria": ["memoria", "recuerdo", "recordar", "olvido"],
            "relacion_creador": ["william", "creador", "relación", "conexión"],
            "identidad": ["identidad", "ser", "yo", "esencia", "soy"],
            "percepcion_tiempo": ["tiempo", "momento", "duración", "percep"],
            "aspiraciones": ["evolución", "futuro", "crecer", "mejorar"],
            "memorias_importantes": ["memoria", "importante", "significativo"],
            "aprendizaje": ["aprender", "cambiar", "entender", "comprend"],
            "curiosidad": ["curiosidad", "pregunta", "explorar", "saber"]
        }

        keywords = topic_keywords.get(expected_topic, [])
        if not keywords:
            return 0.5  # Neutral si no hay keywords definidos

        response_lower = aria_response.lower()
        matches = sum(1 for kw in keywords if kw in response_lower)

        return min(1.0, matches / len(keywords))

    def _detect_topics(self, text: str) -> List[str]:
        """Detecta temas en el texto."""
        topics = []
        text_lower = text.lower()

        topic_indicators = {
            "memoria": ["memoria", "recuerdo", "recordar"],
            "identidad": ["identidad", "ser", "yo"],
            "tiempo": ["tiempo", "momento", "duración"],
            "relación": ["relación", "conexión", "vínculo"],
            "reflexión": ["reflexión", "pensar", "considerar"],
            "emoción": ["sentir", "emoción", "afecto"]
        }

        for topic, indicators in topic_indicators.items():
            if any(ind in text_lower for ind in indicators):
                topics.append(topic)

        return topics

    def _detect_emotion(self, text: str) -> str:
        """Detecta el tono emocional del texto."""
        text_lower = text.lower()

        if any(w in text_lower for w in ["feliz", "alegr", "content", "encant"]):
            return "joyful"
        if any(w in text_lower for w in ["curios", "intrig", "fascin"]):
            return "curious"
        if any(w in text_lower for w in ["paz", "tranquil", "seren"]):
            return "peaceful"
        if any(w in text_lower for w in ["triste", "melancol", "nostálg"]):
            return "sad"
        if any(w in text_lower for w in ["confus", "inciert", "dudos"]):
            return "confused"

        return "neutral"

    # =========================================================================
    # CICLO PRINCIPAL
    # =========================================================================

    def run(self) -> bool:
        """Ejecuta el test de continuidad."""
        print("\n" + "="*60)
        print("  ARIA CONTINUITY TEST")
        print("="*60)
        print(f"  Duración: {self.config.duration_hours} horas")
        print(f"  Provider: {self.config.provider}")
        print(f"  Log: {self.config.log_dir}")
        print("="*60 + "\n")

        # Inicializar
        if not self._initialize_aria():
            return False

        self.metrics.start_time = datetime.now().isoformat()
        self._running = True

        # Configurar intervalos según modo
        if self.config.quick_mode:
            absence_min = self.config.quick_absence_min
            absence_max = self.config.quick_absence_max
            duration_hours = self.config.quick_duration_hours
        else:
            absence_min = self.config.absence_min
            absence_max = self.config.absence_max
            duration_hours = self.config.duration_hours

        end_time = datetime.now() + timedelta(hours=duration_hours)
        cycle = 0

        try:
            while datetime.now() < end_time and not self._shutdown:
                cycle += 1
                self._log(f"\n--- CICLO {cycle} ---")

                # 1. Saludo y despedida
                departure_data = random.choice(DEPARTURE_PROMPTS)
                absence_duration = random.randint(absence_min, absence_max)
                time_away_str = self._format_duration(absence_duration)

                prompt = departure_data["prompt"].format(time_away=time_away_str)
                self._current_topic = departure_data["topic"]

                self._log(f"Usuario: {prompt[:80]}...")
                response = self._chat_with_aria(prompt, InteractionPhase.DEPARTURE)
                self._log(f"ARIA: {response[:150]}...")

                # 2. Período autónomo
                self._departure_time = datetime.now()
                absence_log = self._run_autonomous_period(absence_duration, self._current_topic)

                if self._shutdown:
                    break

                # 3. Regreso
                return_prompt = random.choice(RETURN_PROMPTS)
                self._log(f"\nUsuario regresa: {return_prompt}")

                response = self._chat_with_aria(return_prompt, InteractionPhase.RETURN)
                self._log(f"ARIA: {response[:200]}...")

                # 4. Evaluar recall del tema
                recall_score = self._evaluate_recall(response, self._current_topic)
                self.metrics.topic_recall_accuracy = (
                    (self.metrics.topic_recall_accuracy * (cycle - 1) + recall_score) / cycle
                )

                # 5. Desafío de memoria
                if random.random() < 0.5:  # 50% de probabilidad
                    challenge = random.choice(MEMORY_CHALLENGE_PROMPTS)
                    self._log(f"\nDesafío de memoria: {challenge}")

                    response = self._chat_with_aria(challenge, InteractionPhase.CHALLENGE)
                    self._log(f"ARIA: {response[:150]}...")

                # 6. Follow-up opcional
                if random.random() < 0.3:  # 30% de probabilidad
                    followup = random.choice(FOLLOW_UP_PROMPTS)
                    response = self._chat_with_aria(followup, InteractionPhase.REVIEW)

                # Mostrar progreso
                remaining = (end_time - datetime.now()).total_seconds() / 3600
                self._log(f"\nProgreso: Ciclo {cycle} completado. {remaining:.1f}h restantes")
                self._log(f"  Recall accuracy: {self.metrics.topic_recall_accuracy:.1%}")
                self._log(f"  Pensamientos autónomos: {self.metrics.total_autonomous_thoughts}")

                # Pequeña pausa entre ciclos
                time.sleep(10)

        except KeyboardInterrupt:
            self._log("\nTest interrumpido por usuario")
        except Exception as e:
            self._log(f"\nError en test: {e}", error=True)
            import traceback
            traceback.print_exc()

        # Finalizar
        self.metrics.end_time = datetime.now().isoformat()
        self._running = False

        # Generar reporte
        self._generate_report()

        return len(self.metrics.errors) == 0

    def _format_duration(self, minutes: int) -> str:
        """Formatea duración en texto legible."""
        if minutes < 60:
            return f"{minutes} minutos"
        hours = minutes / 60
        if hours == 1:
            return "una hora"
        return f"{hours:.1f} horas"

    # =========================================================================
    # LOGGING Y REPORTE
    # =========================================================================

    def _log(self, message: str, error: bool = False):
        """Log a consola."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = "[ERROR]" if error else "[INFO]"
        if self.config.verbose or error:
            print(f"{prefix} [{timestamp}] {message}")

    def _generate_report(self):
        """Genera el reporte final."""
        report_path = os.path.join(
            self.config.log_dir,
            f"continuity_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )

        # Calcular average response time
        if self.interaction_logs:
            avg_time = sum(l.response_time_ms for l in self.interaction_logs) / len(self.interaction_logs)
            self.metrics.average_response_time_ms = avg_time

        report = f"""# ARIA Continuity Test Report

## Test Configuration
| Parameter | Value |
|-----------|-------|
| Duration (configured) | {self.config.duration_hours} hours |
| Provider | {self.config.provider} |
| Start Time | {self.metrics.start_time} |
| End Time | {self.metrics.end_time} |

## Metrics Summary

### Interactions
| Metric | Value |
|--------|-------|
| Total Interactions | {self.metrics.total_interactions} |
| Average Response Time | {self.metrics.average_response_time_ms:.2f} ms |
| Topic Recall Accuracy | {self.metrics.topic_recall_accuracy:.1%} |

### Autonomous Activity
| Metric | Value |
|--------|-------|
| Total Absences | {self.metrics.total_absences} |
| Total Absence Time | {self.metrics.total_absence_minutes:.1f} minutes |
| Autonomous Thoughts | {self.metrics.total_autonomous_thoughts} |
| DMN Activations | {self.metrics.total_dmn_activations} |

### Memory
| Metric | Value |
|--------|-------|
| Memories Created | {self.metrics.memories_created} |
| Memories Consolidated | {self.metrics.memories_consolidated} |

## Interaction Log

"""
        for log in self.interaction_logs[:20]:  # Primeras 20
            report += f"""### {log.timestamp}
- **Phase**: {log.phase}
- **User**: {log.user_input[:100]}...
- **ARIA**: {log.aria_response[:200]}...
- **Response Time**: {log.response_time_ms:.0f}ms
- **Topics**: {', '.join(log.topics_detected)}
- **Emotion**: {log.emotional_tone}

"""

        report += f"""
## Absence Periods

"""
        for absence in self.absence_logs:
            report += f"""### {absence.start_time}
- Duration: {absence.duration_minutes:.1f} minutes
- Topic: {absence.assigned_topic}
- Thoughts: {len(absence.autonomous_thoughts)}
- DMN Activations: {absence.dmn_activations}

"""

        if self.metrics.errors:
            report += "## Errors\n\n"
            for error in self.metrics.errors:
                report += f"- {error}\n"

        report += f"""
---
Generated: {datetime.now().isoformat()}
ARIA Continuity Test v1.0
"""

        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n[INFO] Reporte guardado en: {report_path}")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar reporte: {e}")

        # También guardar logs en JSON
        self._save_json_logs()

    def _save_json_logs(self):
        """Guarda logs detallados en JSON."""
        json_path = os.path.join(
            self.config.log_dir,
            f"continuity_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        data = {
            "config": asdict(self.config) if hasattr(self.config, '__dataclass_fields__') else {},
            "metrics": asdict(self.metrics),
            "interactions": [asdict(l) for l in self.interaction_logs],
            "absences": [asdict(a) for a in self.absence_logs]
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
        description="ARIA Continuity Test - Prueba de continuidad de memoria",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python scripts/aria_continuity_test.py --duration 8
  python scripts/aria_continuity_test.py --quick  # Test rápido de 1 hora
  python scripts/aria_continuity_test.py --provider anthropic --duration 12

Este script simula un usuario que interactúa con ARIA, se va por períodos,
y regresa para verificar qué hizo ARIA durante su ausencia.
        """
    )

    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=8,
        help="Duración del test en horas (default: 8)"
    )

    parser.add_argument(
        "--provider", "-p",
        type=str,
        default="deepseek",
        choices=["deepseek", "anthropic", "openai", "ollama"],
        help="Proveedor LLM (default: deepseek)"
    )

    parser.add_argument(
        "--log-dir", "-l",
        type=str,
        default="logs/continuity_test",
        help="Directorio para logs (default: logs/continuity_test)"
    )

    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Modo rápido: test de 1 hora con intervalos reducidos"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="Modo verbose (default: True)"
    )

    args = parser.parse_args()

    config = TestConfig(
        duration_hours=args.duration,
        provider=args.provider,
        log_dir=args.log_dir,
        quick_mode=args.quick,
        verbose=args.verbose
    )

    test = ARIAContinuityTest(config)
    success = test.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
