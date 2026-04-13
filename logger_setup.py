import logging
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logger(name: str = "processMail") -> logging.Logger:
    """
    Configura el logger de la aplicación con rotación diaria.
    - Nivel: INFO, WARNING y ERROR
    - Ficheros en carpeta /log
    - Rotación diaria a medianoche
    - Retención de 30 días
    """
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Evitar duplicar handlers si setup_logger se llama varias veces
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler de fichero: rotación diaria a medianoche, retención 30 días
    log_file = os.path.join(log_dir, "processMail.log")
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    # El sufijo de los ficheros rotados tendrá el formato YYYY-MM-DD
    file_handler.suffix = "%Y-%m-%d"

    # Handler de consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
