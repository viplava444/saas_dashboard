"""
config/settings.py  —  Central application configuration
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR  = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = DATA_DIR / "nexusops.db"

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY          = os.getenv("SECRET_KEY", "dev-secret-CHANGE-in-production")
PASSWORD_MIN_LENGTH = 8
SESSION_EXPIRY_HOURS = 8
MAX_LOGIN_ATTEMPTS  = 5
LOCKOUT_MINUTES     = 15

# ── Bootstrap Admin (first-run only) ──────────────────────────────────────────
ADMIN_EMAIL    = os.getenv("ADMIN_EMAIL",    "admin@nexusops.io")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@1234")
ADMIN_NAME     = "System Administrator"

# ── Branding ──────────────────────────────────────────────────────────────────
APP_NAME    = "NexusOps"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Enterprise Automation Platform"

# ── Roles & Statuses ──────────────────────────────────────────────────────────
ROLE_ADMIN = "admin"
ROLE_USER  = "user"

STATUS_PENDING  = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_REVOKED  = "revoked"

# ── Registered Micro-Apps ─────────────────────────────────────────────────────
# To add a new app: append an entry here — access control is automatic.
AVAILABLE_APPS = [
    {
        "id":          "data_explorer",
        "name":        "Data Explorer",
        "description": "Upload and profile CSV / Excel datasets instantly",
        "icon":        "📊",
        "module_path": "app.apps.data_explorer",
        "category":    "Analytics",
        "enabled":     True,
    },
    {
        "id":          "report_builder",
        "name":        "Report Builder",
        "description": "Generate automated PDF / Excel reports from templates",
        "icon":        "📄",
        "module_path": "app.apps.report_builder",
        "category":    "Productivity",
        "enabled":     True,
    },
    {
        "id":          "api_tester",
        "name":        "API Tester",
        "description": "Test and monitor REST APIs with response analytics",
        "icon":        "🔌",
        "module_path": "app.apps.api_tester",
        "category":    "Development",
        "enabled":     True,
    },
    {
    "id":          "validation_js_generator",
    "name":        "Validation JS Generator",
    "description": "Convert a survey-spec CSV/Excel into a Qualtrics validationConfig JS object",
    "icon":        "📊",
    "module_path": "app.apps.validation_js_generator",
    "category":    "Survey Tools",
    "enabled":     True,
},
]
