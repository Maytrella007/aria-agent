"""Shared modification logging utilities."""

from __future__ import annotations

import os
import hashlib
from datetime import datetime
from typing import Any, Dict, Optional

import yaml

from core.infra.utils import atomic_write_yaml


def generate_modification_id() -> str:
    """Generate a short unique identifier for modification records."""
    return hashlib.sha256(
        f"{datetime.now().isoformat()}{os.urandom(8).hex()}".encode()
    ).hexdigest()[:12]


class ModificationLogger:
    """Append summary and full-content modification records."""

    def __init__(self, log_path: str = "data/modification_log.yaml"):
        self.log_path = log_path
        self.full_log_path = log_path.replace('.yaml', '_full.yaml')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._init_log()

    def _init_log(self):
        if not os.path.exists(self.log_path):
            atomic_write_yaml(
                self.log_path,
                {
                    'created_at': datetime.now().isoformat(),
                    'description': 'ARIA self-modification log',
                    'note': 'ARIA knows about this log and can access it',
                    'modifications': [],
                },
            )

    def record(self, modification: Any):
        self.record_dict(
            modification.to_dict(),
            original_content=getattr(modification, 'original_content', None),
            new_content=getattr(modification, 'new_content', None),
        )

    def record_dict(
        self,
        summary: Dict[str, Any],
        *,
        original_content: Optional[str] = None,
        new_content: Optional[str] = None,
    ):
        with open(self.log_path, 'r', encoding='utf-8') as f:
            log = yaml.safe_load(f) or {'modifications': [], 'last_modified': None, 'total_modifications': 0}

        if 'modifications' not in log:
            log['modifications'] = []

        log['modifications'].append(summary)
        log['last_modified'] = datetime.now().isoformat()
        log['total_modifications'] = len(log['modifications'])
        atomic_write_yaml(self.log_path, log)

        full_entry = {
            **summary,
            'original_content': original_content,
            'new_content': new_content,
        }

        if os.path.exists(self.full_log_path):
            with open(self.full_log_path, 'r', encoding='utf-8') as f:
                full_log = yaml.safe_load(f) or {'entries': []}
        else:
            full_log = {'entries': []}

        full_log['entries'].append(full_entry)
        atomic_write_yaml(self.full_log_path, full_log)

    def get_history(self, limit: Optional[int] = None):
        with open(self.log_path, 'r', encoding='utf-8') as f:
            log = yaml.safe_load(f) or {}

        modifications = log.get('modifications', [])
        if limit:
            return modifications[-limit:]
        return modifications

    def get_full_modification(self, mod_id: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.full_log_path):
            return None

        with open(self.full_log_path, 'r', encoding='utf-8') as f:
            full_log = yaml.safe_load(f) or {}

        for entry in full_log.get('entries', []):
            if entry.get('id') == mod_id:
                return entry
        return None
