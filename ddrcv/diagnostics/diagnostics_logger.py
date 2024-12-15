import logging
from logging.handlers import RotatingFileHandler
from collections import deque


class DiagnosticsLogger:
    """ Class to manage diagnostics logging and maintain recent logs in memory. """
    def __init__(self, logger_name='diagnostics', log_file='diagnostics.log', max_log_size=10 * 1024, backup_count=3, buffer=10):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.DEBUG)

        # Create a rotating file handler
        file_handler = RotatingFileHandler(log_file, maxBytes=max_log_size, backupCount=backup_count)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

        # Maintain a buffer of the last 10 log messages
        self.buffer = buffer
        self.log_buffer = deque(maxlen=self.buffer)
        self.logger.addHandler(file_handler)
        self._load_prev_logs(log_file)

    def add_websocket_handler(self, socketio):
        """ Attach a SocketIO handler to emit logs over WebSocket. """
        socket_handler = self.SocketHandler(socketio, self.log_buffer)
        socket_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(socket_handler)

    class SocketHandler(logging.Handler):
        """ Custom logging handler that emits messages to WebSocket clients. """
        def __init__(self, socketio, log_buffer):
            super().__init__()
            self.socketio = socketio
            self.log_buffer = log_buffer

        def emit(self, record):
            msg = self.format(record)
            # Emit message to connected clients
            self.socketio.emit('log_message', {'message': msg})
            # Store message in the buffer
            self.log_buffer.append(msg)

    def _load_prev_logs(self, log_file):
        """ Load the last self.buffer log messages from the log file. """
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Keep only the last N entries
                recent_logs = lines[-self.buffer:]
                for log in recent_logs:
                    self.log_buffer.append(log.strip())
        except FileNotFoundError:
            print(f"No previous log file found at {log_file}. Starting fresh.")

    def get_logger(self):
        """ Returns the configured logger instance. """
        return self.logger

    def get_recent_logs(self):
        """ Returns the recent log buffer. """
        return self.log_buffer
