import logging


def pytest_configure() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING)
