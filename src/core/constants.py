"""Project-wide constants shared across every VAOS layer.

Values here are immutable and carry no logic; they exist to give a single,
authoritative source for names, defaults, and paths that multiple layers
would otherwise need to duplicate.
"""

from pathlib import Path
from typing import Final

#: Canonical application name, used as the root-logger namespace and as
#: the default value of `AppConfig.app_name`.
APP_NAME: Final[str] = "vaos"

#: Default application version, used when neither `config.yaml` nor an
#: environment override specifies one.
APP_VERSION: Final[str] = "0.1.0"

#: Prefix every VAOS environment-variable override starts with.
ENV_PREFIX: Final[str] = "VAOS_"

#: Directory, relative to the process working directory, holding the
#: project's YAML configuration files.
DEFAULT_CONFIG_DIR: Final[Path] = Path("configs")

#: Filename of the general application configuration file.
DEFAULT_CONFIG_FILENAME: Final[str] = "config.yaml"

#: Filename of the logging configuration file.
DEFAULT_LOGGING_CONFIG_FILENAME: Final[str] = "logging.yaml"

#: Environment names `AppConfig.environment` is allowed to take.
ALLOWED_ENVIRONMENTS: Final[tuple[str, ...]] = ("development", "staging", "production", "test")

#: Log level applied when no logging configuration file is found.
DEFAULT_LOG_LEVEL: Final[str] = "INFO"

#: Text encoding used whenever `core` reads or writes a text file itself.
ENCODING_UTF8: Final[str] = "utf-8"
