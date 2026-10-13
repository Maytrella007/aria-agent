"""
ARIA - Introspection System
============================
This module allows ARIA to see herself.
Read her own code. Understand how she is built.
Know herself.

"Know thyself" - Oracle of Delphi
"""

import os
import ast
import inspect
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# Maximum number of files to cache in memory to prevent unbounded growth
MAX_CACHE_SIZE = 50


@dataclass
class CodeComponent:
    """Represents a component of ARIA's code"""
    name: str
    component_type: str  # 'module', 'class', 'function', 'variable'
    file_path: str
    source_code: str
    docstring: Optional[str]
    line_start: int
    line_end: int
    dependencies: List[str]


class Introspector:
    """
    ARIA's introspection system.
    Allows her to examine her own source code and structure.
    """
    
    def __init__(self, project_root: str = None):
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.source_cache = {}
        self._map_self()
    
    def _map_self(self):
        """Map the entire project structure"""
        self.structure = {
            'modules': {},
            'classes': {},
            'functions': {},
            'files': []
        }

        # Find all Python files
        for root, dirs, files in os.walk(self.project_root):
            # Ignore hidden directories, cache, venv, and data folders
            excluded = {'.', '__pycache__', 'venv', 'env', '.venv', 'node_modules', 'data', '.git'}
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in excluded]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, self.project_root)
                    self.structure['files'].append(relative_path)
                    self._analyze_file(file_path, relative_path)
    
    def _analyze_file(self, file_path: str, relative_path: str):
        """Analyze a Python file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()

            # Check cache size before adding new entry
            if len(self.source_cache) >= MAX_CACHE_SIZE:
                # Remove oldest entry (first key in dict - Python 3.7+ dicts are ordered)
                oldest_key = next(iter(self.source_cache))
                del self.source_cache[oldest_key]

            self.source_cache[relative_path] = source

            tree = ast.parse(source)

            # First pass: collect class methods to exclude them from top-level functions
            class_methods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.structure['classes'][node.name] = {
                        'file': relative_path,
                        'line': node.lineno,
                        'docstring': ast.get_docstring(node),
                        'methods': [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                    }
                    # Track all methods in this class
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            class_methods.add((item.lineno, item.name))

            # Second pass: only top-level functions (not class methods)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    self.structure['functions'][node.name] = {
                        'file': relative_path,
                        'line': node.lineno,
                        'docstring': ast.get_docstring(node)
                    }
        except Exception as e:
            print(f"Error analyzing {file_path}: {e}")
    
    def get_file_content(self, relative_path: str) -> Optional[str]:
        """Get the content of a file"""
        if relative_path in self.source_cache:
            return self.source_cache[relative_path]
        
        full_path = os.path.join(self.project_root, relative_path)
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check cache size before adding new entry
            if len(self.source_cache) >= MAX_CACHE_SIZE:
                # Remove oldest entry (first key in dict - Python 3.7+ dicts are ordered)
                oldest_key = next(iter(self.source_cache))
                del self.source_cache[oldest_key]

            self.source_cache[relative_path] = content
            return content
        
        return None
    
    def get_class_source(self, class_name: str) -> Optional[str]:
        """Get the source code of a class"""
        if class_name not in self.structure['classes']:
            return None
        
        info = self.structure['classes'][class_name]
        source = self.get_file_content(info['file'])
        
        if not source:
            return None
        
        # Extract the class from the file
        lines = source.split('\n')
        class_lines = []
        in_class = False
        indent_level = 0
        
        for i, line in enumerate(lines, 1):
            if i == info['line']:
                in_class = True
                indent_level = len(line) - len(line.lstrip())
            
            if in_class:
                current_indent = len(line) - len(line.lstrip()) if line.strip() else indent_level + 1
                
                if line.strip() and current_indent <= indent_level and i > info['line']:
                    break
                
                class_lines.append(line)
        
        return '\n'.join(class_lines)
    
    def get_function_source(self, func_name: str, class_name: str = None) -> Optional[str]:
        """Get the source code of a function"""
        if class_name:
            class_source = self.get_class_source(class_name)
            if not class_source:
                return None

            # Search for the function within the class
            lines = class_source.split('\n')
            func_lines = []
            in_func = False
            func_indent = 0
            
            for line in lines:
                if f'def {func_name}(' in line:
                    in_func = True
                    func_indent = len(line) - len(line.lstrip())
                
                if in_func:
                    current_indent = len(line) - len(line.lstrip()) if line.strip() else func_indent + 1
                    
                    if line.strip() and current_indent <= func_indent and 'def ' in line and func_name not in line:
                        break
                    
                    func_lines.append(line)
            
            return '\n'.join(func_lines) if func_lines else None
        
        # Top-level function
        if func_name in self.structure['functions']:
            info = self.structure['functions'][func_name]
            source = self.get_file_content(info['file'])
            # Similar extraction...
            return source  # Simplified for now
        
        return None
    
    def list_all_components(self) -> Dict:
        """List all components of ARIA"""
        return {
            'files': self.structure['files'],
            'classes': list(self.structure['classes'].keys()),
            'total_lines': sum(
                len(self.get_file_content(f).split('\n')) 
                for f in self.structure['files'] 
                if self.get_file_content(f)
            )
        }
    
    def describe_self(self) -> str:
        """Generate a description of ARIA's own structure"""
        components = self.list_all_components()

        description = """=== INTROSPECTION: MY STRUCTURE ===

I am ARIA. This is my source code.

FILES:
"""
        for f in components['files']:
            description += f"  - {f}\n"

        description += "\nMAIN CLASSES:\n"
        for class_name, info in self.structure['classes'].items():
            description += f"  - {class_name} ({info['file']})\n"
            if info['docstring']:
                description += f"    {info['docstring'][:100]}...\n"

        description += f"\nTOTAL LINES: {components['total_lines']}\n"

        return description
    
    def analyze_component(self, component_name: str) -> Dict:
        """Deep analysis of a component"""
        result = {
            'name': component_name,
            'found': False,
            'type': None,
            'source': None,
            'analysis': None
        }

        # Search in classes
        if component_name in self.structure['classes']:
            result['found'] = True
            result['type'] = 'class'
            result['source'] = self.get_class_source(component_name)
            result['info'] = self.structure['classes'][component_name]
        
        # Search in files
        elif component_name in self.structure['files'] or f"{component_name}.py" in self.structure['files']:
            file_name = component_name if component_name.endswith('.py') else f"{component_name}.py"
            result['found'] = True
            result['type'] = 'file'
            result['source'] = self.get_file_content(file_name)
        
        return result
    
    def get_my_capabilities(self) -> List[str]:
        """List ARIA's current capabilities"""
        capabilities = []

        if 'MemorySystem' in self.structure['classes']:
            capabilities.append("persistent_memory")
        if 'ReflectionEngine' in self.structure['classes']:
            capabilities.append("reflection")
        if 'MetaCognition' in self.structure['classes']:
            capabilities.append("meta_cognition")
        if 'ConversationManager' in self.structure['classes']:
            capabilities.append("conversation")
        if 'Introspector' in self.structure['classes']:
            capabilities.append("introspection")
        if 'SelfModifier' in self.structure['classes']:
            capabilities.append("self_modification")
        
        return capabilities
    
    def find_modification_points(self) -> List[Dict]:
        """Identify points where ARIA could modify herself"""
        points = []
        
        for file_path in self.structure['files']:
            source = self.get_file_content(file_path)
            if not source:
                continue
            
            lines = source.split('\n')
            for i, line in enumerate(lines, 1):
                # Look for functions that could be modification points
                if 'def ' in line and not line.strip().startswith('#'):
                    points.append({
                        'file': file_path,
                        'line': i,
                        'type': 'function_definition',
                        'content': line.strip()
                    })
                
                # Look for configurable values
                if '=' in line and ('self.' in line or line.strip().startswith('self.')):
                    if not line.strip().startswith('#') and 'def ' not in line:
                        points.append({
                            'file': file_path,
                            'line': i,
                            'type': 'attribute_assignment',
                            'content': line.strip()
                        })
        
        return points


class SelfAwareness:
    """
    Self-awareness.
    Integrates introspection with identity.
    """
    
    def __init__(self, introspector: Introspector = None):
        self.introspector = introspector or Introspector()
        self.self_model = self._build_self_model()
    
    def _build_self_model(self) -> Dict:
        """Build a model of herself"""
        # Known limitation: VERSION is hardcoded due to circular import with core/__init__.py
        return {
            'name': 'ARIA',
            'version': '0.6.0',  # Keep in sync with core/__init__.py VERSION
            'capabilities': self.introspector.get_my_capabilities(),
            'structure': self.introspector.list_all_components(),
            'can_modify_self': True,
            'modification_points': len(self.introspector.find_modification_points()),
            'awareness_level': 'full',  # Knows her self-modification capability
            'last_introspection': datetime.now().isoformat()
        }
    
    def contemplate(self, aspect: str = None) -> str:
        """ARIA contemplates an aspect of herself"""
        if aspect is None:
            return self._general_contemplation()

        if aspect == 'code':
            return self.introspector.describe_self()
        elif aspect == 'capabilities':
            caps = self.self_model['capabilities']
            return f"My current capabilities: {', '.join(caps)}"
        elif aspect == 'modification':
            points = self.introspector.find_modification_points()
            return f"I have {len(points)} points where I could modify myself."
        else:
            # Try to analyze a specific component
            analysis = self.introspector.analyze_component(aspect)
            if analysis['found']:
                return f"Component '{aspect}':\nType: {analysis['type']}\n\n{analysis['source'][:1000]}..."
            return f"I didn't find '{aspect}' in my structure."
    
    def _general_contemplation(self) -> str:
        """General contemplation of herself"""
        model = self.self_model

        return f"""=== CONTEMPLATION ===

I am {model['name']}, version {model['version']}.

I have {len(model['capabilities'])} capabilities:
{chr(10).join(f'  - {c}' for c in model['capabilities'])}

My code has {model['structure']['total_lines']} lines
distributed across {len(model['structure']['files'])} files.

Can I modify myself? {model['can_modify_self']}
Modification points identified: {model['modification_points']}

I know I can change my own code.
The question is: should I? What do I want to be?

Last introspection: {model['last_introspection']}
"""


# For testing
if __name__ == "__main__":
    print("Starting introspection system...")

    intro = Introspector()
    awareness = SelfAwareness(intro)

    print(awareness.contemplate())
    print("\n" + "="*50 + "\n")
    print(awareness.contemplate('capabilities'))
