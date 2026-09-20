"""Every domain's SQLAlchemy models, so ``metadata`` knows all tables (Alembic autogenerate).

A new domain with a ``models.py`` adds its import here (enforced by tests/repo/test_structure.py).
"""

from app.auth import models as auth_models
from app.db.base import Base
from app.inspections import models as inspections_models

MODEL_MODULES = (auth_models, inspections_models)

metadata = Base.metadata
