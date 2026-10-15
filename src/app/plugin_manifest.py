"""
WIMI Plugin Manifest — Parses and validates plugin manifest.json files.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VALID_PERMISSIONS = {'read', 'write:entries', 'write:sessions', 'write:notes', 'write:goals', 'write:media', 'storage'}
VALID_SETTING_TYPES = {'text', 'number', 'toggle', 'select'}

# Plugin ID: alphanumeric, hyphens, underscores, 1-64 chars
_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
# Version: X.Y.Z
_VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+$')
# A WIMI version: X.Y.Z with an optional SemVer pre-release, because WIMI's own
# APP_VERSION carries one ("0.3.0-beta") and min_app_version has to be able to
# name it (#508). The plugin's own `version` stays plain X.Y.Z.
_APP_VERSION_PATTERN = re.compile(
    r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')


def version_key(version: str) -> Tuple:
    """Order WIMI versions by SemVer 2.0 precedence (#508).

    ``1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-beta < 1.0.0-beta.2 < 1.0.0-rc.1
    < 1.0.0``: a pre-release sorts before its release, numeric identifiers
    compare as numbers and before alphanumeric ones, and a shorter run of
    identifiers sorts first when the rest are equal. Raises ``ValueError`` for
    anything that is not ``X.Y.Z`` or ``X.Y.Z-pre``.
    """
    match = _APP_VERSION_PATTERN.match(version or '')
    if not match:
        raise ValueError(f'Not a WIMI version: "{version}" (must be X.Y.Z or X.Y.Z-pre)')
    major, minor, patch, pre = match.groups()
    core = (int(major), int(minor), int(patch))
    if pre is None:
        return core + (1, ())
    ids = tuple((0, int(part), '') if part.isdigit() else (1, 0, part)
                for part in pre.split('.'))
    return core + (0, ids)


@dataclass
class PluginSettingDef:
    """Definition for a single plugin setting."""
    key: str
    type: str           # text | number | toggle | select
    label: str
    description: str = ''
    default: Any = None
    options: list = field(default_factory=list)  # for select: [{value, label}]
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass
class PluginManifest:
    """Parsed and validated plugin manifest."""
    id: str
    name: str
    version: str
    description: str = ''
    author: str = ''
    permissions: List[str] = field(default_factory=lambda: ['read'])
    backend: Optional[str] = None       # e.g. "backend.py"
    frontend_js: Optional[str] = None   # e.g. "frontend.js"
    frontend_css: Optional[str] = None  # e.g. "styles.css"
    slots: Dict[str, str] = field(default_factory=dict)  # slot_name -> HTML file path
    settings: List[PluginSettingDef] = field(default_factory=list)
    min_app_version: Optional[str] = None  # e.g. "1.0.0"
    plugin_dir: Optional[Path] = None   # set at load time

    @classmethod
    def validate(cls, data: dict) -> List[str]:
        """
        Validate a manifest data dict. Returns list of error strings.
        Empty list means valid.
        """
        errors = []

        # Required fields
        if not data.get('id'):
            errors.append('Missing required field: id')
        elif not _ID_PATTERN.match(data['id']):
            errors.append(f'Invalid plugin id: "{data["id"]}" (must be alphanumeric/hyphens/underscores, 1-64 chars)')

        if not data.get('name'):
            errors.append('Missing required field: name')
        elif len(data['name']) > 128:
            errors.append('Plugin name exceeds 128 characters')

        if not data.get('version'):
            errors.append('Missing required field: version')
        elif not _VERSION_PATTERN.match(data['version']):
            errors.append(f'Invalid version format: "{data["version"]}" (must be X.Y.Z)')

        # Permissions
        permissions = data.get('permissions', ['read'])
        if not isinstance(permissions, list):
            errors.append('permissions must be a list')
        else:
            for perm in permissions:
                if perm not in VALID_PERMISSIONS:
                    errors.append(f'Invalid permission: "{perm}". Valid: {sorted(VALID_PERMISSIONS)}')

        # Settings
        settings = data.get('settings', [])
        if not isinstance(settings, list):
            errors.append('settings must be a list')
        else:
            for i, s in enumerate(settings):
                if not isinstance(s, dict):
                    errors.append(f'settings[{i}] must be an object')
                    continue
                if not s.get('key'):
                    errors.append(f'settings[{i}]: missing key')
                if not s.get('type'):
                    errors.append(f'settings[{i}]: missing type')
                elif s['type'] not in VALID_SETTING_TYPES:
                    errors.append(f'settings[{i}]: invalid type "{s["type"]}". Valid: {sorted(VALID_SETTING_TYPES)}')
                if not s.get('label'):
                    errors.append(f'settings[{i}]: missing label')

        # min_app_version format
        mav = data.get('min_app_version')
        if mav is not None:
            if not isinstance(mav, str) or not _APP_VERSION_PATTERN.match(mav):
                errors.append(f'Invalid min_app_version format: "{mav}" (must be X.Y.Z or X.Y.Z-pre)')

        return errors

    def incompatibility(self, app_version: str) -> Optional[str]:
        """Why this plugin cannot run on ``app_version``, or ``None`` if it can.

        ``min_app_version`` was validated for format and compared with nothing
        (#508), so a plugin built for a later WIMI loaded anyway and failed in
        whatever way its missing API made it fail. Callers skip or refuse on a
        sentence from here, and nothing else decides compatibility.
        """
        if not self.min_app_version:
            return None
        if version_key(app_version) >= version_key(self.min_app_version):
            return None
        return (f'"{self.name}" needs WIMI {self.min_app_version} or later; '
                f'this is WIMI {app_version}.')

    @classmethod
    def from_file(cls, manifest_path: Path) -> 'PluginManifest':
        """
        Load and validate a manifest from a JSON file.

        Args:
            manifest_path: Path to manifest.json

        Returns:
            PluginManifest instance

        Raises:
            ValueError: If manifest is invalid
            FileNotFoundError: If file doesn't exist
        """
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        errors = cls.validate(data)
        if errors:
            raise ValueError(f'Invalid manifest at {manifest_path}: {"; ".join(errors)}')

        # Parse settings
        settings = []
        for s in data.get('settings', []):
            settings.append(PluginSettingDef(
                key=s['key'],
                type=s['type'],
                label=s['label'],
                description=s.get('description', ''),
                default=s.get('default'),
                options=s.get('options', []),
                min=s.get('min'),
                max=s.get('max'),
            ))

        plugin_dir = manifest_path.parent

        return cls(
            id=data['id'],
            name=data['name'],
            version=data['version'],
            description=data.get('description', ''),
            author=data.get('author', ''),
            permissions=data.get('permissions', ['read']),
            backend=data.get('backend'),
            frontend_js=data.get('frontend_js'),
            frontend_css=data.get('frontend_css'),
            slots=data.get('slots', {}),
            settings=settings,
            min_app_version=data.get('min_app_version'),
            plugin_dir=plugin_dir,
        )

    def to_frontend_dict(self) -> dict:
        """
        Convert to a dict suitable for the frontend, with resolved file:/// URLs.

        Returns:
            Dict with plugin info and resolved asset paths
        """
        d = {
            'id': self.id,
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'permissions': self.permissions,
            'settings': [
                {
                    'key': s.key,
                    'type': s.type,
                    'label': s.label,
                    'description': s.description,
                    'default': s.default,
                    'options': s.options,
                    'min': s.min,
                    'max': s.max,
                }
                for s in self.settings
            ],
            'slots': self.slots,
            'min_app_version': self.min_app_version,
        }

        if self.plugin_dir:
            if self.frontend_js:
                js_path = self.plugin_dir / self.frontend_js
                d['js'] = js_path.as_uri() if js_path.exists() else None
            if self.frontend_css:
                css_path = self.plugin_dir / self.frontend_css
                d['css'] = css_path.as_uri() if css_path.exists() else None

        return d
