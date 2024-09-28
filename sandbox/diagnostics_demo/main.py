from app import create_app
from ddrcv.diagnostics.diagnostics_logger import DiagnosticsLogger
from ddrcv.diagnostics.diagnostics_wrapper import DiagnosticsWrapper
import time


# Create the Flask app
app = create_app()

if __name__ == "__main__":

    # Initialize the DiagnosticsLogger
    diagnostics_logger = DiagnosticsLogger()

    # Use the DiagnosticsWrapper context manager
    with DiagnosticsWrapper(app, diagnostics_logger) as logger:
        logger.info("Starting main application.")
        for ii in range(10):
            logger.info(f'Step {ii}')
            time.sleep(3)  # Simulated main application work
        logger.info("Main application completed.")
