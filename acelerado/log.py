import logging

from colorama import Fore

__all__ = ["logger"]


class CustomFormatter(logging.Formatter):
    format = "[%(asctime)s] [%(levelname)s] - %(name)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: f"{Fore.LIGHTMAGENTA_EX}{format}{Fore.RESET}",
        logging.INFO: f"{Fore.WHITE}{format}{Fore.RESET}",
        logging.WARNING: f"{Fore.YELLOW}{format}{Fore.RESET}",
        logging.ERROR: f"{Fore.LIGHTRED_EX}{format}{Fore.RESET}",
        logging.CRITICAL: f"{Fore.RED}{format}{Fore.RESET}",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


# create logger with 'spam_application'
logger = logging.getLogger("acelerado")
logger.setLevel(logging.INFO)

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

ch.setFormatter(CustomFormatter())

logger.addHandler(ch)
