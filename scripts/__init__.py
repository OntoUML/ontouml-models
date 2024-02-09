# Remove the default handler and add a new handler with a custom format
import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, format="{time} | {level} - {message}")
sys.path.insert(0, 'scripts')