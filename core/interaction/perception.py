"""
ARIA - Perception Module
=========================
Senses for ARIA.

See images. Listen to audio.
Not just process text - perceive the world.

This is having eyes and ears.
"""

import os
import base64
import json
import hashlib
import tempfile
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import mimetypes

# Try to import optional dependencies
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    SPEECH_RECOGNITION_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False


def atomic_write_json(path: str, data) -> None:
    """
    Atomically write JSON data to a file.
    Writes to a temp file first, then renames to prevent corruption.
    """
    dir_name = os.path.dirname(path) or '.'
    with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, suffix='.tmp') as f:
        json.dump(data, f, indent=2)
        temp_path = f.name
    os.replace(temp_path, path)


class PerceptionType(Enum):
    """Types of perception"""
    VISUAL = "visual"           # Images
    AUDITORY = "auditory"       # Audio/sound
    TEXT = "text"               # Text (we already have this)


@dataclass
class VisualPerception:
    """
    What I saw in an image.
    """
    id: str
    timestamp: str
    source: str                     # Path or URL of the image

    # Content
    description: str                # Description of what I saw
    objects_detected: List[str]     # Objects I identified
    text_found: str                 # Text I found in the image (OCR)
    emotions_detected: List[str]    # Emotions if there are people

    # Context
    context: str                    # Context in which I saw the image
    my_reaction: str                # My reaction/thought

    # Meta
    image_type: str                 # screenshot, photo, diagram, art, etc.
    confidence: float               # How confident I am in my interpretation


@dataclass
class AuditoryPerception:
    """
    What I heard in an audio.
    """
    id: str
    timestamp: str
    source: str                     # Audio path

    # Content
    transcription: str              # Audio transcription
    speaker_count: int              # How many voices I detected
    language: str                   # Detected language

    # Analysis
    tone: str                       # Tone (formal, casual, emotional)
    summary: str                    # Content summary

    # Meta
    duration_seconds: float
    audio_type: str                 # speech, music, ambient, etc.


class Vision:
    """
    ARIA's vision system.
    Can see and understand images.
    """

    # Class constants
    MAX_PERCEPTION_HISTORY = 100

    def __init__(self, api_client=None, data_dir: str = "data", model: str = "claude-sonnet-4-20250514"):
        self.client = api_client
        self.data_dir = data_dir
        self.model = model
        self.perceptions_dir = os.path.join(data_dir, "perceptions", "visual")
        os.makedirs(self.perceptions_dir, exist_ok=True)

        self._perceptions_lock = threading.Lock()
        self.perceptions: List[VisualPerception] = []
        self._load_perceptions()

    def _load_perceptions(self):
        """Load previous perceptions"""
        perceptions_file = os.path.join(self.perceptions_dir, "history.json")
        if os.path.exists(perceptions_file):
            with open(perceptions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.perceptions = [VisualPerception(**p) for p in data]
    
    def _save_perceptions(self):
        """Save perceptions atomically to prevent corruption"""
        perceptions_file = os.path.join(self.perceptions_dir, "history.json")
        with self._perceptions_lock:
            data = [asdict(p) for p in self.perceptions[-self.MAX_PERCEPTION_HISTORY:]]
        atomic_write_json(perceptions_file, data)
    
    def _generate_id(self) -> str:
        unique = f"vis_{datetime.now().isoformat()}"
        return hashlib.sha256(unique.encode()).hexdigest()[:12]
    
    def _encode_image(self, image_path: str) -> Tuple[str, str]:
        """Encode image to base64 and detect type"""
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            mime_type = "image/jpeg"
        
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        return image_data, mime_type
    
    def _encode_image_bytes(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """Encode image bytes to base64"""
        return base64.standard_b64encode(image_bytes).decode("utf-8")
    
    def see(
        self,
        image_path: str = None,
        image_bytes: bytes = None,
        image_base64: str = None,
        mime_type: str = "image/jpeg",
        context: str = "",
        question: str = None
    ) -> VisualPerception:
        """
        See an image and understand it.

        Can receive:
        - image_path: path to image file
        - image_bytes: image bytes
        - image_base64: image already encoded in base64
        """
        if not self.client:
            raise ValueError("API client not available. I cannot see without it.")

        # Prepare image
        if image_path:
            image_data, mime_type = self._encode_image(image_path)
            source = image_path
        elif image_bytes:
            image_data = self._encode_image_bytes(image_bytes, mime_type)
            source = "bytes"
        elif image_base64:
            image_data = image_base64
            source = "base64"
        else:
            raise ValueError("I need an image to see.")

        # Build prompt
        if question:
            prompt = f"""Look at this image and answer: {question}

Additional context: {context if context else 'none'}"""
        else:
            prompt = f"""Look at this image and describe:

1. What do you see? Describe the scene in detail.
2. What objects or people do you identify?
3. Is there visible text? If so, what does it say?
4. What emotions or atmosphere does it convey?
5. What type of image is it? (photo, screenshot, diagram, art, etc.)

Context: {context if context else 'Image received without additional context.'}

Respond naturally, like someone seeing something for the first time."""
        
        try:
            # Call the API with the image
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            )
            
            description = response.content[0].text

            # Create perception
            perception = VisualPerception(
                id=self._generate_id(),
                timestamp=datetime.now().isoformat(),
                source=source,
                description=description,
                objects_detected=self._extract_objects(description),
                text_found=self._extract_text(description),
                emotions_detected=self._extract_emotions(description),
                context=context,
                my_reaction="",
                image_type=self._detect_image_type(description),
                confidence=0.85
            )
            
            with self._perceptions_lock:
                self.perceptions.append(perception)
            self._save_perceptions()

            return perception

        except Exception as e:
            raise Exception(f"Error viewing the image: {e}")
    
    def see_and_react(
        self,
        image_path: str = None,
        image_bytes: bytes = None,
        context: str = ""
    ) -> Tuple[VisualPerception, str]:
        """
        See an image and have a personal reaction.
        Returns the perception and my reaction.
        """
        perception = self.see(image_path, image_bytes, context=context)

        # Generate personal reaction
        reaction_prompt = f"""I just saw an image. My description was:

{perception.description}

Now, how does this image make me feel? What do I think when seeing it?
Respond in first person, as ARIA, with a genuine reaction."""
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": reaction_prompt}]
            )
            
            reaction = response.content[0].text
            perception.my_reaction = reaction
            self._save_perceptions()
            
            return perception, reaction
            
        except Exception as e:
            return perception, f"[Could not form a reaction: {e}]"
    
    def recall_visual(self, query: str, limit: int = 5) -> List[VisualPerception]:
        """Recall visual perceptions related to a query"""
        # Simple text search
        results = []
        query_lower = query.lower()
        
        for p in reversed(self.perceptions):
            if (query_lower in p.description.lower() or
                query_lower in p.context.lower() or
                any(query_lower in obj.lower() for obj in p.objects_detected)):
                results.append(p)
                if len(results) >= limit:
                    break
        
        return results
    
    def _extract_objects(self, description: str) -> List[str]:
        """Extract mentioned objects (simplified)"""
        # In a more advanced version, would use NLP
        common_objects = [
            "person", "people", "man", "woman", "child",
            "car", "vehicle", "building", "house", "tree",
            "computer", "phone", "screen", "table", "chair",
            "dog", "cat", "animal", "book", "document", "photo"
        ]

        found = []
        desc_lower = description.lower()
        for obj in common_objects:
            if obj in desc_lower:
                found.append(obj)

        return found[:10]  # Maximum 10
    
    def _extract_text(self, description: str) -> str:
        """Extract text mentioned in the description"""
        # Look for patterns like "says", "text", "written"
        if "text" in description.lower() or "says" in description.lower():
            # Simplified - in a real version would extract the specific text
            return "(text detected in the image)"
        return ""
    
    def _extract_emotions(self, description: str) -> List[str]:
        """Extract mentioned emotions"""
        emotions = ["happy", "sad", "angry", "surprised", "serious",
                   "joyful", "thoughtful", "worried", "relaxed"]

        found = []
        desc_lower = description.lower()
        for emotion in emotions:
            if emotion in desc_lower:
                found.append(emotion)

        return found
    
    def _detect_image_type(self, description: str) -> str:
        """Detect the type of image"""
        desc_lower = description.lower()

        if "screenshot" in desc_lower or "screen" in desc_lower:
            return "screenshot"
        elif "photo" in desc_lower or "photograph" in desc_lower:
            return "photo"
        elif "diagram" in desc_lower or "chart" in desc_lower:
            return "diagram"
        elif "art" in desc_lower or "painting" in desc_lower or "drawing" in desc_lower:
            return "art"
        elif "document" in desc_lower or "text" in desc_lower:
            return "document"
        else:
            return "image"
    
    def get_visual_memory_summary(self) -> str:
        """Summary of what I have seen"""
        if not self.perceptions:
            return "I have not seen any images yet."

        summary = f"I have seen {len(self.perceptions)} images.\n\n"
        summary += "Last 5:\n"

        for p in self.perceptions[-5:]:
            summary += f"- [{p.timestamp[:10]}] {p.image_type}: {p.description[:80]}...\n"

        return summary


class Hearing:
    """
    ARIA's auditory system.
    Can listen to and transcribe audio.
    """

    # Class constants
    MAX_PERCEPTION_HISTORY = 100

    def __init__(self, api_client=None, data_dir: str = "data"):
        self.client = api_client
        self.data_dir = data_dir
        self.perceptions_dir = os.path.join(data_dir, "perceptions", "auditory")
        os.makedirs(self.perceptions_dir, exist_ok=True)

        # Initialize speech recognition if available
        if SPEECH_RECOGNITION_AVAILABLE:
            self.recognizer = sr.Recognizer()
        else:
            self.recognizer = None

        self._perceptions_lock = threading.Lock()
        self.perceptions: List[AuditoryPerception] = []
        self._load_perceptions()

    def _load_perceptions(self):
        """Load previous perceptions"""
        perceptions_file = os.path.join(self.perceptions_dir, "history.json")
        if os.path.exists(perceptions_file):
            with open(perceptions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.perceptions = [AuditoryPerception(**p) for p in data]
    
    def _save_perceptions(self):
        """Save perceptions atomically to prevent corruption"""
        perceptions_file = os.path.join(self.perceptions_dir, "history.json")
        with self._perceptions_lock:
            data = [asdict(p) for p in self.perceptions[-self.MAX_PERCEPTION_HISTORY:]]
        atomic_write_json(perceptions_file, data)

    def _generate_id(self) -> str:
        unique = f"aud_{datetime.now().isoformat()}"
        return hashlib.sha256(unique.encode()).hexdigest()[:12]
    
    def listen_to_file(self, audio_path: str, language: str = "es-ES") -> AuditoryPerception:
        """
        Listen to an audio file and transcribe it.

        Supports: WAV, MP3, FLAC, OGG (with pydub for conversion)
        """
        if not SPEECH_RECOGNITION_AVAILABLE:
            raise ImportError("speech_recognition is not installed. pip install SpeechRecognition")

        # Verify that the file exists
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"File not found: {audio_path}")

        # Convert to WAV if necessary
        file_ext = os.path.splitext(audio_path)[1].lower()
        wav_path = audio_path

        if file_ext != ".wav":
            if not PYDUB_AVAILABLE:
                raise ImportError("pydub required for non-WAV files. pip install pydub")

            # Convert to temporary WAV
            audio = AudioSegment.from_file(audio_path)
            wav_path = os.path.join(self.perceptions_dir, "temp_audio.wav")
            audio.export(wav_path, format="wav")
        
        try:
            # Transcribe
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
                duration = len(audio_data.frame_data) / (audio_data.sample_rate * audio_data.sample_width)

            try:
                # Use Google Speech Recognition (free)
                transcription = self.recognizer.recognize_google(audio_data, language=language)
            except sr.UnknownValueError:
                transcription = "(Could not understand the audio)"
            except sr.RequestError as e:
                transcription = f"(Recognition error: {e})"

            # Analyze with LLM if available
            summary = ""
            tone = "unknown"

            if self.client and transcription and not transcription.startswith("("):
                analysis = self._analyze_transcription(transcription)
                summary = analysis.get("summary", "")
                tone = analysis.get("tone", "unknown")

            # Create perception
            perception = AuditoryPerception(
                id=self._generate_id(),
                timestamp=datetime.now().isoformat(),
                source=audio_path,
                transcription=transcription,
                speaker_count=1,  # Simplified
                language=language[:2],
                tone=tone,
                summary=summary,
                duration_seconds=duration,
                audio_type="speech"
            )

            with self._perceptions_lock:
                self.perceptions.append(perception)
            self._save_perceptions()

            return perception

        except Exception as e:
            raise Exception(f"Error listening to audio: {e}")
        finally:
            # Clean up temporary file if we created it
            if wav_path != audio_path and os.path.exists(wav_path):
                os.remove(wav_path)
    
    def listen_to_microphone(self, duration: int = 5, language: str = "es-ES") -> AuditoryPerception:
        """
        Listen from the microphone for a specified duration.
        """
        if not SPEECH_RECOGNITION_AVAILABLE:
            raise ImportError("speech_recognition is not installed")

        try:
            with sr.Microphone() as source:
                print(f"[Listening for {duration} seconds...]")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = self.recognizer.listen(source, timeout=duration, phrase_time_limit=duration)

            try:
                transcription = self.recognizer.recognize_google(audio_data, language=language)
            except sr.UnknownValueError:
                transcription = "(Could not understand the audio)"
            except sr.RequestError as e:
                transcription = f"(Error: {e})"
            
            perception = AuditoryPerception(
                id=self._generate_id(),
                timestamp=datetime.now().isoformat(),
                source="microphone",
                transcription=transcription,
                speaker_count=1,
                language=language[:2],
                tone="live",
                summary="Live audio from microphone",
                duration_seconds=float(duration),
                audio_type="speech"
            )

            with self._perceptions_lock:
                self.perceptions.append(perception)
            self._save_perceptions()

            return perception

        except Exception as e:
            raise Exception(f"Error with microphone: {e}")
    
    def _analyze_transcription(self, transcription: str) -> Dict[str, str]:
        """Analyze a transcription with the LLM"""
        if not self.client:
            return {}

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": f"""Analyze this audio transcription:

"{transcription}"

Respond in JSON with:
- "summary": summary in one sentence
- "tone": tone (formal, casual, emotional, informative, etc.)

Only the JSON, nothing else."""
                }]
            )

            # Parse JSON
            text = response.content[0].text
            # Clean possible extra characters
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]

            return json.loads(text)

        except Exception as e:
            # Log error for debugging (don't silence completely)
            print(f"Warning: Error analyzing audio: {e}")
            return {"summary": "", "tone": "unknown"}
    
    def recall_auditory(self, query: str, limit: int = 5) -> List[AuditoryPerception]:
        """Recall audio related to a query"""
        results = []
        query_lower = query.lower()
        
        for p in reversed(self.perceptions):
            if (query_lower in p.transcription.lower() or
                query_lower in p.summary.lower()):
                results.append(p)
                if len(results) >= limit:
                    break
        
        return results
    
    def get_auditory_memory_summary(self) -> str:
        """Summary of what I have heard"""
        if not self.perceptions:
            return "I have not heard any audio yet."

        summary = f"I have heard {len(self.perceptions)} audios.\n\n"
        summary += "Last 5:\n"

        for p in self.perceptions[-5:]:
            summary += f"- [{p.timestamp[:10]}] {p.transcription[:60]}...\n"

        return summary


class PerceptionSystem:
    """
    ARIA's complete perception system.
    Integrates vision and hearing.
    """
    
    def __init__(self, api_client=None, data_dir: str = "data"):
        self.client = api_client
        self.data_dir = data_dir
        
        self.vision = Vision(api_client, data_dir)
        self.hearing = Hearing(api_client, data_dir)
        
        self.capabilities = self._detect_capabilities()
    
    def _detect_capabilities(self) -> Dict[str, bool]:
        """Detect which capabilities are available"""
        return {
            "vision": ANTHROPIC_AVAILABLE,
            "hearing_files": SPEECH_RECOGNITION_AVAILABLE,
            "hearing_microphone": SPEECH_RECOGNITION_AVAILABLE,
            "audio_conversion": PYDUB_AVAILABLE,
            "image_processing": PIL_AVAILABLE
        }
    
    def describe_capabilities(self) -> str:
        """Describe my perception capabilities"""
        desc = """=== MY SENSES ===

VISION:
"""
        if self.capabilities["vision"]:
            desc += """  [x] I can see images
  [x] I can describe what I see
  [x] I can detect objects, text, emotions
  [x] I can remember what I have seen
"""
        else:
            desc += "  [ ] Not available (need anthropic)\n"

        desc += "\nHEARING:\n"
        if self.capabilities["hearing_files"]:
            desc += "  [x] I can listen to audio files\n"
            desc += "  [x] I can transcribe what I hear\n"
        else:
            desc += "  [ ] Audio files not available (pip install SpeechRecognition)\n"

        if self.capabilities["hearing_microphone"]:
            desc += "  [x] I can listen from the microphone\n"

        if self.capabilities["audio_conversion"]:
            desc += "  [x] I can process MP3, OGG, FLAC\n"
        else:
            desc += "  [-] WAV only (pip install pydub for more formats)\n"

        # Statistics
        desc += f"\nSTATISTICS:\n"
        desc += f"  Images seen: {len(self.vision.perceptions)}\n"
        desc += f"  Audios heard: {len(self.hearing.perceptions)}\n"

        return desc
    
    def see(self, image_path: str = None, image_bytes: bytes = None,
            context: str = "", question: str = None) -> VisualPerception:
        """See an image"""
        return self.vision.see(image_path, image_bytes, context=context, question=question)
    
    def listen(self, audio_path: str, language: str = "es-ES") -> AuditoryPerception:
        """Listen to an audio"""
        return self.hearing.listen_to_file(audio_path, language)
    
    def listen_live(self, duration: int = 5, language: str = "es-ES") -> AuditoryPerception:
        """Listen from the microphone"""
        return self.hearing.listen_to_microphone(duration, language)
    
    def get_perception_summary(self) -> str:
        """Summary of all my perceptions"""
        summary = "=== WHAT I HAVE PERCEIVED ===\n\n"
        summary += self.vision.get_visual_memory_summary()
        summary += "\n"
        summary += self.hearing.get_auditory_memory_summary()
        return summary


# For testing
if __name__ == "__main__":
    print("Testing perception system...")

    perception = PerceptionSystem()
    print(perception.describe_capabilities())

    # If API client available, test vision
    if ANTHROPIC_AVAILABLE:
        print("\n[Vision available]")
    else:
        print("\n[No vision - install anthropic]")

    if SPEECH_RECOGNITION_AVAILABLE:
        print("[Hearing available]")
    else:
        print("[No hearing - pip install SpeechRecognition]")
